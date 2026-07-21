from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.authorization import (
    ActivationPayload,
    LiveAuthorization,
    LiveLease,
    PreflightReport,
)
from trading_bot.domain import (
    AccountId,
    CodeHash,
    ConfigHash,
    ExecutionMode,
    PromotionAttestation,
)
from trading_bot.runtime.live import LiveNotReady, build_live_application

NOW = datetime(2026, 7, 21, 12, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64


def preflight() -> PreflightReport:
    return PreflightReport(
        account_id=AccountId("account-1"),
        stage=ExecutionMode.MICRO_LIVE,
        equity=Decimal("100"),
        config_hash=ConfigHash(HASH_A),
        code_hash=CodeHash(HASH_B),
        strategy_eligibility_hash=HASH_C,
        promotion_evidence_hash=HASH_D,
        risk_self_test_hash=HASH_E,
        reconciliation_hash=HASH_F,
        observed_at=NOW,
        account_active=True,
        account_restricted=False,
        code_identity_clean=True,
        strategy_eligible=True,
        promotion_eligible=True,
        kill_switch_active=False,
        reconciliation_clean=True,
        risk_self_test_passed=True,
        critical_alert_count=0,
        clock_drift_seconds=Decimal("0"),
    )


def authorization(report: PreflightReport) -> LiveAuthorization:
    payload = ActivationPayload(
        authorization_id="authorization-1",
        nonce="nonce-1",
        account_id=report.account_id,
        stage=report.stage,
        authorized_risk_equity=report.equity,
        preflight_hash=HASH_E,
        acknowledgement_hash=HASH_F,
        config_hash=report.config_hash,
        code_hash=report.code_hash,
        strategy_eligibility_hash=report.strategy_eligibility_hash,
        promotion_evidence_hash=report.promotion_evidence_hash,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=14),
    )
    return LiveAuthorization(payload, HASH_A, NOW - timedelta(minutes=1))


def lease(report: PreflightReport) -> LiveLease:
    return LiveLease(
        authorization_id="authorization-1",
        account_id=report.account_id,
        stage=report.stage,
        authorized_risk_equity=report.equity,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        config_hash=report.config_hash,
        code_hash=report.code_hash,
        strategy_eligibility_hash=report.strategy_eligibility_hash,
        promotion_evidence_hash=report.promotion_evidence_hash,
    )


def promotion(*, stage: str = "micro_live", evidence_hash: str = HASH_D) -> PromotionAttestation:
    return PromotionAttestation(
        stage=stage,
        eligible=True,
        evidence_hash=evidence_hash,
        evaluated_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=4),
    )


def test_place_factory_is_after_promotion_gate() -> None:
    source = Path("src/trading_bot/runtime/live.py").read_text()
    assert source.index("promotion is None") < source.rindex("place_factory()")


def test_live_accepts_canonical_stage_and_matching_promotion_hash() -> None:
    report = preflight()
    calls: list[object] = []

    def place_factory() -> object:
        value = object()
        calls.append(value)
        return value

    build_live_application(
        live_trading_enabled=True,
        preflight=report,
        authorization=authorization(report),
        lease=lease(report),
        promotion=promotion(),
        place_factory=place_factory,  # type: ignore[arg-type]
        now=NOW,
    )

    assert len(calls) == 1


@pytest.mark.parametrize("stage", ["micro", "normal"])
def test_legacy_promotion_stage_names_fail_closed(stage: str) -> None:
    report = preflight()
    calls: list[object] = []

    with pytest.raises(LiveNotReady, match="stage-specific promotion evidence"):
        build_live_application(
            live_trading_enabled=True,
            preflight=report,
            authorization=authorization(report),
            lease=lease(report),
            promotion=promotion(stage=stage),
            place_factory=lambda: calls.append(object()),  # type: ignore[arg-type,func-returns-value]
            now=NOW,
        )

    assert calls == []


def test_changed_promotion_evidence_hash_keeps_place_factory_unconstructed() -> None:
    report = preflight()
    calls: list[object] = []

    with pytest.raises(LiveNotReady, match="promotion evidence"):
        build_live_application(
            live_trading_enabled=True,
            preflight=report,
            authorization=authorization(report),
            lease=lease(report),
            promotion=promotion(evidence_hash="0" * 64),
            place_factory=lambda: calls.append(object()),  # type: ignore[arg-type,func-returns-value]
            now=NOW,
        )

    assert calls == []


@pytest.mark.parametrize("drifted_record", ["authorization", "lease"])
def test_promotion_hash_must_match_authorization_and_lease(drifted_record: str) -> None:
    report = preflight()
    live_authorization = authorization(report)
    live_lease = lease(report)
    if drifted_record == "authorization":
        live_authorization = replace(
            live_authorization,
            payload=replace(
                live_authorization.payload,
                promotion_evidence_hash="0" * 64,
            ),
        )
    else:
        live_lease = replace(live_lease, promotion_evidence_hash="0" * 64)
    calls: list[object] = []

    with pytest.raises(LiveNotReady, match="promotion evidence"):
        build_live_application(
            live_trading_enabled=True,
            preflight=report,
            authorization=live_authorization,
            lease=live_lease,
            promotion=promotion(),
            place_factory=lambda: calls.append(object()),  # type: ignore[arg-type,func-returns-value]
            now=NOW,
        )

    assert calls == []
