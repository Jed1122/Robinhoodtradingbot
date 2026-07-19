"""Runtime-only public-key verification and exact activation binding."""

import base64
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from trading_bot.authorization.models import SignedActivationArtifact, canonical_payload
from trading_bot.clock import require_utc
from trading_bot.domain import AccountId, CodeHash, ConfigHash, ExecutionMode


class InvalidAuthorization(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VerificationContext:
    account_id: AccountId
    stage: ExecutionMode
    config_hash: ConfigHash
    code_hash: CodeHash
    preflight_hash: str
    acknowledgement_hash: str
    strategy_eligibility_hash: str
    promotion_evidence_hash: str
    reconciled_equity: Decimal


def verify_activation(
    artifact: SignedActivationArtifact,
    verify_key: VerifyKey,
    *,
    now: datetime,
    context: VerificationContext | None = None,
) -> str:
    now = require_utc(now)
    try:
        verify_key.verify(
            canonical_payload(artifact.payload),
            base64.b64decode(artifact.signature_b64, validate=True),
        )
    except (BadSignatureError, ValueError):
        raise InvalidAuthorization("activation signature is invalid") from None
    payload = artifact.payload
    if (
        not payload.issued_at <= now < payload.expires_at
        or payload.expires_at - payload.issued_at > timedelta(minutes=15)
    ):
        raise InvalidAuthorization("activation is expired or exceeds its lifetime")
    if context is not None:
        exact = (
            payload.account_id,
            payload.stage,
            payload.config_hash,
            payload.code_hash,
            payload.preflight_hash,
            payload.acknowledgement_hash,
            payload.strategy_eligibility_hash,
            payload.promotion_evidence_hash,
        )
        expected = (
            context.account_id,
            context.stage,
            context.config_hash,
            context.code_hash,
            context.preflight_hash,
            context.acknowledgement_hash,
            context.strategy_eligibility_hash,
            context.promotion_evidence_hash,
        )
        if exact != expected or payload.authorized_risk_equity > context.reconciled_equity:
            raise InvalidAuthorization("activation evidence does not match current state")
    return hashlib.sha256(canonical_payload(payload) + artifact.signature_b64.encode()).hexdigest()


def load_verify_key(path: str | Path) -> VerifyKey:
    """Load only public material and reject any configured private-key path."""
    if os.environ.get("TRADING_BOT_AUTH_SIGNING_KEY_FILE"):
        raise InvalidAuthorization("runtime signing-key configuration is forbidden")
    key_path = Path(path)
    if key_path.stat().st_mode & 0o022:
        raise InvalidAuthorization("verification key file must not be group/world writable")
    raw = key_path.read_bytes()
    if len(raw) != 32:
        raise InvalidAuthorization("verification key must contain exactly 32 bytes")
    return VerifyKey(raw)
