"""Narrow repositories that never own or end database transactions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.domain.enums import AssetClass, OrderPurpose, OrderType, Side, TimeInForce
from trading_bot.domain.events import AuditEvent
from trading_bot.domain.identifiers import (
    AccountId,
    AuditEventId,
    CodeHash,
    ConfigHash,
    DataHash,
    InstrumentId,
    OrderIntentId,
)
from trading_bot.domain.orders import OrderIntent
from trading_bot.persistence.audit import _stage_audit_event
from trading_bot.persistence.base import PersistenceDataError
from trading_bot.persistence.models import OrderIntentRow

ActiveGuard = Callable[[], None]
ConfigGuard = Callable[[ConfigHash], None]


class OrderRepository(Protocol):
    """Durable order-intent operations supported by current domain records."""

    async def add(self, intent: OrderIntent) -> None: ...

    async def get(self, intent_id: OrderIntentId) -> OrderIntent | None: ...


class AuditRepository(Protocol):
    """Insert-only audit operations; mutation methods intentionally do not exist."""

    async def append(self, event: AuditEvent) -> None: ...

    async def append_correction(
        self,
        event: AuditEvent,
        original_id: AuditEventId,
    ) -> None: ...


class SubmissionAttemptRepository(Protocol):
    """Reserved interface pending a complete submission persistence command."""


class FillRepository(Protocol):
    """Reserved interface pending a provider-scoped fill persistence command."""


class DataQualityRepository(Protocol):
    """Reserved interface pending the data-quality domain record."""


class AuthorizationRepository(Protocol):
    """Reserved interface pending complete authorization and lease commands."""


class ReconciliationRepository(Protocol):
    """Reserved interface pending a lossless reconciliation persistence command."""


class EvidenceRepository(Protocol):
    """Reserved interface pending explicit research and promotion evidence commands."""


def _validate_sha256_hash(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise PersistenceDataError(f"{field_name} must be lowercase SHA-256 hex")


def _validate_code_hash(code_hash: CodeHash) -> None:
    _validate_sha256_hash(code_hash, "code_hash")


def _validate_config_hash(config_hash: ConfigHash) -> None:
    _validate_sha256_hash(config_hash, "config_hash")


def _intent_from_row(row: OrderIntentRow) -> OrderIntent:
    try:
        return OrderIntent(
            id=OrderIntentId(row.id),
            account_id=AccountId(row.account_id),
            instrument_id=InstrumentId(row.instrument_id),
            asset_class=AssetClass(row.asset_class),
            side=Side(row.side),
            purpose=OrderPurpose(row.purpose),
            order_type=OrderType(row.order_type),
            time_in_force=TimeInForce(row.time_in_force),
            quantity=row.quantity,
            limit_price=row.limit_price,
            stop_price=row.stop_price,
            created_at=row.created_at,
            expires_at=row.expires_at,
            strategy_version=row.strategy_version,
            config_hash=ConfigHash(row.config_hash),
            data_hash=DataHash(row.data_hash),
            exit_policy_version=row.exit_policy_version,
        )
    except (DomainValidationError, ValueError):
        raise PersistenceDataError("stored order intent violates the domain contract") from None


class _SqlOrderRepository:
    """SQLAlchemy-backed order-intent repository bound to one active transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        code_hash: CodeHash,
        ensure_active: ActiveGuard,
        ensure_config_hash: ConfigGuard,
    ) -> None:
        _validate_code_hash(code_hash)
        self._session = session
        self._code_hash = code_hash
        self._ensure_active = ensure_active
        self._ensure_config_hash = ensure_config_hash
        self._pending: dict[OrderIntentId, OrderIntent] = {}

    async def add(self, intent: OrderIntent) -> None:
        """Stage one local intent without flushing or ending the transaction."""
        self._ensure_active()
        if type(intent) is not OrderIntent:
            raise PersistenceDataError("intent must use the canonical domain record")
        self._ensure_config_hash(intent.config_hash)
        pending = self._pending.get(intent.id)
        if pending is not None:
            if pending == intent:
                return
            raise PersistenceDataError("intent id conflicts with a pending intent")
        self._session.add(
            OrderIntentRow(
                id=intent.id,
                account_id=intent.account_id,
                instrument_id=intent.instrument_id,
                strategy_decision_id=None,
                asset_class=intent.asset_class.value,
                side=intent.side.value,
                purpose=intent.purpose.value,
                order_type=intent.order_type.value,
                time_in_force=intent.time_in_force.value,
                quantity=intent.quantity,
                limit_price=intent.limit_price,
                stop_price=intent.stop_price,
                created_at=intent.created_at,
                expires_at=intent.expires_at,
                strategy_version=intent.strategy_version,
                config_hash=intent.config_hash,
                code_hash=self._code_hash,
                data_hash=intent.data_hash,
                exit_policy_version=intent.exit_policy_version,
            )
        )
        self._pending[intent.id] = intent

    async def get(self, intent_id: OrderIntentId) -> OrderIntent | None:
        """Load and validate one durable intent by its local identifier."""
        self._ensure_active()
        if type(intent_id) is not str or not intent_id:
            raise PersistenceDataError("intent_id must be a nonempty exact string")
        pending = self._pending.get(intent_id)
        if pending is not None:
            return pending
        row = await self._session.get(OrderIntentRow, intent_id)
        return None if row is None else _intent_from_row(row)


class _SqlAuditRepository:
    """SQLAlchemy-backed append-only audit repository."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        code_hash: CodeHash,
        ensure_active: ActiveGuard,
        ensure_config_hash: ConfigGuard,
    ) -> None:
        _validate_code_hash(code_hash)
        self._session = session
        self._code_hash = code_hash
        self._ensure_active = ensure_active
        self._ensure_config_hash = ensure_config_hash

    def _validate_event(self, event: AuditEvent) -> None:
        if type(event) is not AuditEvent:
            raise PersistenceDataError("audit event must use the canonical domain record")
        if event.code_hash != self._code_hash:
            raise PersistenceDataError("audit event code identity does not match the unit of work")
        self._ensure_config_hash(event.config_hash)

    async def append(self, event: AuditEvent) -> None:
        """Stage one original audit event in the caller-owned transaction."""
        self._ensure_active()
        self._validate_event(event)
        _stage_audit_event(self._session, event)

    async def append_correction(
        self,
        event: AuditEvent,
        original_id: AuditEventId,
    ) -> None:
        """Stage a compensating event that preserves its original event."""
        self._ensure_active()
        self._validate_event(event)
        if type(original_id) is not str or not original_id:
            raise PersistenceDataError("original audit event id must be nonempty")
        _stage_audit_event(self._session, event, corrects_id=original_id)


class _DeferredSqlRepository:
    """Retain transaction identity without inventing an unsupported write API."""

    def __init__(self, session: AsyncSession, *, ensure_active: ActiveGuard) -> None:
        self._session = session
        self._ensure_active = ensure_active


class _SqlSubmissionAttemptRepository(_DeferredSqlRepository):
    """Submission persistence will land with its complete idempotency command."""


class _SqlFillRepository(_DeferredSqlRepository):
    """Fill persistence will land with its provider-scoped replay command."""


class _SqlDataQualityRepository(_DeferredSqlRepository):
    """Data-quality persistence will land with its domain event."""


class _SqlAuthorizationRepository(_DeferredSqlRepository):
    """Authorization persistence will land with its full provenance command."""


class _SqlReconciliationRepository(_DeferredSqlRepository):
    """Reconciliation persistence will land with its lossless command."""


class _SqlEvidenceRepository(_DeferredSqlRepository):
    """Evidence persistence will land with explicit evidence commands."""


__all__ = [
    "AuditRepository",
    "AuthorizationRepository",
    "DataQualityRepository",
    "EvidenceRepository",
    "FillRepository",
    "OrderRepository",
    "ReconciliationRepository",
    "SubmissionAttemptRepository",
]
