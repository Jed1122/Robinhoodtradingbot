"""Single broker-neutral, persisted-before-place execution sequence."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from trading_bot.brokers import BrokerPlace
from trading_bot.clock import Clock, require_utc
from trading_bot.domain import (
    BrokerOrder,
    BrokerOrderReview,
    CorrelationId,
    DomainValidationError,
    ExecutionMode,
    OrderEvent,
    OrderIntent,
    OrderIntentId,
    OrderState,
    OrderTransitionId,
    PersistedReviewedOrder,
    ReviewId,
    RiskEvaluation,
    SubmissionAttemptId,
    SubmissionOutcome,
)
from trading_bot.domain.order_matching import broker_order_matches_submission
from trading_bot.domain.order_state_machine import transition
from trading_bot.execution.exclusion import SubmissionExclusion
from trading_bot.execution.idempotency import derive_deduplication_key
from trading_bot.execution.review import OrderReviewService
from trading_bot.persistence.unit_of_work import UnitOfWork
from trading_bot.risk.pretrade import FinalPretradeContext, InitialRiskContext

_LIVE_MODES = frozenset({ExecutionMode.MICRO_LIVE, ExecutionMode.NORMAL_LIVE})


class PretradeContextLoader(Protocol):
    """Load new immutable broker/account/market evidence for each risk phase."""

    async def load_initial(self, intent: OrderIntent) -> InitialRiskContext: ...

    async def load_final(
        self,
        intent: OrderIntent,
        review: BrokerOrderReview,
    ) -> FinalPretradeContext: ...


class PretradeEvaluator(Protocol):
    """Common preliminary and final evaluator contract used by the service."""

    def evaluate_initial(self, context: InitialRiskContext) -> RiskEvaluation: ...

    def evaluate_final(self, context: FinalPretradeContext) -> RiskEvaluation: ...


class ExecutionObserver(Protocol):
    """Owner-local receipt seam, never a broker or authorization capability."""

    async def decision(self, intent: OrderIntent) -> None: ...

    async def submitting(self, submission: PersistedReviewedOrder) -> None: ...

    async def responded(
        self, submission: PersistedReviewedOrder, response: BrokerOrder
    ) -> None: ...


UnitOfWorkFactory = Callable[[], UnitOfWork]


class DuplicateSubmissionAttempt(RuntimeError):
    """Indicate that the durable one-attempt boundary already exists."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__("submission attempt already exists")


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Sanitized terminal result of one execution-service invocation."""

    intent_id: OrderIntentId
    state: OrderState
    reason_code: str
    correlation_id: CorrelationId
    review_id: ReviewId | None
    submission_attempt_id: SubmissionAttemptId | None
    broker_order: BrokerOrder | None

    def __post_init__(self) -> None:
        if type(self.intent_id) is not str or not self.intent_id.strip():
            raise DomainValidationError("intent_id must be a nonempty exact string")
        if type(self.state) is not OrderState:
            raise DomainValidationError("state must be an OrderState")
        if type(self.reason_code) is not str or not self.reason_code.strip():
            raise DomainValidationError("reason_code must be a nonempty exact string")
        if type(self.correlation_id) is not str or not self.correlation_id.strip():
            raise DomainValidationError("correlation_id must be a nonempty exact string")
        if self.review_id is not None and (
            type(self.review_id) is not str or not self.review_id.strip()
        ):
            raise DomainValidationError("review_id must be a nonempty exact string or None")
        if self.submission_attempt_id is not None and (
            type(self.submission_attempt_id) is not str or not self.submission_attempt_id.strip()
        ):
            raise DomainValidationError(
                "submission_attempt_id must be a nonempty exact string or None"
            )
        if self.broker_order is not None and type(self.broker_order) is not BrokerOrder:
            raise DomainValidationError("broker_order must be a BrokerOrder or None")


def _derived_id(intent: OrderIntent, purpose: str) -> str:
    digest = hashlib.sha256(f"{intent.id}|{purpose}".encode()).hexdigest()
    return f"{purpose}-{digest}"


class ExecutionService:
    """Own the only risk-approved call path to a broker placement capability."""

    __slots__ = (
        "_clock",
        "_context_loader",
        "_exclusion",
        "_mode",
        "_observer",
        "_place",
        "_pretrade",
        "_provider",
        "_review",
        "_uow_factory",
    )

    def __init__(
        self,
        *,
        review: OrderReviewService,
        place: BrokerPlace,
        pretrade: PretradeEvaluator,
        context_loader: PretradeContextLoader,
        uow_factory: UnitOfWorkFactory,
        exclusion: SubmissionExclusion,
        mode: ExecutionMode,
        provider: str,
        clock: Clock,
        observer: ExecutionObserver | None = None,
    ) -> None:
        if type(review) is not OrderReviewService:
            raise DomainValidationError("review must be an OrderReviewService")
        if type(mode) is not ExecutionMode:
            raise DomainValidationError("mode must be an ExecutionMode")
        if mode in _LIVE_MODES:
            raise DomainValidationError("live execution requires the later authorization layer")
        if type(provider) is not str or not provider.strip() or len(provider) > 64:
            raise DomainValidationError("provider must be nonempty bounded text")
        if not isinstance(clock, Clock):
            raise DomainValidationError("clock must implement Clock")
        if not callable(uow_factory):
            raise DomainValidationError("uow_factory must be callable")
        self._review = review
        self._place = place
        self._pretrade = pretrade
        self._context_loader = context_loader
        self._uow_factory = uow_factory
        self._exclusion = exclusion
        self._mode = mode
        self._provider = provider
        self._clock = clock
        self._observer = observer

    def _now(self) -> datetime:
        return require_utc(self._clock.now())

    @staticmethod
    def _validate_evaluation(
        evaluation: RiskEvaluation,
        intent: OrderIntent,
        *,
        expected_check_count: int,
    ) -> RiskEvaluation:
        if type(evaluation) is not RiskEvaluation:
            raise DomainValidationError("pretrade must return a RiskEvaluation")
        if (
            evaluation.intent_id != intent.id
            or evaluation.config_hash != intent.config_hash
            or len(evaluation.checks) != expected_check_count
        ):
            raise DomainValidationError("pretrade evaluation identity or check count is invalid")
        return evaluation

    def _result(
        self,
        intent: OrderIntent,
        state: OrderState,
        reason_code: str,
        correlation_id: CorrelationId,
        *,
        review_id: ReviewId | None = None,
        attempt_id: SubmissionAttemptId | None = None,
        broker_order: BrokerOrder | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            intent_id=intent.id,
            state=state,
            reason_code=reason_code,
            correlation_id=correlation_id,
            review_id=review_id,
            submission_attempt_id=attempt_id,
            broker_order=broker_order,
        )

    async def _persist_transition(
        self,
        intent: OrderIntent,
        *,
        transition_name: str,
        from_state: OrderState,
        event: OrderEvent,
        actor: str,
        reason_code: str,
        correlation_id: CorrelationId,
        occurred_at: datetime,
    ) -> OrderState:
        next_state = transition(from_state, event)
        async with self._uow_factory() as uow:
            await uow.orders.add_transition(
                OrderTransitionId(_derived_id(intent, transition_name)),
                intent.id,
                None,
                from_state,
                event,
                next_state,
                actor,
                reason_code,
                occurred_at,
                correlation_id,
            )
            await uow.commit()
        return next_state

    async def _persist_initial_result(
        self,
        intent: OrderIntent,
        evaluation: RiskEvaluation,
        correlation_id: CorrelationId,
    ) -> OrderState:
        event = OrderEvent.RISK_ALLOW if evaluation.allowed else OrderEvent.RISK_DENY
        next_state = transition(OrderState.PROPOSED, event)
        async with self._uow_factory() as uow:
            await uow.orders.add_risk_evaluation(
                _derived_id(intent, "risk-initial"),
                "initial",
                evaluation,
            )
            await uow.orders.add_transition(
                OrderTransitionId(_derived_id(intent, "transition-initial-risk")),
                intent.id,
                None,
                OrderState.PROPOSED,
                event,
                next_state,
                "pretrade-engine",
                "initial_risk_allowed" if evaluation.allowed else "initial_risk_denied",
                evaluation.evaluated_at,
                correlation_id,
            )
            await uow.commit()
        return next_state

    async def _persist_final_denial(
        self,
        intent: OrderIntent,
        evaluation: RiskEvaluation,
        correlation_id: CorrelationId,
    ) -> None:
        next_state = transition(OrderState.REVIEWED, OrderEvent.FINAL_RISK_DENY)
        async with self._uow_factory() as uow:
            await uow.orders.add_risk_evaluation(
                _derived_id(intent, "risk-final"),
                "final",
                evaluation,
            )
            await uow.orders.add_transition(
                OrderTransitionId(_derived_id(intent, "transition-final-risk-denied")),
                intent.id,
                None,
                OrderState.REVIEWED,
                OrderEvent.FINAL_RISK_DENY,
                next_state,
                "pretrade-engine",
                "final_risk_denied",
                evaluation.evaluated_at,
                correlation_id,
            )
            await uow.commit()

    async def _persist_expired_after_final_risk(
        self,
        intent: OrderIntent,
        evaluation: RiskEvaluation,
        correlation_id: CorrelationId,
        occurred_at: datetime,
    ) -> None:
        next_state = transition(OrderState.REVIEWED, OrderEvent.EXPIRE)
        async with self._uow_factory() as uow:
            await uow.orders.add_risk_evaluation(
                _derived_id(intent, "risk-final"),
                "final",
                evaluation,
            )
            await uow.orders.add_transition(
                OrderTransitionId(_derived_id(intent, "transition-final-expired")),
                intent.id,
                None,
                OrderState.REVIEWED,
                OrderEvent.EXPIRE,
                next_state,
                "execution-service",
                "submission_window_expired",
                occurred_at,
                correlation_id,
            )
            await uow.commit()

    async def _reserve_submission(
        self,
        intent: OrderIntent,
        review: BrokerOrderReview,
        review_id: ReviewId,
        evaluation: RiskEvaluation,
        correlation_id: CorrelationId,
        attempted_at: datetime,
    ) -> PersistedReviewedOrder:
        submission = PersistedReviewedOrder(
            review_id=review_id,
            submission_attempt_id=SubmissionAttemptId(_derived_id(intent, "submission-attempt")),
            review=review,
            deduplication_key=derive_deduplication_key(intent),
            fencing_token=0,
            execution_mode=self._mode,
            live_lease_id=None,
            live_lease_evidence_hash=None,
            account_id=intent.account_id,
            config_hash=intent.config_hash,
        )
        next_state = transition(OrderState.REVIEWED, OrderEvent.PREPARE_SUBMISSION)
        async with self._uow_factory() as uow:
            await uow.orders.add_risk_evaluation(
                _derived_id(intent, "risk-final"),
                "final",
                evaluation,
            )
            reserved = await uow.submission_attempts.reserve(
                submission,
                self._provider,
                attempted_at,
            )
            if not reserved:
                raise DuplicateSubmissionAttempt() from None
            await uow.orders.add_transition(
                OrderTransitionId(_derived_id(intent, "transition-submission-pending")),
                intent.id,
                None,
                OrderState.REVIEWED,
                OrderEvent.PREPARE_SUBMISSION,
                next_state,
                "execution-service",
                "submission_reserved",
                attempted_at,
                correlation_id,
            )
            await uow.commit()
        return submission

    async def _persist_broker_outcome(
        self,
        intent: OrderIntent,
        submission: PersistedReviewedOrder,
        correlation_id: CorrelationId,
        *,
        response: BrokerOrder | None,
        outcome: SubmissionOutcome,
        event: OrderEvent,
        reason_code: str,
        completed_at: datetime,
    ) -> OrderState:
        next_state = transition(OrderState.SUBMISSION_PENDING, event)
        known_response = outcome in {SubmissionOutcome.ACCEPTED, SubmissionOutcome.REJECTED}
        async with self._uow_factory() as uow:
            if known_response:
                if response is None:
                    raise DomainValidationError("known broker outcome requires a response")
                await uow.orders.add_broker_order(response, submission, self._provider)
            await uow.submission_attempts.complete(
                submission.submission_attempt_id,
                outcome,
                completed_at,
                response,
            )
            await uow.orders.add_transition(
                OrderTransitionId(_derived_id(intent, f"transition-{outcome.value}")),
                intent.id,
                None if not known_response or response is None else response.id,
                OrderState.SUBMISSION_PENDING,
                event,
                next_state,
                "execution-service",
                reason_code,
                completed_at,
                correlation_id,
            )
            await uow.commit()
        return next_state

    async def execute(self, intent: OrderIntent) -> ExecutionResult:
        """Execute one intent through every durable risk and broker boundary exactly once."""

        if type(intent) is not OrderIntent:
            raise DomainValidationError("intent must be an OrderIntent")
        correlation_id = CorrelationId(_derived_id(intent, "execution"))
        proposed_at = self._now()
        async with self._uow_factory() as uow:
            await uow.orders.add(intent)
            await uow.orders.add_transition(
                OrderTransitionId(_derived_id(intent, "transition-proposed")),
                intent.id,
                None,
                None,
                None,
                OrderState.PROPOSED,
                "execution-service",
                "intent_persisted",
                proposed_at,
                correlation_id,
            )
            await uow.commit()

        initial_context = await self._context_loader.load_initial(intent)
        initial_evaluation = self._validate_evaluation(
            self._pretrade.evaluate_initial(initial_context),
            intent,
            expected_check_count=23,
        )
        state = await self._persist_initial_result(intent, initial_evaluation, correlation_id)
        if state is OrderState.RISK_REJECTED:
            return self._result(
                intent,
                state,
                "initial_risk_denied",
                correlation_id,
            )

        if self._observer is not None:
            try:
                await self._observer.decision(intent)
            except Exception:
                return self._result(intent, state, "decision_observation_failed", correlation_id)

        state = await self._persist_transition(
            intent,
            transition_name="transition-review-requested",
            from_state=OrderState.RISK_APPROVED,
            event=OrderEvent.REQUEST_REVIEW,
            actor="execution-service",
            reason_code="review_requested",
            correlation_id=correlation_id,
            occurred_at=self._now(),
        )
        try:
            review = await self._review.review(intent)
        except Exception:
            state = await self._persist_transition(
                intent,
                transition_name="transition-review-rejected",
                from_state=state,
                event=OrderEvent.REVIEW_REJECTED,
                actor="execution-service",
                reason_code="review_rejected",
                correlation_id=correlation_id,
                occurred_at=self._now(),
            )
            return self._result(intent, state, "review_rejected", correlation_id)

        review_id = ReviewId(_derived_id(intent, "review"))
        reviewed_state = transition(state, OrderEvent.REVIEW_ACCEPTED)
        async with self._uow_factory() as uow:
            await uow.orders.add_review(review_id, review)
            await uow.orders.add_transition(
                OrderTransitionId(_derived_id(intent, "transition-reviewed")),
                intent.id,
                None,
                state,
                OrderEvent.REVIEW_ACCEPTED,
                reviewed_state,
                "execution-service",
                "review_persisted",
                self._now(),
                correlation_id,
            )
            await uow.commit()

        async with self._exclusion.acquire(intent.account_id):
            final_context = await self._context_loader.load_final(intent, review)
            final_evaluation = self._validate_evaluation(
                self._pretrade.evaluate_final(final_context),
                intent,
                expected_check_count=24,
            )
            if not final_evaluation.allowed:
                await self._persist_final_denial(intent, final_evaluation, correlation_id)
                return self._result(
                    intent,
                    OrderState.RISK_REJECTED,
                    "final_risk_denied",
                    correlation_id,
                    review_id=review_id,
                )

            attempted_at = self._now()
            if (
                attempted_at < final_evaluation.evaluated_at
                or attempted_at >= intent.expires_at
                or attempted_at >= review.expires_at
            ):
                await self._persist_expired_after_final_risk(
                    intent,
                    final_evaluation,
                    correlation_id,
                    attempted_at,
                )
                return self._result(
                    intent,
                    OrderState.EXPIRED,
                    "submission_window_expired",
                    correlation_id,
                    review_id=review_id,
                )

            submission = await self._reserve_submission(
                intent,
                review,
                review_id,
                final_evaluation,
                correlation_id,
                attempted_at,
            )
            if self._observer is not None:
                try:
                    await self._observer.submitting(submission)
                except Exception:
                    # The committed attempt remains unresolved. Observation
                    # failure never releases it or permits another transport.
                    return self._result(
                        intent,
                        OrderState.SUBMISSION_PENDING,
                        "submission_observation_failed",
                        correlation_id,
                        review_id=review_id,
                        attempt_id=submission.submission_attempt_id,
                    )
                # Receipt auditing can consume time. Reload all final evidence,
                # evaluate the same 24 checks and commit that evaluation before
                # any transport. A denial leaves the original attempt held.
                transport_context = await self._context_loader.load_final(intent, review)
                transport_evaluation = self._validate_evaluation(
                    self._pretrade.evaluate_final(transport_context),
                    intent,
                    expected_check_count=24,
                )
                async with self._uow_factory() as uow:
                    await uow.orders.add_risk_evaluation(
                        _derived_id(intent, "risk-transport"), "final", transport_evaluation
                    )
                    await uow.commit()
                transport_at = self._now()
                if (
                    not transport_evaluation.allowed
                    or transport_at < transport_evaluation.evaluated_at
                    or transport_at >= intent.expires_at
                    or transport_at >= review.expires_at
                ):
                    return self._result(
                        intent,
                        OrderState.SUBMISSION_PENDING,
                        "transport_risk_denied",
                        correlation_id,
                        review_id=review_id,
                        attempt_id=submission.submission_attempt_id,
                    )
            try:
                response = await self._place.place_order(submission)
            except Exception:
                completed_at = self._now()
                state = await self._persist_broker_outcome(
                    intent,
                    submission,
                    correlation_id,
                    response=None,
                    outcome=SubmissionOutcome.AMBIGUOUS,
                    event=OrderEvent.BROKER_AMBIGUOUS,
                    reason_code="broker_response_ambiguous",
                    completed_at=completed_at,
                )
                return self._result(
                    intent,
                    state,
                    "broker_response_ambiguous",
                    correlation_id,
                    review_id=review_id,
                    attempt_id=submission.submission_attempt_id,
                )

            completed_at = self._now()
            if type(response) is not BrokerOrder or not broker_order_matches_submission(
                response,
                submission,
            ):
                ambiguous_response = response if type(response) is BrokerOrder else None
                state = await self._persist_broker_outcome(
                    intent,
                    submission,
                    correlation_id,
                    response=ambiguous_response,
                    outcome=SubmissionOutcome.AMBIGUOUS,
                    event=OrderEvent.BROKER_AMBIGUOUS,
                    reason_code="broker_response_mismatch",
                    completed_at=completed_at,
                )
                return self._result(
                    intent,
                    state,
                    "broker_response_mismatch",
                    correlation_id,
                    review_id=review_id,
                    attempt_id=submission.submission_attempt_id,
                )

            if response.state is OrderState.SUBMITTED:
                outcome = SubmissionOutcome.ACCEPTED
                event = OrderEvent.BROKER_ACCEPTED
                reason_code = "broker_accepted"
            elif response.state is OrderState.REJECTED:
                outcome = SubmissionOutcome.REJECTED
                event = OrderEvent.BROKER_REJECTED
                reason_code = "broker_rejected"
            else:
                outcome = SubmissionOutcome.AMBIGUOUS
                event = OrderEvent.BROKER_AMBIGUOUS
                reason_code = "broker_state_ambiguous"

            observation_failed = False
            if self._observer is not None and outcome is not SubmissionOutcome.AMBIGUOUS:
                try:
                    # Observe a matched response before database latency, using
                    # the observer's own UTC/monotonic session. A failed sink
                    # cannot erase the response or schedule a second call.
                    await self._observer.responded(submission, response)
                except Exception:
                    observation_failed = True

            state = await self._persist_broker_outcome(
                intent,
                submission,
                correlation_id,
                response=response,
                outcome=outcome,
                event=event,
                reason_code=reason_code,
                completed_at=completed_at,
            )
            return self._result(
                intent,
                state,
                (
                    "accepted_receipt_failed"
                    if outcome is SubmissionOutcome.ACCEPTED
                    else "rejected_receipt_failed"
                )
                if observation_failed
                else reason_code,
                correlation_id,
                review_id=review_id,
                attempt_id=submission.submission_attempt_id,
                broker_order=response if outcome is not SubmissionOutcome.AMBIGUOUS else None,
            )


__all__ = [
    "DuplicateSubmissionAttempt",
    "ExecutionObserver",
    "ExecutionResult",
    "ExecutionService",
    "PretradeContextLoader",
    "PretradeEvaluator",
    "UnitOfWorkFactory",
]
