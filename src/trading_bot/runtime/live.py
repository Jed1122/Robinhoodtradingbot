"""Locked live composition roots; placement is requested only after every gate."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from trading_bot.authorization import LiveAuthorization, LiveLease, PreflightReport
from trading_bot.brokers.protocols import BrokerCancelOnly, BrokerPlace, BrokerRead
from trading_bot.config import LoadedConfig, enforce_safety_envelope
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import PromotionAttestation, RuntimeState


class LiveNotReady(RuntimeError):
    pass


class LiveStage(StrEnum):
    MICRO = "micro"
    NORMAL = "normal"


@dataclass(frozen=True, slots=True)
class LivePreflightResult:
    ready: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CancelOnlyRecovery:
    broker_read: BrokerRead
    broker_cancel: BrokerCancelOnly


class LiveApplication:
    def __init__(self, broker_place: BrokerPlace) -> None:
        self._broker_place = broker_place
        self.state = RuntimeState.PAUSED

    def start_paused(self) -> RuntimeState:
        self.state = RuntimeState.PAUSED
        return self.state

    async def run_cycle(self) -> None:
        if self.state is not RuntimeState.RUNNING_LIVE:
            raise LiveNotReady("live application is paused")


def evaluate_live_preflight(
    report: PreflightReport, *, loaded_config: LoadedConfig, now: datetime
) -> LivePreflightResult:
    if type(loaded_config) is not LoadedConfig:
        raise LiveNotReady("canonical loaded configuration is required")
    config = loaded_config.config
    enforce_safety_envelope(config, loaded_config.safety_envelope)
    canonical, config_hash = hash_loaded_config(config, loaded_config.safety_envelope)
    if (
        (canonical, config_hash) != (loaded_config.canonical_json, loaded_config.config_hash)
        or report.config_hash != config_hash
    ):
        return LivePreflightResult(False, ("configuration_identity_mismatch",))
    reasons: list[str] = []
    if report.stage is not config.mode:
        reasons.append("configuration_stage_mismatch")
    if report.observed_at > now or (now - report.observed_at).total_seconds() > 300:
        reasons.append("stale_preflight")
    if report.equity > config.portfolio.live_account_equity_ceiling_usd:
        reasons.append("account_equity_ceiling")
    flags = {
        "account_inactive": not report.account_active or report.account_restricted,
        "code_identity_dirty": not report.code_identity_clean,
        "strategy_ineligible": not report.strategy_eligible,
        "promotion_ineligible": not report.promotion_eligible,
        "kill_switch_active": report.kill_switch_active,
        "reconciliation_dirty": not report.reconciliation_clean,
        "risk_self_test_failed": not report.risk_self_test_passed,
        "critical_alerts": report.critical_alert_count != 0,
        "clock_unsynchronized": report.clock_drift_seconds > 2,
    }
    reasons.extend(code for code, failed in flags.items() if failed)
    return LivePreflightResult(not reasons, tuple(reasons))


def build_cancel_only_recovery(
    broker_read: BrokerRead, broker_cancel: BrokerCancelOnly
) -> CancelOnlyRecovery:
    return CancelOnlyRecovery(broker_read, broker_cancel)


def build_live_application(
    *,
    loaded_config: LoadedConfig,
    live_trading_enabled: bool,
    preflight: PreflightReport,
    authorization: LiveAuthorization | None,
    lease: LiveLease | None,
    promotion: PromotionAttestation | None,
    place_factory: Callable[[], BrokerPlace],
    now: datetime,
) -> LiveApplication:
    if not live_trading_enabled:
        raise LiveNotReady("live trading is disabled")
    readiness = evaluate_live_preflight(preflight, loaded_config=loaded_config, now=now)
    if not readiness.ready:
        raise LiveNotReady("live preflight is not ready")
    if not loaded_config.config.live_trading_enabled:
        raise LiveNotReady("live trading is disabled by configuration")
    if promotion is None or not promotion.eligible:
        raise LiveNotReady("promotion evidence is required")
    expected_stage = preflight.stage.value
    promotion_current = promotion.evaluated_at <= now < promotion.expires_at
    if promotion.stage != expected_stage or not promotion_current:
        raise LiveNotReady("stage-specific promotion evidence is invalid")
    if authorization is None or lease is None:
        raise LiveNotReady("authorization and live lease are required")
    payload = authorization.payload
    promotion_hashes = {
        promotion.evidence_hash,
        preflight.promotion_evidence_hash,
        payload.promotion_evidence_hash,
        lease.promotion_evidence_hash,
    }
    if len(promotion_hashes) != 1:
        raise LiveNotReady("promotion evidence does not match all live records")
    expected_identity = (
        preflight.account_id,
        preflight.stage,
        preflight.config_hash,
        preflight.code_hash,
        preflight.strategy_eligibility_hash,
    )
    if (
        (
            payload.account_id,
            payload.stage,
            payload.config_hash,
            payload.code_hash,
            payload.strategy_eligibility_hash,
        )
        != expected_identity
        or (
            lease.account_id,
            lease.stage,
            lease.config_hash,
            lease.code_hash,
            lease.strategy_eligibility_hash,
        )
        != expected_identity
        or lease.authorization_id != payload.authorization_id
        or lease.authorized_risk_equity != payload.authorized_risk_equity
        or lease.authorized_risk_equity > preflight.equity
    ):
        raise LiveNotReady("authorization and live lease do not match preflight")
    if not payload.issued_at <= authorization.consumed_at <= now:
        raise LiveNotReady("authorization consumption time is invalid")
    if not (lease.issued_at <= now < lease.expires_at):
        raise LiveNotReady("live lease is expired")
    return LiveApplication(place_factory())


__all__ = [
    "CancelOnlyRecovery",
    "LiveApplication",
    "LiveNotReady",
    "LivePreflightResult",
    "LiveStage",
    "build_cancel_only_recovery",
    "build_live_application",
    "evaluate_live_preflight",
]
