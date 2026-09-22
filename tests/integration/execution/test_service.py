"""End-to-end fake-broker coverage for the single durable execution sequence."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.unit.risk.test_pretrade import valid_harness
from trading_bot import logging as logging_module
from trading_bot.brokers import BrokerSubmissionAmbiguous
from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrder,
    BrokerOrderId,
    BrokerOrderReview,
    CheckResult,
    CodeHash,
    ConfigHash,
    DataHash,
    DomainValidationError,
    ExecutionMode,
    InstrumentId,
    OrderId,
    OrderIntent,
    OrderIntentId,
    OrderPurpose,
    OrderState,
    OrderType,
    RiskEvaluation,
    Side,
    TimeInForce,
)
from trading_bot.execution import InProcessSubmissionExclusion, OrderReviewService
from trading_bot.execution.service import ExecutionService
from trading_bot.logging import SecretRegistry
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.base import PersistenceDataError
from trading_bot.persistence.models import (
    AccountRow,
    BrokerReviewRow,
    InstrumentRow,
    OrderRow,
    OrderTransitionRow,
    RiskEvaluationRow,
    SubmissionAttemptRow,
)
from trading_bot.persistence.unit_of_work import SqlAlchemyUnitOfWork
from trading_bot.risk import canonical_review_payload_sha256

ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 7, 16, 18, 0, tzinfo=UTC)
CONFIG_HASH = ConfigHash("a" * 64)
CODE_HASH = CodeHash("b" * 64)
DATA_HASH = DataHash("c" * 64)


class FixedClock:
    def now(self) -> datetime:
        return NOW


def make_intent() -> OrderIntent:
    return OrderIntent(
        id=OrderIntentId("00000000-0000-4000-8000-000000000008"),
        account_id=AccountId("paper-account"),
        instrument_id=InstrumentId("paper-instrument"),
        asset_class=AssetClass.EQUITY,
        side=Side.BUY,
        purpose=OrderPurpose.ENTRY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GOOD_FOR_DAY,
        quantity=Decimal("1"),
        limit_price=Decimal("10"),
        stop_price=None,
        created_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        strategy_version="paper-strategy-v1",
        config_hash=CONFIG_HASH,
        data_hash=DATA_HASH,
        exit_policy_version="protective-v1",
    )


def make_review(intent: OrderIntent) -> BrokerOrderReview:
    return BrokerOrderReview(
        normalized_order=intent,
        source="paper",
        reviewed_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
        estimated_notional=Decimal("10"),
        estimated_fees=Decimal("0"),
        client_order_id=None,
        outbound_payload_sha256=canonical_review_payload_sha256(
            intent,
            client_order_id=None,
        ),
        broker_review_id="paper-review-1",
    )


def make_broker_order(intent: OrderIntent, *, state: OrderState) -> BrokerOrder:
    return BrokerOrder(
        id=OrderId("local-order-1"),
        broker_order_id=BrokerOrderId("paper-broker-order-1"),
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
        state=state,
        created_at=NOW,
        updated_at=NOW,
        data_hash=DATA_HASH,
    )


class FakeContextLoader:
    def __init__(self) -> None:
        self.initial_calls = 0
        self.final_calls = 0

    async def load_initial(self, intent: OrderIntent) -> object:
        self.initial_calls += 1
        return intent

    async def load_final(self, intent: OrderIntent, review: BrokerOrderReview) -> object:
        self.final_calls += 1
        return (intent, review)


class FakePretrade:
    def __init__(self, *, initial_allowed: bool = True, final_allowed: bool = True) -> None:
        self.initial_allowed = initial_allowed
        self.final_allowed = final_allowed
        self.initial_calls = 0
        self.final_calls = 0

    @staticmethod
    def _evaluation(intent: OrderIntent, *, allowed: bool, count: int) -> RiskEvaluation:
        checks = tuple(
            CheckResult(
                code=f"fake_check_{index}",
                allowed=allowed,
                observed="satisfied" if allowed else "denied",
                configured_limit="required",
                reason="fake_allowed" if allowed else "fake_denied",
                observed_at=NOW,
            )
            for index in range(count)
        )
        return RiskEvaluation(
            intent_id=intent.id,
            allowed=allowed,
            checks=checks,
            evaluated_at=NOW,
            config_hash=intent.config_hash,
        )

    def evaluate_initial(self, context: object) -> RiskEvaluation:
        self.initial_calls += 1
        assert type(context) is OrderIntent
        return self._evaluation(context, allowed=self.initial_allowed, count=23)

    def evaluate_final(self, context: object) -> RiskEvaluation:
        self.final_calls += 1
        assert type(context) is tuple
        intent, _review = context
        assert type(intent) is OrderIntent
        return self._evaluation(intent, allowed=self.final_allowed, count=24)


class FakeReview:
    def __init__(self, response: BrokerOrderReview) -> None:
        self.response = response
        self.calls = 0

    async def review_order(self, intent: OrderIntent) -> BrokerOrderReview:
        self.calls += 1
        assert type(intent) is OrderIntent
        return self.response


class FakePlace:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        response: BrokerOrder | BaseException,
    ) -> None:
        self._session_factory = session_factory
        self.response = response
        self.calls = 0
        self.observed_pending = False

    async def place_order(self, submission: object) -> BrokerOrder:
        del submission
        self.calls += 1
        async with self._session_factory() as session:
            attempt = await session.scalar(select(SubmissionAttemptRow))
            transition_row = await session.scalar(
                select(OrderTransitionRow)
                .where(OrderTransitionRow.to_state == OrderState.SUBMISSION_PENDING.value)
                .order_by(OrderTransitionRow.occurred_at.desc())
            )
        self.observed_pending = (
            attempt is not None
            and attempt.outcome_class == "pending"
            and transition_row is not None
        )
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


@pytest.fixture
def execution_database_url(tmp_path: Path) -> str:
    """Create the migrated database before pytest enters an async event loop."""

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'execution.sqlite3'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    return database_url


@pytest.fixture
async def execution_database(
    execution_database_url: str,
) -> AsyncIterator[
    tuple[
        AsyncEngine,
        async_sessionmaker[AsyncSession],
    ]
]:
    engine = create_engine(execution_database_url)
    factory = async_session_factory(engine)
    async with factory.begin() as session:
        session.add(
            AccountRow(
                id="paper-account",
                provider="paper",
                provider_account_id="paper-provider-account",
                account_type="cash",
                provider_state="active",
                equity=Decimal("1000"),
                cash=Decimal("1000"),
                equity_buying_power=Decimal("1000"),
                crypto_buying_power=None,
                prediction_buying_power=None,
                restricted=False,
                observed_at=NOW,
                data_hash=DATA_HASH,
                config_hash=CONFIG_HASH,
                code_hash=CODE_HASH,
            )
        )
        session.add(
            InstrumentRow(
                id="paper-instrument",
                provider="paper",
                provider_instrument_id="paper-provider-instrument",
                symbol="TEST",
                asset_class=AssetClass.EQUITY.value,
                provider_status="active",
                tradable=True,
                fractional_eligible=True,
                price_increment=Decimal("0.01"),
                quantity_increment=Decimal("1"),
                minimum_quantity=Decimal("1"),
                minimum_notional=Decimal("1"),
                maximum_quantity=None,
                correlation_group="equity:TEST",
                observed_at=NOW,
                data_hash=DATA_HASH,
            )
        )
    try:
        yield engine, factory
    finally:
        await engine.dispose()


def make_service(
    factory: async_sessionmaker[AsyncSession],
    *,
    pretrade: FakePretrade,
    review: FakeReview,
    place: FakePlace,
    mode: ExecutionMode = ExecutionMode.PAPER,
) -> ExecutionService:
    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(
            factory,
            code_hash=CODE_HASH,
            config_hash=CONFIG_HASH,
        )

    return ExecutionService(
        review=OrderReviewService(review),  # type: ignore[arg-type]
        place=place,  # type: ignore[arg-type]
        pretrade=pretrade,  # type: ignore[arg-type]
        context_loader=FakeContextLoader(),  # type: ignore[arg-type]
        uow_factory=uow_factory,
        exclusion=InProcessSubmissionExclusion(),
        mode=mode,
        provider="paper",
        clock=FixedClock(),
    )


@pytest.mark.asyncio
async def test_denied_initial_risk_never_reviews_or_places(
    execution_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _engine, factory = execution_database
    intent = make_intent()
    review = FakeReview(make_review(intent))
    place = FakePlace(factory, make_broker_order(intent, state=OrderState.SUBMITTED))
    service = make_service(
        factory,
        pretrade=FakePretrade(initial_allowed=False),
        review=review,
        place=place,
    )

    result = await service.execute(intent)

    assert result.state is OrderState.RISK_REJECTED
    assert review.calls == 0
    assert place.calls == 0
    async with factory() as session:
        initial_risk = await session.scalar(
            select(RiskEvaluationRow).where(RiskEvaluationRow.phase == "initial")
        )
    assert initial_risk is not None and initial_risk.check_count == 23


@pytest.mark.asyncio
async def test_safe_fake_order_is_durably_pending_before_exactly_one_place(
    execution_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _engine, factory = execution_database
    intent = make_intent()
    review = FakeReview(make_review(intent))
    place = FakePlace(factory, make_broker_order(intent, state=OrderState.SUBMITTED))
    service = make_service(
        factory,
        pretrade=FakePretrade(),
        review=review,
        place=place,
    )

    result = await service.execute(intent)

    assert result.state is OrderState.SUBMITTED
    assert place.calls == 1
    assert place.observed_pending
    async with factory() as session:
        attempt = await session.scalar(select(SubmissionAttemptRow))
        order_count = await session.scalar(select(func.count()).select_from(OrderRow))
        risk_rows = (
            await session.scalars(select(RiskEvaluationRow).order_by(RiskEvaluationRow.phase))
        ).all()
        transitions = (
            await session.scalars(
                select(OrderTransitionRow).order_by(OrderTransitionRow.occurred_at)
            )
        ).all()
    assert attempt is not None and attempt.outcome_class == "accepted"
    assert order_count == 1
    assert sorted(row.check_count for row in risk_rows) == [23, 24]
    assert [row.to_state for row in transitions] == [
        OrderState.PROPOSED.value,
        OrderState.RISK_APPROVED.value,
        OrderState.REVIEW_REQUESTED.value,
        OrderState.REVIEWED.value,
        OrderState.SUBMISSION_PENDING.value,
        OrderState.SUBMITTED.value,
    ]


@pytest.mark.asyncio
async def test_real_final_pretrade_evidence_is_persisted_canonically(
    execution_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    """Exercise persistence with all 24 checks emitted by the real risk engine."""

    _engine, factory = execution_database
    intent = make_intent()
    harness = valid_harness()
    evaluation = replace(
        harness.engine.evaluate_final(harness.context),
        intent_id=intent.id,
        config_hash=intent.config_hash,
    )
    assert len(evaluation.checks) == 24
    assert any(
        value is not None and len(value) > 128
        for check in evaluation.checks
        for value in (check.observed, check.configured_limit)
    )

    async with SqlAlchemyUnitOfWork(
        factory,
        code_hash=CODE_HASH,
        config_hash=CONFIG_HASH,
    ) as uow:
        await uow.orders.add(intent)
        await uow.orders.add_risk_evaluation("real-final-risk", "final", evaluation)
        await uow.commit()

    async with factory() as session:
        persisted = await session.scalar(
            select(RiskEvaluationRow).where(RiskEvaluationRow.id == "real-final-risk")
        )
    assert persisted is not None
    assert persisted.check_count == 24


@pytest.mark.asyncio
async def test_risk_evidence_still_rejects_registered_secrets(
    execution_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _engine, factory = execution_database
    intent = make_intent()
    secret = "registered_structured_secret"
    monkeypatch.setattr(logging_module, "_REGISTRY_STATE", logging_module._RegistryState())
    SecretRegistry().register(secret)
    evaluation = FakePretrade._evaluation(intent, allowed=True, count=24)
    evaluation = replace(
        evaluation,
        checks=(replace(evaluation.checks[0], observed=secret), *evaluation.checks[1:]),
    )

    with pytest.raises(PersistenceDataError, match="safe bounded evidence") as captured:
        async with SqlAlchemyUnitOfWork(
            factory,
            code_hash=CODE_HASH,
            config_hash=CONFIG_HASH,
        ) as uow:
            await uow.orders.add(intent)
            await uow.orders.add_risk_evaluation("secret-risk", "final", evaluation)

    assert secret not in str(captured.value)


@pytest.mark.asyncio
async def test_final_risk_denial_retains_review_and_all_checks_without_place(
    execution_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _engine, factory = execution_database
    intent = make_intent()
    review = FakeReview(make_review(intent))
    place = FakePlace(factory, make_broker_order(intent, state=OrderState.SUBMITTED))
    service = make_service(
        factory,
        pretrade=FakePretrade(final_allowed=False),
        review=review,
        place=place,
    )

    result = await service.execute(intent)

    assert result.state is OrderState.RISK_REJECTED
    assert place.calls == 0
    async with factory() as session:
        review_count = await session.scalar(select(func.count()).select_from(BrokerReviewRow))
        final_risk = await session.scalar(
            select(RiskEvaluationRow).where(RiskEvaluationRow.phase == "final")
        )
    assert review_count == 1
    assert final_risk is not None and final_risk.check_count == 24


@pytest.mark.asyncio
async def test_ambiguous_place_is_persisted_and_never_retried(
    execution_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _engine, factory = execution_database
    intent = make_intent()
    review = FakeReview(make_review(intent))
    place = FakePlace(factory, BrokerSubmissionAmbiguous())
    service = make_service(
        factory,
        pretrade=FakePretrade(),
        review=review,
        place=place,
    )

    result = await service.execute(intent)

    assert result.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    assert place.calls == 1
    async with factory() as session:
        attempt = await session.scalar(select(SubmissionAttemptRow))
        order_count = await session.scalar(select(func.count()).select_from(OrderRow))
    assert attempt is not None and attempt.outcome_class == "ambiguous"
    assert order_count == 0


@pytest.mark.asyncio
async def test_mismatched_exact_broker_response_becomes_ambiguous(
    execution_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _engine, factory = execution_database
    intent = make_intent()
    review = FakeReview(make_review(intent))
    mismatched = replace(
        make_broker_order(intent, state=OrderState.SUBMITTED),
        broker_order_id=BrokerOrderId("other-provider-order"),
        account_id=AccountId("other-account"),
    )
    place = FakePlace(factory, mismatched)
    service = make_service(
        factory,
        pretrade=FakePretrade(),
        review=review,
        place=place,
    )

    result = await service.execute(intent)

    assert result.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    assert place.calls == 1
    async with factory() as session:
        attempt = await session.scalar(select(SubmissionAttemptRow))
    assert attempt is not None and attempt.outcome_class == "ambiguous"
    assert attempt.sanitized_response_hash is not None


@pytest.mark.asyncio
async def test_exact_broker_rejection_persists_order_and_terminal_attempt(
    execution_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _engine, factory = execution_database
    intent = make_intent()
    review = FakeReview(make_review(intent))
    place = FakePlace(factory, make_broker_order(intent, state=OrderState.REJECTED))
    service = make_service(
        factory,
        pretrade=FakePretrade(),
        review=review,
        place=place,
    )

    result = await service.execute(intent)

    assert result.state is OrderState.REJECTED
    assert result.broker_order is not None
    assert place.calls == 1
    async with factory() as session:
        attempt = await session.scalar(select(SubmissionAttemptRow))
        order = await session.scalar(select(OrderRow))
    assert attempt is not None and attempt.outcome_class == "rejected"
    assert order is not None and order.state == OrderState.REJECTED.value


@pytest.mark.asyncio
async def test_unexpected_exact_broker_state_is_hashed_but_not_accepted(
    execution_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _engine, factory = execution_database
    intent = make_intent()
    review = FakeReview(make_review(intent))
    place = FakePlace(factory, make_broker_order(intent, state=OrderState.CANCELED))
    service = make_service(
        factory,
        pretrade=FakePretrade(),
        review=review,
        place=place,
    )

    result = await service.execute(intent)

    assert result.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    assert result.broker_order is None
    async with factory() as session:
        attempt = await session.scalar(select(SubmissionAttemptRow))
        order_count = await session.scalar(select(func.count()).select_from(OrderRow))
    assert attempt is not None and attempt.outcome_class == "ambiguous"
    assert attempt.sanitized_response_hash is not None
    assert order_count == 0


@pytest.mark.asyncio
async def test_mismatched_review_is_rejected_without_persisting_or_placing(
    execution_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _engine, factory = execution_database
    intent = make_intent()
    mismatched_intent = replace(intent, quantity=Decimal("2"))
    mismatched_review = replace(
        make_review(mismatched_intent),
        estimated_notional=Decimal("20"),
    )
    review = FakeReview(mismatched_review)
    place = FakePlace(factory, make_broker_order(intent, state=OrderState.SUBMITTED))
    service = make_service(
        factory,
        pretrade=FakePretrade(),
        review=review,
        place=place,
    )

    result = await service.execute(intent)

    assert result.state is OrderState.REJECTED
    assert result.reason_code == "review_rejected"
    assert place.calls == 0
    async with factory() as session:
        review_count = await session.scalar(select(func.count()).select_from(BrokerReviewRow))
    assert review_count == 0


@pytest.mark.asyncio
async def test_expired_review_persists_final_checks_and_never_places(
    execution_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _engine, factory = execution_database
    intent = make_intent()
    review = FakeReview(replace(make_review(intent), expires_at=NOW))
    place = FakePlace(factory, make_broker_order(intent, state=OrderState.SUBMITTED))
    service = make_service(
        factory,
        pretrade=FakePretrade(),
        review=review,
        place=place,
    )

    result = await service.execute(intent)

    assert result.state is OrderState.EXPIRED
    assert result.reason_code == "submission_window_expired"
    assert place.calls == 0
    async with factory() as session:
        final_risk = await session.scalar(
            select(RiskEvaluationRow).where(RiskEvaluationRow.phase == "final")
        )
        attempt_count = await session.scalar(select(func.count()).select_from(SubmissionAttemptRow))
    assert final_risk is not None and final_risk.check_count == 24
    assert attempt_count == 0


@pytest.mark.asyncio
async def test_live_modes_remain_blocked_without_later_authorization_layer(
    execution_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
) -> None:
    _engine, factory = execution_database
    intent = make_intent()
    review = FakeReview(make_review(intent))
    place = FakePlace(factory, make_broker_order(intent, state=OrderState.SUBMITTED))

    with pytest.raises(DomainValidationError, match="live execution requires"):
        make_service(
            factory,
            pretrade=FakePretrade(),
            review=review,
            place=place,
            mode=ExecutionMode.MICRO_LIVE,
        )

    assert review.calls == 0
    assert place.calls == 0
