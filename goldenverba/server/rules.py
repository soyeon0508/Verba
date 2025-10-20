from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class RulesError(Exception):
    """Base exception raised for rule configuration issues."""


class RuleValidationError(RulesError):
    """Raised when the rules.yml file fails validation."""


@dataclass(frozen=True)
class SeriesRule:
    code: str
    name: str
    owner: str
    start_serial: int
    detail_prefix_length: int = 0
    detail_prefix_required: bool = False
    detail_prefix_label: str | None = None
    detail_prefix_hint: str | None = None


@dataclass
class RuleSet:
    pattern: str
    serial_pad: int
    revision_pad: int
    revision_default: str
    scope: str
    series: dict[str, SeriesRule]
    reserved_serial_ranges: list[Any]
    blocklist_series: list[str]
    meta_version: str
    meta_notes: str
    version_hash: str


def load_rules(path: Path | None = None) -> RuleSet:
    if path is not None:
        rules_path = path
    else:
        candidates = [
            Path("config/rules.yml"),
            Path(__file__).resolve().parents[2] / "config" / "rules.yml",
        ]
        rules_path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    if not rules_path.exists():
        raise RuleValidationError(f"Rules file not found: {rules_path}")

    with rules_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise RuleValidationError("rules.yml must contain a mapping at the top level")

    format_section = data.get("format")
    if not isinstance(format_section, dict):
        raise RuleValidationError("format section must be a mapping")

    pattern = format_section.get("pattern")
    serial_pad = format_section.get("serial_pad")
    revision_pad = format_section.get("revision_pad")
    revision_default = format_section.get("revision_default")

    if not isinstance(pattern, str) or not pattern:
        raise RuleValidationError("format.pattern must be a non-empty string")
    if not isinstance(serial_pad, int) or serial_pad <= 0:
        raise RuleValidationError("format.serial_pad must be a positive integer")
    if not isinstance(revision_pad, int) or revision_pad <= 0:
        raise RuleValidationError("format.revision_pad must be a positive integer")
    if not isinstance(revision_default, str) or len(revision_default) != revision_pad:
        raise RuleValidationError("format.revision_default must be a string matching revision_pad length")

    counters_section = data.get("counters")
    if not isinstance(counters_section, dict):
        raise RuleValidationError("counters section must be a mapping")

    scope = counters_section.get("scope")
    if scope != "per_series":
        raise RuleValidationError("counters.scope must be 'per_series'")

    series_section = data.get("series")
    if not isinstance(series_section, dict) or not series_section:
        raise RuleValidationError("series section must be a non-empty mapping")

    series_rules: dict[str, SeriesRule] = {}
    for code, entry in series_section.items():
        if not isinstance(code, str) or len(code) != 3 or not code.isdigit():
            raise RuleValidationError(f"series key '{code}' must be a 3-digit string")
        if not isinstance(entry, dict):
            raise RuleValidationError(f"series entry for '{code}' must be a mapping")
        name = entry.get("name")
        owner = entry.get("owner")
        start_serial = entry.get("start_serial")
        if not isinstance(name, str) or not name:
            raise RuleValidationError(f"series '{code}' missing 'name'")
        if not isinstance(owner, str) or not owner:
            raise RuleValidationError(f"series '{code}' missing 'owner'")
        if not isinstance(start_serial, int) or start_serial <= 0:
            raise RuleValidationError(f"series '{code}' start_serial must be a positive integer")

        detail_info = entry.get("detail_prefix")
        detail_prefix_length = 0
        detail_prefix_required = False
        detail_prefix_label: str | None = None
        detail_prefix_hint: str | None = None
        if detail_info is not None:
            if not isinstance(detail_info, dict):
                raise RuleValidationError(f"series '{code}' detail_prefix must be a mapping if provided")
            detail_prefix_length = detail_info.get("length", 0) or 0
            if not isinstance(detail_prefix_length, int) or detail_prefix_length < 0:
                raise RuleValidationError(f"series '{code}' detail_prefix.length must be a non-negative integer")
            if detail_prefix_length > serial_pad:
                raise RuleValidationError(
                    f"series '{code}' detail_prefix.length ({detail_prefix_length}) exceeds serial_pad ({serial_pad})"
                )
            detail_prefix_required = bool(detail_info.get("required", False))
            label = detail_info.get("label")
            hint = detail_info.get("hint")
            if label is not None and not isinstance(label, str):
                raise RuleValidationError(f"series '{code}' detail_prefix.label must be a string if provided")
            if hint is not None and not isinstance(hint, str):
                raise RuleValidationError(f"series '{code}' detail_prefix.hint must be a string if provided")
            detail_prefix_label = label
            detail_prefix_hint = hint

        series_rules[code] = SeriesRule(
            code=code,
            name=name,
            owner=owner,
            start_serial=start_serial,
            detail_prefix_length=detail_prefix_length,
            detail_prefix_required=detail_prefix_required,
            detail_prefix_label=detail_prefix_label,
            detail_prefix_hint=detail_prefix_hint,
        )

    constraints_section = data.get("constraints", {})
    if not isinstance(constraints_section, dict):
        raise RuleValidationError("constraints section must be a mapping")

    reserved_serial_ranges = constraints_section.get("reserved_serial_ranges", [])
    blocklist_series = constraints_section.get("blocklist_series", [])
    if not isinstance(reserved_serial_ranges, list) or not isinstance(blocklist_series, list):
        raise RuleValidationError("constraints reserved_serial_ranges and blocklist_series must be lists")

    meta_section = data.get("meta", {})
    if not isinstance(meta_section, dict):
        raise RuleValidationError("meta section must be a mapping")
    meta_version = meta_section.get("version")
    meta_notes = meta_section.get("notes", "")
    if not isinstance(meta_version, str) or not meta_version:
        raise RuleValidationError("meta.version must be a non-empty string")
    if not isinstance(meta_notes, str):
        raise RuleValidationError("meta.notes must be a string")

    version_hash = hashlib.sha256(meta_version.encode("utf-8")).hexdigest()

    return RuleSet(
        pattern=pattern,
        serial_pad=serial_pad,
        revision_pad=revision_pad,
        revision_default=revision_default,
        scope=scope,
        series=series_rules,
        reserved_serial_ranges=reserved_serial_ranges,
        blocklist_series=[str(item) for item in blocklist_series],
        meta_version=meta_version,
        meta_notes=meta_notes,
        version_hash=version_hash,
    )


def resolve_series(rules: RuleSet, series_code: str) -> SeriesRule:
    if series_code in rules.blocklist_series:
        raise RuleValidationError(f"Series '{series_code}' is blocked")
    try:
        return rules.series[series_code]
    except KeyError as exc:
        raise RuleValidationError(f"Unknown series '{series_code}'") from exc


def default_revision(rules: RuleSet) -> str:
    return rules.revision_default


def pad_serial(rules: RuleSet, serial: int) -> str:
    return str(serial).zfill(rules.serial_pad)


def rule_version(rules: RuleSet) -> str:
    return rules.version_hash


class RulesResolver:
    """Load and cache the part-number rule set."""

    def __init__(self, path: Path | None = None):
        self._path = path
        self._rules = load_rules(path)

    def resolve(self) -> RuleSet:
        """Return the cached rules."""
        return self._rules

    def reload(self) -> RuleSet:
        """Reload rules from disk."""
        self._rules = load_rules(self._path)
        return self._rules

    def __call__(self) -> RuleSet:
        return self.resolve()
