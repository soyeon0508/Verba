from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

try:
    from asyncpg import UniqueViolationError  # type: ignore[import]
except ImportError:  # pragma: no cover
    class UniqueViolationError(Exception):
        pass


try:
    from aiosqlite import IntegrityError as SQLiteIntegrityError  # type: ignore[import]
except ImportError:  # pragma: no cover
    class SQLiteIntegrityError(Exception):
        pass

from goldenverba.server.db import Database, DatabaseSession
from goldenverba.server.rules import (
    RuleSet,
    default_revision,
    resolve_series,
    rule_version,
)

logger = logging.getLogger(__name__)

PN_PATTERN = re.compile(r"^\d{3}-\d{4}-\d{2}$")
SERIES_PATTERN = re.compile(r"^\d{3}$")
REVISION_PATTERN = re.compile(r"^\d{2}$")
BASE_KEY_SPLIT = re.compile(r"[^A-Za-z0-9]+")


def detect_series_code(cat_code: str) -> int:
    """Map a 3-digit category code to its owning series (hundreds family)."""
    value = int(cat_code)
    if value in (975, 980):
        return value
    return (value // 100) * 100


def normalize_base_key(text: str | None) -> str | None:
    """Normalize a free-form description into a compact base key."""
    if not text:
        return None
    collapsed = BASE_KEY_SPLIT.sub("_", text).strip("_").lower()
    if not collapsed:
        return None
    return collapsed[:120]


def infer_part_type(series_code: int) -> str:
    """Default part_type inference aligned with IDS conventions."""
    if series_code == 700:
        return "service"
    if series_code in (800, 900):
        return "engineering_product"
    if series_code in (975, 980):
        return "engineering_product"
    return "material"


class PartNumberError(Exception):
    """Base error for part number operations."""


class PartNumberValidationError(PartNumberError):
    """Raised when user input fails validation."""


class PartNumberConflictError(PartNumberError):
    """Raised when a generated part collides with existing data."""


class PartNumberNotFoundError(PartNumberError):
    """Raised when a requested part cannot be located."""


@dataclass
class GeneratedPart:
    part_no: str
    series: str
    serial: int
    dash: int
    revision: str
    detail_code: str
    detail_prefix: str | None
    detail_suffix: str
    created_by: str
    created_at: str
    owner: str | None
    series_name: str | None
    note: str | None
    rule_version: str | None
    idempotency_key: str | None
    base_key: str | None
    customer_id: str | None
    attrs: dict[str, Any]


class PartNumberService:
    """Generate and persist IDS part numbers with transactional safeguards."""

    def __init__(
        self,
        db: Database,
        rules: RuleSet,
    ):
        self.db = db
        self.rules = rules
        self.pattern = PN_PATTERN

    async def generate_part(
        self,
        *,
        series: str,
        created_by: str,
        revision: str | None = None,
        detail_prefix: str | None = None,
        note: str | None = None,
        idempotency_key: str | None = None,
        description: str | None = None,
        customer_id: str | None = None,
        attrs: dict[str, Any] | None = None,
        vendor_id: int | None = None,
        drawing: str | None = None,
        base_key: str | None = None,
        rma_no: str | None = None,
        source: str = "api",
    ) -> GeneratedPart:
        """Generate a new part number or reuse an existing idempotent allocation."""
        cat_code = series.strip()
        if not SERIES_PATTERN.fullmatch(cat_code):
            raise PartNumberValidationError("series must be a 3-digit string")

        series_rule = resolve_series(self.rules, cat_code)
        dash_str = self._normalize_dash(revision)
        dash_value = int(dash_str)
        normalized_prefix = self._normalize_detail_prefix(series_rule, detail_prefix)
        attrs_payload = self._coerce_attrs(attrs)
        base_key_value = base_key or normalize_base_key(description)
        rule_ver = rule_version(self.rules)

        async with self.db.transaction() as session:
            existing = await self._find_by_idempotency(session, idempotency_key)
            if existing:
                return existing

            series_code = detect_series_code(cat_code)
            await self._ensure_category(session, cat_code, series_rule, series_code)

            ownership, resolved_customer_id = self._resolve_customer_context(series_code, customer_id)
            if ownership and resolved_customer_id is None:
                raise PartNumberValidationError(
                    f"Series {cat_code} requires customer_id or DEFAULT_CUSTOMER_ID"
                )

            item, detail_code, resolved_prefix, detail_suffix = await self._allocate_item(
                session=session,
                cat_code=cat_code,
                series_rule=series_rule,
                detail_prefix=normalized_prefix,
                dash=dash_value,
            )

            pn = self._format_part_number(cat_code, item, dash_str)
            if not self.pattern.fullmatch(pn):
                raise PartNumberValidationError("Generated part number does not match required format")

            linked_pn = None
            if base_key_value:
                linked_pn = await self._find_linked_part(session, base_key_value, pn)

            created_at = await self._store_part(
                session=session,
                pn=pn,
                cat_code=cat_code,
                item=item,
                dash=dash_value,
                rev=None,
                description=description,
                drawing=drawing,
                vendor_id=vendor_id,
                creator=created_by,
                attrs=attrs_payload,
                base_key=base_key_value,
                ownership=ownership,
                customer_id=resolved_customer_id,
                rma_no=rma_no,
                linked_pn=linked_pn,
                detail_prefix=resolved_prefix,
                detail_suffix=detail_suffix,
                detail_code=detail_code,
                note=note,
                rule_version_value=rule_ver,
                idempotency_key=idempotency_key,
                source=source,
            )

            await self._repair_category_counter(session, cat_code, series_rule)

        logger.info(
            "part.generated",
            extra={
                "cat_code": cat_code,
                "item": item,
                "dash": dash_value,
                "part_no": pn,
                "detail_code": detail_code,
                "detail_prefix": resolved_prefix,
                "created_by": created_by,
                "rule_version": rule_ver,
                "idempotency_key": idempotency_key,
            },
        )

        return GeneratedPart(
            part_no=pn,
            series=cat_code,
            serial=item,
            dash=dash_value,
            revision=dash_str,
            detail_code=detail_code,
            detail_prefix=resolved_prefix,
            detail_suffix=detail_suffix,
            created_by=created_by,
            created_at=created_at,
            owner=series_rule.owner,
            series_name=series_rule.name,
            note=note,
            rule_version=rule_ver,
            idempotency_key=idempotency_key,
            base_key=base_key_value,
            customer_id=resolved_customer_id,
            attrs=attrs_payload,
        )

    async def get_part(self, part_no: str) -> GeneratedPart:
        """Load a previously generated part number."""
        if not self.pattern.fullmatch(part_no):
            raise PartNumberValidationError("Part number format invalid")

        async with self.db.transaction() as session:
            if self.db.dialect == "postgres":
                query = (
                    "SELECT p.pn, p.cat_code, p.item, p.dash, p.rev, p.description, p.drawing, "
                    "p.creator, p.created_at, p.attrs, p.base_key, p.ownership, p.customer_id, "
                    "p.rma_no, p.detail_prefix, p.detail_suffix, p.detail_code, p.rule_version, "
                    "p.idempotency_key, p.note, c.name AS category_name, s.name AS series_name "
                    "FROM part p "
                    "JOIN category c ON c.cat_code = p.cat_code "
                    "JOIN series s ON s.series_code = c.series_code "
                    "WHERE p.pn = $1"
                )
                record = await session.fetchrow(query, part_no)
            else:
                query = (
                    "SELECT p.pn, p.cat_code, p.item, p.dash, p.rev, p.description, p.drawing, "
                    "p.creator, p.created_at, p.attrs, p.base_key, p.ownership, p.customer_id, "
                    "p.rma_no, p.detail_prefix, p.detail_suffix, p.detail_code, p.rule_version, "
                    "p.idempotency_key, p.note, c.name AS category_name, s.name AS series_name "
                    "FROM part p "
                    "JOIN category c ON c.cat_code = p.cat_code "
                    "JOIN series s ON s.series_code = c.series_code "
                    "WHERE p.pn = ?"
                )
                record = await session.fetchrow(query, part_no)

        if record is None:
            raise PartNumberNotFoundError("Part number not found")

        return self._hydrate_generated_part(record)

    async def repair_counters(self) -> None:
        """Recompute counters for all categories, mirroring the ETL repair step."""
        async with self.db.transaction() as session:
            if self.db.dialect == "postgres":
                query = (
                    "WITH stats AS ("
                    "  SELECT cat_code, COALESCE(MAX(item), 0) + 1 AS nxt "
                    "  FROM part GROUP BY cat_code"
                    ") "
                    "INSERT INTO counters(cat_code, next_item) "
                    "SELECT cat_code, nxt FROM stats "
                    "ON CONFLICT (cat_code) DO UPDATE SET next_item = EXCLUDED.next_item"
                )
                await session.execute(query)
            else:
                counters: list[tuple[str, int]] = []
                rows = await session.fetchall("SELECT cat_code, COALESCE(MAX(item), 0) AS mx FROM part GROUP BY cat_code")
                for row in rows:
                    cat_code = str(row["cat_code"])
                    maximum = int(row["mx"])
                    counters.append((cat_code, maximum + 1))
                for cat_code, nxt in counters:
                    await session.execute(
                        """
                        INSERT INTO counters(cat_code, next_item)
                        VALUES (?, ?)
                        ON CONFLICT(cat_code) DO UPDATE SET next_item = excluded.next_item
                        """,
                        cat_code,
                        nxt,
                    )

    def _normalize_dash(self, revision: str | None) -> str:
        candidate = revision.strip() if revision else default_revision(self.rules)
        if not REVISION_PATTERN.fullmatch(candidate):
            raise PartNumberValidationError("revision must be exactly two digits")
        return candidate

    def _normalize_detail_prefix(self, series_rule, detail_prefix: str | None) -> str | None:
        length = series_rule.detail_prefix_length or 0
        if length == 0:
            return None
        if detail_prefix is None or detail_prefix.strip() == "":
            if series_rule.detail_prefix_required:
                raise PartNumberValidationError("detail prefix is required for this series")
            return "0" * length
        candidate = detail_prefix.strip()
        if not candidate.isdigit():
            raise PartNumberValidationError("detail prefix must be numeric")
        if len(candidate) != length:
            raise PartNumberValidationError(
                f"detail prefix must be exactly {length} digits for series {series_rule.code}"
            )
        return candidate

    def _detail_suffix_width(self, series_rule) -> int:
        prefix_length = series_rule.detail_prefix_length or 0
        if prefix_length >= self.rules.serial_pad:
            raise PartNumberValidationError(
                f"detail prefix length {prefix_length} is incompatible with serial pad {self.rules.serial_pad}"
            )
        return self.rules.serial_pad - prefix_length

    def _coerce_attrs(self, attrs: dict[str, Any] | None) -> dict[str, Any]:
        if attrs is None:
            return {}
        if not isinstance(attrs, dict):
            raise PartNumberValidationError("attrs must be a JSON object")
        return attrs

    def _resolve_customer_context(
        self,
        series_code: int,
        provided_customer_id: str | None,
    ) -> tuple[str | None, str | None]:
        if series_code in (800, 900):
            return "customer", provided_customer_id or os.getenv("DEFAULT_CUSTOMER_ID")
        return None, provided_customer_id

    async def _allocate_item(
        self,
        *,
        session: DatabaseSession,
        cat_code: str,
        series_rule,
        detail_prefix: str | None,
        dash: int,
    ) -> tuple[int, str, str | None, str]:
        if detail_prefix is None:
            return await self._next_plain_item(session, cat_code, series_rule, dash)
        return await self._next_prefixed_item(session, cat_code, series_rule, detail_prefix, dash)

    async def _next_plain_item(
        self,
        session: DatabaseSession,
        cat_code: str,
        series_rule,
        dash: int,
    ) -> tuple[int, str, None, str]:
        while True:
            candidate = await self._next_counter_value(
                session,
                cat_code,
                seed=series_rule.start_serial,
            )
            if candidate > 9999:
                raise PartNumberValidationError(f"No middle codes remaining for category {cat_code}")
            if await self._is_reserved(session, cat_code, candidate, dash):
                continue
            if await self._part_exists(session, cat_code, candidate, dash):
                continue
            detail_code = str(candidate).zfill(self.rules.serial_pad)
            return candidate, detail_code, None, detail_code

    async def _next_prefixed_item(
        self,
        session: DatabaseSession,
        cat_code: str,
        series_rule,
        detail_prefix: str,
        dash: int,
    ) -> tuple[int, str, str, str]:
        suffix_width = self._detail_suffix_width(series_rule)
        limit = 10**suffix_width
        prefix_value = int(detail_prefix)
        base = prefix_value * limit

        seed = series_rule.start_serial % limit if series_rule.start_serial else 0

        for _ in range(limit):
            suffix = await self._next_suffix_value(
                session,
                cat_code,
                detail_prefix,
                seed=seed,
            )
            if suffix >= limit:
                break
            item = base + suffix
            if item > 9999:
                raise PartNumberValidationError(f"Item value {item} exceeds 4-digit limit for {cat_code}")
            if await self._is_reserved(session, cat_code, item, dash):
                continue
            if await self._part_exists(session, cat_code, item, dash):
                continue
            detail_suffix = str(suffix).zfill(suffix_width)
            detail_code = f"{detail_prefix}{detail_suffix}"
            return item, detail_code, detail_prefix, detail_suffix

        raise PartNumberConflictError(
            f"Exhausted available numbers for prefix {detail_prefix} in category {cat_code}"
        )

    async def _next_counter_value(
        self,
        session: DatabaseSession,
        cat_code: str,
        *,
        seed: int,
    ) -> int:
        if self.db.dialect == "postgres":
            query = (
                "INSERT INTO counters(cat_code, next_item) VALUES ($1, $2 + 1) "
                "ON CONFLICT (cat_code) DO UPDATE SET next_item = counters.next_item + 1 "
                "RETURNING next_item - 1"
            )
            value = await session.fetchval(query, cat_code, seed)
            return int(value)

        row = await session.fetchrow("SELECT next_item FROM counters WHERE cat_code = ?", cat_code)
        if row is None:
            await session.execute(
                "INSERT INTO counters(cat_code, next_item) VALUES (?, ?)",
                cat_code,
                seed + 1,
            )
            return seed

        current = int(row["next_item"])
        await session.execute(
            "UPDATE counters SET next_item = ? WHERE cat_code = ?",
            current + 1,
            cat_code,
        )
        return current

    async def _next_suffix_value(
        self,
        session: DatabaseSession,
        cat_code: str,
        detail_prefix: str,
        *,
        seed: int,
    ) -> int:
        if self.db.dialect == "postgres":
            query = (
                "INSERT INTO detail_counters(cat_code, detail_prefix, next_suffix) "
                "VALUES ($1, $2, $3 + 1) "
                "ON CONFLICT (cat_code, detail_prefix) DO UPDATE "
                "SET next_suffix = detail_counters.next_suffix + 1 "
                "RETURNING next_suffix - 1"
            )
            value = await session.fetchval(query, cat_code, detail_prefix, seed)
            return int(value)

        row = await session.fetchrow(
            "SELECT next_suffix FROM detail_counters WHERE cat_code = ? AND detail_prefix = ?",
            cat_code,
            detail_prefix,
        )
        if row is None:
            await session.execute(
                "INSERT INTO detail_counters(cat_code, detail_prefix, next_suffix) VALUES (?, ?, ?)",
                cat_code,
                detail_prefix,
                seed + 1,
            )
            return seed

        current = int(row["next_suffix"])
        await session.execute(
            "UPDATE detail_counters SET next_suffix = ? WHERE cat_code = ? AND detail_prefix = ?",
            current + 1,
            cat_code,
            detail_prefix,
        )
        return current

    async def _is_reserved(
        self,
        session: DatabaseSession,
        cat_code: str,
        item: int,
        dash: int,
    ) -> bool:
        if self.db.dialect == "postgres":
            query = (
                "SELECT 1 FROM reserved_numbers "
                "WHERE cat_code = $1 AND item = $2 AND (dash IS NULL OR dash = $3) LIMIT 1"
            )
            row = await session.fetchrow(query, cat_code, item, dash)
        else:
            query = (
                "SELECT 1 FROM reserved_numbers "
                "WHERE cat_code = ? AND item = ? AND (dash IS NULL OR dash = ?) LIMIT 1"
            )
            row = await session.fetchrow(query, cat_code, item, dash)
        return row is not None

    async def _part_exists(
        self,
        session: DatabaseSession,
        cat_code: str,
        item: int,
        dash: int,
    ) -> bool:
        if self.db.dialect == "postgres":
            query = (
                "SELECT 1 FROM part WHERE cat_code = $1 AND item = $2 AND dash = $3 LIMIT 1"
            )
            row = await session.fetchrow(query, cat_code, item, dash)
        else:
            query = (
                "SELECT 1 FROM part WHERE cat_code = ? AND item = ? AND dash = ? LIMIT 1"
            )
            row = await session.fetchrow(query, cat_code, item, dash)
        return row is not None

    async def _ensure_category(
        self,
        session: DatabaseSession,
        cat_code: str,
        series_rule,
        series_code: int,
    ) -> None:
        part_type = infer_part_type(series_code)
        name = series_rule.name or f"Series {series_code}"

        if self.db.dialect == "postgres":
            query = (
                "INSERT INTO category (cat_code, series_code, name, part_type) "
                "VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (cat_code) DO UPDATE SET "
                "series_code = EXCLUDED.series_code, "
                "name = COALESCE(category.name, EXCLUDED.name), "
                "part_type = COALESCE(category.part_type, EXCLUDED.part_type)"
            )
            await session.execute(query, cat_code, series_code, name, part_type)
        else:
            query = (
                "INSERT INTO category(cat_code, series_code, name, part_type) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(cat_code) DO UPDATE SET "
                "series_code = excluded.series_code, "
                "name = COALESCE(category.name, excluded.name), "
                "part_type = COALESCE(category.part_type, excluded.part_type)"
            )
            await session.execute(query, cat_code, series_code, name, part_type)

        await self._ensure_counter_seed(session, cat_code, series_rule.start_serial)

    async def _ensure_counter_seed(
        self,
        session: DatabaseSession,
        cat_code: str,
        start_serial: int,
    ) -> None:
        if self.db.dialect == "postgres":
            query = (
                "INSERT INTO counters(cat_code, next_item) VALUES ($1, $2) "
                "ON CONFLICT (cat_code) DO UPDATE SET "
                "next_item = GREATEST(counters.next_item, EXCLUDED.next_item)"
            )
            await session.execute(query, cat_code, start_serial)
        else:
            await session.execute(
                """
                INSERT INTO counters(cat_code, next_item) VALUES (?, ?)
                ON CONFLICT(cat_code) DO UPDATE SET
                  next_item = CASE
                    WHEN counters.next_item < excluded.next_item THEN excluded.next_item
                    ELSE counters.next_item
                  END
                """,
                cat_code,
                start_serial,
            )

    async def _repair_category_counter(
        self,
        session: DatabaseSession,
        cat_code: str,
        series_rule,
    ) -> None:
        row = await session.fetchrow(
            "SELECT MAX(item) AS mx FROM part WHERE cat_code = ?" if self.db.dialect == "sqlite" else
            "SELECT MAX(item) AS mx FROM part WHERE cat_code = $1",
            cat_code,
        )
        maximum = row["mx"] if row is not None else None
        if maximum is None:
            next_item = series_rule.start_serial
        else:
            max_int = int(maximum)
            next_item = max(max_int + 1, series_rule.start_serial)

        if self.db.dialect == "postgres":
            query = (
                "INSERT INTO counters(cat_code, next_item) VALUES ($1, $2) "
                "ON CONFLICT (cat_code) DO UPDATE SET next_item = EXCLUDED.next_item"
            )
            await session.execute(query, cat_code, next_item)
        else:
            await session.execute(
                """
                INSERT INTO counters(cat_code, next_item) VALUES (?, ?)
                ON CONFLICT(cat_code) DO UPDATE SET next_item = excluded.next_item
                """,
                cat_code,
                next_item,
            )

    async def _find_linked_part(
        self,
        session: DatabaseSession,
        base_key: str,
        new_part_no: str,
    ) -> str | None:
        if self.db.dialect == "postgres":
            query = (
                "SELECT pn FROM part WHERE base_key = $1 AND pn <> $2 "
                "ORDER BY created_at ASC LIMIT 1"
            )
            row = await session.fetchrow(query, base_key, new_part_no)
        else:
            query = (
                "SELECT pn FROM part WHERE base_key = ? AND pn <> ? "
                "ORDER BY created_at ASC LIMIT 1"
            )
            row = await session.fetchrow(query, base_key, new_part_no)
        if row is None:
            return None
        return str(row["pn"])

    async def _find_by_idempotency(
        self,
        session: DatabaseSession,
        idempotency_key: str | None,
    ) -> GeneratedPart | None:
        if not idempotency_key:
            return None

        if self.db.dialect == "postgres":
            query = "SELECT * FROM part WHERE idempotency_key = $1"
            record = await session.fetchrow(query, idempotency_key)
        else:
            query = "SELECT * FROM part WHERE idempotency_key = ?"
            record = await session.fetchrow(query, idempotency_key)
        if record is None:
            return None

        return self._hydrate_generated_part(record)

    async def _store_part(
        self,
        *,
        session: DatabaseSession,
        pn: str,
        cat_code: str,
        item: int,
        dash: int,
        rev: str | None,
        description: str | None,
        drawing: str | None,
        vendor_id: int | None,
        creator: str,
        attrs: dict[str, Any],
        base_key: str | None,
        ownership: str | None,
        customer_id: str | None,
        rma_no: str | None,
        linked_pn: str | None,
        detail_prefix: str | None,
        detail_suffix: str,
        detail_code: str,
        note: str | None,
        rule_version_value: str | None,
        idempotency_key: str | None,
        source: str,
    ) -> str:
        attrs_payload: Any
        if self.db.dialect == "postgres":
            attrs_payload = attrs
            query = (
                "INSERT INTO part ("
                "pn, cat_code, item, dash, rev, status, description, drawing, "
                "vendor_id, creator, attrs, base_key, ownership, customer_id, "
                "rma_no, linked_pn, detail_prefix, detail_suffix, detail_code, "
                "rule_version, idempotency_key, note, source"
                ") VALUES ("
                "$1, $2, $3, $4, $5, 'active', $6, $7, "
                "$8, $9, $10, $11, $12, $13, "
                "$14, $15, $16, $17, $18, "
                "$19, $20, $21, $22"
                ") RETURNING created_at"
            )
            params = (
                pn,
                cat_code,
                item,
                dash,
                rev,
                description,
                drawing,
                vendor_id,
                creator,
                attrs_payload,
                base_key,
                ownership,
                customer_id,
                rma_no,
                linked_pn,
                detail_prefix,
                detail_suffix,
                detail_code,
                rule_version_value,
                idempotency_key,
                note,
                source,
            )
            try:
                created_at = await session.fetchval(query, *params)
            except UniqueViolationError as exc:
                raise PartNumberConflictError("Part number already exists") from exc
        else:
            attrs_payload = json.dumps(attrs)
            query = (
                "INSERT INTO part ("
                "pn, cat_code, item, dash, rev, status, description, drawing, "
                "vendor_id, creator, attrs, base_key, ownership, customer_id, "
                "rma_no, linked_pn, detail_prefix, detail_suffix, detail_code, "
                "rule_version, idempotency_key, note, source"
                ") VALUES ("
                "?, ?, ?, ?, ?, 'active', ?, ?, "
                "?, ?, ?, ?, ?, ?, "
                "?, ?, ?, ?, ?, "
                "?, ?, ?, ?"
                ")"
            )
            params = (
                pn,
                cat_code,
                item,
                dash,
                rev,
                description,
                drawing,
                vendor_id,
                creator,
                attrs_payload,
                base_key,
                ownership,
                customer_id,
                rma_no,
                linked_pn,
                detail_prefix,
                detail_suffix,
                detail_code,
                rule_version_value,
                idempotency_key,
                note,
                source,
            )
            try:
                await session.execute(query, *params)
            except SQLiteIntegrityError as exc:
                raise PartNumberConflictError("Part number already exists") from exc
            created_at = await session.fetchval(
                "SELECT created_at FROM part WHERE pn = ?",
                pn,
            )

        if created_at is None:
            raise PartNumberError("Failed to persist part record")
        return self._serialize_created_at(created_at)

    def _format_part_number(self, cat_code: str, item: int, dash: str) -> str:
        return f"{cat_code}-{item:04d}-{dash}"

    def _parse_attrs(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value:
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                logger.debug("Failed to parse attrs JSON", exc_info=True)
        return {}

    def _hydrate_generated_part(self, record: dict[str, Any]) -> GeneratedPart:
        cat_code = str(record["cat_code"])
        series_rule = resolve_series(self.rules, cat_code)
        item = int(record["item"])
        dash = int(record["dash"])
        detail_code = record.get("detail_code") or str(item).zfill(self.rules.serial_pad)
        detail_prefix = record.get("detail_prefix")
        detail_suffix = record.get("detail_suffix") or detail_code[-(self._detail_suffix_width(series_rule)) :]
        revision = f"{dash:02d}"
        attrs = self._parse_attrs(record.get("attrs"))
        created_at = self._serialize_created_at(record.get("created_at"))
        base_key = record.get("base_key")
        rule_ver = record.get("rule_version")
        idempotency_key = record.get("idempotency_key")
        note = record.get("note")
        customer_id = record.get("customer_id")
        series_name = record.get("series_name") or series_rule.name

        creator = record.get("creator") or ""

        return GeneratedPart(
            part_no=str(record["pn"]),
            series=cat_code,
            serial=item,
            dash=dash,
            revision=revision,
            detail_code=detail_code,
            detail_prefix=detail_prefix,
            detail_suffix=detail_suffix,
            created_by=creator,
            created_at=created_at,
            owner=series_rule.owner,
            series_name=series_name,
            note=note,
            rule_version=rule_ver,
            idempotency_key=idempotency_key,
            base_key=base_key,
            customer_id=customer_id,
            attrs=attrs,
        )

    @staticmethod
    def _serialize_created_at(value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        if value is None:
            return datetime.utcnow().isoformat()
        return str(value)
