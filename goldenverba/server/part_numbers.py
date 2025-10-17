from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from dataclasses import dataclass
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
from goldenverba.server.rules import RuleSet, default_revision, resolve_series, rule_version

logger = logging.getLogger(__name__)


class PartNumberError(Exception):
    pass


class PartNumberValidationError(PartNumberError):
    pass


class PartNumberConflictError(PartNumberError):
    pass


class PartNumberNotFoundError(PartNumberError):
    pass


@dataclass
class GeneratedPart:
    part_no: str
    series: str
    serial: int
    revision: str
    created_by: str
    owner: str
    series_name: str
    note: str | None
    rule_version: str
    idempotency_key: str | None
    created_at: str
    detail_code: str
    detail_prefix: str | None
    detail_suffix: str


class PartNumberService:
    def __init__(
        self,
        db: Database,
        rules: RuleSet,
    ):
        self.db = db
        self.rules = rules
        self.pattern = re.compile(self.rules.pattern)

    async def generate_part(
        self,
        *,
        series: str,
        created_by: str,
        revision: str | None = None,
        detail_prefix: str | None = None,
        note: str | None = None,
        idempotency_key: str | None = None,
        source: str = "api",
    ) -> GeneratedPart:
        if not series or not series.isdigit() or len(series) != 3:
            raise PartNumberValidationError("series must be a 3-digit string")

        series_rule = resolve_series(self.rules, series)
        revision_value = revision or default_revision(self.rules)
        if len(revision_value) != self.rules.revision_pad or not revision_value.isdigit():
            raise PartNumberValidationError("revision must be numeric and match configured length")

        normalized_prefix = self._normalize_detail_prefix(series_rule, detail_prefix)
        detail_code = ""
        resolved_prefix: str | None = normalized_prefix
        detail_suffix = ""

        async with self.db.transaction() as session:
            existing = await self._find_by_idempotency(session, idempotency_key)
            if existing:
                return existing

            serial = await self._next_serial(session, series_rule, normalized_prefix)
            detail_code, resolved_prefix, detail_suffix = self._compose_detail_code(
                series_rule=series_rule,
                serial_value=serial,
                detail_prefix=normalized_prefix,
            )
            part_no = f"{series}-{detail_code}-{revision_value}"

            if not self.pattern.fullmatch(part_no):
                raise PartNumberValidationError("Generated part number does not match required format")

            created_at = await self._store_part(
                session=session,
                part_no=part_no,
                series_rule=series_rule,
                serial=serial,
                revision=revision_value,
                created_by=created_by,
                note=note,
                idempotency_key=idempotency_key,
                source=source,
            )

        logger.info(
            "part.generated",
            extra={
                "series": series,
                "serial": serial,
                "part_no": part_no,
                "detail_code": detail_code,
                "detail_prefix": resolved_prefix,
                "created_by": created_by,
                "rule_version": rule_version(self.rules),
                "idempotency_key": idempotency_key,
            },
        )

        return GeneratedPart(
            part_no=part_no,
            series=series,
            serial=serial,
            revision=revision_value,
            created_by=created_by,
            owner=series_rule.owner,
            series_name=series_rule.name,
            note=note,
            rule_version=rule_version(self.rules),
            idempotency_key=idempotency_key,
            created_at=created_at,
            detail_code=detail_code,
            detail_prefix=resolved_prefix,
            detail_suffix=detail_suffix,
        )

    async def get_part(self, part_no: str) -> GeneratedPart:
        if not self.pattern.fullmatch(part_no):
            raise PartNumberValidationError("Part number format invalid")

        async with self.db.transaction() as session:
            query = (
                "SELECT part_no, series, serial, revision, created_by, created_at, owner, "
                "series_name, note, rule_version, idempotency_key, source "
                "FROM parts WHERE part_no = $1"
                if self.db.dialect == "postgres"
                else "SELECT part_no, series, serial, revision, created_by, created_at, owner, "
                "series_name, note, rule_version, idempotency_key, source "
                "FROM parts WHERE part_no = ?"
            )
            record = await session.fetchrow(query, part_no)

        if record is None:
            raise PartNumberNotFoundError("Part number not found")
        return self._hydrate_generated_part(record)

    async def _find_by_idempotency(
        self, session: DatabaseSession, idempotency_key: str | None
    ) -> GeneratedPart | None:
        if not idempotency_key:
            return None

        query = (
            "SELECT part_no, series, serial, revision, created_by, created_at, owner, series_name, note, rule_version, idempotency_key "
            "FROM parts WHERE idempotency_key = $1"
            if self.db.dialect == "postgres"
            else "SELECT part_no, series, serial, revision, created_by, created_at, owner, series_name, note, rule_version, idempotency_key "
            "FROM parts WHERE idempotency_key = ?"
        )
        record = await session.fetchrow(query, idempotency_key)
        if record is None:
            return None

        return self._hydrate_generated_part(record)

    async def _next_serial(
        self,
        session: DatabaseSession,
        series_rule,
        detail_prefix: str | None,
    ) -> int:
        starting_value = series_rule.start_serial
        counter_key = series_rule.code
        if series_rule.detail_prefix_length > 0 and detail_prefix is not None:
            counter_key = f"{series_rule.code}:{detail_prefix}"
        query = (
            "INSERT INTO counters(key, val) VALUES ($1, $2) "
            "ON CONFLICT (key) DO UPDATE SET val = counters.val + 1 "
            "RETURNING val"
            if self.db.dialect == "postgres"
            else "INSERT INTO counters(key, val) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET val = val + 1 RETURNING val"
        )
        value = await session.fetchval(query, counter_key, starting_value)
        if value is None:
            raise PartNumberError("Failed to increment counter")
        return int(value)

    def _normalize_detail_prefix(self, series_rule, detail_prefix: str | None) -> str | None:
        length = series_rule.detail_prefix_length if series_rule.detail_prefix_length else 0
        if length <= 0:
            return None
        if detail_prefix is None or detail_prefix.strip() == "":
            if series_rule.detail_prefix_required:
                raise PartNumberValidationError("detail prefix is required for this series")
            return "0" * length
        candidate = detail_prefix.strip()
        if not candidate.isdigit():
            raise PartNumberValidationError("detail prefix must be numeric")
        if len(candidate) > length:
            raise PartNumberValidationError(
                f"detail prefix must be {length} digits or fewer for series {series_rule.code}"
            )
        return candidate.zfill(length)

    def _suffix_pad(self, series_rule) -> int:
        prefix_length = series_rule.detail_prefix_length if series_rule.detail_prefix_length else 0
        if prefix_length >= self.rules.serial_pad:
            raise PartNumberValidationError(
                f"detail prefix length {prefix_length} is incompatible with serial pad {self.rules.serial_pad}"
            )
        return self.rules.serial_pad - prefix_length if prefix_length > 0 else self.rules.serial_pad

    def _compose_detail_code(
        self,
        *,
        series_rule,
        serial_value: int,
        detail_prefix: str | None,
    ) -> tuple[str, str | None, str]:
        if series_rule.detail_prefix_length > 0:
            suffix_pad = self._suffix_pad(series_rule)
            suffix = str(serial_value).zfill(suffix_pad)
            prefix = detail_prefix if detail_prefix is not None else "0" * series_rule.detail_prefix_length
            detail_code = f"{prefix}{suffix}"
            return detail_code, prefix, suffix
        detail_code = str(serial_value).zfill(self.rules.serial_pad)
        return detail_code, None, detail_code

    def _detail_from_part_no(
        self,
        series_rule,
        part_no: str,
        serial_value: int,
    ) -> tuple[str, str | None, str]:
        try:
            _, detail_code, _ = part_no.split("-")
        except ValueError:
            detail_code = ""
        if series_rule.detail_prefix_length > 0:
            prefix_length = min(series_rule.detail_prefix_length, len(detail_code))
            detail_prefix = detail_code[:prefix_length] if detail_code else None
            suffix = detail_code[prefix_length:]
            if not suffix:
                suffix = str(serial_value).zfill(self._suffix_pad(series_rule))
            if detail_prefix is None and series_rule.detail_prefix_length > 0:
                detail_prefix = "0" * series_rule.detail_prefix_length
            if not detail_code:
                detail_code = (detail_prefix or "") + suffix
            return detail_code, detail_prefix, suffix
        suffix = detail_code or str(serial_value).zfill(self.rules.serial_pad)
        detail_code = detail_code or suffix
        return detail_code, None, suffix

    def _hydrate_generated_part(self, record: dict[str, Any]) -> GeneratedPart:
        series = str(record["series"])
        series_rule = resolve_series(self.rules, series)
        serial_value = int(record["serial"])
        detail_code, detail_prefix, detail_suffix = self._detail_from_part_no(
            series_rule,
            record["part_no"],
            serial_value,
        )
        return GeneratedPart(
            part_no=record["part_no"],
            series=series,
            serial=serial_value,
            revision=record["revision"],
            created_by=record["created_by"],
            owner=record.get("owner") or series_rule.owner,
            series_name=record.get("series_name") or series_rule.name,
            note=record.get("note"),
            rule_version=record.get("rule_version") or rule_version(self.rules),
            idempotency_key=record.get("idempotency_key"),
            created_at=self._serialize_created_at(record.get("created_at")),
            detail_code=detail_code,
            detail_prefix=detail_prefix,
            detail_suffix=detail_suffix,
        )


    async def _store_part(
        self,
        *,
        session: DatabaseSession,
        part_no: str,
        series_rule,
        serial: int,
        revision: str,
        created_by: str,
        note: str | None,
        idempotency_key: str | None,
        source: str,
    ) -> str:
        params = (
            part_no,
            series_rule.code,
            serial,
            revision,
            created_by,
            series_rule.owner,
            series_rule.name,
            note,
            rule_version(self.rules),
            idempotency_key,
            source,
        )
        try:
            if self.db.dialect == "postgres":
                query = (
                    "INSERT INTO parts(part_no, series, serial, revision, created_by, owner, series_name, note, rule_version, idempotency_key, source) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) RETURNING created_at"
                )
                created_at = await session.fetchval(query, *params)
            else:
                query = (
                    "INSERT INTO parts(part_no, series, serial, revision, created_by, owner, series_name, note, rule_version, idempotency_key, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                )
                await session.execute(query, *params)
                created_at = await session.fetchval(
                    "SELECT created_at FROM parts WHERE part_no = ?",
                    part_no,
                )
        except UniqueViolationError as exc:
            raise PartNumberConflictError("Part number already exists") from exc
        except SQLiteIntegrityError as exc:
            raise PartNumberConflictError("Part number already exists") from exc

        if created_at is None:
            raise PartNumberError("Failed to persist part record")

        return self._serialize_created_at(created_at)

    @staticmethod
    def _serialize_created_at(value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)
