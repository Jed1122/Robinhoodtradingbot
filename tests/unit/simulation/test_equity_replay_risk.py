"""Synthetic state feeds canonical economic functions, not production attestations."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from decimal import localcontext
from importlib import import_module
from importlib.util import find_spec

import pytest

from tests.unit.simulation._equity_portfolio_fixtures import configured, intent, scenario
from tests.unit.simulation._equity_replay_fixtures import LATER, NOW, STOP
from tests.unit.simulation.test_equity_replay_policy import features
from trading_bot.domain import Side
from trading_bot.simulation.configured import ConfiguredOrderSession
from trading_bot.simulation.equity_replay_models import ReplaySession, ReplayValidationError
from trading_bot.simulation.equity_replay_policy import derive_entry_policy, planning_policy
from trading_bot.simulation.equity_replay_portfolio import ReplayPortfolio


def api():
    name = "trading_bot.simulation.equity_replay_risk"
    assert find_spec(name) is not None, "synthetic economic adapter is missing"
    return import_module(name)


def setup(req=None):
    req = scenario() if req is None else req
    book = ReplayPortfolio(req)
    return req, book, api().ReplayRiskState(req, book)


def candidate(req, state, *, at=NOW, symbol="SYNTH", quantity="0.1", identifier="buy-1", **changes):
    policy = derive_entry_policy(req, features(symbol=symbol, at=at), D(10))
    quotes = tuple(e.quote for e in req.markets if e.cursor.occurred_at == at)
    state.observe(at, quotes, entry_policies=(policy,))
    return replace(
        intent(
            req,
            instrument=symbol,
            quantity=quantity,
            identifier=identifier,
            exit_policy_version=policy.version,
        ),
        created_at=at,
        **changes,
    )


def checks(req, state, item, at=NOW):
    return {c.code: c for c in api().economic_checks(item, state, req, at)}


def test_initial_flat_entry_uses_canonical_limits_and_frozen_capital():
    req, book, state = setup()
    item = candidate(req, state)
    result = checks(req, state, item)
    assert all(c.allowed for c in result.values())
    assert result["position_notional"].configured_limit == "15"
    assert result["cash_reserve"].observed == "99"
    assert result["replay_final_sizing"].observed == "0.1"
    assert state.production_pretrade_eligible is False
    assert state.evidence_promotable is False
    assert not book.orders  # Evaluation never submits or allocates.


def test_adapter_counts_pending_entries_in_group_and_position_exposure():
    req, book, state = setup()
    book.reserve(intent(req, quantity="1.5"), 4)
    item = candidate(req, state, symbol="SECOND", quantity="1.5", identifier="next")
    result = checks(req, state, item)
    assert result["correlated_group_exposure"].observed == "30"
    assert result["correlated_group_exposure"].configured_limit == "25"
    assert not result["correlated_group_exposure"].allowed
    assert result["open_position_count"].observed == "2"
    assert not result["minimum_order_interval_active"].allowed


def test_reservations_and_commission_capacity_reduce_cash_reserve_projection():
    req, book, state = setup(scenario(commission="1"))
    book.reserve(intent(req, quantity="6"), 4)
    item = candidate(req, state, symbol="SECOND", quantity="1.5", identifier="next")
    result = checks(req, state, item)
    assert result["cash_reserve"].observed == "17"  # 100 - 64 reserved - 15 - 4 commissions.
    assert not result["cash_reserve"].allowed


def test_evaluation_cannot_reuse_snapshot_after_new_reservation():
    req, book, state = setup()
    item = candidate(req, state, symbol="SECOND", identifier="next")
    book.reserve(intent(req, quantity="1"), 4)
    with pytest.raises(ReplayValidationError, match="replay_risk_state_stale"):
        checks(req, state, item)


def test_sizing_rejects_increase_beyond_stop_risk_without_resizing():
    req, book, state = setup()
    item = candidate(req, state, quantity="1")
    result = checks(req, state, item)
    assert not result["replay_final_sizing"].allowed  # 1 share * 2 stop distance > 0.50 risk.
    assert item.quantity == D(1) and not book.orders


@pytest.mark.parametrize(
    "mark,reason",
    [
        ("9", "daily_loss_limit_reached"),
        ("7.5", "weekly_loss_limit_reached"),
        ("5", "drawdown_limit_reached"),
    ],
)
def test_marked_losses_use_existing_purpose_aware_loss_decision(mark, reason):
    base = scenario()
    req = replace(
        base,
        markets=tuple(
            replace(e, quote=replace(e.quote, bid=D(mark))) if e.cursor.occurred_at > LATER else e
            for e in base.markets
        ),
    )
    req, book, state = setup(req)
    buy = book.reserve(intent(req, quantity="2"), 4)
    session = ConfiguredOrderSession(configured(book, req, buy.order_id))
    book.apply(buy.order_id, session.advance_to(NOW))
    state.observe(NOW, ())
    book.apply(buy.order_id, session.advance_to(LATER))
    state.observe(LATER, tuple(e.quote for e in req.markets if e.cursor.occurred_at == LATER))
    at = LATER + timedelta(seconds=1)
    item = candidate(req, state, at=at, symbol="SECOND", identifier="next")
    result = checks(req, state, item, at)
    assert result["replay_loss_limits"].reason == reason
    assert not result["replay_loss_limits"].allowed
    exit_item = replace(
        intent(req, identifier="sell", quantity="2", side=Side.SELL),
        created_at=at,
        limit_price=D(mark),
    )
    exits = checks(req, state, exit_item, at)
    assert exits["replay_loss_limits"].allowed is (reason != "drawdown_limit_reached")
    assert exits["replay_exit_activity"].allowed
    assert state.loss_decision(exit_item.purpose).kill_switch_activation_requested is (
        reason == "drawdown_limit_reached"
    )
    assert len(book.orders) == 1  # A hard-stop/exit decision never liquidates.


def test_gains_do_not_increase_authorized_risk_equity():
    base = scenario()
    req = replace(
        base,
        markets=tuple(
            replace(e, quote=replace(e.quote, bid=D(100), ask=D(100)))
            if e.cursor.occurred_at > LATER
            else e
            for e in base.markets
        ),
    )
    req, book, state = setup(req)
    buy = book.reserve(intent(req, quantity="1"), 4)
    book.apply(
        buy.order_id, ConfiguredOrderSession(configured(book, req, buy.order_id)).advance_to(LATER)
    )
    state.observe(LATER, tuple(e.quote for e in req.markets if e.cursor.occurred_at == LATER))
    at = LATER + timedelta(seconds=1)
    item = candidate(req, state, at=at, symbol="SECOND", identifier="next")
    result = checks(req, state, item, at)
    assert result["position_notional"].configured_limit == "15"
    assert result["cash_reserve"].configured_limit == "76"  # 190 marked equity * 40% reserve.


def multi_day(days=1):
    req = scenario()
    later_sessions = tuple(
        ReplaySession(
            s.instrument_id,
            replace(
                s.window,
                starts_at=s.window.starts_at + timedelta(days=days),
                ends_at=s.window.ends_at + timedelta(days=days),
            ),
            tuple(t + timedelta(days=days) for t in s.opportunity_times),
        )
        for s in req.sessions
    )
    return replace(
        req, end_at=STOP + timedelta(days=days), sessions=(*req.sessions, *later_sessions)
    )


@pytest.mark.parametrize("observe_boundary", [False, True])
@pytest.mark.parametrize("days", [1, 2])
def test_utc_resets_require_explicit_boundary_observation(observe_boundary, days):
    req, _, state = setup(multi_day(days))
    midnight = NOW + timedelta(days=days)
    if observe_boundary:
        state.observe(midnight, ())
    at = midnight + timedelta(microseconds=1)
    item = candidate(req, state, at=at, expires_at=STOP + timedelta(days=days))
    result = checks(req, state, item, at)
    assert result["replay_loss_limits"].allowed is observe_boundary
    if not observe_boundary:
        expected = (
            "daily_reset_reconciliation_required" if days == 1 else "weekly_reset_review_required"
        )
        assert result["replay_loss_limits"].reason == expected


def rejected_request():
    from trading_bot.config import AppConfig, LoadedConfig
    from trading_bot.config.hashing import hash_loaded_config

    base = scenario()
    values = base.loaded.config.model_dump()
    values["simulation"].update(rejection_probability_pct=D(100), full_fill_probability_pct=D(0))
    config = AppConfig.model_validate(values)
    canonical, digest = hash_loaded_config(config, base.loaded.safety_envelope)
    return replace(
        base, loaded=LoadedConfig(config, base.loaded.safety_envelope, canonical, digest)
    )


def test_rejected_submission_counts_once_for_activity():
    req, book, state = setup(rejected_request())
    buy = book.reserve(intent(req, quantity="1"), 4)
    result = ConfiguredOrderSession(configured(book, req, buy.order_id)).advance_to(NOW)
    book.apply(buy.order_id, result)
    book.apply(buy.order_id, result)
    item = candidate(req, state, identifier="next")
    result = checks(req, state, item)
    assert result["symbol_order_limit_reached"].observed == "1"
    assert not result["symbol_order_limit_reached"].allowed


def test_round_trip_losses_are_derived_from_lifecycle_cash_flows():
    req, book, state = setup(scenario(commission="1"))
    buy = book.reserve(intent(req, quantity="1"), 4)
    book.apply(
        buy.order_id, ConfiguredOrderSession(configured(book, req, buy.order_id)).advance_to(LATER)
    )
    state.observe(LATER, tuple(e.quote for e in req.markets if e.cursor.occurred_at == LATER))
    sell = book.reserve(intent(req, identifier="sell", quantity="1", side=Side.SELL, at=LATER), 3)
    at = LATER + timedelta(seconds=1)
    book.apply(
        sell.order_id, ConfiguredOrderSession(configured(book, req, sell.order_id)).advance_to(at)
    )
    state.observe(at, ())
    loss = state.loss_snapshot()
    assert loss.consecutive_loss_count == 1 and loss.last_loss_at == at
    assert loss.daily_loss_pct == D(2)


def test_request_mismatch_cannot_reuse_a_risk_state():
    req, _, state = setup()
    item = candidate(req, state)
    with pytest.raises(ReplayValidationError):
        checks(replace(req, seed=req.seed + 1), state, item)


def test_wrong_book_even_with_same_initial_cash_is_rejected():
    req = scenario()
    changed = replace(req, markets=tuple(replace(e, available_quantity=D(1)) for e in req.markets))
    with pytest.raises(ReplayValidationError):
        api().ReplayRiskState(req, ReplayPortfolio(changed))


def test_planning_adapter_preserves_the_stop_basis():
    req = scenario()
    policy = derive_entry_policy(req, features(), D(10))
    adapted = planning_policy(policy, req)
    assert adapted.stop_distance_per_unit == D(2)
    assert adapted.minimum_reward_risk == D(2)
    assert adapted.maximum_holding_bars == 100
    assert adapted.version == policy.version


def test_economic_checks_ignore_ambient_decimal_precision():
    req, _, state = setup()
    item = candidate(req, state)
    expected = checks(req, state, item)
    with localcontext() as ctx:
        ctx.prec = 2
        assert checks(req, state, item) == expected


def test_skipping_an_exposed_quote_cannot_hide_an_equity_peak():
    base = scenario()
    req = replace(
        base,
        markets=tuple(
            replace(e, quote=replace(e.quote, bid=D(100), ask=D(100)))
            if e.cursor.occurred_at == LATER + timedelta(seconds=1)
            else e
            for e in base.markets
        ),
    )
    req, book, state = setup(req)
    buy = book.reserve(intent(req, quantity="2"), 4)
    book.apply(
        buy.order_id, ConfiguredOrderSession(configured(book, req, buy.order_id)).advance_to(LATER)
    )
    state.observe(LATER, tuple(e.quote for e in req.markets if e.cursor.occurred_at == LATER))
    at = LATER + timedelta(seconds=2)
    with pytest.raises(ReplayValidationError, match="replay_risk_history_gap"):
        state.observe(at, tuple(e.quote for e in req.markets if e.cursor.occurred_at == at))


def test_skipping_intermediate_fills_cannot_manufacture_complete_loss_history():
    req, book, state = setup()
    buy = book.reserve(intent(req, quantity="4"), 4)
    at = LATER + timedelta(seconds=1)
    book.apply(
        buy.order_id, ConfiguredOrderSession(configured(book, req, buy.order_id)).advance_to(at)
    )
    with pytest.raises(ReplayValidationError, match="replay_risk_history_gap"):
        state.observe(at, tuple(e.quote for e in req.markets if e.cursor.occurred_at == at))


def test_older_but_fresh_quote_cannot_hide_a_new_visible_mark():
    req, book, state = setup()
    buy = book.reserve(intent(req, quantity="2"), 4)
    book.apply(
        buy.order_id, ConfiguredOrderSession(configured(book, req, buy.order_id)).advance_to(LATER)
    )
    quotes = tuple(e.quote for e in req.markets if e.cursor.occurred_at == LATER)
    state.observe(LATER, quotes)
    with pytest.raises(ReplayValidationError, match="replay_risk_mark_not_latest"):
        state.observe(LATER + timedelta(seconds=1), quotes)


def test_old_quote_redelivery_cannot_displace_latest_mark():
    base = scenario()
    req, book, state = setup(replace(base, markets=(*base.markets, base.markets[0])))
    buy = book.reserve(intent(req, quantity="2"), 4)
    book.apply(
        buy.order_id, ConfiguredOrderSession(configured(book, req, buy.order_id)).advance_to(LATER)
    )
    state.observe(LATER, tuple(e.quote for e in base.markets if e.cursor.occurred_at == LATER))
    at = LATER + timedelta(seconds=1)
    snapshot = state.observe(at, tuple(e.quote for e in base.markets if e.cursor.occurred_at == at))
    assert snapshot.equity == D(100)


def test_drawdown_hard_stop_does_not_clear_on_a_later_recovery():
    base = scenario()
    req = replace(
        base,
        markets=tuple(
            replace(e, quote=replace(e.quote, bid=D(5)))
            if e.cursor.occurred_at == LATER + timedelta(seconds=1)
            else e
            for e in base.markets
        ),
    )
    req, book, state = setup(req)
    buy = book.reserve(intent(req, quantity="2"), 4)
    book.apply(
        buy.order_id, ConfiguredOrderSession(configured(book, req, buy.order_id)).advance_to(LATER)
    )
    for at in (LATER, LATER + timedelta(seconds=1), LATER + timedelta(seconds=2)):
        state.observe(at, tuple(e.quote for e in req.markets if e.cursor.occurred_at == at))
    assert state.loss_snapshot().peak_to_trough_drawdown_pct == D(10)
    decision = state.loss_decision(intent(req).purpose)
    assert not decision.allowed and decision.kill_switch_activation_requested


def test_daily_activity_cap_includes_each_rejected_intent_once():
    req, book, state = setup(rejected_request())
    for number in range(3):
        buy = book.reserve(intent(req, identifier=f"rejected-{number}", quantity="1"), 4)
        result = ConfiguredOrderSession(configured(book, req, buy.order_id)).advance_to(NOW)
        book.apply(buy.order_id, result)
        book.apply(buy.order_id, result)
    item = candidate(req, state, symbol="SECOND", identifier="next")
    decision = checks(req, state, item)["daily_order_limit_reached"]
    assert not decision.allowed and decision.observed == "3"


@pytest.mark.parametrize("microseconds,allowed", [(1799999999, False), (1800000000, True)])
def test_activity_spacing_uses_exact_canonical_boundary(microseconds, allowed):
    req, book, state = setup(rejected_request())
    buy = book.reserve(intent(req, quantity="1"), 4)
    book.apply(
        buy.order_id, ConfiguredOrderSession(configured(book, req, buy.order_id)).advance_to(NOW)
    )
    state.observe(NOW, ())
    at = NOW + timedelta(microseconds=microseconds)
    item = candidate(req, state, at=at, symbol="SECOND", identifier="next")
    result = checks(req, state, item, at)
    code = "activity_limits" if allowed else "minimum_order_interval_active"
    assert result[code].allowed is allowed


def test_three_loss_pause_uses_lifecycle_history_and_canonical_duration():
    from trading_bot.simulation.configured_models import SyntheticBarWindow
    from trading_bot.simulation.events import EventCursor

    base = scenario(commission="0.01")
    events = list(base.markets)
    for seconds in (5, 6):
        at = NOW + timedelta(seconds=seconds)
        for template in base.markets[:2]:
            events.append(
                replace(
                    template,
                    event_id=f"quote-{len(events)}",
                    cursor=EventCursor(len(events) + 2, at),
                    quote=replace(template.quote, observed_at=at),
                    clock=replace(template.clock, observed_at=at),
                    window=SyntheticBarWindow(at, at + timedelta(seconds=1)),
                )
            )
    slots = tuple(NOW + timedelta(seconds=s) for s in range(1, 7))
    req = replace(
        base,
        markets=tuple(events),
        end_at=NOW + timedelta(hours=5),
        sessions=tuple(replace(s, opportunity_times=slots) for s in base.sessions),
    )
    req, book, state = setup(req)
    for number in range(3):
        buy_at = NOW + timedelta(seconds=number * 2)
        buy = book.reserve(
            intent(req, identifier=f"buy-{number}", quantity="1", at=buy_at), 6 - number * 2
        )
        at = buy_at + timedelta(seconds=1)
        book.apply(
            buy.order_id, ConfiguredOrderSession(configured(book, req, buy.order_id)).advance_to(at)
        )
        state.observe(at, tuple(e.quote for e in req.markets if e.cursor.occurred_at == at))
        sell = book.reserve(
            intent(req, identifier=f"sell-{number}", quantity="1", side=Side.SELL, at=at),
            5 - number * 2,
        )
        at += timedelta(seconds=1)
        result = ConfiguredOrderSession(configured(book, req, sell.order_id)).advance_to(at)
        book.apply(sell.order_id, result)
        book.apply(sell.order_id, result)
        state.observe(at, ())
    snapshot = state.loss_snapshot()
    assert snapshot.consecutive_loss_count == 3
    assert snapshot.daily_loss_pct == D("0.06")
    decision = state.loss_decision(intent(req).purpose)
    assert not decision.allowed
    assert decision.reason_code == "consecutive_loss_pause_active"
    boundary = NOW + timedelta(seconds=6, minutes=240)
    assert decision.entry_pause_until == boundary
    state.observe(boundary, ())
    assert state.loss_decision(intent(req).purpose).allowed


def test_economic_checks_need_no_network_or_database(monkeypatch):
    import socket
    import sqlite3

    req, _, state = setup()
    item = candidate(req, state)

    def forbidden(*args, **kwargs):
        pytest.fail("offline economic checks attempted I/O")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    assert all(c.allowed for c in checks(req, state, item).values())
