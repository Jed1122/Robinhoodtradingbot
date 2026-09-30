import random
import socket
import time
from dataclasses import FrozenInstanceError, replace
from decimal import ROUND_UP, Inexact, localcontext
from decimal import Decimal as D
from pathlib import Path

import pytest

from trading_bot.domain import OrderState, Side
from trading_bot.simulation.configured import simulate_configured_order
from trading_bot.simulation.configured_models import ConfiguredValidationError
from trading_bot.simulation.lifecycle_models import LifecycleErrorReason

from ._configured_fixtures import at, cancel, market, request, settings
from ._lifecycle_fixtures import make_request


def test_duplicate_after_terminal_does_not_reuse_liquidity_or_charge_fees():
    event = market()
    one = simulate_configured_order(request(events=(event,)))
    repeated = simulate_configured_order(request(events=(event, event)))
    assert repeated.lifecycle == one.lifecycle
    assert repeated.events == one.events
    assert repeated.result_hash != one.result_hash
    assert repeated.input_hash != one.input_hash
    duplicate = repeated.decisions[-1]
    assert duplicate.reason.value == "duplicate_event"
    assert duplicate.delivery_index == 1
    assert duplicate.original_event_id == event.event_id
    assert duplicate.generated_event_ids == ()


def test_duplicate_cancel_does_not_redraw_race_or_schedule_second_ack():
    action = cancel()
    quote = market("race", 2, 1200, available_quantity=D("0.25"))
    config = settings(cancel_race_probability_pct=D(100))
    first = simulate_configured_order(request(events=(action, quote), simulation=config))
    again = simulate_configured_order(request(events=(action, quote, action), simulation=config))
    assert first.lifecycle == again.lifecycle
    assert first.events == again.events


def test_future_suffix_and_duplicates_do_not_rewrite_prior_fills():
    config = settings(full_fill_probability_pct=D(0), partial_fill_probability_pct=D(100))
    first_event = market()
    first = simulate_configured_order(
        request(events=(first_event,), simulation=config, end_at=at(1500))
    )
    extended = simulate_configured_order(
        request(events=(first_event, first_event, market("later", 2, 2000)), simulation=config)
    )
    assert first.events == extended.events[: len(first.events)]
    assert first.decisions[1].partial_percentage == extended.decisions[1].partial_percentage
    assert first.input_hash != extended.input_hash


def test_settings_and_seed_changes_are_hash_bound_without_output_promotion():
    original = request(events=(market(),))
    result = simulate_configured_order(original)
    for changed in (
        replace(original, seed=8),
        replace(
            original, costs=original.costs.model_copy(update={"assumed_crypto_spread_pct": D(2)})
        ),
    ):
        other = simulate_configured_order(changed)
        assert other.input_hash != result.input_hash
        assert other.result_hash != result.result_hash
        assert not other.evidence_promotable and not other.assumptions_validated
    with pytest.raises((TypeError, ValueError), match="init=False"):
        replace(result, evidence_promotable=True)
    assert result.evidence_promotable is False
    with pytest.raises(FrozenInstanceError):
        result.result_hash = "wrong"


@pytest.mark.parametrize(
    "initial", [make_request(cash="1"), make_request(side=Side.SELL, position_quantity="0")]
)
def test_insufficient_balances_fail_without_resizing_or_returning_partial_result(initial):
    event = market()
    if initial.order.side is Side.SELL:
        event = replace(event, quote=replace(event.quote, bid=D(101), ask=D(102)))
    with pytest.raises(ConfiguredValidationError) as error:
        simulate_configured_order(request(events=(event,), initial=initial))
    assert error.value.lifecycle_reason is LifecycleErrorReason.ACCOUNTING
    assert str(error.value) == "configured_lifecycle_denied"
    assert error.value.__suppress_context__
    assert initial.order.state is OrderState.SUBMISSION_PENDING


def test_public_api_revalidates_forged_request_before_any_sampling():
    req = request(events=(market(),))
    object.__setattr__(req, "seed", True)
    with pytest.raises(ConfiguredValidationError):
        simulate_configured_order(req)
    with pytest.raises(ConfiguredValidationError):
        simulate_configured_order(object())


def test_public_api_is_context_independent_and_preserves_flags():
    req = request(events=(market(),))
    expected = simulate_configured_order(req)
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        context.flags[Inexact] = True
        assert simulate_configured_order(req) == expected
        assert context.prec == 3 and context.rounding == ROUND_UP
        assert context.flags[Inexact] and context.traps[Inexact]


def test_public_api_has_no_io_sleep_or_global_rng_side_effects(monkeypatch):
    req = request(events=(market(),))
    before = random.getstate()

    def forbidden(*args, **kwargs):
        raise AssertionError("external side effect")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(time, "sleep", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    result = simulate_configured_order(req)
    assert result.lifecycle.order_terminal
    assert random.getstate() == before


def test_same_seed_replays_identically_without_persistent_state():
    req = request(events=(market(),))
    assert simulate_configured_order(req) == simulate_configured_order(req)


def test_cancel_ack_identity_binds_the_triggering_cancel_not_only_its_time():
    first = simulate_configured_order(request(events=(cancel("first"),)))
    second = simulate_configured_order(request(events=(cancel("second"),)))
    assert first.events[-1].event_id != second.events[-1].event_id
