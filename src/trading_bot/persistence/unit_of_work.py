"""Explicit async transaction boundary for coherent ledger writes."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self, TypeVar, cast

from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction, async_sessionmaker

from trading_bot.domain.identifiers import CodeHash, ConfigHash
from trading_bot.persistence.base import PersistenceDataError, _require_validated_session_factory
from trading_bot.persistence.owned_economic_journal import EconomicRepository, SqlEconomicRepository
from trading_bot.persistence.repositories import (
    AuditRepository,
    AuthorizationRepository,
    DataQualityRepository,
    EvidenceRepository,
    FillRepository,
    OrderRepository,
    ReconciliationRepository,
    SubmissionAttemptRepository,
    _SqlAuditRepository,
    _SqlAuthorizationRepository,
    _SqlDataQualityRepository,
    _SqlEvidenceRepository,
    _SqlFillRepository,
    _SqlOrderRepository,
    _SqlReconciliationRepository,
    _SqlSubmissionAttemptRepository,
    _validate_config_hash,
)

RepositoryT = TypeVar("RepositoryT")


class UnitOfWorkStateError(RuntimeError):
    """Raised when callers attempt to escape the explicit transaction lifecycle."""


class UnitOfWork(Protocol):
    """Transaction boundary shared by all durable trading repositories."""

    @property
    def orders(self) -> OrderRepository: ...

    @property
    def submission_attempts(self) -> SubmissionAttemptRepository: ...

    @property
    def fills(self) -> FillRepository: ...

    @property
    def data_quality(self) -> DataQualityRepository: ...

    @property
    def audit(self) -> AuditRepository: ...

    @property
    def authorizations(self) -> AuthorizationRepository: ...

    @property
    def reconciliation(self) -> ReconciliationRepository: ...

    @property
    def evidence(self) -> EvidenceRepository: ...

    @property
    def economics(self) -> EconomicRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class SqlAlchemyUnitOfWork:
    """Single-use SQLAlchemy unit of work with explicit commit and fail-closed exit."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        code_hash: CodeHash,
        config_hash: ConfigHash,
    ) -> None:
        self._session_factory = _require_validated_session_factory(session_factory)
        self._bound_engine = self._session_factory.kw["bind"]
        self._code_hash = code_hash
        _validate_config_hash(config_hash)
        self._config_hash = config_hash
        self._session: AsyncSession | None = None
        self._transaction: AsyncSessionTransaction | None = None
        self._entered = False
        self._completed = False
        self._exited = False
        self._failed = False
        self._orders: OrderRepository | None = None
        self._submission_attempts: SubmissionAttemptRepository | None = None
        self._fills: FillRepository | None = None
        self._data_quality: DataQualityRepository | None = None
        self._audit: AuditRepository | None = None
        self._authorizations: AuthorizationRepository | None = None
        self._reconciliation: ReconciliationRepository | None = None
        self._evidence: EvidenceRepository | None = None
        self._economics: EconomicRepository | None = None

    def _ensure_transaction_active(self) -> None:
        transaction = self._transaction
        if (
            not self._entered
            or self._failed
            or self._completed
            or self._exited
            or transaction is None
            or not transaction.is_active
        ):
            raise UnitOfWorkStateError("unit of work has no active transaction")

    def _mark_failed(self) -> None:
        self._failed = True

    def _repository(self, repository: RepositoryT | None) -> RepositoryT:
        self._ensure_transaction_active()
        if repository is None:
            raise UnitOfWorkStateError("unit of work repository is unavailable")
        return repository

    def _ensure_config_hash(self, config_hash: ConfigHash) -> None:
        if config_hash != self._config_hash:
            raise PersistenceDataError(
                "record configuration identity does not match the unit of work"
            )

    @property
    def orders(self) -> OrderRepository:
        return self._repository(self._orders)

    @property
    def submission_attempts(self) -> SubmissionAttemptRepository:
        return self._repository(self._submission_attempts)

    @property
    def fills(self) -> FillRepository:
        return self._repository(self._fills)

    @property
    def data_quality(self) -> DataQualityRepository:
        return self._repository(self._data_quality)

    @property
    def audit(self) -> AuditRepository:
        return self._repository(self._audit)

    @property
    def authorizations(self) -> AuthorizationRepository:
        return self._repository(self._authorizations)

    @property
    def reconciliation(self) -> ReconciliationRepository:
        return self._repository(self._reconciliation)

    @property
    def evidence(self) -> EvidenceRepository:
        return self._repository(self._evidence)

    @property
    def economics(self) -> EconomicRepository:
        return self._repository(self._economics)

    async def __aenter__(self) -> Self:
        if self._entered or self._exited:
            raise UnitOfWorkStateError("unit of work instances are single-use")

        self._entered = True
        validated_factory = _require_validated_session_factory(self._session_factory)
        if validated_factory.kw.get("bind") is not self._bound_engine:
            raise UnitOfWorkStateError("unit of work session factory binding changed")
        session = self._session_factory()
        self._session = session
        try:
            self._transaction = await session.begin()
            self._orders = _SqlOrderRepository(
                session,
                code_hash=self._code_hash,
                ensure_active=self._ensure_transaction_active,
                ensure_config_hash=self._ensure_config_hash,
            )
            self._submission_attempts = cast(
                SubmissionAttemptRepository,
                _SqlSubmissionAttemptRepository(
                    session,
                    ensure_active=self._ensure_transaction_active,
                    ensure_config_hash=self._ensure_config_hash,
                ),
            )
            self._fills = cast(
                FillRepository,
                _SqlFillRepository(session, ensure_active=self._ensure_transaction_active),
            )
            self._data_quality = cast(
                DataQualityRepository,
                _SqlDataQualityRepository(
                    session,
                    ensure_active=self._ensure_transaction_active,
                ),
            )
            self._audit = _SqlAuditRepository(
                session,
                code_hash=self._code_hash,
                ensure_active=self._ensure_transaction_active,
                ensure_config_hash=self._ensure_config_hash,
            )
            self._authorizations = cast(
                AuthorizationRepository,
                _SqlAuthorizationRepository(
                    session,
                    ensure_active=self._ensure_transaction_active,
                ),
            )
            self._reconciliation = cast(
                ReconciliationRepository,
                _SqlReconciliationRepository(
                    session,
                    ensure_active=self._ensure_transaction_active,
                ),
            )
            self._evidence = cast(
                EvidenceRepository,
                _SqlEvidenceRepository(session, ensure_active=self._ensure_transaction_active),
            )
            self._economics = SqlEconomicRepository(
                session,
                code_hash=self._code_hash,
                ensure_active=self._ensure_transaction_active,
                ensure_config=self._ensure_config_hash,
                mark_failed=self._mark_failed,
            )
        except BaseException:
            transaction = self._transaction
            try:
                if transaction is not None and transaction.is_active:
                    await transaction.rollback()
            finally:
                try:
                    await session.close()
                finally:
                    self._completed = True
                    self._exited = True
                    self._transaction = None
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        session = self._session
        transaction = self._transaction
        if not self._entered or self._exited or session is None or transaction is None:
            raise UnitOfWorkStateError("unit of work context is not active")

        try:
            if transaction.is_active:
                await transaction.rollback()
        finally:
            try:
                await session.close()
            finally:
                self._completed = True
                self._exited = True
                self._transaction = None

    async def commit(self) -> None:
        self._ensure_transaction_active()
        transaction = self._transaction
        if transaction is None:
            raise UnitOfWorkStateError("unit of work transaction is unavailable")
        try:
            await transaction.commit()
        except BaseException:
            try:
                if transaction.is_active:
                    await transaction.rollback()
            finally:
                self._completed = True
            raise
        else:
            self._completed = True

    async def rollback(self) -> None:
        self._ensure_transaction_active()
        transaction = self._transaction
        if transaction is None:
            raise UnitOfWorkStateError("unit of work transaction is unavailable")
        try:
            await transaction.rollback()
        finally:
            self._completed = True


__all__ = ["SqlAlchemyUnitOfWork", "UnitOfWork", "UnitOfWorkStateError"]
