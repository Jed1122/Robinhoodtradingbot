from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from trading_bot.domain import (
    AccountId,
    AlertAttestation,
    AuditEvent,
    CodeHash,
    ConfigHash,
    DomainValidationError,
    LiveLeaseAttestation,
    PromotionAttestation,
    ReconciliationAttestation,
    StrategyEligibilityAttestation,
)
from trading_bot.domain.decisions import AuditEvent as DecisionAuditEvent
from trading_bot.domain.events import AuditEvent as EventAuditEvent

NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


class DatetimeSubclass(datetime):
    pass


def _valid_attestations() -> dict[str, Any]:
    return {
        "reconciliation": ReconciliationAttestation(
            clean=True,
            observed_at=NOW,
            evidence_hash=HASH_A,
        ),
        "live_lease": LiveLeaseAttestation(
            valid=True,
            account_id=AccountId("account-1"),
            config_hash=ConfigHash(HASH_B),
            expires_at=LATER,
            evidence_hash=HASH_A,
        ),
        "alerts": AlertAttestation(
            critical_count=0,
            observed_at=NOW,
            evidence_hash=HASH_A,
        ),
        "strategy": StrategyEligibilityAttestation(
            eligible=True,
            strategy_version="strategy-v1",
            config_hash=ConfigHash(HASH_B),
            code_hash=CodeHash(HASH_C),
            research_manifest_hash=HASH_D,
            report_hash=HASH_A,
            observed_at=NOW,
        ),
        "promotion": PromotionAttestation(
            stage="shadow",
            eligible=True,
            evidence_hash=HASH_A,
            evaluated_at=NOW,
            expires_at=LATER,
        ),
    }


def test_attestation_fields_are_exact_and_stable() -> None:
    expected_fields = {
        ReconciliationAttestation: ("clean", "observed_at", "evidence_hash"),
        LiveLeaseAttestation: (
            "valid",
            "account_id",
            "config_hash",
            "expires_at",
            "evidence_hash",
        ),
        AlertAttestation: ("critical_count", "observed_at", "evidence_hash"),
        StrategyEligibilityAttestation: (
            "eligible",
            "strategy_version",
            "config_hash",
            "code_hash",
            "research_manifest_hash",
            "report_hash",
            "observed_at",
        ),
        PromotionAttestation: (
            "stage",
            "eligible",
            "evidence_hash",
            "evaluated_at",
            "expires_at",
        ),
    }

    for record_type, expected in expected_fields.items():
        assert tuple(field.name for field in fields(record_type)) == expected


@pytest.mark.parametrize(
    "record",
    _valid_attestations().values(),
    ids=_valid_attestations().keys(),
)
def test_attestations_are_frozen_and_slotted(record: Any) -> None:
    first_field = fields(record)[0].name

    with pytest.raises(FrozenInstanceError):
        setattr(record, first_field, getattr(record, first_field))
    assert "__dict__" not in record.__class__.__slots__


@pytest.mark.parametrize(
    ("record_name", "field_name"),
    [
        ("reconciliation", "clean"),
        ("live_lease", "valid"),
        ("strategy", "eligible"),
        ("promotion", "eligible"),
    ],
)
def test_attestation_booleans_are_exact(record_name: str, field_name: str) -> None:
    record = _valid_attestations()[record_name]

    with pytest.raises(DomainValidationError):
        replace(record, **{field_name: 1})


@pytest.mark.parametrize("invalid", [True, -1, Decimal("0"), "0"])
def test_alert_critical_count_is_an_exact_nonnegative_integer(invalid: object) -> None:
    alerts = _valid_attestations()["alerts"]

    with pytest.raises(DomainValidationError, match="critical_count"):
        replace(alerts, critical_count=invalid)


@pytest.mark.parametrize(
    ("record_name", "field_name"),
    [
        ("reconciliation", "observed_at"),
        ("live_lease", "expires_at"),
        ("alerts", "observed_at"),
        ("strategy", "observed_at"),
        ("promotion", "evaluated_at"),
        ("promotion", "expires_at"),
    ],
)
def test_attestation_timestamps_require_utc(record_name: str, field_name: str) -> None:
    record = _valid_attestations()[record_name]

    with pytest.raises(DomainValidationError):
        replace(record, **{field_name: datetime(2026, 7, 13, 12)})


def test_attestation_timestamps_reject_datetime_subclasses() -> None:
    promotion = _valid_attestations()["promotion"]
    subclass_timestamp = DatetimeSubclass(2026, 7, 13, 12, tzinfo=UTC)

    with pytest.raises(DomainValidationError):
        replace(promotion, evaluated_at=subclass_timestamp)


@pytest.mark.parametrize(
    ("record_name", "field_name"),
    [
        ("reconciliation", "evidence_hash"),
        ("live_lease", "config_hash"),
        ("live_lease", "evidence_hash"),
        ("alerts", "evidence_hash"),
        ("strategy", "config_hash"),
        ("strategy", "code_hash"),
        ("strategy", "research_manifest_hash"),
        ("strategy", "report_hash"),
        ("promotion", "evidence_hash"),
    ],
)
def test_attestation_hashes_require_lowercase_sha256(
    record_name: str,
    field_name: str,
) -> None:
    record = _valid_attestations()[record_name]

    with pytest.raises(DomainValidationError):
        replace(record, **{field_name: "not-a-sha256"})


@pytest.mark.parametrize(
    ("record_name", "field_name", "invalid"),
    [
        ("live_lease", "account_id", ""),
        ("strategy", "strategy_version", " "),
        ("promotion", "stage", ""),
        ("promotion", "stage", 1),
    ],
)
def test_attestation_text_identifiers_are_nonempty_strings(
    record_name: str,
    field_name: str,
    invalid: object,
) -> None:
    record = _valid_attestations()[record_name]

    with pytest.raises(DomainValidationError):
        replace(record, **{field_name: invalid})


@pytest.mark.parametrize("expires_at", [NOW, NOW - timedelta(seconds=1)])
def test_promotion_attestation_must_expire_after_evaluation(expires_at: datetime) -> None:
    promotion = _valid_attestations()["promotion"]

    with pytest.raises(DomainValidationError, match=r"evaluated_at.*expires_at"):
        replace(promotion, expires_at=expires_at)


def test_audit_event_has_one_canonical_class_with_legacy_module_compatibility() -> None:
    assert AuditEvent is EventAuditEvent
    assert DecisionAuditEvent is EventAuditEvent
    assert EventAuditEvent.__module__ == "trading_bot.domain.events"
