"""Atomic reconciliation journal and live-lease revocation."""

import hashlib
import json

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trading_bot.domain import CodeHash, ConfigHash
from trading_bot.persistence.models import LiveLeaseRow, ReconciliationEventRow
from trading_bot.reconciliation.models import ReconciliationResult


class SqlReconciliationStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        config_hash: ConfigHash,
        code_hash: CodeHash,
    ) -> None:
        self._factory = session_factory
        self._config_hash = config_hash
        self._code_hash = code_hash

    async def persist(self, result: ReconciliationResult) -> None:
        differences = [
            {
                "broker_value": item.broker_value,
                "code": item.code,
                "identity": item.identity,
                "local_value": item.local_value,
                "material": item.material,
            }
            for item in result.differences
        ]
        encoded = json.dumps(differences, sort_keys=True, separators=(",", ":"))
        evidence_hash = hashlib.sha256(encoded.encode()).hexdigest()
        async with self._factory.begin() as session:
            session.add(
                ReconciliationEventRow(
                    id=result.reconciliation_id,
                    reconciliation_id=result.reconciliation_id,
                    account_id=result.account_id,
                    clean=result.clean,
                    drift_count=len(result.differences),
                    differences_json=encoded,
                    observed_at=result.observed_at,
                    evidence_hash=evidence_hash,
                    config_hash=self._config_hash,
                    code_hash=self._code_hash,
                    corrects_id=None,
                )
            )
            if not result.clean:
                await session.execute(
                    update(LiveLeaseRow)
                    .where(
                        LiveLeaseRow.account_id == result.account_id,
                        LiveLeaseRow.revoked_at.is_(None),
                    )
                    .values(revoked_at=result.observed_at, revocation_reason="reconciliation_drift")
                )


__all__ = ["SqlReconciliationStore"]
