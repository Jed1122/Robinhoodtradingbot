"""Tests for deterministic capability lookup and canonical hashing."""

import traceback
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from trading_bot.capabilities import (
    CapabilityEvidence,
    CapabilityManifest,
    CapabilityNotFoundError,
    CapabilityRecord,
    EvidenceLevel,
    InvalidCapabilityManifest,
    JsonValue,
    OperationKind,
    UnsupportedCapabilityError,
    canonical_sha256,
    require_capability,
)
from trading_bot.capabilities.registry import (
    UnsupportedCapabilityError as RegistryUnsupportedCapabilityError,
)
from trading_bot.domain import AssetClass

NOW = datetime(2026, 7, 12, 12, tzinfo=UTC)
DIGEST = "b" * 64


def documented_record(
    *,
    provider: str = "robinhood-trading",
    operation: str = "get_quote",
    locked_reason: str | None = None,
) -> CapabilityRecord:
    return CapabilityRecord(
        provider=provider,
        operation=operation,
        asset_class=AssetClass.EQUITY,
        operation_kind=OperationKind.READ,
        evidence=(
            CapabilityEvidence(
                level=EvidenceLevel.DOCUMENTED,
                source_uri="https://robinhood.com/support/official-api",
                observed_at=NOW,
                schema_sha256=None,
                authenticated=False,
                contains_account_data=False,
                notes=(),
            ),
        ),
        limitations=(),
        locked_reason=locked_reason,
    )


def forged_authenticated_write_manifest() -> tuple[CapabilityManifest, CapabilityRecord]:
    """Forge exact nested objects that claim write evidence without its safeguards."""
    evidence = object.__new__(CapabilityEvidence)
    object.__setattr__(evidence, "level", EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED)
    object.__setattr__(evidence, "source_uri", "Authorization: Bearer actual-secret-value")
    object.__setattr__(evidence, "observed_at", NOW)
    object.__setattr__(evidence, "schema_sha256", DIGEST)
    object.__setattr__(evidence, "authenticated", False)
    object.__setattr__(evidence, "contains_account_data", True)
    object.__setattr__(evidence, "notes", ("forged evidence",))

    record = object.__new__(CapabilityRecord)
    object.__setattr__(record, "provider", "robinhood-trading")
    object.__setattr__(record, "operation", "place_order")
    object.__setattr__(record, "asset_class", AssetClass.EQUITY)
    object.__setattr__(record, "operation_kind", OperationKind.PLACE)
    object.__setattr__(record, "evidence", (evidence,))
    object.__setattr__(record, "limitations", ())
    object.__setattr__(record, "locked_reason", None)

    manifest = object.__new__(CapabilityManifest)
    object.__setattr__(manifest, "records", (record,))
    return manifest, record


@pytest.mark.parametrize("records", ([], {"record"}, iter(())))
def test_manifest_requires_exact_immutable_record_tuple(records: object) -> None:
    with pytest.raises(InvalidCapabilityManifest, match="immutable tuple"):
        CapabilityManifest(records=records)  # type: ignore[arg-type]


def test_manifest_rejects_non_record_members_and_duplicate_keys() -> None:
    with pytest.raises(InvalidCapabilityManifest, match="CapabilityRecord"):
        CapabilityManifest(records=("record",))  # type: ignore[arg-type]

    first = documented_record()
    duplicate = replace(first, asset_class=AssetClass.CRYPTO)
    with pytest.raises(InvalidCapabilityManifest, match="duplicate"):
        CapabilityManifest(records=(first, duplicate))


def test_manifest_records_have_canonical_provider_operation_order() -> None:
    records = (
        documented_record(provider="z-provider", operation="a-operation"),
        documented_record(provider="a-provider", operation="z-operation"),
        documented_record(provider="a-provider", operation="a-operation"),
    )

    manifest = CapabilityManifest(records=records)

    assert [(item.provider, item.operation) for item in manifest.records] == [
        ("a-provider", "a-operation"),
        ("a-provider", "z-operation"),
        ("z-provider", "a-operation"),
    ]


def test_find_returns_exact_provider_operation_match() -> None:
    target = documented_record(provider="target", operation="read")
    manifest = CapabilityManifest(
        records=(
            documented_record(provider="other", operation="read"),
            documented_record(provider="target", operation="other"),
            target,
        )
    )

    found = manifest.find(provider="target", operation="read")

    assert found == target
    assert found is not target


def test_find_rejects_missing_or_empty_keys() -> None:
    manifest = CapabilityManifest(records=(documented_record(),))

    with pytest.raises(CapabilityNotFoundError, match="not present"):
        manifest.find(provider="robinhood-trading", operation="missing")
    with pytest.raises(CapabilityNotFoundError):
        manifest.find(provider=" ", operation="get_quote")


def test_require_capability_returns_only_exact_unlocked_evidence() -> None:
    record = documented_record()
    manifest = CapabilityManifest(records=(record,))

    result = require_capability(
        manifest,
        provider="robinhood-trading",
        operation="get_quote",
        minimum=EvidenceLevel.DOCUMENTED,
    )

    assert result == record
    assert result is not record
    assert result is not manifest.records[0]


def test_forged_exact_nested_write_evidence_cannot_satisfy_capability_gate() -> None:
    manifest, record = forged_authenticated_write_manifest()

    assert not record.satisfies(EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED)
    with pytest.raises(UnsupportedCapabilityError) as captured:
        require_capability(
            manifest,
            provider="robinhood-trading",
            operation="place_order",
            minimum=EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED,
        )

    rendered = "".join(traceback.format_exception(captured.value))
    assert str(captured.value) == "requested capability does not have the required exact evidence"
    assert "Authorization" not in rendered
    assert "actual-secret-value" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    ("manifest", "operation", "minimum"),
    (
        (
            CapabilityManifest(records=(documented_record(),)),
            "get_quote",
            EvidenceLevel.SCHEMA_DECLARED,
        ),
        (
            CapabilityManifest(
                records=(
                    documented_record(
                        locked_reason="operation remains locked pending classification"
                    ),
                )
            ),
            "get_quote",
            EvidenceLevel.DOCUMENTED,
        ),
        (
            CapabilityManifest(records=(documented_record(),)),
            "missing",
            EvidenceLevel.DOCUMENTED,
        ),
    ),
)
def test_require_capability_fails_closed_for_insufficient_locked_or_missing_records(
    manifest: CapabilityManifest,
    operation: str,
    minimum: EvidenceLevel,
) -> None:
    with pytest.raises(UnsupportedCapabilityError) as captured:
        require_capability(
            manifest,
            provider="robinhood-trading",
            operation=operation,
            minimum=minimum,
        )

    assert captured.value.provider == "robinhood-trading"
    assert captured.value.operation == operation
    assert captured.value.minimum is minimum


def test_unsupported_capability_error_is_defined_once() -> None:
    assert UnsupportedCapabilityError is RegistryUnsupportedCapabilityError


def test_canonical_sha256_ignores_mapping_insertion_order() -> None:
    left: JsonValue = {
        "output": None,
        "input": {"required": ["symbol", "quantity"], "type": "object"},
    }
    right: JsonValue = {
        "input": {"type": "object", "required": ["symbol", "quantity"]},
        "output": None,
    }

    assert canonical_sha256(left) == canonical_sha256(right)
    assert len(canonical_sha256(left)) == 64


def test_canonical_sha256_preserves_list_order() -> None:
    forward: JsonValue = {"required": ["symbol", "quantity"]}
    reverse: JsonValue = {"required": ["quantity", "symbol"]}

    assert canonical_sha256(forward) != canonical_sha256(reverse)
