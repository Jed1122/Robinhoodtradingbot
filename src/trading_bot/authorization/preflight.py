"""One-time activation consumption and bounded live lease creation."""

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from nacl.signing import VerifyKey

from trading_bot.authorization.models import (
    LiveAuthorization,
    LiveLease,
    PreflightReport,
    SignedActivationArtifact,
)
from trading_bot.authorization.verifier import (
    InvalidAuthorization,
    VerificationContext,
    verify_activation,
)
from trading_bot.clock import require_utc


class AuthorizationStore(Protocol):
    async def consume_once(self, authorization: LiveAuthorization, lease: LiveLease) -> None: ...


def validate_preflight(
    report: PreflightReport,
    *,
    now: datetime,
    account_allowlist: tuple[str, ...],
    equity_ceiling: Decimal,
    maximum_age: timedelta = timedelta(minutes=5),
    maximum_clock_drift: Decimal = Decimal("2"),
) -> str:
    """Validate every live readiness gate and return its canonical content hash."""

    now = require_utc(now)
    if report.account_id not in account_allowlist:
        raise InvalidAuthorization("preflight account is not allowlisted")
    if not timedelta(0) <= now - report.observed_at <= maximum_age:
        raise InvalidAuthorization("preflight is stale or from the future")
    if report.equity > equity_ceiling:
        raise InvalidAuthorization("preflight equity exceeds live ceiling")
    ready = (
        report.account_active
        and not report.account_restricted
        and report.code_identity_clean
        and report.strategy_eligible
        and report.promotion_eligible
        and not report.kill_switch_active
        and report.reconciliation_clean
        and report.risk_self_test_passed
        and report.critical_alert_count == 0
        and report.clock_drift_seconds <= maximum_clock_drift
    )
    if not ready:
        raise InvalidAuthorization("preflight readiness evidence is incomplete")
    payload = asdict(report)
    payload["stage"] = report.stage.value
    payload["equity"] = str(report.equity)
    payload["clock_drift_seconds"] = str(report.clock_drift_seconds)
    payload["observed_at"] = report.observed_at.isoformat().replace("+00:00", "Z")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def consume_activation(
    artifact: SignedActivationArtifact,
    store: AuthorizationStore,
    *,
    verify_key: VerifyKey,
    now: datetime,
    context: VerificationContext,
    lease_lifetime: timedelta = timedelta(hours=8),
    envelope: timedelta = timedelta(hours=24),
) -> LiveLease:
    now = require_utc(now)
    artifact_hash = verify_activation(artifact, verify_key, now=now, context=context)
    if lease_lifetime <= timedelta(0) or lease_lifetime > envelope:
        raise InvalidAuthorization("live lease exceeds safety envelope")
    payload = artifact.payload
    lease = LiveLease(
        payload.authorization_id,
        payload.account_id,
        payload.stage,
        payload.authorized_risk_equity,
        now,
        now + lease_lifetime,
        payload.config_hash,
        payload.code_hash,
        payload.strategy_eligibility_hash,
        payload.promotion_evidence_hash,
    )
    await store.consume_once(LiveAuthorization(payload, artifact_hash, now), lease)
    return lease
