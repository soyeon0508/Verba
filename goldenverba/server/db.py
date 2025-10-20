from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Iterable


class DatabaseError(Exception):
    """Base database error."""


class DatabaseConfigError(DatabaseError):
    """Raised when the database URL is missing or invalid."""


@dataclass
class DatabaseSession:
    dialect: str
    connection: Any

    async def fetchval(self, query: str, *args: Any) -> Any:
        if self.dialect == "postgres":
            return await self.connection.fetchval(query, *args)

        cursor = await self.connection.execute(query, args)
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return row[0]

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if self.dialect == "postgres":
            record = await self.connection.fetchrow(query, *args)
            if record is None:
                return None
            return dict(record)

        cursor = await self.connection.execute(query, args)
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return dict(row)

    async def fetchall(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if self.dialect == "postgres":
            records = await self.connection.fetch(query, *args)
            return [dict(record) for record in records]

        cursor = await self.connection.execute(query, args)
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(row) for row in rows]

    async def execute(self, query: str, *args: Any) -> None:
        if self.dialect == "postgres":
            await self.connection.execute(query, *args)
            return

        cursor = await self.connection.execute(query, args)
        await cursor.close()


class Database:
    def __init__(
        self,
        url: str | None = None,
        migrations_path: Path | None = None,
    ):
        self.url = url or os.getenv("PART_DATABASE_URL")
        self._default_sqlite_path = (
            Path(__file__).resolve().parents[2] / "data" / "parts.db"
        )
        if not self.url:
            self.url = f"sqlite+aiosqlite:///{self._default_sqlite_path}"

        self.migrations_path = migrations_path or (
            Path(__file__).resolve().parents[2] / "migrations"
        )
        self.dialect = self._detect_dialect(self.url)
        self._pool = None
        self._connection = None
        self._lock = asyncio.Lock()
        self._sqlite_lock = asyncio.Lock()
        self._initialized = False

    def _detect_dialect(self, url: str) -> str:
        lowered = url.lower()
        if lowered.startswith("postgresql://") or lowered.startswith("postgres://"):
            return "postgres"
        if lowered.startswith("sqlite+aiosqlite://") or lowered.startswith("sqlite://"):
            return "sqlite"
        raise DatabaseConfigError(f"Unsupported database URL: {url}")

    async def connect(self) -> None:
        async with self._lock:
            if self._initialized:
                return

            if self.dialect == "postgres":
                await self._connect_postgres()
            else:
                await self._connect_sqlite()

            await self._apply_migrations()
            self._initialized = True

    async def _connect_postgres(self) -> None:
        import asyncpg  # type: ignore[import]

        self._pool = await asyncpg.create_pool(self.url)

    async def _connect_sqlite(self) -> None:
        import aiosqlite  # type: ignore[import]

        path = self._resolve_sqlite_path(self.url)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.execute("PRAGMA foreign_keys = ON;")
        await self._connection.commit()

    async def disconnect(self) -> None:
        async with self._lock:
            if not self._initialized:
                return

            if self.dialect == "postgres" and self._pool is not None:
                await self._pool.close()
            elif self._connection is not None:
                await self._connection.close()

            self._pool = None
            self._connection = None
            self._initialized = False

    def _resolve_sqlite_path(self, url: str) -> Path:
        if url.startswith("sqlite+aiosqlite:///"):
            path_str = url.replace("sqlite+aiosqlite:///", "", 1)
        elif url.startswith("sqlite:///"):
            path_str = url.replace("sqlite:///", "", 1)
        else:
            raise DatabaseConfigError(f"Unsupported sqlite URL: {url}")

        return Path(path_str or self._default_sqlite_path)

    def _iter_migration_files(self) -> Iterable[Path]:
        if not self.migrations_path.exists():
            return []

        dialect_path = self.migrations_path / self.dialect
        if dialect_path.exists():
            candidates = dialect_path.glob("*.sql")
        else:
            candidates = self.migrations_path.glob("*.sql")

        return sorted(candidates, key=lambda item: item.name)

    async def _apply_migrations(self) -> None:
        migration_files = self._iter_migration_files()
        if not migration_files:
            return

        if self.dialect == "postgres":
            if self._pool is None:
                raise DatabaseError("Postgres pool is not initialized")

            async with self._pool.acquire() as connection:
                for migration in migration_files:
                    sql = migration.read_text(encoding="utf-8").strip()
                    if not sql:
                        continue
                    await connection.execute(sql)
        else:
            if self._connection is None:
                raise DatabaseError("SQLite connection is not initialized")

            for migration in migration_files:
                sql = migration.read_text(encoding="utf-8").strip()
                if not sql:
                    continue
                await self._connection.executescript(sql)
            await self._connection.commit()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[DatabaseSession]:
        if not self._initialized:
            raise DatabaseError("Database is not connected")

        if self.dialect == "postgres":
            if self._pool is None:
                raise DatabaseError("Postgres pool is not initialized")

            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    session = DatabaseSession(self.dialect, connection)
                    yield session
        else:
            if self._connection is None:
                raise DatabaseError("SQLite connection is not initialized")

            async with self._sqlite_lock:
                try:
                    await self._connection.execute("BEGIN;")
                    session = DatabaseSession(self.dialect, self._connection)
                    yield session
                except Exception:
                    await self._connection.rollback()
                    raise
                else:
                    await self._connection.commit()


database = Database()


def part_number_feature_enabled() -> bool:
    flag = os.getenv("FEATURE_PART_NUMBER", "true")
    return flag.strip().lower() not in {"0", "false", "off", "no"}
