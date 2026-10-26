"""Fictional dimensionless paths establish mechanics, never investment evidence."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext

import pytest

from trading_bot.research.hybrid_backtest import compare_returns
from trading_bot.research.hybrid_strategies import PriceBar

D = Decimal
START = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)


def sample(prices):
    opens = tuple(START + timedelta(days=i) for i in range(len(prices)))
    bars = tuple(
        PriceBar(opened + timedelta(hours=6, minutes=30), D(o), D(c))
        for opened, (o, c) in zip(opens, prices, strict=True)
    )
    return bars, opens


def trace(prices, targets, *, bps="0", terminal="liquidate"):
    from trading_bot.research.stock_price_trace import trace_price_targets

    bars, opens = sample(prices)
    return trace_price_targets(
        bars,
        opens,
        tuple(D(t) for t in targets),
        one_way_cost_bps=D(bps),
        terminal_policy=terminal,
    )


def test_trace_rejects_more_than_ten_thousand_sessions():
    with pytest.raises(ValueError):
        trace((("100", "100"),) * 10001, ("0",) * 10001)


def test_flat_round_trip_charges_multiplicative_nav_haircuts():
    result = trace((("100", "100"),) * 3, ("1", "0", "1"), bps="100")
    assert result.rows[0].nav == D("1")
    assert result.rows[1].nav == D("0.99")
    assert result.rows[2].nav == D("0.9801")
    assert result.rows[1].trade_cost == D("0.01")
    assert result.rows[2].trade_cost == D("0.0099")
    assert result.rows[2].terminal_cost == 0
    assert result.pending_target == D("1")


def test_prior_close_signal_executes_at_next_open_and_carries_gap():
    result = trace(
        (("100", "100"), ("200", "220"), ("110", "500")),
        ("1", "0", "1"),
    )
    assert result.rows[0].executed_target is None
    assert result.rows[1].executed_target == D("1")
    assert result.rows[1].nav == D("1.1")
    assert result.rows[2].opening_nav == D("0.55")
    assert result.rows[2].nav == D("0.55")
    assert result.rows[2].executed_target == D("0")


def test_final_signal_cannot_create_an_execution():
    prices = (("100", "100"),) * 3
    first = trace(prices, ("0", "0", "1"), bps="50")
    second = trace(prices, ("0", "0", "0"), bps="50")
    assert tuple(r.nav for r in first.rows) == tuple(r.nav for r in second.rows) == (D(1),) * 3
    assert all(r.cost == 0 and r.actual_turnover == 0 for r in first.rows)
    assert first.pending_target == D(1)
    assert second.pending_target == D(0)


def test_fractional_rebalance_distinguishes_cost_basis_from_actual_turnover():
    result = trace((("100", "100"),) * 3, ("0.5", "0.5", "0"), bps="100")
    entry = result.rows[1]
    assert entry.opening_nav == D(1)
    assert entry.cost_basis_turnover == D("0.5")
    assert entry.trade_cost == D("0.005")
    assert entry.post_trade_nav == D("0.995")
    assert entry.actual_turnover == D("0.4975")
    assert entry.stock_value == entry.cash_value == D("0.4975")
    last = result.rows[2]
    assert last.trade_cost == 0
    assert last.closing_nav_before_terminal == D("0.995")
    assert last.terminal_cost == D("0.004975")
    assert last.nav == last.cash_value == D("0.990025")
    assert last.stock_value == last.stock_quantity == 0
    assert last.actual_turnover == last.cost_basis_turnover == D("0.4975")


def test_fractional_drift_rebalancing_is_self_financing():
    result = trace(
        (("100", "100"), ("100", "200"), ("100", "100")),
        ("0.5", "0.5", "0.5"),
        bps="100",
        terminal="mark",
    )
    # At the third open, the half-sized stock sleeve has fallen back to .4975.
    last = result.rows[2]
    assert last.opening_nav == D("0.995")
    assert last.trade_cost == 0
    assert last.nav == D("0.995")
    for row in result.rows:
        assert row.post_trade_nav == row.opening_nav - row.trade_cost
        assert row.nav == row.stock_value + row.cash_value
        assert row.cost == row.trade_cost + row.terminal_cost


def test_fractional_drift_charges_pre_fee_target_basis_and_records_post_fee_trade():
    result = trace(
        (("100", "100"), ("100", "200"), ("200", "200")),
        ("0.5", "0.5", "0"),
        bps="100",
        terminal="mark",
    )
    last = result.rows[-1]
    assert last.opening_nav == D("1.4925")
    assert last.cost_basis_turnover == D("0.24875")
    assert last.trade_cost == D("0.0024875")
    assert last.post_trade_nav == last.nav == D("1.4900125")
    assert last.actual_turnover == D("0.24999375")
    assert last.stock_value == last.cash_value == D("0.74500625")


def test_entry_and_terminal_exit_on_same_final_session_are_each_charged_once():
    result = trace((("100", "100"),) * 2, ("1", "1"), bps="100")
    last = result.rows[-1]
    assert last.trade_cost == D("0.01")
    assert last.closing_nav_before_terminal == D("0.99")
    assert last.terminal_cost == D("0.0099")
    assert last.nav == D("0.9801")
    assert last.cost == D("0.0199")
    assert last.actual_turnover == D("1.98")


def test_mark_policy_never_charges_terminal_liquidation():
    result = trace((("100", "100"),) * 3, ("1", "1", "0"), bps="100", terminal="mark")
    assert result.rows[-1].nav == D("0.99")
    assert result.rows[-1].stock_value == D("0.99")
    assert result.rows[-1].terminal_cost == 0


def test_future_prices_and_targets_do_not_change_marked_prefix():
    prices = (("100", "100"), ("110", "120"), ("90", "80"), ("300", "400"))
    full = trace(prices, ("1", "0.5", "0", "1"), bps="12.5", terminal="mark")
    prefix = trace(prices[:2], ("1", "0.5"), bps="12.5", terminal="mark")
    mutated = trace(
        (*prices[:2], ("500", "400"), ("10", "20")),
        ("1", "0.5", "1", "0"),
        bps="12.5",
        terminal="mark",
    )
    assert full.rows[:2] == prefix.rows == mutated.rows[:2]


def test_fixed_context_ignores_ambient_precision_rounding_and_traps():
    prices = (("7", "7"), ("7", "11"), ("13", "17"))
    with localcontext() as ctx:
        ctx.prec = 70
        ordinary = trace(
            prices, ("0.3333333333333333333333333333333333333333", "1", "0"), bps="12.5"
        )
    with localcontext() as ctx:
        ctx.prec = 3
        ctx.rounding = ROUND_DOWN
        ctx.traps[Inexact] = True
        hostile = trace(
            prices, ("0.3333333333333333333333333333333333333333", "1", "0"), bps="12.5"
        )
    assert ordinary == hostile
    assert ordinary.arithmetic_precision == 50
    assert len(ordinary.rows[-1].nav.as_tuple().digits) == 50


def test_slice_preserves_prior_close_baseline_and_existing_terminal_charge():
    from trading_bot.research.stock_price_trace import slice_price_trace

    result = trace(
        (("100", "100"), ("100", "200"), ("300", "400"), ("500", "600")),
        ("1", "1", "1", "0"),
        bps="100",
    )
    training = slice_price_trace(result, first_session=0, last_session=1)
    holdout = slice_price_trace(result, first_session=2, last_session=3)
    assert training.baseline_nav == D(1)
    assert training.rows == result.rows[:2]
    assert training.rows[-1].terminal_cost == 0
    assert holdout.baseline_nav == result.rows[1].nav
    assert holdout.baseline_stock_quantity == result.rows[1].stock_quantity
    assert holdout.baseline_cash_value == result.rows[1].cash_value
    assert holdout.pending_target_at_start == D(1)
    assert training.rows + holdout.rows == result.rows
    assert holdout.rows[-1].terminal_cost == result.rows[-1].terminal_cost
    assert slice_price_trace(result, first_session=3, last_session=3).rows == result.rows[-1:]
    assert result.rows[-1].terminal_cost > 0


def test_slice_inherits_prior_high_watermark_instead_of_resetting_it():
    from trading_bot.research.stock_price_trace import slice_price_trace

    result = trace(
        (("100", "100"), ("100", "200"), ("100", "100"), ("100", "90")),
        ("1", "1", "1", "0"),
        terminal="mark",
    )
    segment = slice_price_trace(result, first_session=3, last_session=3)
    assert segment.baseline_nav == D(1)
    assert segment.inherited_high_watermark == D(2)


@pytest.mark.parametrize("signals", [(1, 1, 1, 0), (0, 1, 0, 1), (1, 0, 1, 0)])
@pytest.mark.parametrize("bps", ["0", "5", "12.5", "25", "50"])
def test_binary_endpoint_matches_legacy_comparator(signals, bps):
    prices = (("100", "101"), ("103", "105"), ("90", "110"), ("120", "90"))
    bars, _ = sample(prices)
    legacy = compare_returns(bars, signals, bars, cost_bps=D(bps))
    result = trace(prices, tuple(str(s) for s in signals), bps=bps)
    assert float(result.rows[-1].nav - 1) == pytest.approx(legacy["strategy_return"], abs=1e-15)


@pytest.mark.parametrize(
    "field",
    [
        "qualified",
        "source_qualified",
        "strategy_qualified",
        "investment_eligible",
        "trading_enabled",
        "live_authorized",
    ],
)
def test_trace_and_slice_cannot_be_promoted_by_constructor_or_replace(field):
    from trading_bot.research.stock_price_trace import slice_price_trace

    result = trace((("100", "100"),), ("1",))
    for value in (result, slice_price_trace(result, first_session=0, last_session=0)):
        assert getattr(value, field) is False
        with pytest.raises((ValueError, TypeError)):
            replace(value, **{field: True})
        with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
            setattr(value, field, True)
        assert value.quote_currency is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("targets", (D("-0.01"),)),
        ("targets", (D("1.01"),)),
        ("targets", (D("NaN"),)),
        ("targets", (D("Infinity"),)),
        ("targets", (True,)),
        ("targets", (1,)),
        ("targets", (0.5,)),
        ("targets", [D(0)]),
        ("targets", ()),
        ("one_way_cost_bps", D("NaN")),
        ("one_way_cost_bps", D("Infinity")),
        ("one_way_cost_bps", D("-1")),
        ("one_way_cost_bps", D("10000")),
        ("one_way_cost_bps", True),
        ("one_way_cost_bps", 5),
        ("terminal_policy", "automatic"),
        ("terminal_policy", True),
        ("bars", ()),
        ("bars", [PriceBar(START + timedelta(hours=1), D(1), D(1))]),
        ("bars", (object(),)),
        ("opens_at", ()),
        ("opens_at", [START]),
        ("opens_at", (START.replace(tzinfo=None),)),
        ("opens_at", (START.astimezone(timezone(timedelta(hours=-5))),)),
        ("opens_at", ("2025-01-02T14:30:00Z",)),
        ("opens_at", (START + timedelta(hours=7),)),
    ],
)
def test_invalid_inputs_fail_closed(field, value):
    from trading_bot.research.stock_price_trace import trace_price_targets

    bars, opens = sample((("100", "100"),))
    inputs = {
        "bars": bars,
        "opens_at": opens,
        "targets": (D(0),),
        "one_way_cost_bps": D(5),
        "terminal_policy": "liquidate",
    }
    with pytest.raises(ValueError):
        trace_price_targets(**(inputs | {field: value}))


@pytest.mark.parametrize("corruption", ["reordered", "overlap", "duplicate", "close_equals_open"])
def test_calendar_order_and_session_overlap_fail_closed(corruption):
    from trading_bot.research.stock_price_trace import trace_price_targets

    bars, opens = sample((("100", "100"),) * 2)
    if corruption == "reordered":
        bars, opens = bars[::-1], opens[::-1]
    elif corruption == "overlap":
        opens = (opens[0], bars[0].completed_at - timedelta(minutes=1))
    elif corruption == "duplicate":
        bars = (bars[0], bars[0])
    else:
        opens = (bars[0].completed_at, opens[1])
    with pytest.raises(ValueError):
        trace_price_targets(bars, opens, (D(1), D(0)), one_way_cost_bps=D(5))


@pytest.mark.parametrize(
    "value", [True, 1.0, D(0), D(-1), D("NaN"), D("sNaN"), D("Infinity"), D("1e-31"), D("1e31")]
)
@pytest.mark.parametrize("field", ["open", "close"])
def test_price_bar_is_revalidated_at_boundary(field, value):
    from trading_bot.research.stock_price_trace import trace_price_targets

    bars, opens = sample((("100", "100"),))
    object.__setattr__(bars[0], field, value)
    with pytest.raises(ValueError):
        trace_price_targets(bars, opens, (D(0),), one_way_cost_bps=D(5))


@pytest.mark.parametrize(
    "first,last", [(True, 1), (0, False), (-1, 1), (1, 0), (0, 2), (0.0, 1), (0, D(1))]
)
def test_invalid_slice_boundaries_fail_closed(first, last):
    from trading_bot.research.stock_price_trace import slice_price_trace

    result = trace((("100", "100"),) * 2, ("1", "0"))
    with pytest.raises(ValueError):
        slice_price_trace(result, first_session=first, last_session=last)
