"""Pure event execution uses only fabricated quotes, never an exchange capability."""

import importlib
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from tests.unit.market_data.test_options_quote_stream import ROOT, row, setup
from trading_bot.domain.enums import OrderState, Side
from trading_bot.domain.options import (
    OptionLeg,
    OptionsOrderIntent,
    OptionStructure,
    PositionEffect,
    StructureKind,
)
from trading_bot.market_data.options_session_inputs import _ns
from trading_bot.market_data.recording import content_hash


def api():
    try:
        return importlib.import_module("trading_bot.simulation.options_historical_execution")
    except ModuleNotFoundError:
        pytest.fail("historical execution is not implemented")


def scenario(**changes):
    models = importlib.import_module("trading_bot.research.options_study_models")
    if not hasattr(models, "StudyScenario"):
        pytest.fail("explicit historical scenario is not implemented")
    values = dict(
        name="base",
        latency_ns=1,
        acknowledgement_ns=1,
        cancel_acknowledgement_ns=2,
        reject_ppm=0,
        unfilled_ppm=0,
        ambiguous_ppm=0,
        participation_pct=Decimal("100"),
        slippage_ticks=0,
        cancel_race="fill_before_ack",
        entry_fee=Decimal("0.50"),
        exit_fee=Decimal("0.50"),
        fee_bound_per_unit=Decimal("1.00"),
        settlement_delay_ns=10,
        calibration_hashes=(),
    )
    values.update(changes)
    return models.StudyScenario(**values)


def arrangement(tmp_path, monkeypatch, *, units=1, closing=False):
    execution = api()
    native = [row(offset=n, bid_px=200000000, ask_px=250000000) for n in (1, 2, 3, 4, 5, 6)]
    request, loaded = setup(tmp_path, monkeypatch, options=native)
    from trading_bot.market_data.options_quote_stream import iter_quote_events

    events = tuple(
        e
        for e in iter_quote_events(request, loaded=loaded, repository_root=ROOT)
        if e.record is not None and e.symbol != "SPY"
    )
    c = request.contracts[0]
    at = request.sessions[0].opens_at
    intent = OptionsOrderIntent(
        "fixture-order",
        "synthetic:historical",
        OptionStructure(
            StructureKind.LONG_CALL,
            (
                OptionLeg(
                    c,
                    Side.SELL if closing else Side.BUY,
                    PositionEffect.CLOSE if closing else PositionEffect.OPEN,
                    1,
                ),
            ),
        ),
        units,
        Decimal("0.20" if closing else "0.25"),
        "credit" if closing else "debit",
        at,
        at + timedelta(seconds=10),
        "unvalidated-momentum-20-100-v1",
        loaded.config_hash,
        content_hash("fixture"),
        "signal_invalidation_or_prior_session_expiry",
        "limit",
        "day",
    )
    return execution, execution.propose_order(intent, available_ns=_ns(at)), events


def test_later_ack_then_fill_and_exact_cash(tmp_path, monkeypatch):
    execution, proposed, events = arrangement(tmp_path, monkeypatch)
    ack = execution.advance_order(proposed.order, events[0], scenario=scenario(), seed=7)
    assert ack.order.state is OrderState.SUBMITTED and ack.fill_units == 0
    fill = execution.advance_order(ack.order, events[1], scenario=scenario(), seed=7)
    assert fill.order.state is OrderState.FILLED
    assert fill.fill_units == 1 and fill.cash_flow == Decimal("-25.50")
    assert fill.fee == Decimal("0.50")
    repeat = execution.advance_order(fill.order, events[1], scenario=scenario(), seed=7)
    assert repeat.fill_units == 0 and repeat.cash_flow == 0 and repeat.order == fill.order


def test_close_cash_is_separate_from_settlement(tmp_path, monkeypatch):
    execution, proposed, events = arrangement(tmp_path, monkeypatch, closing=True)
    ack = execution.advance_order(proposed.order, events[0], scenario=scenario(), seed=7)
    fill = execution.advance_order(ack.order, events[1], scenario=scenario(), seed=7)
    assert fill.cash_flow == Decimal("19.50") and fill.fee == Decimal("0.50")
    assert fill.order.state is OrderState.FILLED
    assert fill.settlement_complete is False


@pytest.mark.parametrize(
    "field,state",
    [
        ("reject_ppm", OrderState.REJECTED),
        ("ambiguous_ppm", OrderState.UNKNOWN_REQUIRES_RECONCILIATION),
        ("unfilled_ppm", OrderState.SUBMITTED),
    ],
)
def test_explicit_scenario_outcomes(tmp_path, monkeypatch, field, state):
    execution, proposed, events = arrangement(tmp_path, monkeypatch)
    current = proposed.order
    for e in events:
        result = execution.advance_order(current, e, scenario=scenario(**{field: 1000000}), seed=7)
        current = result.order
        assert result.fill_units == 0
    assert current.state is state


@pytest.mark.parametrize(
    "race,expected",
    [("fill_before_ack", OrderState.FILLED), ("ack_before_fill", OrderState.CANCELED)],
)
def test_cancel_race_is_explicit(tmp_path, monkeypatch, race, expected):
    execution, proposed, events = arrangement(tmp_path, monkeypatch)
    s = scenario(cancel_race=race)
    ack = execution.advance_order(proposed.order, events[0], scenario=s, seed=7)
    cancel = execution.request_cancel(ack.order, available_ns=events[0].available_ns)
    result = execution.advance_order(cancel.order, events[3], scenario=s, seed=7)
    assert result.order.state is expected


def test_integer_participation_and_partial_fill_do_not_reuse_liquidity(tmp_path, monkeypatch):
    execution, proposed, events = arrangement(tmp_path, monkeypatch, units=2)
    s = scenario(participation_pct=Decimal("50"))  # three offered -> one whole contract
    ack = execution.advance_order(proposed.order, events[0], scenario=s, seed=7)
    partial = execution.advance_order(ack.order, events[1], scenario=s, seed=7)
    assert partial.fill_units == 1 and partial.order.state is OrderState.PARTIALLY_FILLED
    duplicate = execution.advance_order(partial.order, events[1], scenario=s, seed=7)
    assert duplicate.fill_units == 0 and duplicate.order == partial.order
    exhausted = execution.advance_order(
        partial.order, events[2], scenario=s, seed=7, consumed_units=1
    )
    assert exhausted.fill_units == 0
    final = execution.advance_order(exhausted.order, events[3], scenario=s, seed=7)
    assert final.fill_units == 1 and final.order.state is OrderState.FILLED


def test_latency_tick_slippage_quality_and_price_limit_deny_fill(tmp_path, monkeypatch):
    execution, proposed, events = arrangement(tmp_path, monkeypatch)
    s = scenario()
    ack = execution.advance_order(proposed.order, events[0], scenario=s, seed=7)
    for altered in (scenario(latency_ns=100), scenario(slippage_ticks=1)):
        variant = execution.advance_order(proposed.order, events[0], scenario=altered, seed=7)
        assert (
            execution.advance_order(variant.order, events[1], scenario=altered, seed=7).fill_units
            == 0
        )
    invalid = replace(events[1], quality_reasons=("zero_bid",))
    assert execution.advance_order(ack.order, invalid, scenario=s, seed=7).fill_units == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"entry_fee": Decimal("1.01")},
        {"participation_pct": Decimal("100.01")},
        {"participation_pct": Decimal("0")},
        {"latency_ns": -1},
        {"latency_ns": True},
        {"reject_ppm": 1000001},
        {"ambiguous_ppm": 600000, "reject_ppm": 600000},
        {"cancel_race": "assume_cancel"},
        {"settlement_delay_ns": 0},
    ],
)
def test_scenarios_reject_unknown_or_unbounded_assumptions(changes):
    api()
    with pytest.raises(ValueError):
        scenario(**changes)


def test_fee_bound_does_not_depend_on_ambient_decimal_precision():
    with localcontext() as context:
        context.prec = 2
        with pytest.raises(ValueError):
            scenario(entry_fee=Decimal("0.505"), exit_fee=Decimal("0.50"))


def test_wait_for_ack_and_cancel_without_fill(tmp_path, monkeypatch):
    execution, proposed, events = arrangement(tmp_path, monkeypatch)
    slow = scenario(acknowledgement_ns=3, unfilled_ppm=1000000)
    waiting = execution.advance_order(proposed.order, events[0], scenario=slow, seed=7)
    assert waiting.order.state is OrderState.SUBMISSION_PENDING
    ack = execution.advance_order(waiting.order, events[2], scenario=slow, seed=7)
    canceled = execution.request_cancel(ack.order, available_ns=events[2].available_ns)
    done = execution.advance_order(canceled.order, events[5], scenario=slow, seed=7)
    assert done.order.state is OrderState.CANCELED and done.fill_units == 0


def test_unknown_size_cannot_fill_and_scenario_substitution_denies(tmp_path, monkeypatch):
    execution, proposed, events = arrangement(tmp_path, monkeypatch)
    s = scenario()
    ack = execution.advance_order(proposed.order, events[0], scenario=s, seed=7)
    with pytest.raises(ValueError):
        execution.advance_order(ack.order, events[1], scenario=scenario(slippage_ticks=1), seed=7)
    with pytest.raises(ValueError):
        execution.advance_order(ack.order, events[1], scenario=s, seed=8)
    record = events[1].record
    assert record is not None
    event = replace(events[1], record=replace(record, value=replace(record.value, ask_size=None)))
    assert execution.advance_order(ack.order, event, scenario=s, seed=7).fill_units == 0


def test_nonadjacent_same_timestamp_duplicate_cannot_reuse_fill(tmp_path, monkeypatch):
    execution, proposed, events = arrangement(tmp_path, monkeypatch, units=3)
    s = scenario(participation_pct=Decimal("50"))
    ack = execution.advance_order(proposed.order, events[0], scenario=s, seed=7)
    partial = execution.advance_order(ack.order, events[1], scenario=s, seed=7)
    control = replace(events[1], record=None, state="gap", quality_reasons=("stale_feed",))
    observed = execution.advance_order(partial.order, control, scenario=s, seed=7)
    repeated = execution.advance_order(observed.order, events[1], scenario=s, seed=7)
    assert repeated.fill_units == 0 and repeated.order.filled_units == 1


def test_proposal_cannot_use_an_intent_from_the_future(tmp_path, monkeypatch):
    execution, proposed, _ = arrangement(tmp_path, monkeypatch)
    future = replace(
        proposed.order.intent, created_at=proposed.order.intent.created_at + timedelta(seconds=1)
    )
    with pytest.raises(ValueError):
        execution.propose_order(future, available_ns=proposed.order.decision_ns)


@pytest.mark.parametrize("offset", [1, 999, 1000])
def test_proposal_binds_exact_upward_datetime_projection(tmp_path, monkeypatch, offset):
    execution, proposed, _ = arrangement(tmp_path, monkeypatch)
    intent = replace(
        proposed.order.intent,
        created_at=proposed.order.intent.created_at + timedelta(microseconds=1),
    )
    result = execution.propose_order(intent, available_ns=proposed.order.decision_ns + offset)
    assert result.order.decision_ns == proposed.order.decision_ns + offset


def test_cancellation_cannot_process_older_unseen_market_event(tmp_path, monkeypatch):
    execution, proposed, events = arrangement(tmp_path, monkeypatch)
    s = scenario()
    ack = execution.advance_order(proposed.order, events[0], scenario=s, seed=7)
    cancel = execution.request_cancel(ack.order, available_ns=events[3].available_ns)
    with pytest.raises(ValueError):
        execution.advance_order(cancel.order, events[1], scenario=s, seed=7)


@pytest.mark.parametrize("field", ["reject_ppm", "ambiguous_ppm"])
def test_nonaccepted_outcome_has_no_acceptance_timestamp(tmp_path, monkeypatch, field):
    execution, proposed, events = arrangement(tmp_path, monkeypatch)
    result = execution.advance_order(
        proposed.order, events[0], scenario=scenario(**{field: 1000000}), seed=7
    )
    assert result.order.accepted_ns is None


def test_due_cancel_follows_partial_fill_at_same_event(tmp_path, monkeypatch):
    from trading_bot.domain.enums import OrderEvent

    execution, proposed, events = arrangement(tmp_path, monkeypatch, units=3)
    s = scenario(participation_pct=Decimal("50"))
    ack = execution.advance_order(proposed.order, events[0], scenario=s, seed=7)
    cancel = execution.request_cancel(ack.order, available_ns=events[0].available_ns)
    result = execution.advance_order(cancel.order, events[3], scenario=s, seed=7)
    assert result.fill_units == 1 and result.order.filled_units == 1
    assert result.order.state is OrderState.CANCELED
    assert tuple(t.event for t in result.transitions) == (
        OrderEvent.PARTIAL_FILL,
        OrderEvent.CANCEL_CONFIRMED,
    )
    assert result.cash_flow == Decimal("-25.50") and result.fee == Decimal("0.50")
    later = execution.advance_order(result.order, events[4], scenario=s, seed=7)
    assert later.fill_units == 0 and later.order == result.order
