"""Fictional daily observations exercise owned accounting, never actual strategy results."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext

import pytest

from trading_bot.market_data.stock_economic_evidence import StockCashDividendEvent
from trading_bot.research.hybrid_policies import CalendarSession
from trading_bot.research.hybrid_strategies import PriceBar

D = Decimal
STAMP = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
HASH = "a" * 64


def fixture(
    *,
    count=225,
    stocks=4,
    closes=None,
    signals=None,
    long_stocks=False,
    dividends=(),
    directives=(),
    funding=(),
    settlement_status=None,
    missing_sector=False,
):
    from trading_bot.research.stock_economic_replay import (
        ModeledAsset,
        SettlementDay,
        make_fictional_replay_inputs,
    )

    times, day = [], STAMP
    while len(times) < count + 12:
        if day.weekday() < 5:
            times.append(day)
        day += timedelta(days=1)
    calendar = tuple(
        CalendarSession(i, t, t + timedelta(hours=6, minutes=30)) for i, t in enumerate(times)
    )
    assets = []
    for slot, symbol in enumerate(("SPY", *(f"S{i}" for i in range(stocks)))):
        price_values = ("100",) * count if closes is None else closes.get(symbol, ("100",) * count)
        bars = tuple(
            PriceBar(calendar[i].closes_at, D(price_values[i]), D(price_values[i]))
            for i in range(count)
        )
        active = (
            tuple(i >= 199 for i in range(count))
            if signals is None
            else signals.get(symbol, (False,) * count)
        )
        assets.append(
            ModeledAsset(
                symbol,
                "passive_comparison" if slot == 0 else "stock_candidate",
                None if missing_sector and slot else f"sector-{slot}",
                D(50000000),
                True,
                calendar[0].closes_at,
                bars,
                active,
            )
        )
    settlement = []
    current = times[0].date()
    while current <= times[-1].date():
        status = "ordinary_supported" if current.weekday() < 5 else "closed"
        if settlement_status is not None:
            status = settlement_status.get(current, status)
        settlement.append(SettlementDay(current, status, HASH))
        current += timedelta(days=1)
    allocation = (("S0", D(".10")),) if long_stocks else (("SPY", D(".75")),)
    return make_fictional_replay_inputs(
        tuple(assets),
        calendar,
        tuple(settlement),
        long_term_allocations=allocation,
        dividends=dividends,
        execution_directives=directives,
        dividend_funding_days=funding,
        calendar_source_hash=HASH,
    )


def begin(inputs=None, **settings):
    from trading_bot.research.stock_economic_replay import (
        StockEconomicReplayProtocol,
        begin_stock_economic_replay,
    )

    return begin_stock_economic_replay(
        fixture() if inputs is None else inputs, StockEconomicReplayProtocol(**settings)
    )


def through(state, last):
    from trading_bot.research.stock_economic_replay import advance_stock_economic_session

    while state.next_session <= last:
        state = advance_stock_economic_session(state, session_index=state.next_session)
    return state


def test_initial_account_has_one_cash_owner_and_next_open_intents():
    original = begin()
    assert original.book.account.cash == D(1000)
    assert original.book.account.lots == original.book.account.orders == ()
    assert original.book.account.paused is True
    assert original.next_session == 200
    assert original.snapshots[-1].session_index == 199
    assert sum((intent.cash_budget for intent in original.pending), D(0)) <= D(900)
    entered = through(original, 200)
    assert any(
        lot.symbol == "SPY" and lot.sleeve == "long_term" for lot in entered.book.account.lots
    )
    assert any(lot.symbol == "S0" and lot.sleeve == "tactical" for lot in entered.book.account.lots)
    assert all(
        fill.at == original.inputs.calendar[200].opens_at for fill in entered.book.account.fills
    )
    assert entered.book.account.cash >= entered.snapshots[-1].gross_equity * D(".10")


def test_stock_long_term_targets_are_supported_and_same_symbol_tactical_overlap_is_denied():
    result = through(begin(fixture(long_stocks=True)), 200)
    owned = tuple(lot for lot in result.book.account.lots if lot.symbol == "S0")
    assert owned and all(lot.sleeve == "long_term" for lot in owned)
    assert any(record.reason == "overlapping_symbol" for record in result.records)
    assert result.quality_selection_implemented is False


def test_missing_sector_denies_stock_entry_without_inventing_a_quote():
    result = through(begin(fixture(missing_sector=True)), 200)
    assert all(lot.symbol == "SPY" for lot in result.book.account.lots)
    assert any(record.reason == "modeled_risk_inputs_unavailable" for record in result.records)


def test_tactical_caps_fees_and_lot_basis_are_conserved():
    result = through(begin(), 200)
    snapshot = result.snapshots[-1]
    assert snapshot.tactical_value <= snapshot.gross_equity * D(".15")
    assert all(lot.basis > lot.quantity * D(100) for lot in result.book.account.lots)
    assert result.book.account.cash + sum(
        (lot.basis for lot in result.book.account.lots), D(0)
    ) == D(1000)
    assert result.book.account.reserved_cash == 0
    assert result.book.account.fees > 0


@pytest.mark.parametrize(
    "method", ["principal", "partial", "trailing", "full_target", "fixed_holding"]
)
def test_all_declared_exit_models_use_owned_fills_and_keep_long_term_shares(method):
    count = 226
    path = ["100"] * count
    for index in range(201, count):
        path[index] = "125" if index < 206 else "115"
    closes = {f"S{i}": tuple(path) for i in range(8)}
    entered = through(
        begin(
            fixture(count=count, stocks=8, closes=closes),
            exit_method=method,
            slippage_bps=D(0),
            fee_usd=D(0),
        ),
        200,
    )
    spy_quantity = sum(
        (lot.quantity for lot in entered.book.account.lots if lot.symbol == "SPY"), D(0)
    )
    result = through(entered, count - 1)
    # Settled tactical proceeds may restore the long-term target; profit exits
    # must never reduce those original long-term shares.
    assert (
        sum((lot.quantity for lot in result.book.account.lots if lot.symbol == "SPY"), D(0))
        >= spy_quantity
    )
    assert any(record.side == "sell" and record.outcome == "filled" for record in result.records)
    assert all(
        order.sleeve == "tactical" for order in result.book.account.orders if order.side == "sell"
    )


def test_principal_proceeds_are_not_recorded_as_realized_gain():
    path = ("100",) * 201 + ("116",) * 4
    data = fixture(count=205, stocks=8, closes={f"S{i}": path for i in range(8)})
    result = through(
        begin(data, exit_method="principal", slippage_bps=D(0), fee_usd=D(0), tax_rate=D(".25")),
        203,
    )
    sales = tuple(
        record for record in result.records if record.side == "sell" and record.outcome == "filled"
    )
    assert sales and all(record.proceeds > record.realized_gain > 0 for record in sales)
    with localcontext() as ctx:
        ctx.prec = 50
        assert result.book.account.realized_gain == sum(
            (record.realized_gain for record in sales), D(0)
        )
        assert result.book.account.tax_reserve == result.book.account.realized_gain * D(".25")


def test_partial_exit_cancellation_resumes_original_rung_without_double_sale():
    from trading_bot.research.stock_economic_replay import ModeledExecutionDirective

    path = ("100",) * 201 + ("113",) * 5
    data = fixture(
        count=206,
        stocks=8,
        closes={f"S{i}": path for i in range(8)},
        directives=(ModeledExecutionDirective(202, "S0", D(".5")),),
    )
    partial = through(begin(data, exit_method="partial", slippage_bps=D(0), fee_usd=D(0)), 202)
    progress = next(p for p in partial.book.account.exit_progress if p.symbol == "S0")
    assert 0 < progress.filled < progress.target
    assert progress.threshold not in partial.book.account.completed_thresholds
    completed = through(partial, 203)
    updated = next(
        p for p in completed.book.account.exit_progress if p.threshold == progress.threshold
    )
    assert updated.filled == updated.target == D(".046875")
    assert completed.book.account.completed_thresholds.count(progress.threshold) == 1
    assert completed.book.account.reserved_cash == 0


def test_modeled_rejection_releases_reservation_and_cannot_create_a_lot():
    from trading_bot.research.stock_economic_replay import ModeledExecutionDirective

    result = through(
        begin(fixture(directives=(ModeledExecutionDirective(200, "S0", reject=True),))), 200
    )
    assert not any(lot.symbol == "S0" for lot in result.book.account.lots)
    assert result.book.account.reserved_cash == 0
    assert any(r.symbol == "S0" and r.outcome == "rejected" for r in result.records)


def test_sector_cap_is_shared_across_long_term_and_tactical_stock_allocations():
    data = fixture(stocks=8)
    data = replace(
        data,
        assets=tuple(
            replace(a, sector="shared-stock-sector") if a.role == "stock_candidate" else a
            for a in data.assets
        ),
        long_term_allocations=(("S0", D(".10")), ("S1", D(".10")), ("S2", D(".10"))),
    )
    result = through(begin(data), 200)
    snap = result.snapshots[-1]
    assert snap.long_term_value + snap.tactical_value <= snap.gross_equity * D(".25")


def test_future_modeled_risk_annotation_does_not_authorize_an_earlier_buy():
    data = fixture()
    data = replace(
        data,
        assets=tuple(
            replace(a, available_at=data.calendar[209].closes_at) if a.symbol == "S0" else a
            for a in data.assets
        ),
    )
    result = through(begin(data), 200)
    assert not any(lot.symbol == "S0" for lot in result.book.account.lots)
    assert any(
        r.symbol == "S0" and r.reason == "modeled_risk_inputs_unavailable" for r in result.records
    )


def test_sale_below_modeled_minimum_cannot_charge_more_than_its_proceeds():
    path = ("100",) * 201 + (".0001",) * 6
    result = through(begin(fixture(count=207, stocks=1, closes={"S0": path})), 203)
    assert any(r.reason == "below_modeled_sale_minimum" for r in result.records)
    assert not any(r.side == "sell" and r.outcome == "filled" for r in result.records)
    assert result.book.account.cash >= 0


def test_initial_stop_uses_execution_price_instead_of_fee_inclusive_tax_basis():
    entered = through(begin(fixture(stocks=8), slippage_bps=D(0), fee_usd=D(1)), 200)
    assert any(lot.sleeve == "tactical" for lot in entered.book.account.lots)
    assert not any(
        intent.side == "sell" and intent.reason == "initial_stop" for intent in entered.pending
    )


def test_pre_activation_dividend_cannot_be_silently_omitted_by_the_fixture_kernel():
    data = fixture(count=205)
    native = StockCashDividendEvent(
        id="preactivation",
        ticker="S0",
        cash_amount=D(1),
        currency="USD",
        ex_dividend_date=data.calendar[190].opens_at.date(),
        pay_date=data.calendar[195].opens_at.date(),
        record_date=None,
        declaration_date=data.calendar[189].opens_at.date(),
        distribution_type="recurring",
        frequency=4,
        received_at=datetime(2026, 10, 26, tzinfo=UTC),
        source_csv_sha256=HASH,
    )
    with pytest.raises(ValueError):
        begin(replace(data, dividends=(native,)))


def test_bank_closed_day_is_not_the_next_market_row_for_funding():
    data = fixture(count=212, stocks=1)
    closed = data.calendar[203].opens_at.date()
    signals = {"S0": tuple(199 <= i <= 200 for i in range(212))}
    data = fixture(count=212, stocks=1, signals=signals, settlement_status={closed: "closed"})
    result = through(begin(data, slippage_bps=D(0), fee_usd=D(0)), 202)
    sale = next(
        record for record in result.records if record.side == "sell" and record.outcome == "filled"
    )
    # Signal closes201, executes202. Advance from its trade date using supplied support.
    assert sale.settlement_at == data.calendar[205].opens_at
    assert result.book.account.settlements
    assert all(item.due_at > sale.at for item in result.book.account.settlements)


def test_unknown_settlement_support_blocks_a_sale_fill():
    data = fixture(count=210, stocks=1)
    signals = {"S0": tuple(199 <= i <= 200 for i in range(210))}
    unknown = data.calendar[203].opens_at.date()
    data = fixture(count=210, stocks=1, signals=signals, settlement_status={unknown: "unknown"})
    result = through(begin(data), 202)
    assert any(record.reason == "settlement_support_unavailable" for record in result.records)
    assert not any(
        record.side == "sell" and record.outcome == "filled" for record in result.records
    )


def test_dividend_right_uses_pre_ex_ownership_and_waits_for_available_cash():
    from trading_bot.research.stock_economic_replay import DividendFundingDay

    data = fixture(count=212, stocks=1)
    native = StockCashDividendEvent(
        id="fictional-dividend",
        ticker="S0",
        cash_amount=D(1),
        currency="USD",
        ex_dividend_date=data.calendar[201].opens_at.date(),
        pay_date=data.calendar[203].opens_at.date(),
        record_date=None,
        declaration_date=data.calendar[198].opens_at.date(),
        distribution_type="recurring",
        frequency=4,
        received_at=datetime(2026, 10, 26, tzinfo=UTC),
        source_csv_sha256=HASH,
    )
    funding = (
        DividendFundingDay(native.pay_date, "supported", HASH),
        DividendFundingDay(data.calendar[204].opens_at.date(), "supported", HASH),
    )
    data = fixture(count=212, stocks=1, dividends=(native,), funding=funding)
    accrued = through(begin(data), 201)
    assert accrued.book.gross_earned > 0
    assert accrued.book.gross_paid == 0
    assert accrued.snapshots[-1].receivable > 0
    paid = through(accrued, 204)
    assert paid.book.gross_paid == accrued.book.gross_earned
    assert paid.book.credited_events == (native.id,)


def test_new_signal_reenters_only_after_cooldown_and_settlement():
    signals = {"S0": tuple(i == 199 or i >= 208 for i in range(217))}
    result = through(
        begin(fixture(count=217, stocks=1, signals=signals), slippage_bps=D(0), fee_usd=D(0)), 213
    )
    entries = tuple(
        record
        for record in result.records
        if record.symbol == "S0" and record.side == "buy" and record.outcome == "filled"
    )
    assert len(entries) == 2
    assert entries[0].order_id != entries[1].order_id
    assert entries[1].at >= result.inputs.calendar[209].opens_at
    assert len(tuple(e for e in result.book.account.episodes if e.symbol == "S0")) == 2


def test_unchanged_signal_cannot_repurchase_after_a_risk_exit():
    path = ("100",) * 201 + ("90",) * 17
    result = through(begin(fixture(count=218, stocks=1, closes={"S0": path})), 217)
    entries = tuple(
        record
        for record in result.records
        if record.symbol == "S0" and record.side == "buy" and record.outcome == "filled"
    )
    assert len(entries) == 1


def test_drawdown_and_kill_switch_latch_without_selling_long_term():
    from trading_bot.research.stock_economic_replay import halt_stock_economic_replay

    path = ("100",) * 201 + ("80",) * 7
    dropped = through(begin(fixture(count=208, closes={"SPY": path})), 202)
    assert dropped.book.account.tactical_suspended is True
    assert dropped.book.account.weekly_review_required is True
    assert any(lot.symbol == "SPY" for lot in dropped.book.account.lots)
    halted = halt_stock_economic_replay(dropped)
    assert halted.book.account.kill_switch is True
    assert halted.pending == ()
    advanced = through(halted, 207)
    assert advanced.book.account.kill_switch is True
    assert len(advanced.book.account.fills) == len(halted.book.account.fills)


def test_prefix_future_mutation_resume_and_final_close_are_causal():
    from trading_bot.research.stock_economic_replay import finish_stock_economic_replay

    original = fixture(count=211)
    mutated_path = ("100",) * 206 + ("1000",) * 5
    changed = fixture(count=211, closes={"S0": mutated_path})
    left = through(begin(original), 205)
    right = through(begin(changed), 205)
    assert left.book.account == right.book.account
    assert left.records == right.records
    resumed = through(left, 210)
    full = through(begin(original), 210)
    assert resumed == full
    result = finish_stock_economic_replay(full)
    assert result.pending_final_intents == full.pending
    assert all(fill.at <= original.calendar[210].opens_at for fill in result.book.account.fills)
    assert result.full_task5_complete is False


def test_existing_50_200_policy_can_supply_causal_fictional_stock_signals():
    from trading_bot.research.hybrid_policies import (
        PolicyInput,
        SessionObservation,
        StrategyProposal,
        UniverseMembership,
        evaluate_policies,
    )

    data = fixture(count=205, stocks=1, closes={"S0": tuple(str(100 + i) for i in range(205))})
    stock = next(asset for asset in data.assets if asset.symbol == "S0")
    signals = [False] * 205
    held = False
    for index in range(199, 205):
        request = PolicyInput(
            sessions=data.calendar[: index + 2],
            observations=tuple(
                SessionObservation("S0", i, stock.bars[i], None) for i in range(index + 1)
            ),
            universe=(
                UniverseMembership(
                    "S0",
                    data.calendar[0].closes_at,
                    data.calendar[0].closes_at,
                    True,
                    "fictional-membership",
                ),
            ),
            information_at=stock.bars[index].completed_at,
            calendar_verified=True,
            held_positions=(("S0", "trend"),) if held else (),
        )
        outcome = next(value for value in evaluate_policies(request) if value.family == "trend")
        assert isinstance(outcome, StrategyProposal)
        held = (
            True if outcome.decision == "enter" else False if outcome.decision == "exit" else held
        )
        signals[index] = held
    composed = replace(
        data,
        assets=tuple(
            replace(asset, signals=tuple(signals)) if asset.symbol == "S0" else asset
            for asset in data.assets
        ),
    )
    result = through(begin(composed), 200)
    assert any(lot.symbol == "S0" and lot.sleeve == "tactical" for lot in result.book.account.lots)
    assert all(fill.at == data.calendar[200].opens_at for fill in result.book.account.fills)
    assert result.inputs.source_profile == "fictional_stock_economic_fixture_v1"


@pytest.mark.parametrize(
    "flag",
    ["qualified", "source_qualified", "investment_eligible", "live_authorized", "trading_enabled"],
)
def test_fictional_inputs_and_output_cannot_be_promoted(flag):
    from trading_bot.research.stock_economic_replay import finish_stock_economic_replay

    state = through(begin(), 224)
    for value in (state.inputs, state, finish_stock_economic_replay(state)):
        assert getattr(value, flag) is False
        with pytest.raises((ValueError, TypeError)):
            replace(value, **{flag: True})
        with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
            setattr(value, flag, True)
    assert state.inputs.source_profile == "fictional_stock_economic_fixture_v1"


def test_fixed_arithmetic_survives_hostile_ambient_context():
    ordinary = through(begin(), 204)
    with localcontext() as ctx:
        ctx.prec = 3
        ctx.rounding = ROUND_DOWN
        ctx.traps[Inexact] = True
        hostile = through(begin(), 204)
    assert hostile.book.account == ordinary.book.account
    assert hostile.records == ordinary.records
    assert hostile.evidence_hash == ordinary.evidence_hash


@pytest.mark.parametrize(
    "method,first_price,later_price", [("principal", "116", "116"), ("partial", "113", "112")]
)
def test_activated_partial_profit_rung_resumes_below_its_fresh_trigger(
    method, first_price, later_price
):
    from trading_bot.research.stock_economic_replay import ModeledExecutionDirective

    path = ("100",) * 201 + (first_price,) + (later_price,) * 4
    data = fixture(
        count=206,
        stocks=8,
        closes={f"S{i}": path for i in range(8)},
        directives=(ModeledExecutionDirective(202, "S0", D(".5")),),
    )
    partial = through(begin(data, exit_method=method, slippage_bps=D(0), fee_usd=D(0)), 202)
    progress = next(p for p in partial.book.account.exit_progress if p.symbol == "S0")
    assert 0 < progress.filled < progress.target
    assert any(p.symbol == "S0" and p.reason == "resume_owned_profit_rung" for p in partial.pending)
    completed = through(partial, 203)
    updated = next(
        p for p in completed.book.account.exit_progress if p.threshold == progress.threshold
    )
    assert updated.filled == updated.target == progress.target
    assert completed.book.account.completed_thresholds.count(progress.threshold) == 1
    episode = next(e for e in completed.book.account.episodes if e.symbol == "S0")
    remaining = sum(
        (lot.quantity for lot in completed.book.account.lots if lot.symbol == "S0"), D(0)
    )
    assert remaining + updated.filled == episode.original_quantity


def test_common_full_exit_precedes_an_unfinished_profit_rung_without_overselling():
    from trading_bot.research.stock_economic_replay import ModeledExecutionDirective

    path = ("100",) * 201 + ("116",) * 5
    signals = {f"S{i}": tuple(199 <= i <= 201 for i in range(206)) for i in range(8)}
    data = fixture(
        count=206,
        stocks=8,
        closes={f"S{i}": path for i in range(8)},
        signals=signals,
        directives=(ModeledExecutionDirective(202, "S0", D(".5")),),
    )
    partial = through(begin(data, slippage_bps=D(0), fee_usd=D(0)), 202)
    intent = next(p for p in partial.pending if p.symbol == "S0")
    assert intent.reason == "family_signal_exit"
    result = through(partial, 203)
    episode = next(e for e in result.book.account.episodes if e.symbol == "S0")
    sold = sum(
        (
            r.quantity
            for r in result.records
            if r.symbol == "S0" and r.side == "sell" and r.outcome == "filled"
        ),
        D(0),
    )
    assert sold == episode.original_quantity
    assert not any(lot.symbol == "S0" for lot in result.book.account.lots)


def test_known_two_leg_fees_alone_exceeding_initial_risk_budget_deny_entry():
    data = replace(fixture(stocks=1), long_term_allocations=())
    result = through(begin(data, slippage_bps=D(0), fee_usd=D("4.5")), 200)
    assert result.snapshots[0].gross_equity == D(1000)
    assert not any(r.symbol == "S0" and r.outcome == "filled" for r in result.records)
    assert result.book.account.cash == D(1000)


def test_initial_risk_quantity_includes_both_fees_and_adverse_sale_slippage():
    data = replace(fixture(stocks=1), long_term_allocations=())
    result = through(begin(data, slippage_bps=D(100), fee_usd=D(2)), 200)
    fill = next(r for r in result.records if r.symbol == "S0" and r.outcome == "filled")
    assert fill.price == D(101)
    assert fill.quantity == D(".166403")
    assert fill.quantity * D("6.0095") + D(4) == D("4.9999988285")


def test_ineligible_new_signals_do_not_dilute_an_eligible_stock_budget():
    one = through(begin(fixture(stocks=1), slippage_bps=D(0), fee_usd=D(0)), 200)
    data = fixture(stocks=15)
    data = replace(
        data,
        assets=tuple(
            replace(a, earnings_clear=None)
            if a.role == "stock_candidate" and a.symbol != "S0"
            else a
            for a in data.assets
        ),
    )
    screened = through(begin(data, slippage_bps=D(0), fee_usd=D(0)), 200)
    only_fill = next(r for r in one.records if r.symbol == "S0" and r.outcome == "filled")
    screened_fill = next(r for r in screened.records if r.symbol == "S0" and r.outcome == "filled")
    assert only_fill.quantity == screened_fill.quantity == D(".4")
    denied = tuple(r for r in screened.records if r.reason == "modeled_risk_inputs_unavailable")
    assert len(denied) == 14
    assert len(screened.inputs.assets) == 16


def test_missing_explicit_dividend_funding_support_stays_receivable():
    data = fixture(count=207, stocks=1)
    native = StockCashDividendEvent(
        id="no-funding-proof",
        ticker="S0",
        cash_amount=D(1),
        currency="USD",
        ex_dividend_date=data.calendar[201].opens_at.date(),
        pay_date=data.calendar[203].opens_at.date(),
        record_date=None,
        declaration_date=data.calendar[198].opens_at.date(),
        distribution_type="recurring",
        frequency=4,
        received_at=datetime(2026, 10, 26, tzinfo=UTC),
        source_csv_sha256=HASH,
    )
    result = through(begin(fixture(count=207, stocks=1, dividends=(native,))), 205)
    assert result.book.gross_earned > 0
    assert result.book.gross_paid == 0
    assert result.snapshots[-1].receivable == result.book.gross_earned


def funding_fixture():
    data = fixture(count=207, stocks=1)
    native = StockCashDividendEvent(
        id="separate-funding",
        ticker="S0",
        cash_amount=D(1),
        currency="USD",
        ex_dividend_date=data.calendar[201].opens_at.date(),
        pay_date=data.calendar[203].opens_at.date(),
        record_date=None,
        declaration_date=data.calendar[198].opens_at.date(),
        distribution_type="recurring",
        frequency=4,
        received_at=datetime(2026, 10, 26, tzinfo=UTC),
        source_csv_sha256=HASH,
    )
    return data, native


def test_dividend_funding_is_independent_of_no_cns_settlement_service():
    from trading_bot.research.stock_economic_replay import DividendFundingDay

    data, native = funding_fixture()
    candidate = data.calendar[204].opens_at.date()
    funding = (
        DividendFundingDay(native.pay_date, "supported", HASH),
        DividendFundingDay(candidate, "supported", HASH),
    )
    result = through(
        begin(
            fixture(
                count=207,
                stocks=1,
                dividends=(native,),
                funding=funding,
                settlement_status={native.pay_date: "closed", candidate: "closed"},
            )
        ),
        204,
    )
    assert result.book.gross_paid == result.book.gross_earned > 0
    assert result.book.entitlements[0].modeled_pay_available_at == data.calendar[204].opens_at


@pytest.mark.parametrize("which", ["native_pay_date", "candidate_open"])
@pytest.mark.parametrize("status", [None, "unknown", "unavailable", "contradictory"])
def test_missing_or_unsupported_dividend_funding_never_becomes_available(which, status):
    from trading_bot.research.stock_economic_replay import DividendFundingDay

    data, native = funding_fixture()
    candidate = data.calendar[204].opens_at.date()
    statuses = {native.pay_date: "supported", candidate: "supported"}
    changed = native.pay_date if which == "native_pay_date" else candidate
    if status is None:
        del statuses[changed]
    else:
        statuses[changed] = status
    # A later supported date must not bypass the book's exact first-open rule.
    statuses[data.calendar[205].opens_at.date()] = "supported"
    funding = tuple(DividendFundingDay(day, value, HASH) for day, value in sorted(statuses.items()))
    result = through(begin(fixture(count=207, stocks=1, dividends=(native,), funding=funding)), 205)
    assert result.book.gross_earned > 0
    assert result.book.gross_paid == 0
    assert result.book.entitlements[0].modeled_pay_available_at is None
    assert result.snapshots[-1].receivable == result.book.gross_earned


def test_duplicate_or_mutable_dividend_funding_table_fails_begin_validation():
    from trading_bot.research.stock_economic_replay import DividendFundingDay

    data, native = funding_fixture()
    supported = DividendFundingDay(native.pay_date, "supported", HASH)
    for funding in ((supported, replace(supported, status="contradictory")), [supported]):
        with pytest.raises(ValueError):
            begin(replace(data, dividend_funding_days=funding))


def half_profit_rung_at_known_close(current_close, *, method="principal"):
    from trading_bot.research.stock_economic_replay import ModeledExecutionDirective

    first_price = "116" if method == "principal" else "113"
    path = ("100",) * 201 + (first_price,) * 5
    data = fixture(
        count=206,
        stocks=8,
        closes={f"S{i}": path for i in range(8)},
        directives=(ModeledExecutionDirective(202, "S0", D(".5")),),
    )
    assets = []
    for asset in data.assets:
        if asset.symbol != "S0":
            assets.append(asset)
            continue
        # The original half fill occurs at first_price at open202; the lower
        # closing observation is already known when the next intent is planned.
        bars = tuple(
            replace(bar, open=D(first_price), close=D(current_close))
            if i == 202
            else replace(bar, open=D(current_close), close=D(current_close))
            if i > 202
            else bar
            for i, bar in enumerate(asset.bars)
        )
        assets.append(replace(asset, bars=bars))
    data = replace(data, assets=tuple(assets))
    return through(begin(data, exit_method=method, slippage_bps=D(0), fee_usd=D(0)), 202)


def test_principal_resume_pauses_when_known_close_has_no_current_surplus():
    state = half_profit_rung_at_known_close("104")
    progress = next(p for p in state.book.account.exit_progress if p.symbol == "S0")
    episode = next(e for e in state.book.account.episodes if e.symbol == "S0")
    owned = sum((lot.quantity for lot in state.book.account.lots if lot.symbol == "S0"), D(0))
    assert owned * D(104) == D("18.155176") < episode.original_cash == D("18.75")
    assert not any(intent.symbol == "S0" for intent in state.pending)
    advanced = through(state, 203)
    assert (
        next(p for p in advanced.book.account.exit_progress if p.threshold == progress.threshold)
        == progress
    )
    assert progress.threshold not in advanced.book.account.completed_thresholds


def test_principal_resume_caps_known_surplus_without_resetting_owned_target():
    state = half_profit_rung_at_known_close("110")
    progress = next(p for p in state.book.account.exit_progress if p.symbol == "S0")
    intent = next(p for p in state.pending if p.symbol == "S0")
    assert intent.exit_order.quantity == D(".004114")
    assert progress.target - progress.filled == D(".012931")
    # Existing modeled minimum blocks this sub-dollar proposal; it cannot invent
    # completed shares or a lower principal allocation to make it executable.
    advanced = through(state, 203)
    assert any(
        r.symbol == "S0" and r.reason == "below_modeled_sale_minimum" for r in advanced.records
    )
    assert (
        next(p for p in advanced.book.account.exit_progress if p.threshold == progress.threshold)
        == progress
    )
    assert next(e for e in advanced.book.account.episodes if e.symbol == "S0").original_cash == D(
        "18.75"
    )


def test_principal_current_surplus_cap_can_fill_without_selling_below_known_allocation():
    state = half_profit_rung_at_known_close("114")
    intent = next(p for p in state.pending if p.symbol == "S0")
    assert intent.exit_order.quantity == D(".010095")
    result = through(state, 203)
    owned = sum((lot.quantity for lot in result.book.account.lots if lot.symbol == "S0"), D(0))
    assert owned * D(114) == D("18.750036")
    progress = next(p for p in result.book.account.exit_progress if p.symbol == "S0")
    assert progress.target == D(".025862")
    assert progress.filled == D(".023026") < progress.target


def test_unchanged_principal_surplus_and_partial_percentage_rungs_keep_owned_remainders():
    principal = half_profit_rung_at_known_close("116")
    assert next(p for p in principal.pending if p.symbol == "S0").exit_order.quantity == D(
        ".012931"
    )
    completed = through(principal, 203)
    progress = next(p for p in completed.book.account.exit_progress if p.symbol == "S0")
    assert progress.filled == progress.target == D(".025862")
    partial = half_profit_rung_at_known_close("104", method="partial")
    assert next(p for p in partial.pending if p.symbol == "S0").exit_order.quantity == D(".023438")
    completed_partial = through(partial, 203)
    fixed_rung = next(p for p in completed_partial.book.account.exit_progress if p.symbol == "S0")
    assert fixed_rung.filled == fixed_rung.target == D(".046875")
