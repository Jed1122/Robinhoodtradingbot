"""Exact-match capability lookup, documented fixtures, and matrix rendering."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from trading_bot.capabilities.models import (
    CapabilityEvidence,
    CapabilityManifest,
    CapabilityNotFoundError,
    CapabilityRecord,
    EvidenceLevel,
    InvalidCapabilityManifest,
    OperationKind,
    UnsupportedCapabilityError,
)
from trading_bot.domain import AssetClass

__all__ = [
    "UnsupportedCapabilityError",
    "load_capability_manifest",
    "render_capability_matrix",
    "require_capability",
]


def require_capability(
    manifest: CapabilityManifest,
    *,
    provider: str,
    operation: str,
    minimum: EvidenceLevel,
) -> CapabilityRecord:
    """Require an exact unlocked evidence category for a provider operation."""
    try:
        record = manifest.find(provider=provider, operation=operation)
    except CapabilityNotFoundError:
        raise UnsupportedCapabilityError(provider, operation, minimum) from None
    if not record.satisfies(minimum):
        raise UnsupportedCapabilityError(provider, operation, minimum)
    return record


def load_capability_manifest(path: Path) -> CapabilityManifest:
    """Load a strict public-evidence fixture into validated immutable records."""
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        root = _mapping(raw)
        if root.get("format_version") != 1:
            raise ValueError
        records_raw = _list(root["records"])
        records = tuple(_parse_record(item) for item in records_raw)
    except (KeyError, TypeError, ValueError):
        raise InvalidCapabilityManifest("capability fixture is invalid") from None
    return CapabilityManifest(records=records)


def render_capability_matrix(manifest: CapabilityManifest) -> str:
    """Render a stable Markdown view without implying adapter implementation."""
    lines = [
        "| Provider | Operation | Asset | Kind | Evidence | State | Limitations |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in manifest.records:
        levels = ", ".join(sorted(item.level.value for item in record.evidence))
        limitations = "; ".join(sorted(record.limitations)) or "none recorded"
        lines.append(
            "| "
            + " | ".join(
                (
                    _markdown(record.provider),
                    f"`{_markdown(record.operation)}`",
                    record.asset_class.value,
                    record.operation_kind.value,
                    _markdown(levels),
                    _matrix_state(record),
                    _markdown(limitations),
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _parse_record(raw: object) -> CapabilityRecord:
    value = _mapping(raw)
    return CapabilityRecord(
        provider=_string(value["provider"]),
        operation=_string(value["operation"]),
        asset_class=AssetClass(_string(value["asset_class"])),
        operation_kind=OperationKind(_string(value["operation_kind"])),
        evidence=tuple(_parse_evidence(item) for item in _list(value["evidence"])),
        limitations=tuple(_string(item) for item in _list(value["limitations"])),
        locked_reason=_optional_string(value["locked_reason"]),
    )


def _parse_evidence(raw: object) -> CapabilityEvidence:
    value = _mapping(raw)
    observed_at = datetime.fromisoformat(_string(value["observed_at"]).replace("Z", "+00:00"))
    return CapabilityEvidence(
        level=EvidenceLevel(_string(value["level"])),
        source_uri=_string(value["source_uri"]),
        observed_at=observed_at,
        schema_sha256=_optional_string(value["schema_sha256"]),
        authenticated=_boolean(value["authenticated"]),
        contains_account_data=_boolean(value["contains_account_data"]),
        notes=tuple(_string(item) for item in _list(value["notes"])),
    )


def _matrix_state(record: CapabilityRecord) -> str:
    levels = frozenset(item.level for item in record.evidence)
    if levels == {EvidenceLevel.UNSUPPORTED}:
        return "unsupported_locked"
    if record.locked_reason is not None and EvidenceLevel.DOCUMENTED in levels:
        return "documented_locked_external_pending"
    if record.locked_reason is not None:
        return "locked_external_pending"
    if EvidenceLevel.SCHEMA_DECLARED in levels:
        return "schema_declared_only"
    return "evidence_recorded_not_implemented"


def _markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _mapping(value: object) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise TypeError
    return value


def _list(value: object) -> list[Any]:
    if type(value) is not list:
        raise TypeError
    return value


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError
    return value
