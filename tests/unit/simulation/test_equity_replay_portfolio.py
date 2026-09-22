"""Literal conservation tests: no debit on reserve, cash reuse, or double application."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.simulation._equity_portfolio_fixtures import configured, intent, scenario
from tests.unit.simulation._equity_replay_fixtures import LATER, NOW, STOP
from trading_bot.domain import Side
from trading_bot.simulation.configured import ConfiguredOrderSession, simulate_configured_order
from trading_bot.simulation.configured_models import SyntheticCancelRequest
from trading_bot.simulation.equity_replay_models import ReplayValidationError
from trading_bot.simulation.equity_replay_portfolio import ReplayPortfolio as portfolio
from trading_bot.simulation.events import EventCursor


def reserve(book, req, **changes):
    item = intent(req, **changes)
    slots = sum(
        item.created_at < t < item.expires_at
        for s in req.sessions
        if s.instrument_id == item.instrument_id
        for t in s.opportunity_times
    )
    outcome = book.reserve(item, slots)
    assert outcome.accepted
    return outcome.order_id


def quotes(req, at=LATER):
    return tuple(e.quote for e in req.markets if e.cursor.occurred_at == at)


def test_reservations_are_disjoint_allocations_not_cash_debits():
    req = scenario()
    book = portfolio(req)
    reserve(book, req)
    assert (book.cash, book.allocatable_cash, book.reserved_cash) == (D(100), D(40), D(60))
    outcome = book.reserve(intent(req, identifier="buy-2", instrument="SECOND", quantity="5"), 4)
    assert not outcome.accepted
    assert outcome.reasons == ("replay_insufficient_cash",)
    assert book.cash == D(100)
    assert book.allocatable_cash == D(40)


def test_cancel_without_fills_releases_allocation_once():
    req = scenario()
    book = portfolio(req)
    order_id = reserve(book, req)
    cancel = SyntheticCancelRequest("cancel", EventCursor(2, LATER))
    result = simulate_configured_order(configured(book, req, order_id, events=(cancel,)))
    book.apply(order_id, result)
    book.apply(order_id, result)
    assert (book.cash, book.allocatable_cash, book.reserved_cash, book.fees) == (
        D(100),
        D(100),
        D(0),
        D(0),
    )
    assert book.orders_terminal and book.positions_flat


def test_partial_fill_uses_lifecycle_cash_and_charges_fee_only_once():
    req = scenario(commission="1")
    book = portfolio(req)
    order_id = reserve(book, req)
    assert book.allocatable_cash == D(36)  # 60 notional + four possible commissions.
    session = ConfiguredOrderSession(configured(book, req, order_id))
    result = session.advance_to(LATER)
    book.apply(order_id, result)
    book.apply(order_id, result)
    assert (book.cash, book.allocatable_cash, book.reserved_cash, book.fees) == (
        D(79),
        D(36),
        D(43),
        D(1),
    )
    snapshot = book.snapshot(LATER, quotes(req))
    assert snapshot.positions[0].quantity == D(2)
    assert snapshot.cash == D(79)
    assert snapshot.equity == D(99)
    assert snapshot.realized_pnl == D(0)
    assert snapshot.unrealized_pnl == D(-1)
    assert not book.orders_terminal and not book.positions_flat


def test_fill_then_expiry_releases_only_unused_balance_and_leaves_position_open():
    req = scenario(commission="1")
    book = portfolio(req)
    order_id = reserve(book, req)
    first = next(e for e in req.markets if e.quote.instrument_id == "SYNTH")
    result = simulate_configured_order(configured(book, req, order_id, events=(first,)))
    book.apply(order_id, result)
    assert (book.cash, book.allocatable_cash, book.reserved_cash) == (D(79), D(79), D(0))
    assert book.orders_terminal and not book.positions_flat


def test_fee_bound_depends_on_declared_schedule_not_deliveries():
    populated, empty = scenario(commission="1"), scenario(commission="1", deliveries=False)
    left, right = portfolio(populated), portfolio(empty)
    assert reserve(left, populated) == reserve(right, empty)
    assert left.initial_order(left.orders[0].initial.order.id) == right.orders[0].initial
    assert left.allocatable_cash == right.allocatable_cash == D(36)


@pytest.mark.parametrize("count", [0, 3, 5, True, D(4)])
def test_caller_cannot_understate_or_invent_fee_capacity(count):
    req = scenario(commission="1")
    book = portfolio(req)
    with pytest.raises(ReplayValidationError):
        book.reserve(intent(req), count)
    assert book.cash == book.allocatable_cash == D(100)
    assert not book.valid


def test_one_active_order_per_symbol_and_no_averaging_down():
    req = scenario()
    book = portfolio(req)
    order_id = reserve(book, req, quantity="2")
    assert book.reserve(intent(req, identifier="another"), 4).reasons == ("replay_instrument_busy",)
    result = ConfiguredOrderSession(configured(book, req, order_id)).advance_to(LATER)
    book.apply(order_id, result)
    assert book.reserve(intent(req, identifier="add", at=LATER, quantity="1"), 3).reasons == (
        "replay_position_already_open",
    )


def test_sell_reserves_existing_shares_and_proceeds_until_terminal():
    req = scenario(commission="1")
    book = portfolio(req)
    buy = reserve(book, req, quantity="4")
    buy_result = ConfiguredOrderSession(configured(book, req, buy)).advance_to(
        NOW + timedelta(seconds=2)
    )
    book.apply(buy, buy_result)
    at = NOW + timedelta(seconds=2)
    assert book.cash == book.allocatable_cash == D(58)
    denied = book.reserve(
        intent(req, identifier="oversell", quantity="5", side=Side.SELL, at=at), 2
    )
    assert denied.reasons == ("replay_insufficient_shares",)
    sell = reserve(book, req, identifier="sell", quantity="4", side=Side.SELL, at=at)
    assert book.reserved_shares == (("SYNTH", D(4)),)
    session = ConfiguredOrderSession(configured(book, req, sell))
    partial = session.advance_to(NOW + timedelta(seconds=3))
    book.apply(sell, partial)
    assert (book.cash, book.allocatable_cash, book.reserved_cash) == (D(77), D(58), D(19))
    assert book.reserved_shares == (("SYNTH", D(2)),)
    book.apply(sell, session.advance_to(NOW + timedelta(seconds=4)))
    snap = book.snapshot(NOW + timedelta(seconds=4), ())
    assert (snap.cash, snap.realized_pnl, snap.unrealized_pnl) == (D(96), D(-4), D(0))
    assert book.orders_terminal and book.positions_flat
    assert book.allocatable_cash == D(96)


def test_identical_intent_redelivery_does_not_allocate_twice():
    req = scenario()
    book = portfolio(req)
    item = intent(req)
    assert book.reserve(item, 4) == book.reserve(item, 4)
    assert book.allocatable_cash == D(40)
    assert len(book.orders) == len(book.outcomes) == 1


def test_regressive_result_invalidates_run_without_changing_balances():
    req = scenario()
    book = portfolio(req)
    order_id = reserve(book, req)
    session = ConfiguredOrderSession(configured(book, req, order_id))
    first = session.advance_to(LATER)
    book.apply(order_id, first)
    book.apply(order_id, session.advance_to(LATER + timedelta(seconds=1)))
    with pytest.raises(ReplayValidationError):
        book.apply(order_id, first)
    assert book.cash == D(60) and book.fees == D(0)
    assert not book.valid
    with pytest.raises(ReplayValidationError):
        book.reserve(intent(req, identifier="later", instrument="SECOND"), 4)


def test_forged_cash_is_rejected_before_any_portfolio_publication():
    req = scenario()
    book = portfolio(req)
    order_id = reserve(book, req)
    result = ConfiguredOrderSession(configured(book, req, order_id)).advance_to(LATER)
    fake = replace(
        result,
        lifecycle=replace(
            result.lifecycle, snapshot=replace(result.lifecycle.snapshot, cash=D(99))
        ),
    )
    with pytest.raises(ReplayValidationError):
        book.apply(order_id, fake)
    assert book.cash == D(100) and book.positions_flat
    assert not book.valid


@pytest.mark.parametrize("kind", ["missing", "future", "stale", "unverified", "provider"])
def test_open_positions_never_use_missing_stale_future_or_unverified_marks(kind):
    req = scenario()
    book = portfolio(req)
    order_id = reserve(book, req, quantity="2")
    book.apply(order_id, ConfiguredOrderSession(configured(book, req, order_id)).advance_to(LATER))
    q = quotes(req)[0]
    if kind == "missing":
        values = ()
    else:
        changes = {
            "future": {"observed_at": STOP},
            "stale": {"observed_at": NOW - timedelta(days=1)},
            "unverified": {"freshness_verified": False},
            "provider": {"source": "provider"},
        }[kind]
        values = (replace(q, **changes),)
    with pytest.raises(ReplayValidationError):
        book.snapshot(LATER, values)


def test_accounting_is_independent_of_ambient_decimal_precision():
    req = scenario(commission="1")
    with localcontext() as context:
        context.prec = 2
        book = portfolio(req)
        order_id = reserve(book, req)
        book.apply(
            order_id, ConfiguredOrderSession(configured(book, req, order_id)).advance_to(LATER)
        )
        assert book.snapshot(LATER, quotes(req)).equity == D(99)


def test_future_delivery_changes_cannot_change_current_portfolio_identity():
    original = scenario()
    changed = replace(
        original,
        markets=tuple(
            replace(e, available_quantity=D(1)) if e.cursor.occurred_at > LATER else e
            for e in original.markets
        ),
    )
    snapshots = []
    for req in (original, changed):
        book = portfolio(req)
        order_id = reserve(book, req)
        book.apply(
            order_id, ConfiguredOrderSession(configured(book, req, order_id)).advance_to(LATER)
        )
        snapshots.append(book.snapshot(LATER, quotes(req)))
    assert snapshots[0] == snapshots[1]


def test_old_terminal_redelivery_cannot_overwrite_later_exit_position():
    req = scenario()
    book = portfolio(req)
    buy = reserve(book, req, quantity="2")
    result = ConfiguredOrderSession(configured(book, req, buy)).advance_to(LATER)
    book.apply(buy, result)
    sell = reserve(book, req, identifier="sell", quantity="2", side=Side.SELL, at=LATER)
    at = LATER + timedelta(seconds=1)
    book.apply(sell, ConfiguredOrderSession(configured(book, req, sell)).advance_to(at))
    book.apply(buy, result)
    assert book.positions_flat and book.cash == D(100)


@pytest.mark.parametrize("kind", ["account", "config", "instrument", "expiry", "tick", "lot"])
def test_invalid_intent_cannot_create_allocation(kind):
    req = scenario()
    book = portfolio(req)
    changes = {
        "account": {"account_id": "synthetic:wrong"},
        "config": {"config_hash": "e" * 64},
        "instrument": {"instrument_id": "OTHER"},
        "expiry": {"expires_at": STOP + timedelta(seconds=1)},
        "tick": {"limit_price": D("10.001")},
        "lot": {"quantity": D("1.0001")},
    }[kind]
    with pytest.raises(ReplayValidationError):
        book.reserve(intent(req, **changes), 4)
    assert book.cash == book.allocatable_cash == D(100)
    assert not book.orders


def test_conflicting_intent_redelivery_invalidates_without_extra_allocation():
    req = scenario()
    book = portfolio(req)
    reserve(book, req)
    with pytest.raises(ReplayValidationError):
        book.reserve(intent(req, quantity="5"), 4)
    assert book.cash == D(100) and book.allocatable_cash == D(40)


def test_fees_omitted_in_self_consistent_lifecycle_are_rejected():
    from trading_bot.simulation.configured_codec import configured_hash
    from trading_bot.simulation.lifecycle import replay_order_lifecycle
    from trading_bot.simulation.lifecycle_models import LifecycleFillEvent

    req = scenario(commission="1")
    book = portfolio(req)
    order_id = reserve(book, req)
    result = ConfiguredOrderSession(configured(book, req, order_id)).advance_to(LATER)
    events = tuple(
        replace(e, fill=replace(e.fill, fee=D(0))) if type(e) is LifecycleFillEvent else e
        for e in result.events
    )
    lifecycle = replay_order_lifecycle(replace(book.initial_order(order_id), events=events))
    corrupted = replace(
        result,
        events=events,
        lifecycle=lifecycle,
        result_hash=configured_hash(
            "result",
            {
                "input": result.input_hash,
                "settings": result.settings_hash,
                "events": events,
                "decisions": result.decisions,
                "lifecycle": lifecycle,
            },
        ),
    )
    with pytest.raises(ReplayValidationError):
        book.apply(order_id, corrupted)
    assert book.cash == D(100) and book.fees == D(0)


def test_two_symbols_apply_from_independent_allocations_in_event_time_order():
    req = scenario()
    book = portfolio(req)
    first = reserve(book, req)
    second = reserve(book, req, identifier="buy-2", instrument="SECOND", quantity="4")
    left = ConfiguredOrderSession(configured(book, req, first))
    right = ConfiguredOrderSession(configured(book, req, second))
    book.apply(first, left.advance_to(NOW))
    book.apply(second, right.advance_to(NOW))
    book.apply(first, left.advance_to(LATER))
    book.apply(second, right.advance_to(LATER))
    assert (book.cash, book.allocatable_cash, book.reserved_cash) == (D(60), D(0), D(60))
    snap = book.snapshot(LATER, quotes(req))
    assert tuple(p.quantity for p in snap.positions) == (D(2), D(2))
    assert snap.equity == D(100)


def test_funding_failure_does_not_invalidate_well_formed_replay():
    req = scenario()
    book = portfolio(req)
    denial = book.reserve(intent(req, quantity="11"), 4)
    assert not denial.accepted
    assert book.valid and book.cash == D(100)
    assert book.reserve(intent(req, quantity="11"), 4) == denial


def test_mark_is_bid_not_cost_basis_or_ask():
    original = scenario()
    req = replace(
        original,
        markets=tuple(replace(e, quote=replace(e.quote, bid=D(9))) for e in original.markets),
    )
    book = portfolio(req)
    order_id = reserve(book, req, quantity="2")
    book.apply(order_id, ConfiguredOrderSession(configured(book, req, order_id)).advance_to(LATER))
    snapshot = book.snapshot(LATER, quotes(req))
    assert snapshot.gross_exposure == snapshot.net_exposure == D(18)
    assert snapshot.equity == D(98)
    assert snapshot.unrealized_pnl == D(-2)


def test_freshness_boundary_uses_recorded_quote_and_exact_microseconds():
    req = scenario()
    book = portfolio(req)
    order_id = reserve(book, req, quantity="2")
    book.apply(order_id, ConfiguredOrderSession(configured(book, req, order_id)).advance_to(LATER))
    assert book.snapshot(LATER + timedelta(seconds=5), quotes(req)).equity == D(100)
    with pytest.raises(ReplayValidationError, match="replay_mark_stale"):
        book.snapshot(LATER + timedelta(seconds=5, microseconds=1), quotes(req))


def test_result_cannot_arrive_before_the_last_shared_event():
    req = scenario()
    book = portfolio(req)
    first = reserve(book, req)
    second = reserve(book, req, identifier="buy-2", instrument="SECOND", quantity="4")
    book.apply(first, ConfiguredOrderSession(configured(book, req, first)).advance_to(LATER))
    with pytest.raises(ReplayValidationError, match="replay_ordering_invalid"):
        book.apply(second, ConfiguredOrderSession(configured(book, req, second)).advance_to(NOW))
    assert book.cash == D(80) and not book.valid


def test_two_fills_in_one_declared_slot_cannot_exceed_fee_capacity():
    from trading_bot.simulation.configured_codec import configured_hash
    from trading_bot.simulation.lifecycle import replay_order_lifecycle

    req = scenario(commission="1")
    book = portfolio(req)
    order_id = reserve(book, req)
    result = ConfiguredOrderSession(configured(book, req, order_id)).advance_to(LATER)
    original = result.events[-1]
    duplicate_slot = replace(
        original,
        event_id="second-fill",
        cursor=EventCursor(3, LATER),
        fill=replace(original.fill, id="second-fill"),
    )
    events = (*result.events, duplicate_slot)
    lifecycle = replay_order_lifecycle(replace(book.initial_order(order_id), events=events))
    fake = replace(
        result,
        events=events,
        lifecycle=lifecycle,
        result_hash=configured_hash(
            "result",
            {
                "input": result.input_hash,
                "settings": result.settings_hash,
                "events": events,
                "decisions": result.decisions,
                "lifecycle": lifecycle,
            },
        ),
    )
    with pytest.raises(ReplayValidationError, match="replay_fill_contract_invalid"):
        book.apply(order_id, fake)
    assert book.cash == D(100) and book.fees == D(0)


@pytest.mark.parametrize("field", ["settings_hash", "result_hash"])
def test_result_identity_mismatch_keeps_published_cash(field):
    req = scenario()
    book = portfolio(req)
    order_id = reserve(book, req)
    result = ConfiguredOrderSession(configured(book, req, order_id)).advance_to(LATER)
    with pytest.raises(ReplayValidationError, match="replay_result_identity_invalid"):
        book.apply(order_id, replace(result, **{field: "e" * 64}))
    assert book.cash == D(100) and not book.valid


def test_partial_exit_is_not_a_completed_round_trip():
    req = scenario(commission="1")
    book = portfolio(req)
    buy = reserve(book, req, quantity="4")
    at = NOW + timedelta(seconds=2)
    book.apply(buy, ConfiguredOrderSession(configured(book, req, buy)).advance_to(at))
    sell = reserve(book, req, identifier="sell", quantity="2", side=Side.SELL, at=at)
    at += timedelta(seconds=1)
    book.apply(sell, ConfiguredOrderSession(configured(book, req, sell)).advance_to(at))
    snapshot = book.snapshot(at, quotes(req, at))
    assert snapshot.cash == D(77)
    assert snapshot.realized_pnl == D(0)
    assert snapshot.unrealized_pnl == D(-3)
    assert book.orders_terminal and not book.positions_flat


def test_portfolio_does_not_require_network_or_database_capabilities(monkeypatch):
    import socket
    import sqlite3

    req = scenario()

    def forbidden(*args, **kwargs):
        pytest.fail("offline portfolio attempted external I/O")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    book = portfolio(req)
    order_id = reserve(book, req, quantity="2")
    book.apply(order_id, ConfiguredOrderSession(configured(book, req, order_id)).advance_to(LATER))
    assert book.snapshot(LATER, quotes(req)).cash == D(80)


def test_rejected_submission_releases_reservation_without_a_position():
    from trading_bot.config import AppConfig, LoadedConfig
    from trading_bot.config.hashing import hash_loaded_config

    base = scenario()
    values = base.loaded.config.model_dump()
    values["simulation"].update(rejection_probability_pct=D(100), full_fill_probability_pct=D(0))
    config = AppConfig.model_validate(values)
    canonical, digest = hash_loaded_config(config, base.loaded.safety_envelope)
    req = replace(base, loaded=LoadedConfig(config, base.loaded.safety_envelope, canonical, digest))
    book = portfolio(req)
    order_id = reserve(book, req)
    book.apply(order_id, ConfiguredOrderSession(configured(book, req, order_id)).advance_to(NOW))
    assert book.cash == book.allocatable_cash == D(100)
    assert book.orders_terminal and book.positions_flat


def test_result_cannot_hide_event_time_by_dropping_configured_decisions():
    from trading_bot.simulation.configured_codec import configured_hash

    req = scenario()
    book = portfolio(req)
    order_id = reserve(book, req, quantity="2")
    result = ConfiguredOrderSession(configured(book, req, order_id)).advance_to(LATER)
    forged = replace(
        result,
        decisions=(),
        result_hash=configured_hash(
            "result",
            {
                "input": result.input_hash,
                "settings": result.settings_hash,
                "events": result.events,
                "decisions": (),
                "lifecycle": result.lifecycle,
            },
        ),
    )
    with pytest.raises(ReplayValidationError, match="replay_result_identity_invalid"):
        book.apply(order_id, forged)
    assert book.cash == D(100) and book.positions_flat
