"""Exact-match capability lookup, documented fixtures, and matrix rendering."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Never

from trading_bot.capabilities.models import (
    CapabilityEvidence,
    CapabilityManifest,
    CapabilityRecord,
    EvidenceLevel,
    InvalidCapabilityManifest,
    OperationKind,
    UnsupportedCapabilityError,
    validated_manifest_copy,
)
from trading_bot.capabilities.snapshot import text_contains_sensitive_material
from trading_bot.clock import require_utc
from trading_bot.domain import AssetClass

_ROOT_FIELDS = frozenset({"format_version", "checked_at", "records"})
_RECORD_FIELDS = frozenset(
    {
        "provider",
        "operation",
        "asset_class",
        "operation_kind",
        "evidence",
        "limitations",
        "locked_reason",
    }
)
_EVIDENCE_FIELDS = frozenset(
    {
        "level",
        "source_uri",
        "observed_at",
        "schema_sha256",
        "authenticated",
        "contains_account_data",
        "notes",
    }
)

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
    validated: CapabilityManifest | None = None
    try:
        validated = validated_manifest_copy(manifest)
    except MemoryError:
        raise
    except Exception:
        pass
    if validated is None:
        raise UnsupportedCapabilityError(provider, operation, minimum) from None
    record = next(
        (
            item
            for item in validated.records
            if item.provider == provider and item.operation == operation
        ),
        None,
    )
    if record is None:
        raise UnsupportedCapabilityError(provider, operation, minimum) from None
    if not record.satisfies(minimum):
        raise UnsupportedCapabilityError(provider, operation, minimum) from None
    return record


def load_capability_manifest(path: Path) -> CapabilityManifest:
    """Load a strict public-evidence fixture into validated immutable records."""
    manifest: CapabilityManifest | None = None
    invalid = False
    try:
        raw: object = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite_constant,
        )
        root = _mapping(raw)
        _require_exact_fields(root, _ROOT_FIELDS)
        if type(root["format_version"]) is not int or root["format_version"] != 1:
            raise ValueError
        checked_at = datetime.fromisoformat(_string(root["checked_at"]).replace("Z", "+00:00"))
        require_utc(checked_at)
        records_raw = _list(root["records"])
        records = tuple(_parse_record(item) for item in records_raw)
        manifest = CapabilityManifest(records=records)
    except MemoryError:
        raise
    except Exception:
        invalid = True
    if invalid or manifest is None:
        raise InvalidCapabilityManifest("capability fixture is invalid") from None
    return manifest


def render_capability_matrix(manifest: CapabilityManifest) -> str:
    """Render a stable Markdown view without implying adapter implementation."""
    validated: CapabilityManifest | None = None
    try:
        validated = validated_manifest_copy(manifest)
    except MemoryError:
        raise
    except Exception:
        pass
    if validated is None or not _manifest_freeform_is_safe(validated):
        raise InvalidCapabilityManifest("capability manifest contains unsafe text") from None
    lines = [
        "| Provider | Operation | Asset | Kind | Evidence | State | Limitations |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in validated.records:
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
    _require_exact_fields(value, _RECORD_FIELDS)
    return CapabilityRecord(
        provider=_safe_freeform_string(value["provider"]),
        operation=_safe_freeform_string(value["operation"]),
        asset_class=AssetClass(_string(value["asset_class"])),
        operation_kind=OperationKind(_string(value["operation_kind"])),
        evidence=tuple(_parse_evidence(item) for item in _list(value["evidence"])),
        limitations=tuple(_safe_freeform_string(item) for item in _list(value["limitations"])),
        locked_reason=_optional_safe_freeform_string(value["locked_reason"]),
    )


def _parse_evidence(raw: object) -> CapabilityEvidence:
    value = _mapping(raw)
    _require_exact_fields(value, _EVIDENCE_FIELDS)
    observed_at = datetime.fromisoformat(_string(value["observed_at"]).replace("Z", "+00:00"))
    return CapabilityEvidence(
        level=EvidenceLevel(_string(value["level"])),
        source_uri=_safe_source_uri_string(value["source_uri"]),
        observed_at=observed_at,
        schema_sha256=_optional_string(value["schema_sha256"]),
        authenticated=_boolean(value["authenticated"]),
        contains_account_data=_boolean(value["contains_account_data"]),
        notes=tuple(_safe_freeform_string(item) for item in _list(value["notes"])),
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


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> Never:
    raise ValueError


def _require_exact_fields(value: dict[str, Any], expected: frozenset[str]) -> None:
    if frozenset(value) != expected:
        raise ValueError


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


def _safe_freeform_string(value: object) -> str:
    result = _string(value)
    if text_contains_sensitive_material(result):
        raise ValueError
    return result


def _optional_safe_freeform_string(value: object) -> str | None:
    if value is None:
        return None
    return _safe_freeform_string(value)


def _safe_source_uri_string(value: object) -> str:
    result = _string(value)
    if text_contains_sensitive_material(result):
        raise ValueError
    return result


def _manifest_freeform_is_safe(manifest: CapabilityManifest) -> bool:
    try:
        for record in manifest.records:
            values = (
                record.provider,
                record.operation,
                *record.limitations,
                *((record.locked_reason,) if record.locked_reason is not None else ()),
                *(note for evidence in record.evidence for note in evidence.notes),
            )
            if any(text_contains_sensitive_material(value) for value in values):
                return False
    except Exception:
        return False
    return True


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError
    return value
