"""Transactional one-time activation consumption in the durable ledger."""

import hashlib
import json

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trading_bot.authorization.models import LiveAuthorization, LiveLease
from trading_bot.authorization.verifier import InvalidAuthorization
from trading_bot.domain.decimal_utils import canonical_decimal_text
from trading_bot.persistence.models import LiveAuthorizationRow, LiveLeaseRow, UsedNonceRow


def _lease_hash(lease: LiveLease) -> str:
    payload = {
        "account_id": lease.account_id,
        "authorization_id": lease.authorization_id,
        "authorized_risk_equity": canonical_decimal_text(lease.authorized_risk_equity),
        "code_hash": lease.code_hash,
        "config_hash": lease.config_hash,
        "expires_at": lease.expires_at.isoformat(),
        "issued_at": lease.issued_at.isoformat(),
        "promotion_evidence_hash": lease.promotion_evidence_hash,
        "stage": lease.stage.value,
        "strategy_eligibility_hash": lease.strategy_eligibility_hash,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class SqlAuthorizationStore:
    """Persist authorization, nonce, and lease in one database transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def consume_once(self, authorization: LiveAuthorization, lease: LiveLease) -> None:
        payload = authorization.payload
        lease_hash = _lease_hash(lease)
        try:
            async with self._session_factory.begin() as session:
                session.add(
                    LiveAuthorizationRow(
                        id=payload.authorization_id,
                        account_id=payload.account_id,
                        stage=payload.stage.value,
                        activation_nonce=payload.nonce,
                        artifact_hash=authorization.artifact_hash,
                        preflight_hash=payload.preflight_hash,
                        acknowledgement_hash=payload.acknowledgement_hash,
                        config_hash=payload.config_hash,
                        code_hash=payload.code_hash,
                        strategy_eligibility_hash=payload.strategy_eligibility_hash,
                        promotion_evidence_hash=payload.promotion_evidence_hash,
                        promotion_eligible=True,
                        authorized_risk_equity=payload.authorized_risk_equity,
                        issued_at=payload.issued_at,
                        expires_at=payload.expires_at,
                        consumed_at=authorization.consumed_at,
                        status="consumed",
                        evidence_hash=authorization.artifact_hash,
                        corrects_id=None,
                    )
                )
                session.add(
                    UsedNonceRow(
                        nonce=payload.nonce,
                        authorization_id=payload.authorization_id,
                        artifact_hash=authorization.artifact_hash,
                        used_at=authorization.consumed_at,
                    )
                )
                session.add(
                    LiveLeaseRow(
                        id=f"lease-{payload.authorization_id}",
                        authorization_id=payload.authorization_id,
                        account_id=payload.account_id,
                        stage=payload.stage.value,
                        issued_at=lease.issued_at,
                        expires_at=lease.expires_at,
                        revoked_at=None,
                        revocation_reason=None,
                        authorized_risk_equity=lease.authorized_risk_equity,
                        config_hash=lease.config_hash,
                        code_hash=lease.code_hash,
                        strategy_eligibility_hash=lease.strategy_eligibility_hash,
                        promotion_evidence_hash=lease.promotion_evidence_hash,
                        evidence_hash=lease_hash,
                    )
                )
        except IntegrityError:
            raise InvalidAuthorization(
                "activation nonce is already used or evidence is invalid"
            ) from None


__all__ = ["SqlAuthorizationStore"]
