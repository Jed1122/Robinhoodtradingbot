"""Monthly close decisions and daily protective assumptions, synthetic only."""

import importlib
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from tests.unit.research.test_etf_daily_protocol import daily_bar
from tests.unit.research.test_etf_monthly_protocol import request
from trading_bot.domain import Side
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import EtfBenchmarkDistribution

D = Decimal


def api():
    return importlib.import_module("trading_bot.simulation.etf_monthly_screen")


def inputs(end=date(2016, 11, 8)):
    req = request(end)
    return replace(
        req, bars=tuple(daily_bar(r.session_date, r.raw.close, D(".25")) for r in req.bars)
    )


def fills(result):
    return tuple(e.fill for e in result.events if e.kind == "fill")


def test_decision_after_tenth_month_close_and_fill_only_next_open():
    req = inputs()
    out = api().run_etf_monthly_screen(req)
    decision = out.decisions[0]
    anchor = next(r for r in req.bars if r.session_date == date(2016, 10, 31))
    assert decision.session_date == date(2016, 10, 31)
    assert decision.signal.decision_at > anchor.raw.ends_at
    assert decision.scheduled == "entry"
    assert fills(out)[0].occurred_at.date() == date(2016, 11, 1)
    assert len(fills(out)) == 1 and fills(out)[0].side is Side.BUY
    assert out.points[0].session_date == date(2016, 11, 1)
    assert out.execution_enabled is out.economic_admitted is out.live_authorized is False
    assert out.checkpoint.pending is None and "open_account_obligations" in out.incomplete_reasons


def test_gap_stop_settlement_and_no_midmonth_reentry():
    req = inputs()
    rows = tuple(
        daily_bar(r.session_date, D("98"), D(".25")) if r.session_date >= date(2016, 11, 2) else r
        for r in req.bars
    )
    out = api().run_etf_monthly_screen(replace(req, bars=rows))
    assert tuple(f.side for f in fills(out)) == (Side.BUY, Side.SELL)
    assert fills(out)[1].price == D("98.000000")
    assert out.exits[0].reason == "stop_gap" and out.account.complete
    assert len(out.attempts) == 2
    # Frozen fabricated terminal calendar group is explicit, not a real month-end.
    assert tuple(d.session_date for d in out.decisions) == (date(2016, 10, 31), date(2016, 11, 8))


def test_terminal_monthly_intent_and_missing_input_remain_incomplete():
    req = inputs(date(2016, 10, 31))
    out = api().run_etf_monthly_screen(req)
    assert not fills(out) and not out.points
    assert out.checkpoint.pending is not None
    assert "unattempted_scheduled_intent" in out.incomplete_reasons
    missing = replace(req, bars=tuple(r for r in req.bars if r.session_date != date(2016, 1, 29)))
    denied = api().run_etf_monthly_screen(missing)
    assert not denied.attempts and denied.checkpoint.pending is None
    assert "monthly_history_missing" in denied.incomplete_reasons


def test_unknown_basis_and_fee_reserve_never_get_resized_into_admission():
    req = inputs()
    unknown = api().run_etf_monthly_screen(
        replace(req, protocol=replace(req.protocol, price_basis="unknown"))
    )
    assert not unknown.events and unknown.incomplete_reasons == ("price_action_basis_unknown",)
    wide = replace(req, bars=tuple(daily_bar(r.session_date, D("5"), D(".5")) for r in req.bars))
    # Only the anchor close is higher, so an eligible signal exists.
    rows = list(wide.bars)
    i = wide.protocol.sessions.index(date(2016, 10, 31))
    rows[i] = daily_bar(rows[i].session_date, D("5.01"), D(".5"))
    denied = api().run_etf_monthly_screen(replace(wide, bars=tuple(rows)))
    assert not fills(denied) and denied.attempts[0].reason == "canonical_account_admission_denied"


@pytest.mark.parametrize(
    "opening,high,low,reason,expected",
    [
        (D("105"), D("106"), D("104.9"), "target_gap_conservative", D("104.16")),
        (D("102"), D("105"), D("100"), "stop_first_ambiguous", D("101.16")),
        (D("102"), D("105"), D("101.9"), "target", D("104.16")),
        (D("102"), D("102.2"), D("100"), "stop", D("101.16")),
    ],
)
def test_daily_protection_is_independent_of_monthly_signal(opening, high, low, reason, expected):
    req = inputs()
    rows = tuple(
        daily_bar(r.session_date, opening, opening=opening, high=high, low=low)
        if r.session_date == date(2016, 11, 2)
        else r
        for r in req.bars
    )
    out = api().run_etf_monthly_screen(replace(req, bars=rows))
    assert out.exits[0].reason == reason and out.exits[0].assumed_price == expected
    assert len(tuple(f for f in fills(out) if f.side is Side.SELL)) == 1


def test_maximum_hold_counts_entry_session_and_sells_next_open():
    req = inputs(date(2017, 4, 3))
    anchor = req.protocol.sessions.index(date(2016, 10, 31))
    # Rise only to the first anchor; then constant price leaves protection alone.
    rows = tuple(
        daily_bar(r.session_date, D("102.13"), D(".25")) if i > anchor else r
        for i, r in enumerate(req.bars)
    )
    out = api().run_etf_monthly_screen(replace(req, bars=rows))
    exit = next(e for e in out.exits if e.reason == "maximum_hold")
    assert exit.session_date == req.protocol.sessions[anchor + 101]
    assert tuple(a.session_date for a in out.attempts if a.side is Side.BUY)[:1] == (
        date(2016, 11, 1),
    )


def test_monthly_cash_exit_does_not_use_daily_momentum_and_keeps_original_protection():
    req = inputs(date(2016, 12, 5))
    anchor = req.protocol.sessions.index(date(2016, 10, 31))
    # Literal Jan-Sep100/Oct102 -> LONG; Nov100.1 < SMA100.21 -> CASH.
    rows = tuple(
        daily_bar(
            r.session_date,
            D("102") if i == anchor else D("100.1") if i > anchor else D("100"),
            D("2.5"),
        )
        for i, r in enumerate(req.bars)
    )
    # Wide ATR would force fee denial; zero fees lets the canonical .50 budget bind.
    p = replace(req.protocol, side_fee=D("0"), episode_fee_bound=D("0"))
    out = api().run_etf_monthly_screen(replace(req, protocol=p, bars=rows))
    assert out.decisions[0].signal.regime == "LONG_ELIGIBLE"
    assert out.decisions[1].signal.regime == "CASH"
    assert out.exits[0].reason == "monthly_cash_exit"
    assert fills(out)[1].occurred_at.date() == date(2016, 12, 1)


def test_missing_session_and_atr_history_and_dividend_obligations_stay_explicit():
    req = inputs()
    missing = replace(req, bars=tuple(r for r in req.bars if r.session_date != date(2016, 11, 2)))
    out = api().run_etf_monthly_screen(missing)
    assert out.points[-1].session_date == date(2016, 11, 1)
    assert out.incomplete_reasons == ("missing_session_price", "open_account_obligations")
    missing_atr = replace(
        req, bars=tuple(r for r in req.bars if r.session_date != date(2016, 10, 3))
    )
    denied = api().run_etf_monthly_screen(missing_atr)
    assert "monthly_atr_history_missing" in denied.incomplete_reasons and not fills(denied)
    action = EtfBenchmarkDistribution(
        date(2016, 11, 2), date(2016, 12, 1), D(".2"), content_hash("monthly-synthetic-dividend")
    )
    owed = api().run_etf_monthly_screen(replace(req, distributions=(action,)))
    assert owed.account.dividend_receivable == D(".0292") and not owed.account.complete


@pytest.mark.parametrize(
    "marker",
    [
        "source_qualified",
        "cost_qualified",
        "execution_enabled",
        "economic_admitted",
        "evidence_promotable",
        "live_authorized",
    ],
)
def test_mutated_input_markers_are_not_laundered(marker):
    req = inputs()
    object.__setattr__(req, marker, True)
    with pytest.raises(ValueError):
        api().run_etf_monthly_screen(req)


def test_invalid_runner_and_result_boundaries_are_sanitized():
    with pytest.raises(ValueError):
        api().run_etf_monthly_screen(None)
    with pytest.raises(ValueError):
        api().run_etf_monthly_screen(inputs(), through_session=date(2024, 1, 2))
    with pytest.raises(ValueError):
        api().run_etf_monthly_screen(inputs(), through_session=date(2016, 1, 5))
    with pytest.raises(ValueError):
        api().verify_etf_monthly_result(None)
    result = api().run_etf_monthly_screen(inputs())
    with pytest.raises(ValueError):
        api().verify_etf_monthly_result(replace(result, incomplete_reasons=()))
