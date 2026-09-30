"""Real decision pipeline, canonical risk, and configured fills in one offline replay."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import Decimal as D
from decimal import localcontext
from importlib import import_module
from importlib.util import find_spec

import pytest

from tests.integration.simulation._equity_strategy_fixtures import (
    cancel_race_scenario,
    replay_scenario,
    simulation_settings,
)
from tests.unit.simulation._equity_replay_fixtures import NOW
from trading_bot.domain import OrderPurpose, OrderState, Side
from trading_bot.simulation.configured_models import SyntheticBarWindow
from trading_bot.simulation.equity_replay_models import ReplayValidationError


def api():
    name = "trading_bot.simulation.equity_replay"
    assert find_spec(name) is not None, "whole-strategy replay coordinator is missing"
    return import_module(name)


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["equity_momentum", "equity_relative_strength"])
async def test_real_pipeline_enters_and_exits_with_literal_balances(strategy):
    req = replay_scenario(strategy=strategy)
    result = await api().replay_equity_strategy(req)
    assert len(result.cycles) == 2 and len(result.orders) == 2
    buy, sell = result.orders
    assert (buy.intent.side, buy.intent.purpose, buy.intent.quantity, buy.intent.limit_price) == (
        Side.BUY,
        OrderPurpose.ENTRY,
        D("0.25"),
        D(10),
    )
    assert (
        sell.intent.side,
        sell.intent.purpose,
        sell.intent.quantity,
        sell.intent.limit_price,
    ) == (Side.SELL, OrderPurpose.STRATEGY_EXIT, D("0.25"), D(8))
    assert result.final_portfolio.cash == D("99.3") and result.fees == D("0.2")
    assert result.orders_terminal and result.positions_flat and result.strategy_outcomes_complete
    assert result.run_valid
    assert not result.assumptions_validated and not result.evidence_promotable
    assert not result.production_pretrade_eligible
    assert result.cycles[1].result.decisions[0].reason_codes == ("replay_stop_triggered",)
    assert [e.cursor.occurred_at for e in buy.result.events if hasattr(e, "fill")] == [
        NOW + timedelta(seconds=1)
    ]
    with pytest.raises(FrozenInstanceError):
        result.evidence_promotable = True


@pytest.mark.asyncio
async def test_terminal_entry_is_not_flat_or_a_complete_strategy():
    req = replace(replay_scenario(), decisions=replay_scenario().decisions[:1])
    result = await api().replay_equity_strategy(req)
    assert result.orders_terminal and not result.positions_flat
    assert not result.strategy_outcomes_complete
    assert result.final_portfolio.positions[0].quantity == D("0.25")
    assert "replay_positions_open" in result.unresolved_reasons
    assert len(result.orders) == 1


@pytest.mark.asyncio
async def test_future_market_extension_preserves_existing_cycles_and_fills():
    full = replay_scenario()
    horizon = NOW + timedelta(seconds=2)
    short = replace(
        full,
        end_at=horizon,
        markets=tuple(e for e in full.markets if e.cursor.occurred_at <= horizon),
    )
    early = await api().replay_equity_strategy(short)
    later = await api().replay_equity_strategy(full)
    assert early.cycles == later.cycles[: len(early.cycles)]
    assert early.orders[0].result.events == later.orders[0].result.events
    assert not early.orders_terminal and not early.positions_flat
    assert not early.strategy_outcomes_complete and later.strategy_outcomes_complete


@pytest.mark.asyncio
async def test_duplicate_delivery_does_not_change_economics_or_consume_liquidity_twice():
    req = replay_scenario()
    normal = await api().replay_equity_strategy(req)
    repeated = await api().replay_equity_strategy(
        replace(req, markets=(*req.markets, req.markets[1]))
    )
    assert repeated.result_hash == normal.result_hash
    assert repeated.cycles == normal.cycles and repeated.final_portfolio == normal.final_portfolio
    assert repeated.identity.delivery_hash != normal.identity.delivery_hash


@pytest.mark.asyncio
async def test_replay_ignores_ambient_decimal_precision():
    req = replay_scenario()
    normal = await api().replay_equity_strategy(req)
    with localcontext() as context:
        context.prec = 2
        repeated = await api().replay_equity_strategy(req)
    assert repeated == normal


@pytest.mark.asyncio
async def test_missing_visible_quote_cannot_create_an_entry_or_successful_result():
    req = replay_scenario()
    req = replace(req, markets=req.markets[1:])
    with pytest.raises(ReplayValidationError, match="replay_quote_unavailable"):
        await api().replay_equity_strategy(req)


@pytest.mark.asyncio
async def test_whole_strategy_replay_has_no_network_or_database_capability(monkeypatch):
    import socket
    import sqlite3

    req = replay_scenario()
    module = api()

    def forbidden(*args, **kwargs):
        pytest.fail("whole-strategy replay attempted external I/O")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    result = await module.replay_equity_strategy(req)
    assert result.strategy_outcomes_complete and result.final_portfolio.cash == D("99.3")


@pytest.mark.asyncio
async def test_exit_waits_for_cancel_race_and_uses_actual_filled_quantity():
    result = await api().replay_equity_strategy(cancel_race_scenario())
    assert len(result.orders) == 2 and len(result.cycles) == 3
    buy, sell = result.orders
    assert buy.intent.quantity == D("0.25")
    assert buy.lifecycle.snapshot.position.quantity == D("0.2")
    assert buy.lifecycle.snapshot.order.state.value == "canceled"
    assert sell.intent.quantity == D("0.2") and sell.intent.created_at == NOW + timedelta(seconds=5)
    assert result.cycles[1].result.intents == ()
    assert result.cycles[1].cancellation_reasons == (("SYNTH", "replay_stop_triggered"),)
    reasons = [
        (t.decision.occurred_at, t.decision.reason.value)
        for t in result.transitions
        if t.order_id == buy.initial.order.id
    ]
    assert (NOW + timedelta(seconds=3), "cancel_requested") in reasons
    assert (NOW + timedelta(seconds=4), "partial_fill") in reasons
    assert (NOW + timedelta(milliseconds=4500), "cancel_confirmed") in reasons
    assert result.final_portfolio.cash == D("99.8") and result.strategy_outcomes_complete


@pytest.mark.asyncio
async def test_cancel_confirmation_without_another_decision_does_not_invent_an_exit():
    request = cancel_race_scenario()
    result = await api().replay_equity_strategy(replace(request, decisions=request.decisions[:2]))
    assert len(result.orders) == 1 and result.orders_terminal
    assert not result.positions_flat and not result.strategy_outcomes_complete
    assert result.final_portfolio.positions[0].quantity == D("0.2")


@pytest.mark.asyncio
async def test_rejection_remains_explicit_and_does_not_get_blindly_retried():
    req = simulation_settings(
        replay_scenario(), rejection_probability_pct=D(100), full_fill_probability_pct=D(0)
    )
    result = await api().replay_equity_strategy(req)
    assert (
        len(result.orders) == 1
        and result.orders[0].lifecycle.snapshot.order.state.value == "rejected"
    )
    assert result.cycles[1].result.order_outcomes[0].accepted is False
    assert "symbol_order_limit_reached" in result.cycles[1].result.order_outcomes[0].reasons
    assert result.final_portfolio.cash == D(100) and result.strategy_outcomes_complete


@pytest.mark.asyncio
@pytest.mark.parametrize("expire", [False, True])
async def test_no_fill_is_distinct_from_expired_flat_completion(expire):
    req = simulation_settings(
        replay_scenario(), no_fill_probability_pct=D(100), full_fill_probability_pct=D(0)
    )
    if expire:
        req = replace(req, end_at=req.sessions[0].window.ends_at)
    result = await api().replay_equity_strategy(req)
    assert result.positions_flat and result.final_portfolio.cash == D(100)
    assert result.orders_terminal is expire
    assert result.strategy_outcomes_complete is expire


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["is_open", "halted", "trading_disabled", "cancel_only"])
async def test_market_session_denials_never_submit_or_force_a_fill(field):
    base = replay_scenario()
    req = replace(
        base,
        markets=tuple(
            replace(e, clock=replace(e.clock, **{field: field != "is_open"})) for e in base.markets
        ),
    )
    result = await api().replay_equity_strategy(req)
    assert not result.orders and result.final_portfolio.cash == D(100)
    assert all(
        not outcome.accepted for cycle in result.cycles for outcome in cycle.result.order_outcomes
    )


@pytest.mark.asyncio
async def test_same_submission_bar_cannot_fill_despite_its_available_liquidity():
    base = replay_scenario()
    window = SyntheticBarWindow(NOW, NOW + timedelta(seconds=2))
    req = replace(
        base,
        markets=tuple(
            replace(e, window=window) if i < 2 else e for i, e in enumerate(base.markets)
        ),
    )
    result = await api().replay_equity_strategy(req)
    buy = result.orders[0]
    assert [e.cursor.occurred_at for e in buy.result.events if hasattr(e, "fill")] == [
        NOW + timedelta(seconds=2)
    ]
    assert result.final_portfolio.cash == D("99.8") and result.strategy_outcomes_complete


@pytest.mark.asyncio
async def test_result_flags_cannot_be_requested_or_replaced():
    module = api()
    with pytest.raises(TypeError):
        module.EquityStrategyReplayResult()
    result = await module.replay_equity_strategy(replay_scenario())
    with pytest.raises((TypeError, ValueError), match="init=False"):
        replace(result, evidence_promotable=True)
    assert result.evidence_promotable is False


@pytest.mark.asyncio
async def test_expired_partial_entry_retains_open_exposure():
    base = replay_scenario()
    boundary = NOW + timedelta(seconds=3)
    (first,) = base.sessions
    sessions = (
        replace(
            first,
            window=SyntheticBarWindow(NOW, boundary),
            opportunity_times=first.opportunity_times[:3],
        ),
        replace(
            first,
            window=SyntheticBarWindow(boundary, first.window.ends_at),
            opportunity_times=first.opportunity_times[3:],
        ),
    )
    markets = tuple(
        replace(e, available_quantity=D("0.1") if i == 1 else D(0))
        for i, e in enumerate(base.markets)
    )
    result = await api().replay_equity_strategy(
        replace(base, sessions=sessions, markets=markets, decisions=base.decisions[:1])
    )
    assert (
        result.orders_terminal
        and result.orders[0].lifecycle.snapshot.order.state.value == "expired"
    )
    assert result.final_portfolio.positions[0].quantity == D("0.1")
    assert result.final_portfolio.cash == D("98.9") and not result.strategy_outcomes_complete


@pytest.mark.asyncio
async def test_two_symbols_recheck_pending_exposure_and_activity_after_first_admission():
    req = replay_scenario(symbols=("SYNTH", "SECOND"), tight_ranges=True)
    req = replace(
        req,
        decisions=req.decisions[:1],
        markets=tuple(
            replace(e, quote=replace(e.quote, bid=D(10), ask=D(10))) for e in req.markets
        ),
    )
    result = await api().replay_equity_strategy(req)
    assert len(result.cycles[0].result.intents) == 2
    first, second = result.cycles[0].result.order_outcomes
    assert first.accepted and not second.accepted
    assert (
        "correlated_group_exposure" in second.reasons
        and "minimum_order_interval_active" in second.reasons
    )
    assert result.orders[0].intent.instrument_id == "SECOND"
    assert result.orders[0].intent.quantity == D("1.5")
    diagnostics = dict(result.cycles[0].economic_checks)[second.intent_id]
    group = next(c for c in diagnostics if c.code == "correlated_group_exposure")
    assert group.observed == "30" and group.configured_limit == "25"
    assert not result.positions_flat and not result.strategy_outcomes_complete


@pytest.mark.asyncio
async def test_stale_mark_denies_without_inventing_end_of_run_valuation():
    req = replay_scenario()
    req = replace(req, decisions=req.decisions[:1], end_at=NOW + timedelta(seconds=10))
    with pytest.raises(ReplayValidationError, match="replay_mark_missing"):
        await api().replay_equity_strategy(req)


@pytest.mark.asyncio
async def test_missing_required_history_stays_a_reported_denial():
    req = replay_scenario()
    req = replace(
        req,
        snapshot_settings=replace(
            req.snapshot_settings,
            history_start=req.snapshot_settings.history_start + timedelta(days=1),
        ),
    )
    with pytest.raises(ReplayValidationError, match="snapshot_history_insufficient"):
        await api().replay_equity_strategy(req)


@pytest.mark.asyncio
async def test_drawdown_cancels_entry_remainder_and_records_why_without_liquidation():
    base = replay_scenario(tight_ranges=True)
    events = tuple(
        replace(
            e,
            quote=replace(e.quote, bid=D(10) if i < 2 else D(1), ask=D(10) if i < 2 else D(1)),
            available_quantity=D("1.4") if i == 1 else D(0),
        )
        for i, e in enumerate(base.markets)
    )
    result = await api().replay_equity_strategy(replace(base, markets=events))
    assert len(result.orders) == 1 and result.orders[0].intent.side is Side.BUY
    assert result.orders[0].lifecycle.snapshot.order.state.value == "canceled"
    assert result.final_portfolio.positions[0].quantity == D("1.4")
    assert not result.strategy_outcomes_complete
    assert result.cycles[1].result.order_outcomes[0].reasons == ("drawdown_limit_reached",)
    assert len(result.cancellations) == 1
    assert result.cancellations[0].reason == "drawdown_limit_reached"
    assert result.cancellations[0].occurred_at == NOW + timedelta(seconds=2)


@pytest.mark.asyncio
async def test_configured_target_exit_has_literal_cash_and_no_implicit_fill():
    base = replay_scenario()
    req = replace(
        base,
        markets=tuple(
            replace(e, quote=replace(e.quote, bid=D(14), ask=D(14))) if i >= 2 else e
            for i, e in enumerate(base.markets)
        ),
    )
    result = await api().replay_equity_strategy(req)
    assert result.cycles[1].result.decisions[0].reason_codes == ("replay_target_triggered",)
    assert result.orders[1].intent.created_at == NOW + timedelta(seconds=2)
    assert result.orders[1].lifecycle.snapshot.cursor.occurred_at == NOW + timedelta(seconds=3)
    assert result.final_portfolio.cash == D("100.8") and result.strategy_outcomes_complete


@pytest.mark.asyncio
async def test_relative_strength_does_not_rebalance_twice_on_the_same_completed_bar():
    req = simulation_settings(
        replay_scenario(strategy="equity_relative_strength"),
        rejection_probability_pct=D(100),
        full_fill_probability_pct=D(0),
    )
    result = await api().replay_equity_strategy(req)
    assert len(result.orders) == 1
    assert result.cycles[1].result.intents == ()
    assert result.cycles[1].result.decisions[0].reason_codes == ("replay_no_new_selection",)


@pytest.mark.asyncio
async def test_cancel_race_prefix_is_not_changed_by_a_later_exit_decision():
    full = cancel_race_scenario()
    horizon = NOW + timedelta(seconds=4)
    short = replace(
        full,
        end_at=horizon,
        markets=tuple(e for e in full.markets if e.cursor.occurred_at <= horizon),
        decisions=full.decisions[:2],
    )
    early = await api().replay_equity_strategy(short)
    later = await api().replay_equity_strategy(full)
    assert early.cycles == later.cycles[:2]
    assert early.transitions == later.transitions[: len(early.transitions)]
    assert early.cancellations == later.cancellations
    assert early.cancellations[0].reason == "replay_stop_triggered"
    assert early.orders[0].lifecycle.snapshot.order.state is OrderState.CANCEL_PENDING
    assert early.final_portfolio.positions[0].quantity == D("0.2")
    assert not early.strategy_outcomes_complete and later.strategy_outcomes_complete


@pytest.mark.asyncio
async def test_post_cancel_decision_does_not_reuse_an_obsolete_exit_trigger():
    base = cancel_race_scenario()
    req = replace(
        base,
        markets=tuple(
            replace(e, quote=replace(e.quote, bid=D(10), ask=D(10)))
            if e.cursor.occurred_at >= NOW + timedelta(seconds=5)
            else e
            for e in base.markets
        ),
    )
    result = await api().replay_equity_strategy(req)
    assert len(result.orders) == 1 and result.orders_terminal
    assert result.cycles[-1].result.decisions[0].reason_codes == ("replay_holding_position",)
    assert result.cycles[-1].result.intents == ()
    assert result.final_portfolio.positions[0].quantity == D("0.2")
    assert result.final_portfolio.cash == D("98.2") and not result.strategy_outcomes_complete


@pytest.mark.asyncio
async def test_runner_rejects_arbitrary_input_without_formatting_it():
    class Unsafe:
        def __repr__(self):
            pytest.fail("runner formatted arbitrary input")

    with pytest.raises(ReplayValidationError, match=r"^replay_input_invalid$"):
        await api().replay_equity_strategy(Unsafe())
