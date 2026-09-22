"""Narrow repositories that never own or end database transactions."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol, cast

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.capabilities.sanitization import text_contains_sensitive_material
from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import (
    MAX_CANONICAL_DECIMAL_TEXT_LENGTH,
    DomainValidationError,
    canonical_decimal_text,
    parse_decimal,
)
from trading_bot.domain.decisions import RiskEvaluation
from trading_bot.domain.enums import (
    AssetClass,
    OrderEvent,
    OrderPurpose,
    OrderState,
    OrderType,
    Side,
    SubmissionOutcome,
    TimeInForce,
)
from trading_bot.domain.events import AuditEvent
from trading_bot.domain.identifiers import (
    AccountId,
    AuditEventId,
    CodeHash,
    ConfigHash,
    CorrelationId,
    DataHash,
    InstrumentId,
    OrderId,
    OrderIntentId,
    OrderTransitionId,
    ReviewId,
    SubmissionAttemptId,
)
from trading_bot.domain.order_matching import broker_order_matches_submission
from trading_bot.domain.order_state_machine import InvalidOrderTransition, transition
from trading_bot.domain.orders import (
    BrokerOrder,
    BrokerOrderReview,
    OrderIntent,
    PersistedReviewedOrder,
)
from trading_bot.logging import contains_registered_secret
from trading_bot.persistence.audit import _stage_audit_event
from trading_bot.persistence.base import PersistenceDataError
from trading_bot.persistence.evidence import (
    canonical_broker_order_response_sha256,
    canonical_order_intent_sha256,
    canonical_review_response_sha256,
)
from trading_bot.persistence.models import (
    BrokerReviewRow,
    OrderIntentRow,
    OrderRow,
    OrderTransitionRow,
    RiskEvaluationRow,
    SubmissionAttemptRow,
)

ActiveGuard = Callable[[], None]
ConfigGuard = Callable[[ConfigHash], None]

_STRUCTURED_EVIDENCE_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*(?::[a-z0-9_]+)*\Z")


class OrderRepository(Protocol):
    """Durable order intent, review, risk, transition, and broker-order writes."""

    async def add(self, intent: OrderIntent) -> None: ...

    async def get(self, intent_id: OrderIntentId) -> OrderIntent | None: ...

    async def add_risk_evaluation(
        self,
        evaluation_id: str,
        phase: str,
        evaluation: RiskEvaluation,
    ) -> None: ...

    async def add_transition(
        self,
        transition_id: OrderTransitionId,
        intent_id: OrderIntentId,
        order_id: OrderId | None,
        from_state: OrderState | None,
        event: OrderEvent | None,
        to_state: OrderState,
        actor: str,
        reason_code: str,
        occurred_at: datetime,
        correlation_id: CorrelationId,
    ) -> None: ...

    async def add_review(
        self,
        review_id: ReviewId,
        review: BrokerOrderReview,
    ) -> None: ...

    async def add_broker_order(
        self,
        order: BrokerOrder,
        submission: PersistedReviewedOrder,
        provider: str,
    ) -> None: ...


class AuditRepository(Protocol):
    """Insert-only audit operations; mutation methods intentionally do not exist."""

    async def append(self, event: AuditEvent) -> None: ...

    async def append_correction(
        self,
        event: AuditEvent,
        original_id: AuditEventId,
    ) -> None: ...


class SubmissionAttemptRepository(Protocol):
    """Atomic single-attempt reservation and exactly-once terminal completion."""

    async def reserve(
        self,
        submission: PersistedReviewedOrder,
        provider: str,
        attempted_at: datetime,
    ) -> bool: ...

    async def complete(
        self,
        attempt_id: SubmissionAttemptId,
        outcome: SubmissionOutcome,
        completed_at: datetime,
        response: BrokerOrder | None,
    ) -> None: ...


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


def _validate_identifier(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 255
        or contains_registered_secret(value)
    ):
        raise PersistenceDataError(f"{field_name} must be a safe nonempty identifier")


def _validate_safe_text(value: str, field_name: str, *, maximum_length: int = 128) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > maximum_length
        or contains_registered_secret(value)
        or text_contains_sensitive_material(value)
    ):
        raise PersistenceDataError(f"{field_name} must be safe bounded text")


def _validate_evidence_text(value: str, field_name: str) -> None:
    if type(value) is not str or not value.strip():
        raise PersistenceDataError(f"{field_name} must be safe bounded evidence")
    if contains_registered_secret(value):
        raise PersistenceDataError(f"{field_name} must be safe bounded evidence")
    try:
        numeric = canonical_decimal_text(parse_decimal(value)) == value
    except DomainValidationError:
        numeric = False
    if numeric:
        if len(value) > MAX_CANONICAL_DECIMAL_TEXT_LENGTH:
            raise PersistenceDataError(f"{field_name} must be safe bounded evidence")
        return
    if len(value) > 128:
        raise PersistenceDataError(f"{field_name} must be safe bounded evidence")
    if _STRUCTURED_EVIDENCE_IDENTIFIER.fullmatch(value) is not None:
        return
    if text_contains_sensitive_material(value):
        raise PersistenceDataError(f"{field_name} must be safe bounded evidence")


def _validate_evidence_identifier(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) > 128
        or _STRUCTURED_EVIDENCE_IDENTIFIER.fullmatch(value) is None
        or contains_registered_secret(value)
    ):
        raise PersistenceDataError(f"{field_name} must be a safe structured identifier")


def _utc_text(value: datetime) -> str:
    try:
        return require_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except DomainValidationError:
        raise PersistenceDataError("risk check timestamp must be UTC") from None


def _serialize_risk_checks(evaluation: RiskEvaluation) -> str:
    checks: list[dict[str, object]] = []
    for check in evaluation.checks:
        _validate_evidence_identifier(check.code, "risk check code")
        _validate_evidence_identifier(check.reason, "risk check reason")
        if check.observed is not None:
            _validate_evidence_text(check.observed, "risk check observation")
        if check.configured_limit is not None:
            _validate_evidence_text(check.configured_limit, "risk check configured limit")
        checks.append(
            {
                "allowed": check.allowed,
                "code": check.code,
                "configured_limit": check.configured_limit,
                "observed": check.observed,
                "observed_at": _utc_text(check.observed_at),
                "reason": check.reason,
            }
        )
    try:
        return json.dumps(
            checks,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise PersistenceDataError("risk checks cannot be serialized canonically") from exc


def _broker_order_matches_attempt(
    order: BrokerOrder,
    attempt: SubmissionAttemptRow,
    intent: OrderIntent,
) -> bool:
    return (
        order.intent_id == intent.id == attempt.intent_id
        and order.account_id == intent.account_id == attempt.account_id
        and order.client_order_id == attempt.provider_client_reference
        and order.instrument_id == intent.instrument_id == attempt.instrument_id
        and order.side is intent.side
        and order.purpose is intent.purpose
        and order.order_type is intent.order_type
        and order.time_in_force is intent.time_in_force
        and order.requested_quantity == intent.quantity
        and order.limit_price == intent.limit_price
        and order.stop_price == intent.stop_price
    )


def _order_row_matches_response(
    row: OrderRow,
    response: BrokerOrder,
    attempt: SubmissionAttemptRow,
) -> bool:
    """Bind the terminal response hash to the durable order row for this attempt."""

    return (
        row.id == response.id
        and row.intent_id == response.intent_id == attempt.intent_id
        and row.review_id == attempt.review_id
        and row.submission_attempt_id == attempt.id
        and row.provider == attempt.provider
        and row.broker_order_id == response.broker_order_id
        and row.client_order_id == response.client_order_id
        and row.account_id == response.account_id == attempt.account_id
        and row.instrument_id == response.instrument_id == attempt.instrument_id
        and row.side == response.side.value
        and row.purpose == response.purpose.value
        and row.order_type == response.order_type.value
        and row.time_in_force == response.time_in_force.value
        and row.state == response.state.value
        and row.requested_quantity == response.requested_quantity
        and row.filled_quantity == response.filled_quantity
        and row.limit_price == response.limit_price
        and row.stop_price == response.stop_price
        and row.created_at == response.created_at
        and row.updated_at == response.updated_at
        and row.data_hash == response.data_hash
    )


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
        row = OrderIntentRow(
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
        self._session.add(row)
        await self._session.flush((row,))
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

    async def _require_intent(self, intent_id: OrderIntentId) -> OrderIntent:
        intent = await self.get(intent_id)
        if intent is None:
            raise PersistenceDataError("order intent must be durable before dependent evidence")
        return intent

    async def add_risk_evaluation(
        self,
        evaluation_id: str,
        phase: str,
        evaluation: RiskEvaluation,
    ) -> None:
        """Stage one append-only preliminary or final risk evaluation."""

        self._ensure_active()
        _validate_identifier(evaluation_id, "risk evaluation id")
        if type(phase) is not str or phase not in {"initial", "final"}:
            raise PersistenceDataError("risk evaluation phase must be initial or final")
        if type(evaluation) is not RiskEvaluation:
            raise PersistenceDataError("evaluation must use the canonical domain record")
        intent = await self._require_intent(evaluation.intent_id)
        if evaluation.config_hash != intent.config_hash:
            raise PersistenceDataError("risk evaluation configuration does not match intent")
        self._ensure_config_hash(evaluation.config_hash)
        self._session.add(
            RiskEvaluationRow(
                id=evaluation_id,
                intent_id=evaluation.intent_id,
                phase=phase,
                allowed=evaluation.allowed,
                check_count=len(evaluation.checks),
                checks_json=_serialize_risk_checks(evaluation),
                evaluated_at=evaluation.evaluated_at,
                config_hash=evaluation.config_hash,
                corrects_id=None,
            )
        )

    async def add_transition(
        self,
        transition_id: OrderTransitionId,
        intent_id: OrderIntentId,
        order_id: OrderId | None,
        from_state: OrderState | None,
        event: OrderEvent | None,
        to_state: OrderState,
        actor: str,
        reason_code: str,
        occurred_at: datetime,
        correlation_id: CorrelationId,
    ) -> None:
        """Stage one validated append-only order transition."""

        self._ensure_active()
        _validate_identifier(transition_id, "order transition id")
        _validate_identifier(intent_id, "order intent id")
        if order_id is not None:
            _validate_identifier(order_id, "local order id")
        _validate_identifier(correlation_id, "transition correlation id")
        _validate_safe_text(actor, "transition actor")
        _validate_safe_text(reason_code, "transition reason code")
        try:
            require_utc(occurred_at)
        except DomainValidationError:
            raise PersistenceDataError("transition timestamp must be UTC") from None
        if type(to_state) is not OrderState:
            raise PersistenceDataError("transition target must be an OrderState")

        if from_state is None or event is None:
            if not (
                from_state is None
                and event is None
                and to_state is OrderState.PROPOSED
                and order_id is None
            ):
                raise PersistenceDataError("initial transition must be exactly PROPOSED")
            event_value = OrderState.PROPOSED.value
        else:
            if type(from_state) is not OrderState or type(event) is not OrderEvent:
                raise PersistenceDataError("transition source and event must be canonical enums")
            try:
                expected = transition(from_state, event)
            except InvalidOrderTransition:
                raise PersistenceDataError("order transition is not allowed") from None
            if expected is not to_state:
                raise PersistenceDataError("order transition target does not match the event")
            event_value = event.value

        intent = await self._require_intent(intent_id)
        self._ensure_config_hash(intent.config_hash)
        self._session.add(
            OrderTransitionRow(
                id=transition_id,
                intent_id=intent_id,
                order_id=order_id,
                from_state=None if from_state is None else from_state.value,
                event=event_value,
                to_state=to_state.value,
                actor=actor,
                reason_code=reason_code,
                occurred_at=occurred_at,
                config_hash=intent.config_hash,
                correlation_id=correlation_id,
                corrects_id=None,
            )
        )

    async def add_review(
        self,
        review_id: ReviewId,
        review: BrokerOrderReview,
    ) -> None:
        """Stage sanitized review evidence with repository-derived binding hashes."""

        self._ensure_active()
        _validate_identifier(review_id, "review id")
        if type(review) is not BrokerOrderReview:
            raise PersistenceDataError("review must use the canonical domain record")
        _validate_safe_text(review.source, "review source")
        if review.broker_review_id is not None:
            _validate_identifier(review.broker_review_id, "broker review id")
        intent = await self._require_intent(review.normalized_order.id)
        if intent != review.normalized_order:
            raise PersistenceDataError("review normalization does not match the durable intent")
        self._ensure_config_hash(intent.config_hash)
        row = BrokerReviewRow(
            id=review_id,
            intent_id=intent.id,
            source=review.source,
            reviewed_at=review.reviewed_at,
            expires_at=review.expires_at,
            estimated_notional=review.estimated_notional,
            estimated_fees=review.estimated_fees,
            client_order_id=review.client_order_id,
            outbound_payload_sha256=review.outbound_payload_sha256,
            normalized_intent_hash=canonical_order_intent_sha256(intent),
            sanitized_response_hash=canonical_review_response_sha256(review),
            broker_review_id=review.broker_review_id,
        )
        self._session.add(row)
        await self._session.flush((row,))

    async def add_broker_order(
        self,
        order: BrokerOrder,
        submission: PersistedReviewedOrder,
        provider: str,
    ) -> None:
        """Stage one canonical broker response bound to its complete local chain."""

        self._ensure_active()
        if type(order) is not BrokerOrder:
            raise PersistenceDataError("order must use the canonical domain record")
        if type(submission) is not PersistedReviewedOrder:
            raise PersistenceDataError("submission must use the canonical domain record")
        _validate_safe_text(provider, "provider", maximum_length=64)
        _validate_identifier(order.id, "local order id")
        _validate_identifier(order.broker_order_id, "broker order id")
        self._ensure_config_hash(submission.config_hash)
        intent = await self._require_intent(submission.review.normalized_order.id)
        if intent != submission.review.normalized_order:
            raise PersistenceDataError("submission review does not match the durable intent")
        if not broker_order_matches_submission(order, submission):
            raise PersistenceDataError("broker order does not match the persisted submission")
        row = OrderRow(
            id=order.id,
            intent_id=intent.id,
            review_id=submission.review_id,
            submission_attempt_id=submission.submission_attempt_id,
            provider=provider,
            broker_order_id=order.broker_order_id,
            client_order_id=order.client_order_id,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            side=order.side.value,
            purpose=order.purpose.value,
            order_type=order.order_type.value,
            time_in_force=order.time_in_force.value,
            state=order.state.value,
            requested_quantity=order.requested_quantity,
            filled_quantity=order.filled_quantity,
            limit_price=order.limit_price,
            stop_price=order.stop_price,
            average_fill_price=None,
            created_at=order.created_at,
            updated_at=order.updated_at,
            data_hash=order.data_hash,
        )
        self._session.add(row)
        await self._session.flush((row,))


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
    """SQL-backed crash boundary for one and only one placement attempt."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        ensure_active: ActiveGuard,
        ensure_config_hash: ConfigGuard,
    ) -> None:
        super().__init__(session, ensure_active=ensure_active)
        self._ensure_config_hash = ensure_config_hash

    async def reserve(
        self,
        submission: PersistedReviewedOrder,
        provider: str,
        attempted_at: datetime,
    ) -> bool:
        """Atomically insert the sole pending attempt; return false on any duplicate key."""

        self._ensure_active()
        if type(submission) is not PersistedReviewedOrder:
            raise PersistenceDataError("submission must use the canonical domain record")
        _validate_safe_text(provider, "provider", maximum_length=64)
        try:
            require_utc(attempted_at)
        except DomainValidationError:
            raise PersistenceDataError("submission timestamp must be UTC") from None
        review = submission.review
        if attempted_at < review.reviewed_at or attempted_at >= review.expires_at:
            raise PersistenceDataError("submission attempt requires a current prior review")
        self._ensure_config_hash(submission.config_hash)
        if submission.account_id != review.normalized_order.account_id:
            raise PersistenceDataError("submission account does not match the review")

        statement = (
            sqlite_insert(SubmissionAttemptRow)
            .values(
                id=submission.submission_attempt_id,
                intent_id=review.normalized_order.id,
                review_id=submission.review_id,
                account_id=submission.account_id,
                instrument_id=review.normalized_order.instrument_id,
                deduplication_key=submission.deduplication_key,
                provider=provider,
                provider_client_reference=review.client_order_id,
                fencing_token=submission.fencing_token,
                attempt_started_at=attempted_at,
                execution_mode=submission.execution_mode.value,
                live_lease_id=submission.live_lease_id,
                live_lease_evidence_hash=submission.live_lease_evidence_hash,
                completed_at=None,
                outcome_class=SubmissionOutcome.PENDING.value,
                sanitized_response_hash=None,
            )
            .on_conflict_do_nothing()
        )
        result = cast(CursorResult[Any], await self._session.execute(statement))
        return result.rowcount == 1

    async def complete(
        self,
        attempt_id: SubmissionAttemptId,
        outcome: SubmissionOutcome,
        completed_at: datetime,
        response: BrokerOrder | None,
    ) -> None:
        """Complete one pending attempt exactly once with only canonical response evidence."""

        self._ensure_active()
        _validate_identifier(attempt_id, "submission attempt id")
        if type(outcome) is not SubmissionOutcome or outcome is SubmissionOutcome.PENDING:
            raise PersistenceDataError("submission completion requires a terminal outcome")
        try:
            require_utc(completed_at)
        except DomainValidationError:
            raise PersistenceDataError("submission completion timestamp must be UTC") from None
        if response is not None and type(response) is not BrokerOrder:
            raise PersistenceDataError("submission response must be a BrokerOrder or None")

        attempt = await self._session.get(SubmissionAttemptRow, attempt_id)
        if attempt is None:
            raise PersistenceDataError("submission attempt does not exist")
        if (
            attempt.outcome_class != SubmissionOutcome.PENDING.value
            or attempt.completed_at is not None
        ):
            raise PersistenceDataError("submission attempt already has a terminal outcome")
        if completed_at < attempt.attempt_started_at:
            raise PersistenceDataError("submission completion cannot precede its attempt")

        intent_row = await self._session.get(OrderIntentRow, attempt.intent_id)
        if intent_row is None:
            raise PersistenceDataError("submission intent is not durable")
        intent = _intent_from_row(intent_row)
        if outcome in {SubmissionOutcome.ACCEPTED, SubmissionOutcome.REJECTED}:
            if response is None or not _broker_order_matches_attempt(response, attempt, intent):
                raise PersistenceDataError("terminal broker response does not match the attempt")
            if outcome is SubmissionOutcome.ACCEPTED and response.state not in {
                OrderState.SUBMITTED,
                OrderState.PARTIALLY_FILLED,
                OrderState.FILLED,
            }:
                raise PersistenceDataError("accepted response has a non-accepted order state")
            if outcome is SubmissionOutcome.REJECTED and response.state is not OrderState.REJECTED:
                raise PersistenceDataError("rejected response has a non-rejected order state")
            order_row = await self._session.scalar(
                select(OrderRow).where(OrderRow.submission_attempt_id == attempt_id)
            )
            if order_row is None or not _order_row_matches_response(
                order_row,
                response,
                attempt,
            ):
                raise PersistenceDataError(
                    "known submission outcome requires its matching durable broker order"
                )

        response_hash = (
            None if response is None else canonical_broker_order_response_sha256(response)
        )
        statement = (
            update(SubmissionAttemptRow)
            .where(
                SubmissionAttemptRow.id == attempt_id,
                SubmissionAttemptRow.outcome_class == SubmissionOutcome.PENDING.value,
                SubmissionAttemptRow.completed_at.is_(None),
            )
            .values(
                completed_at=completed_at,
                outcome_class=outcome.value,
                sanitized_response_hash=response_hash,
            )
        )
        result = cast(CursorResult[Any], await self._session.execute(statement))
        if result.rowcount != 1:
            raise PersistenceDataError("submission attempt already has a terminal outcome")


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
