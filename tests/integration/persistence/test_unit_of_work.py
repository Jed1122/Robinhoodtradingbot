"""Integration contract for the explicit transactional unit of work."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import trading_bot.logging as logging_module
from trading_bot.domain.decisions import CheckResult, RiskEvaluation
from trading_bot.domain.enums import (
    AssetClass,
    ExecutionMode,
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
    BrokerOrderId,
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
from trading_bot.domain.orders import (
    BrokerOrder,
    BrokerOrderReview,
    OrderIntent,
    PersistedReviewedOrder,
)
from trading_bot.logging import SecretRegistry
from trading_bot.persistence import (
    PersistenceConfigurationError,
    PersistenceDataError,
    async_session_factory,
)
from trading_bot.persistence.evidence import (
    canonical_broker_order_response_sha256,
    canonical_order_intent_sha256,
    canonical_review_response_sha256,
)
from trading_bot.persistence.models import (
    AccountRow,
    AuditEventRow,
    BrokerReviewRow,
    InstrumentRow,
    OrderIntentRow,
    OrderRow,
    OrderTransitionRow,
    RiskEvaluationRow,
    SubmissionAttemptRow,
)
from trading_bot.persistence.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWorkStateError
from trading_bot.risk import canonical_review_payload_sha256

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def _make_intent(*, intent_id: str = "intent-1") -> OrderIntent:
    return OrderIntent(
        id=OrderIntentId(intent_id),
        account_id=AccountId("account-1"),
        instrument_id=InstrumentId("instrument-1"),
        asset_class=AssetClass.EQUITY,
        side=Side.BUY,
        purpose=OrderPurpose.ENTRY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GOOD_FOR_DAY,
        quantity=Decimal("1.25"),
        limit_price=Decimal("10.50"),
        stop_price=None,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        strategy_version="strategy-v1",
        config_hash=ConfigHash(HASH_A),
        data_hash=DataHash(HASH_C),
        exit_policy_version="exit-v1",
    )


def _make_audit(
    *,
    event_id: str = "audit-1",
    details: tuple[tuple[str, str], ...] = (("result", "allowed"),),
) -> AuditEvent:
    return AuditEvent(
        id=AuditEventId(event_id),
        occurred_at=NOW,
        category="persistence",
        actor="paper-runtime",
        reason_code="intent_recorded",
        correlation_id=CorrelationId("correlation-1"),
        config_hash=ConfigHash(HASH_A),
        code_hash=CodeHash(HASH_B),
        data_hash=DataHash(HASH_C),
        details=details,
    )


def _make_review(intent: OrderIntent) -> BrokerOrderReview:
    return BrokerOrderReview(
        normalized_order=intent,
        source="paper",
        reviewed_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
        estimated_notional=Decimal("13.125"),
        estimated_fees=Decimal("0"),
        client_order_id=None,
        outbound_payload_sha256=canonical_review_payload_sha256(
            intent,
            client_order_id=None,
        ),
        broker_review_id="paper-review-1",
    )


def _make_risk_evaluation(intent: OrderIntent) -> RiskEvaluation:
    return RiskEvaluation(
        intent_id=intent.id,
        allowed=True,
        checks=(
            CheckResult(
                code="test_check",
                allowed=True,
                observed="satisfied",
                configured_limit="required",
                reason="test_allowed",
                observed_at=NOW,
            ),
        ),
        evaluated_at=NOW,
        config_hash=intent.config_hash,
    )


def _make_submission(intent: OrderIntent) -> PersistedReviewedOrder:
    return PersistedReviewedOrder(
        review_id=ReviewId("review-1"),
        submission_attempt_id=SubmissionAttemptId("attempt-1"),
        review=_make_review(intent),
        deduplication_key=HASH_C,
        fencing_token=0,
        execution_mode=ExecutionMode.PAPER,
        live_lease_id=None,
        live_lease_evidence_hash=None,
        account_id=intent.account_id,
        config_hash=intent.config_hash,
    )


def _make_broker_order(intent: OrderIntent) -> BrokerOrder:
    return BrokerOrder(
        id=OrderId("order-1"),
        broker_order_id=BrokerOrderId("broker-order-1"),
        account_id=intent.account_id,
        intent_id=intent.id,
        client_order_id=None,
        instrument_id=intent.instrument_id,
        side=intent.side,
        purpose=intent.purpose,
        order_type=intent.order_type,
        time_in_force=intent.time_in_force,
        requested_quantity=intent.quantity,
        filled_quantity=Decimal("0"),
        limit_price=intent.limit_price,
        stop_price=intent.stop_price,
        state=OrderState.SUBMITTED,
        created_at=NOW,
        updated_at=NOW,
        data_hash=DataHash(HASH_C),
    )


async def _seed_parents(engine: AsyncEngine) -> None:
    factory = async_session_factory(engine)
    async with factory.begin() as session:
        session.add(
            AccountRow(
                id="account-1",
                provider="paper",
                provider_account_id="paper-account-1",
                account_type="cash",
                provider_state="active",
                equity=Decimal("1000"),
                cash=Decimal("1000"),
                equity_buying_power=Decimal("1000"),
                crypto_buying_power=None,
                prediction_buying_power=None,
                restricted=False,
                observed_at=NOW,
                data_hash=HASH_C,
                config_hash=HASH_A,
                code_hash=HASH_B,
            )
        )
        session.add(
            InstrumentRow(
                id="instrument-1",
                provider="paper",
                provider_instrument_id="paper-instrument-1",
                symbol="TEST",
                asset_class=AssetClass.EQUITY.value,
                provider_status="active",
                tradable=True,
                fractional_eligible=True,
                price_increment=Decimal("0.01"),
                quantity_increment=Decimal("0.01"),
                minimum_quantity=Decimal("0.01"),
                minimum_notional=Decimal("1"),
                maximum_quantity=None,
                correlation_group="equity:TEST",
                observed_at=NOW,
                data_hash=HASH_C,
            )
        )


async def _count(engine: AsyncEngine, model: type[OrderIntentRow] | type[AuditEventRow]) -> int:
    factory = async_session_factory(engine)
    async with factory() as session:
        count = await session.scalar(select(func.count()).select_from(model))
    assert count is not None
    return count


def _make_uow(engine: AsyncEngine) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(
        async_session_factory(engine),
        code_hash=CodeHash(HASH_B),
        config_hash=ConfigHash(HASH_A),
    )


@pytest.fixture
def migrated_schema(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")


@pytest.fixture
async def migrated_engine(
    migrated_schema: None,
    sqlite_engine: AsyncEngine,
) -> AsyncEngine:
    del migrated_schema
    await _seed_parents(sqlite_engine)
    return sqlite_engine


@pytest.mark.asyncio
async def test_unit_of_work_commits_order_and_audit_atomically(
    migrated_engine: AsyncEngine,
) -> None:
    async with _make_uow(migrated_engine) as uow:
        await uow.orders.add(_make_intent())
        await uow.audit.append(_make_audit(details=(("step", "one"), ("step", "two"))))
        assert await uow.orders.get(OrderIntentId("intent-1")) == _make_intent()
        await uow.commit()

    assert await _count(migrated_engine, OrderIntentRow) == 1
    assert await _count(migrated_engine, AuditEventRow) == 1

    async with _make_uow(migrated_engine) as uow:
        assert await uow.orders.get(OrderIntentId("intent-1")) == _make_intent()
        await uow.rollback()

    factory = async_session_factory(migrated_engine)
    async with factory() as session:
        stored = await session.get(AuditEventRow, "audit-1")
    assert stored is not None
    assert stored.sanitized_details_json == '[["step","one"],["step","two"]]'


@pytest.mark.asyncio
async def test_exception_rolls_back_order_and_audit_together(
    migrated_engine: AsyncEngine,
) -> None:
    with pytest.raises(RuntimeError, match="force rollback"):
        async with _make_uow(migrated_engine) as uow:
            await uow.orders.add(_make_intent())
            await uow.audit.append(_make_audit())
            raise RuntimeError("force rollback")

    assert await _count(migrated_engine, OrderIntentRow) == 0
    assert await _count(migrated_engine, AuditEventRow) == 0


@pytest.mark.asyncio
async def test_normal_exit_without_commit_rolls_back(
    migrated_engine: AsyncEngine,
) -> None:
    async with _make_uow(migrated_engine) as uow:
        await uow.orders.add(_make_intent())
        await uow.audit.append(_make_audit())

    assert await _count(migrated_engine, OrderIntentRow) == 0
    assert await _count(migrated_engine, AuditEventRow) == 0


@pytest.mark.asyncio
async def test_commit_failure_rolls_back_every_staged_record(
    migrated_engine: AsyncEngine,
) -> None:
    factory = async_session_factory(migrated_engine)
    async with factory.begin() as session:
        session.add(
            AuditEventRow(
                id="audit-1",
                occurred_at=NOW,
                category="seed",
                actor="test",
                reason_code="seed",
                correlation_id="correlation-seed",
                config_hash=HASH_A,
                code_hash=HASH_B,
                data_hash=HASH_C,
                sanitized_details_json="[]",
                corrects_id=None,
            )
        )

    with pytest.raises(IntegrityError):
        async with _make_uow(migrated_engine) as uow:
            await uow.orders.add(_make_intent())
            await uow.audit.append(_make_audit())
            await uow.commit()

    assert await _count(migrated_engine, OrderIntentRow) == 0
    assert await _count(migrated_engine, AuditEventRow) == 1


@pytest.mark.asyncio
async def test_audit_repository_appends_a_correction_without_mutating_the_original(
    migrated_engine: AsyncEngine,
) -> None:
    async with _make_uow(migrated_engine) as uow:
        await uow.audit.append(_make_audit())
        await uow.commit()

    async with _make_uow(migrated_engine) as uow:
        await uow.audit.append_correction(
            _make_audit(event_id="audit-2", details=(("result", "corrected"),)),
            AuditEventId("audit-1"),
        )
        await uow.commit()

    factory = async_session_factory(migrated_engine)
    async with factory() as session:
        original = await session.get(AuditEventRow, "audit-1")
        correction = await session.get(AuditEventRow, "audit-2")
    assert original is not None and original.corrects_id is None
    assert correction is not None and correction.corrects_id == "audit-1"


@pytest.mark.asyncio
async def test_audit_persistence_rejects_sensitive_details_without_echoing_them(
    migrated_engine: AsyncEngine,
) -> None:
    secret = "must-not-escape"
    with pytest.raises(PersistenceDataError) as captured:
        async with _make_uow(migrated_engine) as uow:
            await uow.audit.append(_make_audit(details=(("api_key", secret),)))

    assert secret not in str(captured.value)
    assert await _count(migrated_engine, AuditEventRow) == 0


@pytest.mark.asyncio
async def test_audit_persistence_rejects_registered_secret_values(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logging_module, "_REGISTRY_STATE", logging_module._RegistryState())
    secret = "ordinary-looking-registered-value"
    SecretRegistry().register(secret)

    with pytest.raises(PersistenceDataError) as captured:
        async with _make_uow(migrated_engine) as uow:
            await uow.audit.append(_make_audit(details=(("note", secret),)))

    assert secret not in str(captured.value)
    assert await _count(migrated_engine, AuditEventRow) == 0


@pytest.mark.asyncio
async def test_audit_persistence_rejects_registered_secrets_in_identifiers(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logging_module, "_REGISTRY_STATE", logging_module._RegistryState())
    secret = "ordinary-registered-identifier"
    SecretRegistry().register(secret)

    with pytest.raises(PersistenceDataError, match="unsafe identifier"):
        async with _make_uow(migrated_engine) as uow:
            await uow.audit.append(_make_audit(event_id=secret))

    secret_correlation = AuditEvent(
        id=AuditEventId("audit-correlation-screen"),
        occurred_at=NOW,
        category="persistence",
        actor="paper-runtime",
        reason_code="intent_recorded",
        correlation_id=CorrelationId(secret),
        config_hash=ConfigHash(HASH_A),
        code_hash=CodeHash(HASH_B),
        data_hash=DataHash(HASH_C),
        details=(),
    )
    with pytest.raises(PersistenceDataError, match="unsafe identifier"):
        async with _make_uow(migrated_engine) as uow:
            await uow.audit.append(secret_correlation)

    with pytest.raises(PersistenceDataError, match="unsafe identifier"):
        async with _make_uow(migrated_engine) as uow:
            await uow.audit.append_correction(
                _make_audit(event_id="audit-correction-screen"),
                AuditEventId(secret),
            )

    assert await _count(migrated_engine, AuditEventRow) == 0


@pytest.mark.asyncio
async def test_audit_code_identity_must_match_the_unit_of_work(
    migrated_engine: AsyncEngine,
) -> None:
    mismatched = AuditEvent(
        id=AuditEventId("audit-mismatch"),
        occurred_at=NOW,
        category="persistence",
        actor="paper-runtime",
        reason_code="intent_recorded",
        correlation_id=CorrelationId("correlation-mismatch"),
        config_hash=ConfigHash(HASH_A),
        code_hash=CodeHash(HASH_C),
        data_hash=DataHash(HASH_C),
        details=(),
    )

    with pytest.raises(PersistenceDataError, match="code identity"):
        async with _make_uow(migrated_engine) as uow:
            await uow.audit.append(mismatched)

    assert await _count(migrated_engine, AuditEventRow) == 0


@pytest.mark.asyncio
async def test_atomic_records_must_share_one_configuration_identity(
    migrated_engine: AsyncEngine,
) -> None:
    mismatched = AuditEvent(
        id=AuditEventId("audit-config-mismatch"),
        occurred_at=NOW,
        category="persistence",
        actor="paper-runtime",
        reason_code="intent_recorded",
        correlation_id=CorrelationId("correlation-config-mismatch"),
        config_hash=ConfigHash(HASH_C),
        code_hash=CodeHash(HASH_B),
        data_hash=DataHash(HASH_C),
        details=(),
    )

    with pytest.raises(PersistenceDataError, match="configuration identity"):
        async with _make_uow(migrated_engine) as uow:
            await uow.orders.add(_make_intent())
            await uow.audit.append(mismatched)

    assert await _count(migrated_engine, OrderIntentRow) == 0
    assert await _count(migrated_engine, AuditEventRow) == 0


@pytest.mark.asyncio
async def test_order_repository_persists_the_complete_reviewed_submission_chain(
    migrated_engine: AsyncEngine,
) -> None:
    intent = _make_intent()
    review = _make_review(intent)
    evaluation = _make_risk_evaluation(intent)
    submission = _make_submission(intent)
    broker_order = _make_broker_order(intent)
    completed_at = NOW + timedelta(seconds=1)

    async with _make_uow(migrated_engine) as uow:
        await uow.orders.add(intent)
        await uow.orders.add_transition(
            OrderTransitionId("transition-proposed"),
            intent.id,
            None,
            None,
            None,
            OrderState.PROPOSED,
            "execution-service",
            "intent_persisted",
            NOW,
            CorrelationId("correlation-execution-1"),
        )
        await uow.orders.add_risk_evaluation(
            "risk-evaluation-initial-1",
            "initial",
            evaluation,
        )
        await uow.orders.add_transition(
            OrderTransitionId("transition-risk-approved"),
            intent.id,
            None,
            OrderState.PROPOSED,
            OrderEvent.RISK_ALLOW,
            OrderState.RISK_APPROVED,
            "pretrade-engine",
            "initial_risk_allowed",
            NOW + timedelta(microseconds=1),
            CorrelationId("correlation-execution-1"),
        )
        await uow.orders.add_transition(
            OrderTransitionId("transition-review-requested"),
            intent.id,
            None,
            OrderState.RISK_APPROVED,
            OrderEvent.REQUEST_REVIEW,
            OrderState.REVIEW_REQUESTED,
            "execution-service",
            "review_requested",
            NOW + timedelta(microseconds=2),
            CorrelationId("correlation-execution-1"),
        )
        await uow.orders.add_review(submission.review_id, review)
        await uow.orders.add_transition(
            OrderTransitionId("transition-reviewed"),
            intent.id,
            None,
            OrderState.REVIEW_REQUESTED,
            OrderEvent.REVIEW_ACCEPTED,
            OrderState.REVIEWED,
            "execution-service",
            "review_matched",
            NOW + timedelta(microseconds=3),
            CorrelationId("correlation-execution-1"),
        )
        assert await uow.submission_attempts.reserve(
            submission,
            "paper",
            NOW + timedelta(microseconds=4),
        )
        await uow.orders.add_transition(
            OrderTransitionId("transition-submission-pending"),
            intent.id,
            None,
            OrderState.REVIEWED,
            OrderEvent.PREPARE_SUBMISSION,
            OrderState.SUBMISSION_PENDING,
            "execution-service",
            "submission_reserved",
            NOW + timedelta(microseconds=5),
            CorrelationId("correlation-execution-1"),
        )
        await uow.orders.add_broker_order(broker_order, submission, "paper")
        await uow.submission_attempts.complete(
            submission.submission_attempt_id,
            SubmissionOutcome.ACCEPTED,
            completed_at,
            broker_order,
        )
        await uow.orders.add_transition(
            OrderTransitionId("transition-submitted"),
            intent.id,
            broker_order.id,
            OrderState.SUBMISSION_PENDING,
            OrderEvent.BROKER_ACCEPTED,
            OrderState.SUBMITTED,
            "paper-broker",
            "broker_accepted",
            completed_at,
            CorrelationId("correlation-execution-1"),
        )
        await uow.commit()

    factory = async_session_factory(migrated_engine)
    async with factory() as session:
        persisted_review = await session.get(BrokerReviewRow, submission.review_id)
        persisted_risk = await session.get(RiskEvaluationRow, "risk-evaluation-initial-1")
        persisted_attempt = await session.get(
            SubmissionAttemptRow,
            submission.submission_attempt_id,
        )
        persisted_order = await session.get(OrderRow, broker_order.id)
        persisted_transitions = (
            await session.scalars(
                select(OrderTransitionRow).order_by(OrderTransitionRow.occurred_at)
            )
        ).all()

    assert persisted_review is not None
    assert persisted_review.intent_id == intent.id
    assert persisted_review.source == review.source
    assert persisted_review.client_order_id == review.client_order_id
    assert persisted_review.outbound_payload_sha256 == review.outbound_payload_sha256
    assert persisted_review.normalized_intent_hash == canonical_order_intent_sha256(intent)
    assert persisted_review.sanitized_response_hash == canonical_review_response_sha256(review)

    assert persisted_risk is not None
    assert persisted_risk.intent_id == intent.id
    assert persisted_risk.phase == "initial"
    assert persisted_risk.allowed is True
    assert persisted_risk.check_count == len(evaluation.checks)
    assert json.loads(persisted_risk.checks_json) == [
        {
            "allowed": True,
            "code": "test_check",
            "configured_limit": "required",
            "observed": "satisfied",
            "observed_at": "2026-07-14T12:00:00.000000Z",
            "reason": "test_allowed",
        }
    ]
    assert persisted_risk.config_hash == intent.config_hash

    assert persisted_attempt is not None
    assert persisted_attempt.intent_id == intent.id
    assert persisted_attempt.review_id == submission.review_id
    assert persisted_attempt.account_id == intent.account_id
    assert persisted_attempt.instrument_id == intent.instrument_id
    assert persisted_attempt.deduplication_key == submission.deduplication_key
    assert persisted_attempt.provider == "paper"
    assert persisted_attempt.fencing_token == 0
    assert persisted_attempt.execution_mode == ExecutionMode.PAPER.value
    assert persisted_attempt.live_lease_id is None
    assert persisted_attempt.live_lease_evidence_hash is None
    assert persisted_attempt.completed_at == completed_at
    assert persisted_attempt.outcome_class == SubmissionOutcome.ACCEPTED.value
    assert persisted_attempt.sanitized_response_hash == canonical_broker_order_response_sha256(
        broker_order
    )

    assert persisted_order is not None
    assert persisted_order.intent_id == intent.id
    assert persisted_order.review_id == submission.review_id
    assert persisted_order.submission_attempt_id == submission.submission_attempt_id
    assert persisted_order.broker_order_id == broker_order.broker_order_id
    assert persisted_order.account_id == intent.account_id
    assert persisted_order.instrument_id == intent.instrument_id
    assert persisted_order.requested_quantity == intent.quantity
    assert persisted_order.filled_quantity == Decimal("0")
    assert persisted_order.state == OrderState.SUBMITTED.value

    assert [transition.id for transition in persisted_transitions] == [
        "transition-proposed",
        "transition-risk-approved",
        "transition-review-requested",
        "transition-reviewed",
        "transition-submission-pending",
        "transition-submitted",
    ]
    assert [transition.event for transition in persisted_transitions] == [
        OrderState.PROPOSED.value,
        OrderEvent.RISK_ALLOW.value,
        OrderEvent.REQUEST_REVIEW.value,
        OrderEvent.REVIEW_ACCEPTED.value,
        OrderEvent.PREPARE_SUBMISSION.value,
        OrderEvent.BROKER_ACCEPTED.value,
    ]
    assert [transition.to_state for transition in persisted_transitions] == [
        OrderState.PROPOSED.value,
        OrderState.RISK_APPROVED.value,
        OrderState.REVIEW_REQUESTED.value,
        OrderState.REVIEWED.value,
        OrderState.SUBMISSION_PENDING.value,
        OrderState.SUBMITTED.value,
    ]


@pytest.mark.asyncio
async def test_submission_attempt_reservation_is_durable_and_rejects_a_second_attempt(
    migrated_engine: AsyncEngine,
) -> None:
    intent = _make_intent()
    submission = _make_submission(intent)

    async with _make_uow(migrated_engine) as uow:
        await uow.orders.add(intent)
        await uow.orders.add_review(submission.review_id, submission.review)
        assert await uow.submission_attempts.reserve(submission, "paper", NOW)
        await uow.commit()

    conflicting_attempt = replace(
        submission,
        submission_attempt_id=SubmissionAttemptId("attempt-2"),
        deduplication_key=HASH_B,
    )
    async with _make_uow(migrated_engine) as uow:
        assert not await uow.submission_attempts.reserve(
            conflicting_attempt,
            "paper",
            NOW + timedelta(seconds=1),
        )
        await uow.commit()

    factory = async_session_factory(migrated_engine)
    async with factory() as session:
        attempts = (await session.scalars(select(SubmissionAttemptRow))).all()
    assert len(attempts) == 1
    assert attempts[0].id == submission.submission_attempt_id
    assert attempts[0].outcome_class == SubmissionOutcome.PENDING.value
    assert attempts[0].completed_at is None


@pytest.mark.asyncio
async def test_submission_attempt_terminal_completion_is_exactly_once(
    migrated_engine: AsyncEngine,
) -> None:
    intent = _make_intent()
    submission = _make_submission(intent)
    completed_at = NOW + timedelta(seconds=1)
    rejected_order = replace(_make_broker_order(intent), state=OrderState.REJECTED)

    async with _make_uow(migrated_engine) as uow:
        await uow.orders.add(intent)
        await uow.orders.add_review(submission.review_id, submission.review)
        assert await uow.submission_attempts.reserve(submission, "paper", NOW)
        await uow.commit()

    async with _make_uow(migrated_engine) as uow:
        await uow.orders.add_broker_order(rejected_order, submission, "paper")
        await uow.submission_attempts.complete(
            submission.submission_attempt_id,
            SubmissionOutcome.REJECTED,
            completed_at,
            rejected_order,
        )
        await uow.commit()

    with pytest.raises(PersistenceDataError, match="terminal"):
        async with _make_uow(migrated_engine) as uow:
            await uow.submission_attempts.complete(
                submission.submission_attempt_id,
                SubmissionOutcome.ACCEPTED,
                completed_at + timedelta(seconds=1),
                _make_broker_order(intent),
            )

    factory = async_session_factory(migrated_engine)
    async with factory() as session:
        attempt = await session.get(SubmissionAttemptRow, submission.submission_attempt_id)
    assert attempt is not None
    assert attempt.outcome_class == SubmissionOutcome.REJECTED.value
    assert attempt.completed_at == completed_at
    assert attempt.sanitized_response_hash == canonical_broker_order_response_sha256(rejected_order)


@pytest.mark.asyncio
async def test_known_submission_outcome_requires_matching_durable_order(
    migrated_engine: AsyncEngine,
) -> None:
    intent = _make_intent()
    submission = _make_submission(intent)
    broker_order = _make_broker_order(intent)

    async with _make_uow(migrated_engine) as uow:
        await uow.orders.add(intent)
        await uow.orders.add_review(submission.review_id, submission.review)
        assert await uow.submission_attempts.reserve(submission, "paper", NOW)
        await uow.commit()

    with pytest.raises(PersistenceDataError, match="matching durable broker order"):
        async with _make_uow(migrated_engine) as uow:
            await uow.submission_attempts.complete(
                submission.submission_attempt_id,
                SubmissionOutcome.ACCEPTED,
                NOW + timedelta(seconds=1),
                broker_order,
            )

    factory = async_session_factory(migrated_engine)
    async with factory() as session:
        attempt = await session.get(SubmissionAttemptRow, submission.submission_attempt_id)
    assert attempt is not None
    assert attempt.outcome_class == SubmissionOutcome.PENDING.value
    assert attempt.completed_at is None
    assert attempt.sanitized_response_hash is None


@pytest.mark.asyncio
async def test_unit_of_work_exposes_named_repositories_but_no_critical_mutators(
    migrated_engine: AsyncEngine,
) -> None:
    async with _make_uow(migrated_engine) as uow:
        assert uow.submission_attempts is not None
        assert uow.fills is not None
        assert uow.data_quality is not None
        assert uow.authorizations is not None
        assert uow.reconciliation is not None
        assert uow.evidence is not None
        assert not hasattr(uow.audit, "update")
        assert not hasattr(uow.audit, "delete")
        await uow.rollback()


@pytest.mark.asyncio
async def test_unit_of_work_rejects_invalid_lifecycle_use(
    migrated_engine: AsyncEngine,
) -> None:
    uow = _make_uow(migrated_engine)

    with pytest.raises(UnitOfWorkStateError):
        await uow.commit()

    async with uow:
        retained_orders = uow.orders
        await uow.rollback()
        with pytest.raises(UnitOfWorkStateError):
            await retained_orders.add(_make_intent())
        with pytest.raises(UnitOfWorkStateError):
            await uow.commit()

    with pytest.raises(UnitOfWorkStateError):
        async with uow:
            pass


@pytest.mark.asyncio
async def test_unit_of_work_rejects_unvalidated_or_rebound_session_factories(
    database_url: str,
    migrated_engine: AsyncEngine,
) -> None:
    unvalidated_engine = create_async_engine(database_url)
    raw_factory = async_sessionmaker(
        bind=unvalidated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        with pytest.raises(PersistenceConfigurationError, match="validated"):
            SqlAlchemyUnitOfWork(
                raw_factory,
                code_hash=CodeHash(HASH_B),
                config_hash=ConfigHash(HASH_A),
            )

        validated_factory = async_session_factory(migrated_engine)
        uow = SqlAlchemyUnitOfWork(
            validated_factory,
            code_hash=CodeHash(HASH_B),
            config_hash=ConfigHash(HASH_A),
        )
        validated_factory.configure(bind=unvalidated_engine)
        with pytest.raises(PersistenceConfigurationError, match="validated"):
            async with uow:
                pass

        routed_factory = async_session_factory(migrated_engine)
        routed_uow = SqlAlchemyUnitOfWork(
            routed_factory,
            code_hash=CodeHash(HASH_B),
            config_hash=ConfigHash(HASH_A),
        )
        routed_factory.configure(binds={OrderIntentRow: unvalidated_engine})
        with pytest.raises(PersistenceConfigurationError, match="safety options"):
            async with routed_uow:
                pass
    finally:
        await unvalidated_engine.dispose()


@pytest.mark.asyncio
async def test_failed_unit_of_work_entry_rolls_back_and_releases_the_database(
    migrated_engine: AsyncEngine,
) -> None:
    invalid = SqlAlchemyUnitOfWork(
        async_session_factory(migrated_engine),
        code_hash=CodeHash("not-a-hash"),
        config_hash=ConfigHash(HASH_A),
    )
    with pytest.raises(PersistenceDataError, match="code_hash"):
        async with invalid:
            pass

    async with _make_uow(migrated_engine) as valid:
        await valid.orders.add(_make_intent())
        await valid.commit()
    assert await _count(migrated_engine, OrderIntentRow) == 1
