"""Synthetic evidence exercises; no actual account/runtime verification is performed."""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trading_bot.capabilities.models import (
    CapabilityAssetClass,
    CapabilityEvidence,
    CapabilityManifest,
    CapabilityRecord,
    CapabilityVerification,
    EvidenceLevel,
    InvalidCapabilityManifest,
    InvalidCapabilityVerification,
    OperationKind,
    VerificationDimension,
    VerificationStatus,
    validated_manifest_copy,
)
from trading_bot.capabilities.registry import load_capability_manifest, require_capability
from trading_bot.capabilities.verification import (
    DimensionAssessment,
    VerificationContext,
    VerificationDecision,
    assess_operation,
)
from trading_bot.domain import AssetClass

NOW = datetime(2026, 9, 18, 12, tzinfo=UTC)
PROVIDER = "robinhood-trading"
OPERATION = "place_option_order"
SCHEMA = "a" * 64
CONTEXT = VerificationContext(
    now=NOW,
    schema_sha256=SCHEMA,
    session_ref="b" * 64,
    account_ref="c" * 64,
    runtime_ref="d" * 64,
)


def observation(dimension: VerificationDimension) -> CapabilityVerification:
    level = {
        VerificationDimension.PUBLIC: EvidenceLevel.DOCUMENTED,
        VerificationDimension.SESSION: EvidenceLevel.SCHEMA_DECLARED,
        VerificationDimension.ACCOUNT: EvidenceLevel.AUTHENTICATED_READ_VERIFIED,
        VerificationDimension.RUNTIME: EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED,
    }[dimension]
    return CapabilityVerification(
        provider=PROVIDER,
        operation=OPERATION,
        dimension=dimension,
        status=VerificationStatus.VERIFIED,
        evidence=CapabilityEvidence(
            level=level,
            source_uri="https://robinhood.com/us/en/support/articles/trading-with-your-agent/",
            observed_at=NOW - timedelta(minutes=1),
            schema_sha256=None if dimension is VerificationDimension.PUBLIC else SCHEMA,
            authenticated=dimension
            in {VerificationDimension.ACCOUNT, VerificationDimension.RUNTIME},
            contains_account_data=False,
            notes=("fabricated unit-test witness; not real verification",),
        ),
        valid_until=NOW + timedelta(minutes=1),
        session_ref=CONTEXT.session_ref if dimension is VerificationDimension.SESSION else None,
        account_ref=CONTEXT.account_ref
        if dimension in {VerificationDimension.ACCOUNT, VerificationDimension.RUNTIME}
        else None,
        runtime_ref=CONTEXT.runtime_ref if dimension is VerificationDimension.RUNTIME else None,
        synthetic=False,  # Tests the observed-evidence branch, not a real-world claim.
    )


def manifest(*observations: CapabilityVerification) -> CapabilityManifest:
    return CapabilityManifest(
        records=(
            CapabilityRecord(
                provider=PROVIDER,
                operation=OPERATION,
                asset_class=CapabilityAssetClass.OPTIONS,
                operation_kind=OperationKind.PLACE,
                evidence=(observation(VerificationDimension.PUBLIC).evidence,),
                limitations=("unit-test fixture",),
                locked_reason=None,
            ),
        ),
        verifications=observations,
    )


def assess(value: CapabilityManifest, context: VerificationContext = CONTEXT):
    return assess_operation(value, provider=PROVIDER, operation=OPERATION, context=context)


def complete_manifest() -> CapabilityManifest:
    return manifest(*(observation(dimension) for dimension in VerificationDimension))


def test_legacy_levels_never_infer_four_dimensional_verification() -> None:
    value = manifest()
    assert not assess(value).evidence_complete
    assert {item.reason for item in assess(value).dimensions} == {"missing"}
    assert value.verifications == ()


def test_legacy_single_category_gate_cannot_unlock_options() -> None:
    from trading_bot.capabilities.models import UnsupportedCapabilityError

    value = complete_manifest()
    assert not value.records[0].satisfies(EvidenceLevel.DOCUMENTED)
    with pytest.raises(UnsupportedCapabilityError):
        require_capability(
            value, provider=PROVIDER, operation=OPERATION, minimum=EvidenceLevel.DOCUMENTED
        )


def test_exact_independent_evidence_does_not_authorize_production() -> None:
    result = assess(complete_manifest())
    assert result.evidence_complete
    assert not result.production_eligible
    assert all(item.reason == "verified" for item in result.dimensions)


def test_duplicate_dimensions_cannot_report_evidence_complete() -> None:
    repeated = (DimensionAssessment(VerificationDimension.PUBLIC, "verified"),) * 4
    assert not VerificationDecision(repeated, "unlocked").evidence_complete
    original = assess(complete_manifest())
    object.__setattr__(original, "dimensions", repeated)
    assert not original.evidence_complete
    object.__setattr__(original, "dimensions", None)
    assert not original.evidence_complete
    assert not original.production_eligible


@pytest.mark.parametrize(
    "changes",
    [
        {"now": "2026-09-18"},
        {"now": NOW.replace(tzinfo=None)},
        {"schema_sha256": "invalid"},
        {"session_ref": 1},
        {"account_ref": None},
    ],
)
def test_invalid_context_is_sanitized(changes) -> None:
    with pytest.raises(ValueError, match="invalid verification context"):
        replace(CONTEXT, **changes)


def test_forged_context_cannot_be_used_by_assessment() -> None:
    assert not assess(complete_manifest(), None).evidence_complete
    context = replace(CONTEXT)
    object.__setattr__(context, "account_ref", "invalid")
    assert not assess(complete_manifest(), context).evidence_complete


@pytest.mark.parametrize("dimension", list(VerificationDimension))
@pytest.mark.parametrize(
    "change", ["missing", "expired", "future", "denied", "unknown", "synthetic"]
)
def test_every_dimension_fails_closed(dimension, change) -> None:
    items = list(complete_manifest().verifications)
    source = next(item for item in items if item.dimension is dimension)
    items.remove(source)
    if change == "expired":
        items.append(replace(source, valid_until=NOW))
    elif change == "future":
        items.append(
            replace(
                source, evidence=replace(source.evidence, observed_at=NOW + timedelta(seconds=1))
            )
        )
    elif change in {"denied", "unknown"}:
        items.append(replace(source, status=VerificationStatus(change)))
    elif change == "synthetic":
        items.append(replace(source, synthetic=True))
    result = assess(manifest(*items))
    assert not result.evidence_complete
    assert next(item for item in result.dimensions if item.dimension is dimension).reason == change


@pytest.mark.parametrize("field", ["schema_sha256", "session_ref", "account_ref", "runtime_ref"])
def test_binding_and_schema_changes_deny(field) -> None:
    assert not assess(complete_manifest(), replace(CONTEXT, **{field: "e" * 64})).evidence_complete


def test_latest_denial_is_not_hidden_by_older_verified_evidence() -> None:
    value = complete_manifest()
    old = next(
        item for item in value.verifications if item.dimension is VerificationDimension.RUNTIME
    )
    denial = replace(
        old, status=VerificationStatus.DENIED, evidence=replace(old.evidence, observed_at=NOW)
    )
    updated = replace(value, verifications=(*value.verifications, denial))
    assert len(updated.verifications) == 5
    assert not assess(updated).evidence_complete
    assert not assess(replace(updated, verifications=updated.verifications[::-1])).evidence_complete


def test_expired_latest_never_falls_back_to_older_positive() -> None:
    value = complete_manifest()
    old = next(
        item for item in value.verifications if item.dimension is VerificationDimension.RUNTIME
    )
    latest = replace(
        old, evidence=replace(old.evidence, observed_at=NOW - timedelta(seconds=1)), valid_until=NOW
    )
    assert not assess(
        replace(value, verifications=(*value.verifications, latest))
    ).evidence_complete


def test_old_negative_finding_is_preserved_after_new_positive() -> None:
    value = complete_manifest()
    old = replace(
        value.verifications[0],
        status=VerificationStatus.DENIED,
        evidence=replace(value.verifications[0].evidence, observed_at=NOW - timedelta(days=1)),
        valid_until=NOW - timedelta(hours=1),
    )
    updated = replace(value, verifications=(*value.verifications, old))
    assert old in updated.verifications
    assert assess(updated).evidence_complete


def test_lock_and_unknown_operation_deny_even_with_complete_evidence() -> None:
    value = complete_manifest()
    locked = replace(
        value, records=(replace(value.records[0], locked_reason="external prerequisites pending"),)
    )
    assert not assess(locked).evidence_complete
    assert not assess_operation(
        value, provider=PROVIDER, operation="cancel_option_order", context=CONTEXT
    ).evidence_complete


def test_ambiguous_same_time_and_dangling_observations_rejected() -> None:
    item = observation(VerificationDimension.RUNTIME)
    with pytest.raises(InvalidCapabilityManifest):
        manifest(item, replace(item, status=VerificationStatus.DENIED))
    with pytest.raises(InvalidCapabilityManifest):
        replace(manifest(), verifications=(replace(item, operation="cancel_option_order"),))


@pytest.mark.parametrize("dimension", list(VerificationDimension))
def test_dimension_cannot_borrow_another_evidence_category(dimension) -> None:
    item = observation(dimension)
    other = observation(
        VerificationDimension.SESSION
        if dimension is VerificationDimension.PUBLIC
        else VerificationDimension.PUBLIC
    )
    with pytest.raises(InvalidCapabilityVerification):
        replace(item, evidence=other.evidence)


def test_write_runtime_cannot_use_read_verification() -> None:
    item = observation(VerificationDimension.RUNTIME)
    read_only = replace(
        item, evidence=replace(item.evidence, level=EvidenceLevel.AUTHENTICATED_READ_VERIFIED)
    )
    with pytest.raises(InvalidCapabilityManifest):
        manifest(read_only)


@pytest.mark.parametrize(
    "changes",
    [
        {"synthetic": 1},
        {"status": "verified"},
        {"dimension": "runtime"},
        {"valid_until": NOW.replace(tzinfo=None)},
        {"valid_until": NOW - timedelta(days=1)},
        {"runtime_ref": "secret-value"},
        {"session_ref": "a" * 64},
        {"account_ref": None},
    ],
)
def test_invalid_verifications_are_rejected(changes) -> None:
    with pytest.raises(InvalidCapabilityVerification):
        replace(observation(VerificationDimension.RUNTIME), **changes)


def test_rebuild_does_not_trust_mutated_frozen_observation() -> None:
    value = complete_manifest()
    object.__setattr__(value.verifications[0], "synthetic", "false")
    with pytest.raises(InvalidCapabilityManifest):
        validated_manifest_copy(value)
    assert not assess(value).evidence_complete


def test_v2_loader_preserves_observations_and_v1_stays_readable(tmp_path: Path) -> None:
    value = complete_manifest()
    payload = {"format_version": 2, "checked_at": NOW.isoformat(), **asdict(value)}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload, default=lambda item: item.isoformat()))
    assert load_capability_manifest(path) == value
    payload.pop("verifications")
    payload["format_version"] = 1
    payload["records"][0]["asset_class"] = "equity"
    path.write_text(json.dumps(payload, default=lambda item: item.isoformat()))
    assert load_capability_manifest(path) == replace(
        value, verifications=(), records=(replace(value.records[0], asset_class=AssetClass.EQUITY),)
    )
    payload["format_version"] = 2
    path.write_text(json.dumps(payload, default=lambda item: item.isoformat()))
    with pytest.raises(InvalidCapabilityManifest):
        load_capability_manifest(path)
