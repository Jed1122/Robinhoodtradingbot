"""Unit tests for the ordered, fail-closed pretrade checklist."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from trading_bot.config import AppConfig, hash_config, load_config
from trading_bot.domain import (
    AccountId,
    AccountSnapshot,
    AlertAttestation,
    AssetBuyingPower,
    AssetClass,
    BrokerHealth,
    BrokerOrderReview,
    ClientOrderId,
    CodeHash,
    ConfigHash,
    DataHash,
    DomainValidationError,
    ExecutionMode,
    Instrument,
    InstrumentId,
    InvalidDecimal,
    LiveLeaseAttestation,
    MarketClock,
    OrderIntent,
    OrderIntentId,
    OrderPurpose,
    OrderType,
    PortfolioSnapshot,
    Position,
    Quote,
    ReconciliationAttestation,
    RuntimeState,
    Side,
    StrategyEligibilityAttestation,
    TimeInForce,
    TimestampSource,
)
from trading_bot.risk import ActivitySnapshot, ExposureProjection, LossSnapshot
from trading_bot.risk.pretrade import (
    ExecutionCostEstimate,
    FinalPretradeContext,
    InitialRiskContext,
    InstrumentEligibility,
    PretradeCheckCode,
    PretradeEngine,
    canonical_review_payload_sha256,
)

ROOT = Path(__file__).parents[3]
CONFIGS = ROOT / "configs"
NOW = datetime(2026, 7, 15, 16, 0, tzinfo=UTC)
DAY_STARTED_AT = datetime(2026, 7, 15, 0, 0, tzinfo=UTC)
WEEK_STARTED_AT = datetime(2026, 7, 13, 0, 0, tzinfo=UTC)
ACCOUNT_ID = AccountId("account-1")
INSTRUMENT_ID = InstrumentId("btc-usd")
INTENT_ID = OrderIntentId("00000000-0000-4000-8000-000000000001")
CODE_HASH = CodeHash("c" * 64)
DATA_HASH = DataHash("d" * 64)
EVIDENCE_HASH = "e" * 64


@dataclass(frozen=True, slots=True)
class FixedClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


CLOCK = FixedClock(NOW)


def live_config() -> tuple[AppConfig, ConfigHash]:
    loaded = load_config(
        base_path=CONFIGS / "base.yaml",
        mode_path=CONFIGS / "normal_live.yaml",
        safety_path=CONFIGS / "safety-envelope.yaml",
        environ={},
    )
    research = loaded.config.research.model_copy(
        update={"assumptions_validated": True, "evidence_promotable": True}
    )
    config = loaded.config.model_copy(update={"live_trading_enabled": True, "research": research})
    return config, hash_config(config)[1]


def order_intent(config_hash: ConfigHash, **overrides: object) -> OrderIntent:
    values: dict[str, object] = {
        "id": INTENT_ID,
        "account_id": ACCOUNT_ID,
        "instrument_id": INSTRUMENT_ID,
        "asset_class": AssetClass.CRYPTO,
        "side": Side.BUY,
        "purpose": OrderPurpose.ENTRY,
        "order_type": OrderType.LIMIT,
        "time_in_force": TimeInForce.GOOD_TIL_CANCELED,
        "quantity": Decimal("0.100"),
        "limit_price": Decimal("10.01"),
        "stop_price": None,
        "created_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(minutes=5),
        "strategy_version": "crypto-v1",
        "config_hash": config_hash,
        "data_hash": DATA_HASH,
        "exit_policy_version": "stop-v1",
    }
    values.update(overrides)
    return OrderIntent(**values)  # type: ignore[arg-type]


def quote(**overrides: object) -> Quote:
    values: dict[str, object] = {
        "instrument_id": INSTRUMENT_ID,
        "observed_at": NOW - timedelta(seconds=1),
        "bid": Decimal("10.00"),
        "ask": Decimal("10.01"),
        "last": Decimal("10.00"),
        "source": "validated-test-feed",
        "data_hash": DATA_HASH,
        "freshness_verified": True,
        "timestamp_source": TimestampSource.PROVIDER,
    }
    values.update(overrides)
    return Quote(**values)  # type: ignore[arg-type]


def costs(intent: OrderIntent, current_quote: Quote, **overrides: object) -> ExecutionCostEstimate:
    values: dict[str, object] = {
        "intent": intent,
        "quote": current_quote,
        "slippage_pct": Decimal("0.10"),
        "fees_usd": Decimal("0.001"),
        "commission_usd": Decimal("0"),
        "expected_gross_edge_usd": Decimal("0.50"),
        "expected_reward_usd": Decimal("1"),
        "initial_risk_usd": Decimal("0.50"),
        "verified": True,
        "observed_at": current_quote.observed_at,
        "data_hash": DataHash("f" * 64),
    }
    values.update(overrides)
    return ExecutionCostEstimate.from_quote(**values)  # type: ignore[arg-type]


def instrument(**overrides: object) -> Instrument:
    values: dict[str, object] = {
        "id": INSTRUMENT_ID,
        "symbol": "BTC-USD",
        "asset_class": AssetClass.CRYPTO,
        "provider_status": "active",
        "tradable": True,
        "fractional_eligible": True,
        "price_increment": Decimal("0.01"),
        "quantity_increment": Decimal("0.001"),
        "minimum_quantity": Decimal("0.001"),
        "minimum_notional": Decimal("1"),
        "maximum_quantity": Decimal("100"),
        "correlation_group": "crypto-major",
        "observed_at": NOW - timedelta(seconds=1),
        "data_hash": DATA_HASH,
    }
    values.update(overrides)
    return Instrument(**values)  # type: ignore[arg-type]


def eligibility(**overrides: object) -> InstrumentEligibility:
    values: dict[str, object] = {
        "instrument_id": INSTRUMENT_ID,
        "symbol_allowlisted": True,
        "asset_policy_eligible": True,
        "provider_restriction_clear": True,
        "fractional_eligibility_verified": True,
        "earnings_restriction_clear": True,
        "session_order_type_eligible": True,
        "exit_policy_monitorable": True,
        "average_daily_dollar_volume_usd": None,
        "observed_at": NOW - timedelta(seconds=1),
        "evidence_hash": EVIDENCE_HASH,
    }
    values.update(overrides)
    return InstrumentEligibility(**values)  # type: ignore[arg-type]


def exposure(**overrides: object) -> ExposureProjection:
    values: dict[str, object] = {
        "account_id": ACCOUNT_ID,
        "intent_id": INTENT_ID,
        "instrument_id": INSTRUMENT_ID,
        "asset_class": AssetClass.CRYPTO,
        "correlation_group": "crypto-major",
        "equity": Decimal("100"),
        "authorized_risk_equity": Decimal("100"),
        "cash": Decimal("98.90"),
        "gross_exposure": Decimal("1.10"),
        "open_position_count": 1,
        "position_notional": Decimal("1.001"),
        "correlated_group_exposure": Decimal("1.001"),
        "crypto_exposure": Decimal("1.001"),
        "single_crypto_exposure": Decimal("1.001"),
        "observed_at": NOW,
    }
    values.update(overrides)
    return ExposureProjection(**values)  # type: ignore[arg-type]


def valid_initial_context(config_hash: ConfigHash) -> InitialRiskContext:
    intent = order_intent(config_hash)
    current_quote = quote()
    return InitialRiskContext(
        intent=intent,
        account=AccountSnapshot(
            account_id=ACCOUNT_ID,
            provider_state="active",
            equity=Decimal("100"),
            cash=Decimal("100"),
            buying_power=(AssetBuyingPower(asset_class=AssetClass.CRYPTO, amount=Decimal("100")),),
            restricted=False,
            observed_at=NOW - timedelta(seconds=1),
            data_hash=DATA_HASH,
        ),
        portfolio=PortfolioSnapshot(
            account_id=ACCOUNT_ID,
            positions=(),
            cash=Decimal("100"),
            equity=Decimal("100"),
            gross_exposure=Decimal("0"),
            net_exposure=Decimal("0"),
            crypto_exposure=Decimal("0"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            observed_at=NOW - timedelta(seconds=1),
            data_hash=DATA_HASH,
        ),
        instrument=instrument(),
        eligibility=eligibility(),
        quote=current_quote,
        market_clock=MarketClock(
            asset_class=AssetClass.CRYPTO,
            venue="crypto-24x7",
            observed_at=NOW - timedelta(seconds=1),
            is_open=True,
            halted=False,
            trading_disabled=False,
            cancel_only=False,
            next_open_at=None,
            next_close_at=None,
        ),
        broker_health=BrokerHealth(
            healthy=True,
            observed_at=NOW - timedelta(seconds=1),
            latency_ms=Decimal("10"),
            reason_codes=(),
        ),
        open_orders=(),
        local_pending_intents=(),
        reconciliation=ReconciliationAttestation(
            account_id=ACCOUNT_ID,
            clean=True,
            observed_at=NOW - timedelta(seconds=1),
            evidence_hash=EVIDENCE_HASH,
        ),
        live_lease=LiveLeaseAttestation(
            valid=True,
            account_id=ACCOUNT_ID,
            config_hash=config_hash,
            mode=ExecutionMode.NORMAL_LIVE,
            expires_at=NOW + timedelta(hours=1),
            evidence_hash=EVIDENCE_HASH,
        ),
        alerts=AlertAttestation(
            critical_count=0,
            observed_at=NOW - timedelta(seconds=1),
            evidence_hash=EVIDENCE_HASH,
        ),
        strategy_eligibility=StrategyEligibilityAttestation(
            eligible=True,
            strategy_version=intent.strategy_version,
            config_hash=config_hash,
            code_hash=CODE_HASH,
            research_manifest_hash="a" * 64,
            report_hash="b" * 64,
            observed_at=NOW - timedelta(seconds=1),
        ),
        runtime_state=RuntimeState.RUNNING_LIVE,
        kill_switch_active=False,
        losses=LossSnapshot(
            account_id=ACCOUNT_ID,
            daily_loss_pct=Decimal("0"),
            weekly_loss_pct=Decimal("0"),
            peak_to_trough_drawdown_pct=Decimal("0"),
            consecutive_loss_count=0,
            last_loss_at=None,
            daily_window_started_at=DAY_STARTED_AT,
            weekly_window_started_at=WEEK_STARTED_AT,
            daily_reset_reconciled=True,
            weekly_reset_reviewed=True,
            observed_at=NOW,
        ),
        activity=ActivitySnapshot(
            account_id=ACCOUNT_ID,
            instrument_id=INSTRUMENT_ID,
            new_orders_today=0,
            new_orders_for_symbol_today=0,
            last_new_order_at=None,
            daily_window_started_at=DAY_STARTED_AT,
            observed_at=NOW,
        ),
        projection=exposure(),
        costs=costs(intent, current_quote),
        observed_at=NOW,
    )


def reviewed_order(intent: OrderIntent, **overrides: object) -> BrokerOrderReview:
    client_order_id = ClientOrderId(str(intent.id))
    values: dict[str, object] = {
        "normalized_order": intent,
        "source": "fake-crypto-review",
        "reviewed_at": NOW - timedelta(seconds=1),
        "expires_at": NOW + timedelta(seconds=30),
        "estimated_notional": Decimal("1.001"),
        "estimated_fees": Decimal("0.001"),
        "client_order_id": client_order_id,
        "outbound_payload_sha256": canonical_review_payload_sha256(
            intent,
            client_order_id=client_order_id,
        ),
        "broker_review_id": "review-1",
    }
    values.update(overrides)
    return BrokerOrderReview(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class Harness:
    config: AppConfig
    config_hash: ConfigHash
    engine: PretradeEngine
    context: FinalPretradeContext


def valid_harness() -> Harness:
    config, config_hash = live_config()
    initial = valid_initial_context(config_hash)
    return Harness(
        config=config,
        config_hash=config_hash,
        engine=PretradeEngine(
            config,
            config_hash=config_hash,
            account_allowlist=(ACCOUNT_ID,),
            active_code_hash=CODE_HASH,
            clock=CLOCK,
        ),
        context=FinalPretradeContext(
            initial=initial,
            reviewed_order=reviewed_order(initial.intent),
        ),
    )


def exit_harness() -> Harness:
    harness = valid_harness()
    entry = harness.context.initial
    intent = order_intent(
        harness.config_hash,
        side=Side.SELL,
        purpose=OrderPurpose.PROTECTIVE_EXIT,
        limit_price=Decimal("10.00"),
        exit_policy_version=None,
    )
    current_position = Position(
        account_id=ACCOUNT_ID,
        instrument_id=INSTRUMENT_ID,
        asset_class=AssetClass.CRYPTO,
        quantity=Decimal("1"),
        average_price=Decimal("9"),
        market_value=Decimal("10"),
        observed_at=NOW - timedelta(seconds=1),
        data_hash=DATA_HASH,
    )
    current_quote = quote()
    initial = replace(
        entry,
        intent=intent,
        account=replace(entry.account, cash=Decimal("90")),
        portfolio=replace(
            entry.portfolio,
            positions=(current_position,),
            cash=Decimal("90"),
            gross_exposure=Decimal("10"),
            net_exposure=Decimal("10"),
            crypto_exposure=Decimal("10"),
        ),
        runtime_state=RuntimeState.ENTRY_BLOCKED,
        losses=replace(entry.losses, daily_loss_pct=Decimal("2")),
        activity=replace(
            entry.activity,
            new_orders_today=3,
            new_orders_for_symbol_today=1,
            last_new_order_at=NOW - timedelta(minutes=1),
        ),
        projection=exposure(
            cash=Decimal("91"),
            gross_exposure=Decimal("9"),
            position_notional=Decimal("9"),
            correlated_group_exposure=Decimal("9"),
            crypto_exposure=Decimal("9"),
            single_crypto_exposure=Decimal("9"),
        ),
        costs=costs(
            intent,
            current_quote,
            expected_gross_edge_usd=Decimal("0"),
            expected_reward_usd=Decimal("0"),
            initial_risk_usd=Decimal("0"),
        ),
    )
    return replace(
        harness,
        context=FinalPretradeContext(
            initial=initial,
            reviewed_order=reviewed_order(
                intent,
                estimated_notional=Decimal("1"),
            ),
        ),
    )


def equity_harness() -> Harness:
    harness = valid_harness()
    initial = harness.context.initial
    intent = order_intent(harness.config_hash, asset_class=AssetClass.EQUITY)
    equity_instrument = replace(
        initial.instrument,
        symbol="AAPL",
        asset_class=AssetClass.EQUITY,
    )
    equity_quote = quote()
    rebuilt = replace(
        initial,
        intent=intent,
        account=replace(
            initial.account,
            buying_power=(AssetBuyingPower(asset_class=AssetClass.EQUITY, amount=Decimal("100")),),
        ),
        portfolio=replace(initial.portfolio, crypto_exposure=Decimal("0")),
        instrument=equity_instrument,
        eligibility=replace(
            initial.eligibility,
            average_daily_dollar_volume_usd=Decimal("50000000"),
        ),
        quote=equity_quote,
        market_clock=replace(
            initial.market_clock,
            asset_class=AssetClass.EQUITY,
            venue="equity-test-venue",
        ),
        projection=replace(
            initial.projection,
            asset_class=AssetClass.EQUITY,
            crypto_exposure=Decimal("0"),
            single_crypto_exposure=Decimal("0"),
        ),
        costs=costs(intent, equity_quote),
    )
    return replace(
        harness,
        context=FinalPretradeContext(
            initial=rebuilt,
            reviewed_order=reviewed_order(
                intent,
                client_order_id=None,
                outbound_payload_sha256=canonical_review_payload_sha256(
                    intent,
                    client_order_id=None,
                ),
            ),
        ),
    )


def prediction_simulation_harness() -> Harness:
    loaded = load_config(
        base_path=CONFIGS / "base.yaml",
        mode_path=CONFIGS / "paper.yaml",
        safety_path=CONFIGS / "safety-envelope.yaml",
        environ={},
    )
    initial = valid_initial_context(loaded.config_hash)
    intent = order_intent(loaded.config_hash, asset_class=AssetClass.PREDICTION)
    prediction_quote = quote()
    rebuilt = replace(
        initial,
        intent=intent,
        account=replace(
            initial.account,
            buying_power=(
                AssetBuyingPower(asset_class=AssetClass.PREDICTION, amount=Decimal("100")),
            ),
        ),
        portfolio=replace(initial.portfolio, crypto_exposure=Decimal("0")),
        instrument=replace(
            initial.instrument,
            symbol="PREDICTION-YES",
            asset_class=AssetClass.PREDICTION,
        ),
        quote=prediction_quote,
        market_clock=replace(
            initial.market_clock,
            asset_class=AssetClass.PREDICTION,
            venue="prediction-simulation",
        ),
        live_lease=None,
        strategy_eligibility=replace(
            initial.strategy_eligibility,
            config_hash=loaded.config_hash,
        ),
        runtime_state=RuntimeState.PAUSED,
        projection=replace(
            initial.projection,
            asset_class=AssetClass.PREDICTION,
            crypto_exposure=Decimal("0"),
            single_crypto_exposure=Decimal("0"),
        ),
        costs=costs(intent, prediction_quote),
    )
    engine = PretradeEngine(
        loaded.config,
        config_hash=loaded.config_hash,
        account_allowlist=(ACCOUNT_ID,),
        active_code_hash=CODE_HASH,
        clock=CLOCK,
    )
    return Harness(
        config=loaded.config,
        config_hash=loaded.config_hash,
        engine=engine,
        context=FinalPretradeContext(
            initial=rebuilt,
            reviewed_order=reviewed_order(
                intent,
                client_order_id=None,
                outbound_payload_sha256=canonical_review_payload_sha256(
                    intent,
                    client_order_id=None,
                ),
            ),
        ),
    )


ContextMutator = Callable[[FinalPretradeContext], FinalPretradeContext]


def with_initial(
    context: FinalPretradeContext,
    **changes: object,
) -> FinalPretradeContext:
    return replace(
        context,
        initial=replace(context.initial, **changes),  # type: ignore[arg-type]
    )


def without_live_lease(context: FinalPretradeContext) -> FinalPretradeContext:
    assert context.initial.live_lease is not None
    return with_initial(
        context,
        live_lease=replace(context.initial.live_lease, valid=False),
    )


def with_kill_switch(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(context, kill_switch_active=True)


def with_restricted_account(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(context, account=replace(context.initial.account, restricted=True))


def with_unhealthy_broker(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        broker_health=replace(context.initial.broker_health, healthy=False),
    )


def with_unverified_quote(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        quote=replace(context.initial.quote, freshness_verified=False),
    )


def without_symbol_eligibility(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        eligibility=replace(context.initial.eligibility, symbol_allowlisted=False),
    )


def without_fractional_eligibility(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        instrument=replace(context.initial.instrument, fractional_eligible=False),
    )


def with_closed_session(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        market_clock=replace(context.initial.market_clock, is_open=False),
    )


def with_market_halt(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        market_clock=replace(context.initial.market_clock, halted=True),
    )


def without_buying_power(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        account=replace(
            context.initial.account,
            buying_power=(AssetBuyingPower(asset_class=AssetClass.CRYPTO, amount=Decimal("0")),),
        ),
    )


def below_cash_reserve(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(context, projection=replace(context.initial.projection, cash=Decimal("39")))


def above_position_cap(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        projection=replace(
            context.initial.projection,
            cash=Decimal("84"),
            gross_exposure=Decimal("16"),
            position_notional=Decimal("16"),
        ),
    )


def above_correlation_cap(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        projection=replace(
            context.initial.projection,
            cash=Decimal("74"),
            gross_exposure=Decimal("26"),
            correlated_group_exposure=Decimal("26"),
        ),
    )


def above_crypto_cap(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        projection=replace(
            context.initial.projection,
            cash=Decimal("79"),
            gross_exposure=Decimal("21"),
            crypto_exposure=Decimal("21"),
        ),
    )


def at_daily_loss_limit(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        losses=replace(context.initial.losses, daily_loss_pct=Decimal("2")),
    )


def at_daily_activity_limit(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        activity=replace(
            context.initial.activity,
            new_orders_today=3,
            last_new_order_at=NOW - timedelta(hours=1),
        ),
    )


def above_spread_limit(context: FinalPretradeContext) -> FinalPretradeContext:
    wide_quote = replace(
        context.initial.quote,
        bid=Decimal("9"),
        ask=Decimal("10"),
        last=Decimal("9.5"),
    )
    return with_initial(
        context,
        quote=wide_quote,
        costs=costs(context.initial.intent, wide_quote),
    )


def above_slippage_limit(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        costs=costs(
            context.initial.intent,
            context.initial.quote,
            slippage_pct=Decimal("0.51"),
        ),
    )


def without_after_cost_edge(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        costs=costs(
            context.initial.intent,
            context.initial.quote,
            expected_gross_edge_usd=Decimal("0"),
        ),
    )


def with_duplicate_intent(context: FinalPretradeContext) -> FinalPretradeContext:
    duplicate = replace(
        context.initial.intent,
        id=OrderIntentId("00000000-0000-4000-8000-000000000002"),
    )
    return with_initial(context, local_pending_intents=(duplicate,))


def without_monitorable_exit_policy(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        eligibility=replace(context.initial.eligibility, exit_policy_monitorable=False),
    )


def with_review_hash_mismatch(context: FinalPretradeContext) -> FinalPretradeContext:
    return replace(
        context,
        reviewed_order=replace(
            context.reviewed_order,
            outbound_payload_sha256="0" * 64,
        ),
    )


def below_broker_minimum(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        instrument=replace(context.initial.instrument, minimum_notional=Decimal("2")),
    )


def with_dirty_reconciliation(context: FinalPretradeContext) -> FinalPretradeContext:
    return with_initial(
        context,
        reconciliation=replace(context.initial.reconciliation, clean=False),
    )


DENIAL_CASES: tuple[tuple[ContextMutator, PretradeCheckCode], ...] = (
    (without_live_lease, PretradeCheckCode.LIVE_AUTHORIZATION),
    (with_kill_switch, PretradeCheckCode.KILL_SWITCH),
    (with_restricted_account, PretradeCheckCode.ACCOUNT_ALLOWLIST),
    (with_unhealthy_broker, PretradeCheckCode.BROKER_HEALTH),
    (with_unverified_quote, PretradeCheckCode.MARKET_DATA_FRESHNESS),
    (without_symbol_eligibility, PretradeCheckCode.SYMBOL_TRADABILITY),
    (without_fractional_eligibility, PretradeCheckCode.FRACTIONAL_ELIGIBILITY),
    (with_closed_session, PretradeCheckCode.MARKET_SESSION),
    (with_market_halt, PretradeCheckCode.MARKET_HALT),
    (without_buying_power, PretradeCheckCode.BUYING_POWER),
    (below_cash_reserve, PretradeCheckCode.CASH_RESERVE),
    (above_position_cap, PretradeCheckCode.POSITION_CAP),
    (above_correlation_cap, PretradeCheckCode.CORRELATION_CAP),
    (above_crypto_cap, PretradeCheckCode.CRYPTO_CAP),
    (at_daily_loss_limit, PretradeCheckCode.LOSS_LIMITS),
    (at_daily_activity_limit, PretradeCheckCode.ACTIVITY_LIMITS),
    (above_spread_limit, PretradeCheckCode.SPREAD),
    (above_slippage_limit, PretradeCheckCode.SLIPPAGE),
    (without_after_cost_edge, PretradeCheckCode.AFTER_COST_EDGE),
    (with_duplicate_intent, PretradeCheckCode.DUPLICATE_ORDER),
    (without_monitorable_exit_policy, PretradeCheckCode.EXIT_POLICY),
    (with_review_hash_mismatch, PretradeCheckCode.REVIEW_MATCH),
    (below_broker_minimum, PretradeCheckCode.BROKER_MINIMUMS),
    (with_dirty_reconciliation, PretradeCheckCode.RECONCILIATION),
)


@pytest.mark.parametrize(("mutator", "expected_code"), DENIAL_CASES)
def test_each_failed_check_denies_without_short_circuiting(
    mutator: ContextMutator,
    expected_code: PretradeCheckCode,
) -> None:
    harness = valid_harness()
    result = harness.engine.evaluate_final(mutator(harness.context))

    assert len(result.checks) == 24
    assert not result.allowed
    assert expected_code in {check.code for check in result.checks if not check.allowed}


def test_valid_final_context_returns_all_24_checks_in_approved_order() -> None:
    harness = valid_harness()
    result = harness.engine.evaluate_final(harness.context)

    assert result.allowed
    assert tuple(check.code for check in result.checks) == tuple(PretradeCheckCode)
    assert all(check.allowed for check in result.checks)
    assert result.config_hash == harness.config_hash


def test_valid_initial_context_runs_same_checks_except_review_match() -> None:
    harness = valid_harness()
    result = harness.engine.evaluate_initial(harness.context.initial)

    assert result.allowed
    assert len(result.checks) == 23
    assert PretradeCheckCode.REVIEW_MATCH not in {check.code for check in result.checks}
    assert tuple(check.code for check in result.checks) == tuple(
        code for code in PretradeCheckCode if code is not PretradeCheckCode.REVIEW_MATCH
    )


@pytest.mark.parametrize(
    ("equity", "allowed"),
    [("150.01", True), ("500", True), ("1000", True), ("1000.01", False)],
)
def test_account_gate_enforces_configured_equity_ceiling(equity: str, allowed: bool) -> None:
    harness = valid_harness()
    original = harness.context.initial
    balance = Decimal(equity)
    initial = replace(
        original,
        account=replace(original.account, equity=balance, cash=balance),
        portfolio=replace(original.portfolio, equity=balance, cash=balance),
        projection=replace(original.projection, equity=balance, cash=balance - Decimal("1.10")),
    )

    result = harness.engine.evaluate_initial(initial)
    account_check = next(
        check for check in result.checks if check.code == PretradeCheckCode.ACCOUNT_ALLOWLIST
    )

    assert account_check.allowed is allowed
    assert result.allowed is allowed
    assert initial.projection.authorized_risk_equity == Decimal("100")


@pytest.mark.parametrize(
    ("created_at", "expires_at"),
    [
        (NOW + timedelta(microseconds=1), NOW + timedelta(minutes=5)),
        (NOW - timedelta(minutes=5), NOW),
    ],
)
def test_future_or_expired_intent_is_denied_by_live_authorization(
    created_at: datetime,
    expires_at: datetime,
) -> None:
    harness = valid_harness()
    intent = replace(
        harness.context.initial.intent,
        created_at=created_at,
        expires_at=expires_at,
    )
    initial = replace(harness.context.initial, intent=intent)

    result = harness.engine.evaluate_initial(initial)
    live = {check.code: check for check in result.checks}[PretradeCheckCode.LIVE_AUTHORIZATION]

    assert not result.allowed
    assert not live.allowed
    assert live.reason == "live_authorization_denied"


def test_multiple_failures_are_all_reported() -> None:
    harness = valid_harness()
    context = with_dirty_reconciliation(with_kill_switch(with_unhealthy_broker(harness.context)))
    result = harness.engine.evaluate_final(context)

    denied = {check.code for check in result.checks if not check.allowed}
    assert PretradeCheckCode.KILL_SWITCH in denied
    assert PretradeCheckCode.BROKER_HEALTH in denied
    assert PretradeCheckCode.RECONCILIATION in denied
    assert len(result.checks) == 24


def test_paper_mode_marks_only_lease_requirement_not_applicable() -> None:
    loaded = load_config(
        base_path=CONFIGS / "base.yaml",
        mode_path=CONFIGS / "paper.yaml",
        safety_path=CONFIGS / "safety-envelope.yaml",
        environ={},
    )
    initial = replace(
        valid_initial_context(loaded.config_hash),
        live_lease=None,
        runtime_state=RuntimeState.PAUSED,
        strategy_eligibility=replace(
            valid_initial_context(loaded.config_hash).strategy_eligibility,
            config_hash=loaded.config_hash,
        ),
    )
    engine = PretradeEngine(
        loaded.config,
        config_hash=loaded.config_hash,
        account_allowlist=(ACCOUNT_ID,),
        active_code_hash=CODE_HASH,
        clock=CLOCK,
    )
    result = engine.evaluate_initial(initial)
    live_check = result.checks[0]

    assert result.allowed
    assert live_check.code == PretradeCheckCode.LIVE_AUTHORIZATION
    assert live_check.allowed
    assert live_check.reason == "not_applicable_non_live_mode"


def test_cost_estimate_is_factory_only_and_binds_intent_quote_and_hash() -> None:
    _, config_hash = live_config()
    intent = order_intent(config_hash)
    current_quote = quote()
    estimate = costs(intent, current_quote)

    with pytest.raises(TypeError, match="from_quote"):
        ExecutionCostEstimate()
    assert estimate.intent_id == intent.id
    assert estimate.instrument_id == current_quote.instrument_id
    assert estimate.quote_data_hash == current_quote.data_hash
    assert estimate.quantity == intent.quantity


def test_reduce_only_exit_survives_entry_loss_and_activity_blocks() -> None:
    harness = exit_harness()
    result = harness.engine.evaluate_final(harness.context)
    checks = {check.code: check for check in result.checks}

    assert result.allowed
    assert checks[PretradeCheckCode.LOSS_LIMITS].reason == "daily_loss_limit_reached"
    assert checks[PretradeCheckCode.ACTIVITY_LIMITS].reason == ("not_applicable_reduce_only_exit")
    assert checks[PretradeCheckCode.BUYING_POWER].reason == ("not_applicable_reduce_only_exit")


def test_reduce_only_exit_bypasses_entry_symbol_allowlist_policy() -> None:
    harness = exit_harness()
    context = with_initial(
        harness.context,
        instrument=replace(harness.context.initial.instrument, symbol="REMOVED-USD"),
        eligibility=replace(
            harness.context.initial.eligibility,
            symbol_allowlisted=False,
            asset_policy_eligible=False,
        ),
    )

    result = harness.engine.evaluate_final(context)
    symbol = {check.code: check for check in result.checks}[PretradeCheckCode.SYMBOL_TRADABILITY]

    assert result.allowed
    assert symbol.allowed
    assert symbol.reason == "symbol_tradable"


def test_exit_is_denied_when_it_can_exceed_the_owned_position() -> None:
    harness = exit_harness()
    position = harness.context.initial.portfolio.positions[0]
    context = with_initial(
        harness.context,
        portfolio=replace(
            harness.context.initial.portfolio,
            positions=(
                replace(
                    position,
                    quantity=Decimal("0.05"),
                    market_value=Decimal("0.50"),
                ),
            ),
        ),
    )
    result = harness.engine.evaluate_final(context)

    assert not result.allowed
    assert not {check.code: check for check in result.checks}[PretradeCheckCode.EXIT_POLICY].allowed


def test_drawdown_hard_stop_blocks_a_new_exit_intent() -> None:
    harness = exit_harness()
    context = with_initial(
        harness.context,
        losses=replace(
            harness.context.initial.losses,
            peak_to_trough_drawdown_pct=Decimal("10"),
        ),
    )
    result = harness.engine.evaluate_final(context)
    loss_check = {check.code: check for check in result.checks}[PretradeCheckCode.LOSS_LIMITS]

    assert not result.allowed
    assert not loss_check.allowed
    assert loss_check.reason == "drawdown_limit_reached"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("instrument_id", ""),
        ("symbol_allowlisted", 1),
        ("asset_policy_eligible", 1),
        ("provider_restriction_clear", 1),
        ("fractional_eligibility_verified", 1),
        ("earnings_restriction_clear", 1),
        ("session_order_type_eligible", 1),
        ("exit_policy_monitorable", 1),
        ("average_daily_dollar_volume_usd", Decimal("-1")),
        ("observed_at", NOW.replace(tzinfo=None)),
        ("evidence_hash", "invalid"),
    ],
)
def test_instrument_eligibility_rejects_invalid_evidence(
    field: str,
    value: object,
) -> None:
    with pytest.raises((DomainValidationError, InvalidDecimal)):
        eligibility(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("slippage_pct", Decimal("101")),
        ("fees_usd", Decimal("-1")),
        ("commission_usd", Decimal("-1")),
        ("expected_gross_edge_usd", Decimal("NaN")),
        ("expected_reward_usd", Decimal("-1")),
        ("initial_risk_usd", Decimal("-1")),
        ("verified", 1),
        ("observed_at", NOW.replace(tzinfo=None)),
        ("data_hash", "invalid"),
    ],
)
def test_cost_factory_rejects_invalid_evidence(field: str, value: object) -> None:
    _, config_hash = live_config()

    with pytest.raises((DomainValidationError, InvalidDecimal)):
        costs(order_intent(config_hash), quote(), **{field: value})


def test_cost_factory_rejects_noncanonical_dependencies_and_time_travel() -> None:
    _, config_hash = live_config()
    intent = order_intent(config_hash)
    current_quote = quote()
    values: dict[str, object] = {
        "intent": intent,
        "quote": current_quote,
        "slippage_pct": Decimal("0"),
        "fees_usd": Decimal("0"),
        "commission_usd": Decimal("0"),
        "expected_gross_edge_usd": Decimal("0"),
        "expected_reward_usd": Decimal("0"),
        "initial_risk_usd": Decimal("0"),
        "verified": True,
        "observed_at": current_quote.observed_at,
        "data_hash": DATA_HASH,
    }
    for field in ("intent", "quote"):
        invalid = dict(values)
        invalid[field] = object()
        with pytest.raises(DomainValidationError):
            ExecutionCostEstimate.from_quote(**invalid)  # type: ignore[arg-type]

    with pytest.raises(DomainValidationError, match="predate"):
        ExecutionCostEstimate.from_quote(
            **{
                **values,
                "observed_at": current_quote.observed_at - timedelta(microseconds=1),
            }  # type: ignore[arg-type]
        )


def test_cost_factory_rejects_unbounded_order_arithmetic_inputs() -> None:
    _, config_hash = live_config()
    intent = order_intent(config_hash)

    with pytest.raises(InvalidDecimal, match="safe Decimal arithmetic bounds"):
        costs(
            replace(intent, quantity=Decimal("1E+10000")),
            quote(),
        )
    with pytest.raises(InvalidDecimal, match="safe Decimal arithmetic bounds"):
        costs(
            intent,
            quote(ask=Decimal("1E+10000")),
        )


def test_contexts_are_immutable_and_reject_noncanonical_dependencies() -> None:
    harness = valid_harness()

    with pytest.raises(FrozenInstanceError):
        harness.context.initial.kill_switch_active = True  # type: ignore[misc]
    with pytest.raises(DomainValidationError):
        replace(harness.context.initial, intent=object())  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError):
        replace(harness.context.initial, open_orders=(object(),))  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError):
        replace(
            harness.context.initial,
            local_pending_intents=(object(),),  # type: ignore[arg-type]
        )
    with pytest.raises(DomainValidationError):
        replace(harness.context.initial, live_lease=object())  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError):
        FinalPretradeContext(
            initial=object(),  # type: ignore[arg-type]
            reviewed_order=harness.context.reviewed_order,
        )
    with pytest.raises(DomainValidationError):
        FinalPretradeContext(
            initial=harness.context.initial,
            reviewed_order=object(),  # type: ignore[arg-type]
        )


def test_engine_rejects_invalid_construction_and_evaluation_inputs() -> None:
    harness = valid_harness()
    config = harness.config
    values: dict[str, object] = {
        "config": config,
        "config_hash": harness.config_hash,
        "account_allowlist": (ACCOUNT_ID,),
        "active_code_hash": CODE_HASH,
        "clock": CLOCK,
    }
    cases = (
        {"config": object()},
        {"config_hash": "invalid"},
        {"active_code_hash": "invalid"},
        {"clock": object()},
        {"account_allowlist": [ACCOUNT_ID]},
        {"account_allowlist": (ACCOUNT_ID, ACCOUNT_ID)},
        {"account_allowlist": ("",)},
    )
    for overrides in cases:
        invalid = dict(values)
        invalid.update(overrides)
        with pytest.raises(DomainValidationError):
            PretradeEngine(**invalid)  # type: ignore[arg-type]

    unsafe_runtime = config.runtime.model_copy(update={"start_paused": "invalid"})
    unsafe_config = config.model_copy(update={"runtime": unsafe_runtime})
    with pytest.raises(DomainValidationError, match="canonical revalidation"):
        PretradeEngine(
            unsafe_config,
            config_hash=harness.config_hash,
            account_allowlist=(ACCOUNT_ID,),
            active_code_hash=CODE_HASH,
            clock=CLOCK,
        )
    unsafe_activity = config.activity.model_copy(
        update={"max_order_notional_usd": Decimal("1E+10000")}
    )
    unsafe_decimal_config = config.model_copy(update={"activity": unsafe_activity})
    with pytest.raises(InvalidDecimal, match="safe Decimal arithmetic bounds"):
        PretradeEngine(
            unsafe_decimal_config,
            config_hash=harness.config_hash,
            account_allowlist=(ACCOUNT_ID,),
            active_code_hash=CODE_HASH,
            clock=CLOCK,
        )
    with pytest.raises(DomainValidationError):
        harness.engine.evaluate_initial(object())  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError):
        harness.engine.evaluate_final(object())  # type: ignore[arg-type]


def test_unbound_projection_denies_every_dependent_exposure_check() -> None:
    harness = valid_harness()
    context = with_initial(
        harness.context,
        projection=replace(
            harness.context.initial.projection,
            account_id=AccountId("other-account"),
        ),
    )
    result = harness.engine.evaluate_final(context)
    checks = {check.code: check for check in result.checks}

    for code in (
        PretradeCheckCode.CASH_RESERVE,
        PretradeCheckCode.POSITION_CAP,
        PretradeCheckCode.CORRELATION_CAP,
        PretradeCheckCode.CRYPTO_CAP,
    ):
        assert not checks[code].allowed


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("intent_id", OrderIntentId("other-intent")),
        ("asset_class", AssetClass.EQUITY),
        ("correlation_group", "other-group"),
    ],
)
def test_projection_provenance_mismatch_denies_dependent_exposure_checks(
    field: str,
    value: object,
) -> None:
    harness = valid_harness()
    context = with_initial(
        harness.context,
        projection=replace(
            harness.context.initial.projection,
            **{field: value},  # type: ignore[arg-type]
        ),
    )
    result = harness.engine.evaluate_final(context)
    checks = {check.code: check for check in result.checks}

    for code in (
        PretradeCheckCode.CASH_RESERVE,
        PretradeCheckCode.POSITION_CAP,
        PretradeCheckCode.CORRELATION_CAP,
        PretradeCheckCode.CRYPTO_CAP,
    ):
        assert not checks[code].allowed


def test_unbound_loss_activity_and_cost_evidence_fail_closed() -> None:
    harness = valid_harness()
    quote_with_other_hash = replace(harness.context.initial.quote, data_hash=DataHash("1" * 64))
    unbound_costs = costs(harness.context.initial.intent, quote_with_other_hash)
    context = with_initial(
        harness.context,
        losses=replace(
            harness.context.initial.losses,
            account_id=AccountId("other-account"),
        ),
        activity=replace(
            harness.context.initial.activity,
            instrument_id=InstrumentId("other-instrument"),
        ),
        costs=unbound_costs,
    )
    result = harness.engine.evaluate_final(context)
    checks = {check.code: check for check in result.checks}

    for code in (
        PretradeCheckCode.LOSS_LIMITS,
        PretradeCheckCode.ACTIVITY_LIMITS,
        PretradeCheckCode.BUYING_POWER,
        PretradeCheckCode.POSITION_CAP,
        PretradeCheckCode.SPREAD,
        PretradeCheckCode.SLIPPAGE,
        PretradeCheckCode.AFTER_COST_EDGE,
    ):
        assert not checks[code].allowed


def test_missing_asset_class_buying_power_is_an_explicit_denial() -> None:
    harness = valid_harness()
    context = with_initial(
        harness.context,
        account=replace(harness.context.initial.account, buying_power=()),
    )
    result = harness.engine.evaluate_final(context)
    buying_power = {check.code: check for check in result.checks}[PretradeCheckCode.BUYING_POWER]

    assert not buying_power.allowed
    assert buying_power.reason == "authoritative_buying_power_unavailable"


def test_exact_quote_age_boundary_is_allowed_and_one_microsecond_more_is_denied() -> None:
    harness = valid_harness()
    boundary_quote = replace(
        harness.context.initial.quote,
        observed_at=NOW - timedelta(seconds=5),
    )
    boundary = with_initial(
        harness.context,
        quote=boundary_quote,
        costs=costs(harness.context.initial.intent, boundary_quote),
    )
    stale_quote = replace(
        boundary_quote, observed_at=boundary_quote.observed_at - timedelta(microseconds=1)
    )
    stale = with_initial(
        harness.context,
        quote=stale_quote,
        costs=costs(harness.context.initial.intent, stale_quote),
    )

    boundary_result = harness.engine.evaluate_initial(boundary.initial)
    stale_result = harness.engine.evaluate_initial(stale.initial)
    boundary_check = {check.code: check for check in boundary_result.checks}[
        PretradeCheckCode.MARKET_DATA_FRESHNESS
    ]
    stale_check = {check.code: check for check in stale_result.checks}[
        PretradeCheckCode.MARKET_DATA_FRESHNESS
    ]

    assert boundary_check.allowed
    assert not stale_check.allowed


def test_trusted_clock_is_captured_once_and_caller_time_cannot_revive_stale_data() -> None:
    @dataclass(slots=True)
    class CountingClock:
        current: datetime
        calls: int = 0

        def now(self) -> datetime:
            self.calls += 1
            return self.current

    harness = valid_harness()
    clock = CountingClock(NOW)
    engine = PretradeEngine(
        harness.config,
        config_hash=harness.config_hash,
        account_allowlist=(ACCOUNT_ID,),
        active_code_hash=CODE_HASH,
        clock=clock,
    )
    claimed_time = NOW - timedelta(seconds=6)
    stale_quote = replace(harness.context.initial.quote, observed_at=claimed_time)
    initial = replace(
        harness.context.initial,
        quote=stale_quote,
        costs=costs(harness.context.initial.intent, stale_quote),
        losses=replace(harness.context.initial.losses, observed_at=claimed_time),
        activity=replace(harness.context.initial.activity, observed_at=claimed_time),
        projection=replace(harness.context.initial.projection, observed_at=claimed_time),
        observed_at=claimed_time,
    )
    context = replace(harness.context, initial=initial)

    result = engine.evaluate_final(context)
    freshness = {check.code: check for check in result.checks}[
        PretradeCheckCode.MARKET_DATA_FRESHNESS
    ]

    assert clock.calls == 1
    assert result.evaluated_at == NOW
    assert all(check.observed_at == NOW for check in result.checks)
    assert not freshness.allowed


def test_review_missing_from_corrupted_final_context_fails_closed() -> None:
    harness = valid_harness()
    object.__setattr__(harness.context, "reviewed_order", None)
    result = harness.engine.evaluate_final(harness.context)
    review = {check.code: check for check in result.checks}[PretradeCheckCode.REVIEW_MATCH]

    assert not result.allowed
    assert not review.allowed
    assert review.reason == "review_missing"


def test_evaluation_is_independent_of_process_decimal_precision() -> None:
    harness = valid_harness()

    with localcontext() as context:
        context.prec = 2
        result = harness.engine.evaluate_final(harness.context)

    assert result.allowed
    assert all(check.allowed for check in result.checks)


def test_review_hash_builder_rejects_invalid_inputs_and_supports_no_client_id() -> None:
    _, config_hash = live_config()
    intent = order_intent(config_hash)

    with pytest.raises(DomainValidationError):
        canonical_review_payload_sha256(object(), client_order_id=None)  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError):
        canonical_review_payload_sha256(intent, client_order_id=ClientOrderId(""))
    assert len(canonical_review_payload_sha256(intent, client_order_id=None)) == 64


def test_equity_context_uses_equity_filters_and_spread_policy() -> None:
    harness = equity_harness()
    result = harness.engine.evaluate_final(harness.context)

    assert result.allowed
    low_volume = with_initial(
        harness.context,
        eligibility=replace(
            harness.context.initial.eligibility,
            average_daily_dollar_volume_usd=Decimal("49999999"),
        ),
    )
    denied = harness.engine.evaluate_final(low_volume)
    symbol = {check.code: check for check in denied.checks}[PretradeCheckCode.SYMBOL_TRADABILITY]
    assert not symbol.allowed


def test_prediction_pretrade_is_allowed_only_in_non_live_simulation_context() -> None:
    harness = prediction_simulation_harness()
    result = harness.engine.evaluate_final(harness.context)

    assert result.allowed
    assert result.checks[0].reason == "not_applicable_non_live_mode"


def test_stop_reference_price_is_used_for_review_and_broker_minimums() -> None:
    harness = valid_harness()
    intent = replace(
        harness.context.initial.intent,
        order_type=OrderType.STOP_LOSS,
        limit_price=None,
        stop_price=Decimal("10.00"),
    )
    rebuilt = with_initial(
        harness.context,
        intent=intent,
        costs=costs(intent, harness.context.initial.quote),
    )
    rebuilt = replace(
        rebuilt,
        reviewed_order=reviewed_order(
            intent,
            estimated_notional=Decimal("1"),
        ),
    )
    result = harness.engine.evaluate_final(rebuilt)

    assert result.allowed


def test_entry_market_order_is_denied_while_broker_minimums_still_evaluate() -> None:
    harness = valid_harness()
    intent = replace(
        harness.context.initial.intent,
        order_type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
    )
    rebuilt = with_initial(
        harness.context,
        intent=intent,
        costs=costs(intent, harness.context.initial.quote),
    )
    rebuilt = replace(
        rebuilt,
        reviewed_order=reviewed_order(intent),
    )
    result = harness.engine.evaluate_final(rebuilt)
    checks = {check.code: check for check in result.checks}

    assert not result.allowed
    assert not checks[PretradeCheckCode.MARKET_SESSION].allowed
    assert checks[PretradeCheckCode.BROKER_MINIMUMS].allowed


def test_unbounded_broker_metadata_fails_closed_without_decimal_exception() -> None:
    harness = valid_harness()
    context = with_initial(
        harness.context,
        instrument=replace(
            harness.context.initial.instrument,
            quantity_increment=Decimal("1E-10000"),
            minimum_notional=Decimal("1E+10000"),
        ),
    )

    result = harness.engine.evaluate_final(context)
    broker_minimums = {check.code: check for check in result.checks}[
        PretradeCheckCode.BROKER_MINIMUMS
    ]

    assert not result.allowed
    assert not broker_minimums.allowed
    assert broker_minimums.configured_limit == "outside_safe_decimal_bounds"


def test_exit_market_order_is_denied_by_emergency_market_policy() -> None:
    harness = exit_harness()
    intent = replace(
        harness.context.initial.intent,
        order_type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
    )
    rebuilt = with_initial(
        harness.context,
        intent=intent,
        costs=costs(
            intent,
            harness.context.initial.quote,
            expected_gross_edge_usd=Decimal("0"),
            expected_reward_usd=Decimal("0"),
            initial_risk_usd=Decimal("0"),
        ),
    )
    rebuilt = replace(
        rebuilt,
        reviewed_order=reviewed_order(
            intent,
            estimated_notional=Decimal("1"),
        ),
    )
    result = harness.engine.evaluate_final(rebuilt)

    assert not result.allowed
    assert not {check.code: check for check in result.checks}[
        PretradeCheckCode.MARKET_SESSION
    ].allowed
