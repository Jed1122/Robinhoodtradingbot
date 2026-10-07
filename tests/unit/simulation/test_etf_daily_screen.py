"""Independent exact cash expectations for assumed daily execution only."""

import importlib
from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from tests.unit.research.test_etf_daily_protocol import daily_bar, protocol
from trading_bot.domain import Side
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import EtfBenchmarkDistribution
from trading_bot.simulation.etf_account import (
    EtfAccountRequest,
    replay_etf_account,
    resume_etf_account,
)

D = Decimal


def api():
    return importlib.import_module("trading_bot.simulation.etf_daily_screen")


def request(count=105, **changes):
    from trading_bot.research.etf_daily_protocol import EtfDailyRequest

    p = protocol(count)
    rows = tuple(daily_bar(day, D("100") + D(i) / 100) for i, day in enumerate(p.sessions))
    return replace(EtfDailyRequest(p, rows, (), D("500")), **changes)


def run(req):
    return api().run_etf_daily_screen(req)


def fills(result):
    return tuple(e.fill for e in result.events if e.kind == "fill")


def test_fixed_anchor_prior_features_next_open_and_no_terminal_sale():
    req = request()
    out = run(req)
    assert out.decisions[0].session_date == req.protocol.first_rebalance
    assert out.decisions[0].signal == "enter_long"
    assert out.decisions[0].feature_source_hashes == tuple(r.raw.data_hash for r in req.bars[:100])
    assert len(fills(out)) == 1
    fill = fills(out)[0]
    assert fill.side is Side.BUY and fill.occurred_at.date() == req.protocol.sessions[101]
    assert fill.quantity == D(".148") and fill.price == D("101.010000")
    assert out.account.cash == D("485.040520") and out.account.shares == D(".148")
    assert out.account.trial.reserved_risk == D("14.969480")
    assert not out.account.complete and out.incomplete_reasons == ("open_account_obligations",)
    assert out.execution_enabled is False and out.evidence_promotable is False
    assert (
        replay_etf_account(EtfAccountRequest(req.protocol.study, req.initial_cash, out.events))
        == out.account
    )
    assert (
        resume_etf_account(
            EtfAccountRequest(req.protocol.study, req.initial_cash, out.events), out.account
        )
        == out.account
    )


def test_stop_gap_uses_worse_open_and_reconciles_fees_and_t_plus_two():
    req = request()
    rows = list(req.bars)
    rows[102] = daily_bar(rows[102].session_date, D("98"))
    out = run(replace(req, bars=tuple(rows)))
    assert tuple(f.side for f in fills(out)) == (Side.BUY, Side.SELL)
    assert fills(out)[1].price == D("98.000000")
    assert out.exits[0].reason == "stop_gap"
    assert out.account.cash == D("499.534520")
    assert out.account.fees == D(".02") and out.account.shares == 0
    assert out.account.complete and out.account.trial.consumed_loss == D(".465480")
    settlements = tuple(e for e in out.events if e.kind == "settlement")
    assert tuple(e.at_ns for e in settlements) == tuple(
        int(req.bars[i].raw.starts_at.timestamp()) * 10**9 for i in (103, 104)
    )


def test_ambiguous_range_chooses_stop_not_target():
    req = request()
    rows = list(req.bars)
    rows[102] = daily_bar(rows[102].session_date, D("101"), high=D("104"), low=D("99"))
    out = run(replace(req, bars=tuple(rows)))
    assert out.exits[0].reason == "stop_first_ambiguous"
    assert fills(out)[1].price == D("100.010000")
    assert out.account.cash == D("499.832000")


def test_adverse_cost_is_embedded_once_and_fees_once():
    req = request()
    p = replace(req.protocol, per_side_cost_bps=D("25"))
    rows = list(req.bars)
    rows[102] = daily_bar(rows[102].session_date, D("98"))
    out = run(replace(req, protocol=p, bars=tuple(rows)))
    buy, sell = fills(out)
    assert buy.price == D("101.262525") and sell.price == D("97.755000")
    assert buy.quantity == D(".148")
    assert out.account.cash == D("499.460886300")
    assert out.account.fees == D(".02")


def test_generic_sizing_cannot_evade_whole_episode_fee_reserve():
    req = request()
    rows = tuple(
        daily_bar(day, D("5") + D(i) / 1000, D(".5")) for i, day in enumerate(req.protocol.sessions)
    )
    out = run(replace(req, bars=rows))
    assert not fills(out) and out.account.cash == D("500")
    assert out.attempts[0].reason == "canonical_account_admission_denied"


def test_missing_execution_session_stops_without_reinventing_cadence_or_future_fills():
    req = request()
    out = run(replace(req, bars=tuple(r for i, r in enumerate(req.bars) if i != 102)))
    assert len(fills(out)) == 1 and out.account.shares == D(".148")
    assert out.incomplete_reasons == ("missing_session_price", "open_account_obligations")
    assert out.points[-1].session_date == req.protocol.sessions[101]


def test_distributions_before_entries_and_retained_entitlement_after_sale():
    req = request()
    entry_ex = EtfBenchmarkDistribution(
        req.protocol.sessions[101], req.protocol.sessions[104], D("10"), content_hash("entry-ex")
    )
    held_ex = EtfBenchmarkDistribution(
        req.protocol.sessions[102], req.protocol.sessions[104], D(".2"), content_hash("held-ex")
    )
    rows = list(req.bars)
    rows[102] = daily_bar(rows[102].session_date, D("98"))
    out = run(replace(req, bars=tuple(rows), distributions=(entry_ex, held_ex)))
    assert out.account.cash == D("499.564120")
    assert out.account.trial.consumed_loss == D(".435880")
    assert out.account.complete


def test_unknown_basis_has_no_execution_or_screening_conclusion():
    req = request()
    out = run(replace(req, protocol=replace(req.protocol, price_basis="unknown")))
    assert not out.events and not out.points and not out.decisions
    assert out.incomplete_reasons == ("price_action_basis_unknown",)


def test_future_price_changes_and_ambient_precision_do_not_rewrite_prefix():
    req = request(110)
    prefix = run(replace(req, bars=req.bars[:103]))
    full = run(req)
    assert full.events[: len(prefix.events)] == prefix.events
    assert full.decisions[: len(prefix.decisions)] == prefix.decisions
    with localcontext() as context:
        context.prec = 5
        assert run(req) == full


def test_full_predicate_not_positive_return_alone():
    req = request()
    rows = list(req.bars)
    rows[99] = daily_bar(rows[99].session_date, D("100.1"))
    out = run(replace(req, bars=tuple(rows)))
    assert out.decisions[0].signal == "hold" and not fills(out)


def test_fixed_five_session_rebalance_and_no_position_additions():
    req = request(116)
    out = run(req)
    scheduled = tuple(d.session_date for d in out.decisions if d.rebalance)
    assert scheduled == tuple(req.protocol.sessions[i] for i in (100, 105, 110, 115))
    assert len(tuple(f for f in fills(out) if f.side is Side.BUY)) == 1


def test_maximum_hold_exit_uses_next_open_after_100_held_sessions():
    req = request(205)
    p = replace(req.protocol, side_fee=D("0"), episode_fee_bound=D("0"))
    rows = tuple(daily_bar(day, D("100") + D(i) / 100, D("1")) for i, day in enumerate(p.sessions))
    out = run(replace(req, protocol=p, bars=rows))
    buy, sell = fills(out)
    assert buy.quantity == D(".125")
    assert sell.occurred_at.date() == p.sessions[201]
    assert out.exits[0].reason == "maximum_hold"
    assert out.account.cash == D("500.125000") and out.account.complete


def test_entry_cost_can_put_the_new_stop_above_raw_open_without_guaranteeing_stop_price():
    req = request()
    p = replace(req.protocol, per_side_cost_bps=D("25"))
    rows = tuple(
        daily_bar(day, D("100") + D(i) / 100000, D(".00001")) for i, day in enumerate(p.sessions)
    )
    out = run(replace(req, protocol=p, bars=rows))
    buy, sell = fills(out)
    assert buy.side is Side.BUY and sell.side is Side.SELL
    assert sell.price == D("99.751007")
    assert out.exits[0].reason == "stop_gap_after_entry"
    assert sell.occurred_at > buy.occurred_at


@pytest.mark.parametrize(
    "marker",
    [
        "source_qualified",
        "cost_qualified",
        "execution_enabled",
        "economic_admitted",
        "evidence_promotable",
    ],
)
def test_runner_does_not_launder_top_level_markers_via_replace(marker):
    req = request()
    object.__setattr__(req, marker, True)
    with pytest.raises(ValueError, match="etf_daily_invalid"):
        run(req)


def test_invalid_or_tampered_result_cannot_be_reused_as_a_verified_economic_input():
    req = request()
    out = run(req)
    api().verify_etf_daily_result(out)
    with pytest.raises(ValueError, match="etf_daily_invalid"):
        api().verify_etf_daily_result(replace(out, account=replace(out.account, cash=D("900"))))
    object.__setattr__(out, "evidence_promotable", True)
    with pytest.raises(ValueError, match="etf_daily_invalid"):
        api().verify_etf_daily_result(out)
    with pytest.raises(ValueError, match="etf_daily_invalid"):
        run(None)


def test_regime_exit_is_daily_not_only_on_the_five_session_cadence():
    req = request(107)
    p = replace(req.protocol, side_fee=D("0"), episode_fee_bound=D("0"))
    rows = [daily_bar(day, D("100") + D(i) / 100, D("1")) for i, day in enumerate(p.sessions)]
    rows[102] = daily_bar(p.sessions[102], D("99"))
    rows[104] = daily_bar(p.sessions[104], D("100"))
    out = run(replace(req, protocol=p, bars=tuple(rows)))
    assert out.decisions[3].signal == "hold" and not out.decisions[3].rebalance
    assert out.exits[0].reason == "regime_exit"
    assert fills(out)[1].occurred_at.date() == p.sessions[104]


@pytest.mark.parametrize(
    "opening,high,expected",
    [
        (D("104"), D("104.1"), "target_gap_conservative"),
        (D("101"), D("104"), "target"),
    ],
)
def test_target_assumptions_do_not_use_better_opening_price(opening, high, expected):
    req = request()
    rows = list(req.bars)
    rows[102] = daily_bar(
        rows[102].session_date, opening, opening=opening, high=high, low=opening - D(".25")
    )
    out = run(replace(req, bars=tuple(rows)))
    assert out.exits[0].reason == expected
    assert fills(out)[1].price == D("103.010000")


def test_missing_prior_session_is_unknown_not_a_shorter_feature_window():
    req = request()
    out = run(replace(req, bars=req.bars[1:]))
    assert out.decisions[0].signal is None
    assert out.decisions[0].reasons == ("prior_session_history_missing",)
    assert "prior_session_history_missing" in out.incomplete_reasons
    assert not fills(out)


def test_below_minimum_adverse_order_size_has_zero_effect():
    req = request()
    rows = tuple(
        daily_bar(day, D(".50") + D(i) / 10000, D(".2"))
        for i, day in enumerate(req.protocol.sessions)
    )
    out = run(replace(req, bars=rows))
    assert out.attempts[0].reason == "sizing_denied"
    assert out.attempts[0].quantity == 0 and not fills(out)
