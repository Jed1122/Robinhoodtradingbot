"""Configured exit boundaries; synthetic triggers never claim executions."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import Decimal as D
from decimal import localcontext
from importlib import import_module
from importlib.util import find_spec

import pytest

from tests.unit.simulation._equity_portfolio_fixtures import configured, intent, scenario
from tests.unit.simulation._equity_replay_fixtures import LATER, NOW
from trading_bot.domain import ConfigHash, DataHash
from trading_bot.simulation.configured import ConfiguredOrderSession
from trading_bot.simulation.equity_replay_models import ReplayCandidate, ReplayValidationError
from trading_bot.simulation.equity_replay_portfolio import ReplayPortfolio
from trading_bot.strategies.protocol import FeatureSnapshot, FeatureVector, StrategyContext


def api():
    name = "trading_bot.simulation.equity_replay_policy"
    assert find_spec(name) is not None, "configured replay exits are missing"
    return import_module(name)


def features(*, symbol="SYNTH", at=NOW, **values):
    defaults = dict(
        average_true_range=D(1),
        total_return_pct=D(2),
        moving_average_short=D(11),
        moving_average_long=D(10),
        latest_close=D(12),
    )
    defaults.update(values)
    return FeatureVector(symbol, at, tuple(defaults.items()), DataHash("a" * 64))


def filled_policy(req, *, quantity="4"):
    policy = api().derive_entry_policy(req, features(), D(10))
    book = ReplayPortfolio(req)
    item = intent(req, quantity=quantity, exit_policy_version=policy.version)
    outcome = book.reserve(item, 4)
    session = ConfiguredOrderSession(configured(book, req, outcome.order_id))
    book.apply(outcome.order_id, session.advance_to(LATER))
    return api().observe_entry(policy, book.orders[0], (), LATER, req), book, session


def test_atr_stop_and_target_are_derived_from_canonical_settings():
    req = scenario()
    policy = api().derive_entry_policy(req, features(), D(10))
    assert (policy.entry_limit, policy.stop_distance, policy.stop_price, policy.target_price) == (
        D(10),
        D(2),
        D(8),
        D(14),
    )
    assert policy.first_fill_at is None and policy.holding_bars == 0
    with pytest.raises(FrozenInstanceError):
        policy.stop_price = D(7)


@pytest.mark.parametrize("atr", [None, D(0), D(-1), D(5), True, "1"])
def test_unusable_atr_cannot_create_entry_policy(atr):
    with pytest.raises(ReplayValidationError):
        api().derive_entry_policy(scenario(), features(average_true_range=atr), D(10))


@pytest.mark.parametrize(
    "bid,selected,expected",
    [
        ("8", False, "replay_stop_triggered"),
        ("7", True, "replay_stop_triggered"),
        ("14", False, "replay_target_triggered"),
        ("13.99", True, None),
        ("10", False, "replay_regime_exit"),
        ("10", None, None),
    ],
)
def test_exit_trigger_priority_and_boundaries(bid, selected, expected):
    base = scenario()
    req = replace(
        base,
        markets=tuple(
            replace(e, quote=replace(e.quote, bid=D(bid), ask=max(D(15), D(bid))))
            if e.cursor.occurred_at > LATER
            else e
            for e in base.markets
        ),
    )
    policy, _, _ = filled_policy(req)
    event = req.markets[2]
    assert (
        api().exit_reason(policy, event.quote, selected, event.cursor.occurred_at, req) == expected
    )


def test_partial_fill_does_not_reset_first_fill_or_reprice_stop():
    req = scenario()
    policy, book, session = filled_policy(req)
    book.apply(book.orders[0].initial.order.id, session.advance_to(LATER + timedelta(seconds=1)))
    updated = api().observe_entry(policy, book.orders[0], (), LATER + timedelta(seconds=1), req)
    assert updated.first_fill_at == LATER
    assert (updated.stop_distance, updated.stop_price, updated.target_price, updated.version) == (
        D(2),
        D(8),
        D(14),
        policy.version,
    )


def test_holding_time_counts_only_complete_bars_after_first_fill():
    from tests.unit.strategies.test_features import bars as history_bars

    req = replace(scenario(), end_at=NOW + timedelta(days=102))
    policy, book, _ = filled_policy(req)
    # Bar records are explicit; no calendar or future high/low is consulted for triggers.
    prototype = history_bars(1)[0]
    bars = tuple(
        replace(
            prototype,
            instrument_id="SYNTH",
            starts_at=LATER + timedelta(days=i),
            ends_at=LATER + timedelta(days=i + 1),
        )
        for i in range(101)
    )
    at = LATER + timedelta(days=100)
    updated = api().observe_entry(policy, book.orders[0], bars[:100], at, req)
    assert updated.holding_bars == 100
    quote = replace(req.markets[0].quote, observed_at=at)
    assert api().exit_reason(updated, quote, True, at, req) == "replay_maximum_holding"
    before = api().observe_entry(policy, book.orders[0], bars[:99], at, req)
    assert api().exit_reason(before, quote, True, at, req) is None
    with pytest.raises(ReplayValidationError):
        api().observe_entry(policy, book.orders[0], bars, at, req)


@pytest.mark.parametrize("kind", ["missing", "future", "stale", "unverified", "wrong_symbol"])
def test_invalid_quote_does_not_trigger_exit(kind):
    req = scenario()
    policy, _, _ = filled_policy(req)
    quote = req.markets[0].quote
    if kind == "missing":
        quote = None
    else:
        quote = replace(
            quote,
            **{
                "future": {"observed_at": LATER + timedelta(seconds=1)},
                "stale": {"observed_at": NOW - timedelta(days=1)},
                "unverified": {"freshness_verified": False},
                "wrong_symbol": {"instrument_id": "SECOND"},
            }[kind],
        )
    with pytest.raises(ReplayValidationError):
        api().exit_reason(policy, quote, False, LATER, req)


def test_selection_reuses_momentum_predicate_and_relative_strength_schedule():
    req = scenario()
    context = StrategyContext(
        NOW,
        FeatureSnapshot(
            NOW,
            (
                features(),
                features(symbol="SECOND", total_return_pct=D(3), moving_average_short=D(9)),
            ),
            DataHash("b" * 64),
        ),
        ConfigHash(req.loaded.config_hash),
        ("SYNTH", "SECOND"),
    )
    assert api().selected_instruments(req, context, completed_bars=1) == ("SYNTH",)
    relative = replace(
        req, candidate=ReplayCandidate("equity_relative_strength", 20, 100, 1, D("0.5"))
    )
    assert api().selected_instruments(relative, context, completed_bars=4) is None
    assert api().selected_instruments(relative, context, completed_bars=5) == ("SECOND",)


def test_future_features_do_not_become_a_regime_exit():
    req = scenario()
    context = StrategyContext(
        NOW,
        FeatureSnapshot(NOW, (features(at=LATER),), DataHash("b" * 64)),
        ConfigHash(req.loaded.config_hash),
        ("SYNTH",),
    )
    with pytest.raises(ReplayValidationError):
        api().selected_instruments(req, context, completed_bars=1)


def test_policy_is_independent_of_ambient_decimal_precision():
    req = scenario()
    with localcontext() as ctx:
        ctx.prec = 2
        policy = api().derive_entry_policy(req, features(average_true_range=D("1.234")), D(10))
    assert policy.stop_price == D("7.532") and policy.target_price == D("14.936")


def test_entry_record_cannot_change_account_or_intent_identity():
    req = scenario()
    policy, book, _ = filled_policy(req)
    wrong = replace(
        book.orders[0], intent=replace(book.orders[0].intent, account_id="synthetic:other")
    )
    with pytest.raises(ReplayValidationError):
        api().observe_entry(policy, wrong, (), LATER, req)


def test_entry_record_cannot_change_submitted_quantity():
    req = scenario()
    policy, book, _ = filled_policy(req)
    wrong = replace(book.orders[0], intent=replace(book.orders[0].intent, quantity=D(2)))
    with pytest.raises(ReplayValidationError):
        api().observe_entry(policy, wrong, (), LATER, req)


def test_unfilled_entry_does_not_trigger_exit():
    req = scenario()
    policy = api().derive_entry_policy(req, features(), D(10))
    assert (
        api().exit_reason(policy, replace(req.markets[0].quote, bid=D(8)), False, LATER, req)
        is None
    )


def test_stop_and_target_take_priority_over_maximum_holding():
    req = scenario()
    policy, _, _ = filled_policy(req)
    policy = replace(policy, holding_bars=req.loaded.config.equity_strategies.maximum_holding_bars)
    quote = req.markets[0].quote
    assert (
        api().exit_reason(policy, replace(quote, bid=D(8)), False, LATER, req)
        == "replay_stop_triggered"
    )
    assert (
        api().exit_reason(policy, replace(quote, bid=D(14), ask=D(14)), False, LATER, req)
        == "replay_target_triggered"
    )


def test_relative_strength_deselection_uses_configured_exit_kind():
    req = replace(
        scenario(), candidate=ReplayCandidate("equity_relative_strength", 20, 100, 1, D("0.5"))
    )
    policy, _, _ = filled_policy(req)
    assert api().exit_reason(policy, req.markets[0].quote, False, LATER, req) == "replay_deselected"
    assert api().exit_reason(policy, req.markets[0].quote, None, LATER, req) is None
