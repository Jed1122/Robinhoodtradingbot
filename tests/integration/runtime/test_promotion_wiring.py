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
from trading_bot.config import LoadedConfig, load_config
from trading_bot.domain import (
    AccountId,
    CodeHash,
    ExecutionMode,
    PromotionAttestation,
    RuntimeState,
)
from trading_bot.runtime.live import LiveNotReady, build_live_application, evaluate_live_preflight

NOW = datetime(2026, 7, 21, 12, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64
CONFIGS = Path(__file__).parents[3] / "configs"


def loaded_config(*, live_enabled: bool = True, ceiling: str | None = None) -> LoadedConfig:
    environ = {"LIVE_TRADING_ENABLED": "true" if live_enabled else "false"}
    if ceiling is not None:
        environ["TRADING_BOT__PORTFOLIO__LIVE_ACCOUNT_EQUITY_CEILING_USD"] = ceiling
    return load_config(
        base_path=CONFIGS / "base.yaml",
        mode_path=CONFIGS / "micro_live.yaml",
        safety_path=CONFIGS / "safety-envelope.yaml",
        environ=environ,
    )


def preflight() -> PreflightReport:
    return PreflightReport(
        account_id=AccountId("account-1"),
        stage=ExecutionMode.MICRO_LIVE,
        equity=Decimal("100"),
        config_hash=loaded_config().config_hash,
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


@pytest.mark.parametrize("equity", ["100", "1000"])
def test_live_accepts_canonical_stage_and_matching_promotion_hash(equity: str) -> None:
    report = replace(preflight(), equity=Decimal(equity))
    original_authorization = authorization(report)
    live_authorization = replace(
        original_authorization,
        payload=replace(original_authorization.payload, authorized_risk_equity=Decimal("100")),
    )
    live_lease = replace(lease(report), authorized_risk_equity=Decimal("100"))
    calls: list[object] = []

    def place_factory() -> object:
        value = object()
        calls.append(value)
        return value

    application = build_live_application(
        loaded_config=loaded_config(),
        live_trading_enabled=True,
        preflight=report,
        authorization=live_authorization,
        lease=live_lease,
        promotion=promotion(),
        place_factory=place_factory,  # type: ignore[arg-type]
        now=NOW,
    )

    assert len(calls) == 1
    assert application.state is RuntimeState.PAUSED
    assert live_lease.authorized_risk_equity == Decimal("100")


@pytest.mark.parametrize("stage", ["micro", "normal"])
def test_legacy_promotion_stage_names_fail_closed(stage: str) -> None:
    report = preflight()
    calls: list[object] = []

    with pytest.raises(LiveNotReady, match="stage-specific promotion evidence"):
        build_live_application(
            loaded_config=loaded_config(),
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
            loaded_config=loaded_config(),
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
            loaded_config=loaded_config(),
            live_trading_enabled=True,
            preflight=report,
            authorization=live_authorization,
            lease=live_lease,
            promotion=promotion(),
            place_factory=lambda: calls.append(object()),  # type: ignore[arg-type,func-returns-value]
            now=NOW,
        )

    assert calls == []


@pytest.mark.parametrize(
    ("equity", "ready"),
    [("150.01", True), ("500", True), ("1000", True), ("1000.01", False)],
)
def test_live_preflight_uses_canonical_equity_ceiling(equity: str, ready: bool) -> None:
    report = replace(preflight(), equity=Decimal(equity))

    result = evaluate_live_preflight(report, loaded_config=loaded_config(), now=NOW)

    assert result.ready is ready
    assert ("account_equity_ceiling" in result.reason_codes) is (not ready)


def test_live_preflight_preserves_tighter_configured_ceiling() -> None:
    loaded = loaded_config(ceiling="150")
    report = replace(preflight(), config_hash=loaded.config_hash, equity=Decimal("150.01"))

    result = evaluate_live_preflight(report, loaded_config=loaded, now=NOW)

    assert not result.ready
    assert "account_equity_ceiling" in result.reason_codes


def test_live_preflight_requires_canonical_loaded_configuration() -> None:
    with pytest.raises(LiveNotReady, match="canonical loaded configuration"):
        evaluate_live_preflight(preflight(), loaded_config=object(), now=NOW)  # type: ignore[arg-type]


@pytest.mark.parametrize("offset_seconds", [-301, 1])
def test_live_preflight_still_rejects_stale_or_future_observations(offset_seconds: int) -> None:
    report = replace(preflight(), observed_at=NOW + timedelta(seconds=offset_seconds))

    result = evaluate_live_preflight(report, loaded_config=loaded_config(), now=NOW)

    assert not result.ready
    assert "stale_preflight" in result.reason_codes


@pytest.mark.parametrize(
    "denial",
    ["disabled", "no_promotion", "no_authorization", "identity", "future_consumption", "expired"],
)
def test_other_live_gates_remain_closed_after_ceiling_amendment(denial: str) -> None:
    report = preflight()
    live_authorization = authorization(report)
    live_lease = lease(report)
    if denial == "identity":
        live_lease = replace(live_lease, account_id=AccountId("different-account"))
    elif denial == "future_consumption":
        live_authorization = replace(live_authorization, consumed_at=NOW + timedelta(seconds=1))
    elif denial == "expired":
        live_lease = replace(live_lease, expires_at=NOW)
    calls: list[object] = []

    with pytest.raises(LiveNotReady):
        build_live_application(
            loaded_config=loaded_config(),
            live_trading_enabled=denial != "disabled",
            preflight=report,
            authorization=None if denial == "no_authorization" else live_authorization,
            lease=live_lease,
            promotion=None if denial == "no_promotion" else promotion(),
            place_factory=lambda: calls.append(object()),  # type: ignore[arg-type,func-returns-value]
            now=NOW,
        )

    assert calls == []


@pytest.mark.parametrize(
    "denial", ["above_ceiling", "stale_config", "live_disabled", "mode_mismatch"]
)
def test_changed_account_policy_cannot_construct_placement_before_all_gates(denial: str) -> None:
    loaded = loaded_config(live_enabled=denial != "live_disabled")
    report = replace(preflight(), config_hash=loaded.config_hash)
    if denial == "above_ceiling":
        report = replace(report, equity=Decimal("1000.01"))
    elif denial == "stale_config":
        report = replace(report, config_hash=loaded_config(ceiling="150").config_hash)
    elif denial == "mode_mismatch":
        report = replace(report, stage=ExecutionMode.NORMAL_LIVE)
    calls: list[object] = []

    with pytest.raises(LiveNotReady):
        build_live_application(
            loaded_config=loaded,
            live_trading_enabled=True,
            preflight=report,
            authorization=authorization(report),
            lease=lease(report),
            promotion=promotion(),
            place_factory=lambda: calls.append(object()),  # type: ignore[arg-type,func-returns-value]
            now=NOW,
        )

    assert calls == []


def test_live_preflight_rejects_changed_loaded_configuration_bytes() -> None:
    loaded = loaded_config()
    changed = replace(loaded, canonical_json=b"{}")

    result = evaluate_live_preflight(preflight(), loaded_config=changed, now=NOW)

    assert not result.ready
    assert "configuration_identity_mismatch" in result.reason_codes
