"""Adversarial fabricated finality evidence; not authenticated observations."""

from dataclasses import replace
from decimal import Decimal

import pytest

from tests.unit.simulation.test_etf_capital_account import opening, script
from trading_bot.simulation.etf_capital_account import replay_capital_account


@pytest.mark.parametrize("field", ["intent_id", "client_order_id"])
def test_optional_submission_identifiers_are_bounded_before_hashing(field):
    event = opening()
    with pytest.raises(ValueError):
        replace(
            event,
            request=replace(
                event.request, order=replace(event.request.order, **{field: "x" * 257})
            ),
        )


def old_script():
    from trading_bot.simulation.etf_capital_account import CapitalFeesFinal

    events = script()
    final = events[-1]
    return (*events[:-1], CapitalFeesFinal(final.event_id, final.cursor, final.total_fees))


def test_unbound_legacy_finality_cannot_release_current_reservations():
    with pytest.raises(ValueError):
        replay_capital_account(initial_cash=Decimal("100"), events=old_script())


@pytest.mark.parametrize("account,episode", [("another-account", "order-0"), (None, "old-entry")])
def test_equal_fee_finality_for_other_account_or_episode_denies(account, episode):
    from trading_bot.simulation.etf_capital_account import CapitalEpisodeFeesFinal

    events = script()
    final = events[-1]
    bound = CapitalEpisodeFeesFinal(
        final.event_id,
        final.cursor,
        final.total_fees,
        account or events[0].request.order.account_id,
        episode,
    )
    with pytest.raises(ValueError):
        replay_capital_account(initial_cash=Decimal("100"), events=(*events[:-1], bound))


def test_explicit_historical_reader_retains_original_v1_hash():
    from trading_bot.simulation.etf_capital_account import replay_capital_account_v1

    old = replay_capital_account_v1(initial_cash=Decimal("100"), events=old_script())
    assert old.economic_hash == "1213ed107e0b282c94fbc5014fee3751107d965c0e412bc94159cdaa3fc18ce8"
    assert old.cash == Decimal("100.11")
    assert not old.execution_enabled and not old.evidence_promotable


@pytest.mark.parametrize("field", ["intent_id", "client_order_id"])
@pytest.mark.parametrize("value", [None, "x" * 256])
def test_optional_identifier_boundary_remains_readable(field, value):
    event = opening()
    original = replace(
        event, request=replace(event.request, order=replace(event.request.order, **{field: value}))
    )
    assert replay_capital_account(initial_cash=Decimal("100"), events=(original,)).cash == Decimal(
        "100"
    )


def test_current_bound_completion_has_distinct_versioned_identity():
    current = replay_capital_account(initial_cash=Decimal("100"), events=script())
    assert current.cash == Decimal("100.11")
    assert current.complete
    assert (
        current.economic_hash != "1213ed107e0b282c94fbc5014fee3751107d965c0e412bc94159cdaa3fc18ce8"
    )
    assert not current.execution_enabled and not current.evidence_promotable


def test_historical_reader_cannot_interpret_bound_v2_finality_as_v1():
    from trading_bot.simulation.etf_capital_account import replay_capital_account_v1

    with pytest.raises(ValueError):
        replay_capital_account_v1(initial_cash=Decimal("100"), events=script())
