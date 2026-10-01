"""Feature-to-account seams retain original causal observations and safe labels."""

import importlib
from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from tests.unit.simulation.test_etf_history import bar, bars, request, session
from trading_bot.strategies.protocol import StrategyAction

D = Decimal


def frames(inputs):
    module = importlib.import_module("trading_bot.simulation.etf_history")
    function = getattr(module, "etf_fixture_decision_frames", None)
    if not callable(function):
        pytest.fail("causal ETF decision-feature seam is missing")
    return function(inputs)


def test_frame_carries_exact_prior_features_without_turning_observation_into_admission():
    frame = frames(request((*bars(), session(751, 750))))[0]
    values = dict(frame.features.values)
    assert values["latest_close"] == D("107.49")
    assert values["moving_average_short"] == D("107.395")
    assert values["moving_average_long"] == D("106.995")
    assert frame.atr == D("2")
    assert frame.observation.signal.action is StrategyAction.ENTER_LONG
    assert frame.can_propose_fixture_entry
    assert not frame.observation.admission_allowed
    assert not frame.execution_enabled and not frame.evidence_promotable
    assert frame.features.observed_at == frame.observation.signal.decided_at


@pytest.mark.parametrize("count", [0, 99, 100, 749])
def test_incomplete_history_never_becomes_an_entry_proposal(count):
    frame = frames(request((*bars(count), session(751, count))))[0]
    assert not frame.can_propose_fixture_entry
    assert (frame.features is None) == (count < 100)


@pytest.mark.parametrize("flag", ["halted", "cancel_only", "trading_disabled"])
def test_blocked_session_never_gets_proposal_permission(flag):
    assert not frames(request((*bars(), session(751, 750, **{flag: True}))))[
        0
    ].can_propose_fixture_entry


def test_between_cadence_and_zero_atr_cannot_propose_entries():
    observations = frames(request((*bars(), session(751, 750), session(752, 751))))
    assert observations[0].can_propose_fixture_entry
    assert not observations[1].can_propose_fixture_entry
    flat = tuple(bar(i, D("100"), width=D("0")) for i in range(750))
    assert not frames(request((*flat, session(751, 750))))[0].can_propose_fixture_entry


def test_old_prefix_observations_are_identical_and_future_corrections_do_not_reprice_frames():
    from trading_bot.simulation.etf_history import run_etf_fixture_prefix

    original = bars()
    opening = session(751, 750)
    before = frames(request((*original, opening)))
    correction = bar(
        749,
        D("1"),
        ordinal=751,
        available=opening.available_at_ns + 1,
        revision=original[-1].source_record_hash,
        width=D(".5"),
    )
    inputs = request((*original, opening, correction, session(756, 752)))
    after = frames(inputs)
    assert after[0] == before[0]
    assert after[-1].features != before[0].features
    assert after[-1].observation.signal.action is StrategyAction.HOLD
    assert tuple(frame.observation for frame in after) == run_etf_fixture_prefix(inputs).decisions


def test_frame_features_are_not_rounded_by_hostile_caller_precision():
    inputs = request((*bars(), session(751, 750)))
    expected = frames(inputs)
    with localcontext() as context:
        context.prec = 2
        assert frames(inputs) == expected


def test_mutated_frame_feature_identity_and_authority_markers_are_rejected():
    frame = frames(request((*bars(), session(751, 750))))[0]
    for features in (
        replace(frame.features, instrument_id="QQQ"),
        replace(frame.features, observed_at=session(752, 751).payload.observed_at),
        replace(frame.features, data_hash="bad"),
        replace(frame.features, values=(("average_true_range", D("NaN")),)),
        replace(frame.features, values=(("average_true_range", D("2")),) * 2),
    ):
        with pytest.raises(ValueError):
            replace(frame, features=features)
    object.__setattr__(frame, "execution_enabled", True)
    with pytest.raises(ValueError):
        frame.__post_init__()
