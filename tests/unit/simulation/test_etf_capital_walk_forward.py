"""Owned walk-forward timing; fabricated originals, never economic evidence."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tests.unit.research.test_etf_capital_feasibility import instrument
from tests.unit.research.test_etf_capital_prepared import long_source
from tests.unit.simulation.test_etf_capital_trajectory import request as trajectory_request
from trading_bot.domain import InstrumentId
from trading_bot.research.etf_capital_signals import capital_candidates


@pytest.fixture(scope="module")
def originals():
    return long_source(1424, start_day=date(2016, 1, 4))


@pytest.fixture(scope="module")
def short_originals():
    return long_source(206)


@pytest.fixture(scope="module")
def owned_originals(originals):
    from trading_bot.market_data.etf_capital_owned import _own_capital_source

    return _own_capital_source(originals)


def request(source, **changes):
    from trading_bot.simulation.etf_capital_walk_forward import CapitalWalkForwardRequest

    terms = tuple(
        instrument(
            id=InstrumentId("fixture-" + symbol),
            symbol=symbol,
            observed_at=source.calendar.sessions[0].opens_at,
            price_increment=D(".000001"),
        )
        for symbol in ("SPY", "QQQ", "IWM", "SHY", "IEF")
    )
    return replace(
        CapitalWalkForwardRequest(source, D(100), terms, D(".1"), D(".01"), D(".02"), D(".10")),
        **changes,
    )


def run(value):
    from trading_bot.simulation.etf_capital_walk_forward import replay_capital_walk_forward

    return replay_capital_walk_forward(value)


@pytest.fixture
def orchestration_probe(monkeypatch, owned_originals):
    """Only path orchestration is doubled; real execution is tested below.

    Removing the owning composer's cutoff/purge/selection/policy scheduling
    changes observable returned choices/attempts, not assertions on mock calls.
    This fixture cannot establish workload, execution or economic qualification.
    """
    import trading_bot.simulation.etf_capital_walk_forward as module

    paths = []
    preparations = []
    profits = {}
    incomplete = set()

    def prepare(source, *, sessions):
        preparations.append(sessions)
        return SimpleNamespace(source_hash=owned_originals.source_hash, input_hash="a" * 64)

    def replay(**kwargs):
        days = kwargs["schedule"]
        terms = kwargs["terms"]
        paths.append(kwargs)
        candidate = days[0].candidate
        training = len(days) == 750
        key = (days[0].session, candidate)
        pnl = profits.get(key, D(0)) if training else D(0)
        complete = key not in incomplete
        close = next(
            s.closes_at
            for s in kwargs["source"].calendar.sessions
            if s.session_date == days[-1].session
        )
        return SimpleNamespace(
            account=SimpleNamespace(
                complete=complete, quantity=D(0), cash=terms.initial_cash + pnl
            ),
            points=(SimpleNamespace(at=close + timedelta(seconds=3)),),
            input_hash=(str(len(paths) % 10) * 64),
        )

    monkeypatch.setattr(module, "_prepare_capital_days", prepare)
    monkeypatch.setattr(module, "_replay_prepared_capital_trajectory", replay)
    # The real immutable source snapshot is made once for these orchestration-
    # only probes. Public ownership validation is separately exercised without
    # this double by short-source/kernel tests and the source boundary suites.
    monkeypatch.setattr(module, "_own_capital_source", lambda source: owned_originals)
    return SimpleNamespace(
        paths=paths, preparations=preparations, profits=profits, incomplete=incomplete
    )


def test_all_original_training_attempts_and_literal_cutoffs_are_retained(
    originals, orchestration_probe
):
    result = run(request(originals))
    sessions = originals.calendar.sessions
    assert len(result.folds) == 5 and all(len(f.training) == 28 for f in result.folds)
    assert tuple(f.training_cutoff for f in result.folds) == tuple(
        sessions[i].closes_at + timedelta(seconds=3) for i in (749, 875, 1001, 1127, 1253)
    )
    assert tuple(f.selection_at for f in result.folds) == tuple(
        sessions[i].closes_at for i in (769, 895, 1021, 1147, 1273)
    )
    assert all(
        a.outcome.last_outcome_at == f.training_cutoff for f in result.folds for a in f.training
    )
    assert all(f.selection.selected is None for f in result.folds)
    assert len(orchestration_probe.preparations) == 1
    assert len(orchestration_probe.preparations[0]) == 1423


def test_training_purge_keeps_last_eligible_next_open_without_embargo_extension(
    originals, orchestration_probe
):
    run(request(originals))
    days = orchestration_probe.paths[0]["schedule"]
    assert len(days) == 750
    assert days[729].entry_decision_allowed and days[730].entry_submission_allowed
    assert all(not d.entry_decision_allowed for d in days[730:])
    assert days[-1].session == originals.calendar.sessions[749].session_date
    assert all(
        p["terms"].roundtrip_friction_pct == D(".40") for p in orchestration_probe.paths[:140]
    )


def test_complete_profits_and_incomplete_exclusion_use_owned_runs_not_marks(
    originals, orchestration_probe
):
    start = originals.calendar.sessions[0].session_date
    grid = capital_candidates()
    orchestration_probe.profits[(start, grid[0])] = D(999)
    orchestration_probe.incomplete.add((start, grid[0]))
    orchestration_probe.profits[(start, grid[1])] = D(".2")
    orchestration_probe.profits[(start, grid[2])] = D(".2")
    result = run(request(originals))
    assert result.folds[0].selection.selected == grid[1]
    assert result.folds[0].selection.excluded == (grid[0],)
    assert result.folds[0].training[0].outcome.net_pnl is None
    assert result.folds[0].training[1].outcome.net_pnl == D(".2")
    assert result.folds[0].selection.selected_net_pnl == D(".2")


def test_close_winner_cannot_retroactively_cancel_same_day_old_opening(
    originals, orchestration_probe
):
    sessions = originals.calendar.sessions
    first = capital_candidates()[0]
    orchestration_probe.profits[(sessions[0].session_date, first)] = D(1)
    run(request(originals))
    selected = orchestration_probe.paths[140]
    days = selected["schedule"]
    opening = selected["opening_candidates"]
    boundary = 895 - 769
    assert days[boundary - 1].candidate == first
    assert opening[boundary] == first
    assert days[boundary].candidate is None
    assert opening[boundary + 1] is None
    assert days[boundary].entry_submission_allowed


def test_continuous_comparisons_only_final_tail_is_exit_only(originals, orchestration_probe):
    result = run(request(originals))
    dates = tuple(s.session_date for s in originals.calendar.sessions)
    assert result.used_sessions == dates[:1423] and result.unused_sessions == dates[1423:]
    assert (
        len(result.fixed) == 28 and tuple(p.candidate for p in result.fixed) == capital_candidates()
    )
    assert len(orchestration_probe.paths) == 169
    for path in orchestration_probe.paths[140:]:
        days = path["schedule"]
        assert tuple(d.session for d in days) == dates[769:1423]
        assert days[895 - 769].entry_submission_allowed
        assert days[896 - 769].entry_decision_allowed
        assert days[1398 - 769].entry_decision_allowed
        assert not days[1399 - 769].entry_decision_allowed
        assert all(not d.entry_submission_allowed for d in days[1400 - 769 :])
        assert all(not d.weekly_review_assumed for d in days)


def test_review_assumptions_and_capital_are_bound_without_claiming_qualification(
    originals, orchestration_probe
):
    first = run(request(originals))
    day = originals.calendar.sessions[769].session_date
    changed = run(request(originals, initial_cash=D(250), weekly_review_sessions=(day,)))
    assert first.input_hash != changed.input_hash
    assert all(
        flag is False
        for flag in (
            changed.source_qualified,
            changed.cost_qualified,
            changed.execution_enabled,
            changed.economic_admitted,
            changed.evidence_promotable,
        )
    )
    assert orchestration_probe.paths[169 + 140]["schedule"][0].weekly_review_assumed


@pytest.mark.parametrize("change", ("tier", "reviews", "flag", "terms"))
def test_invalid_public_authority_is_denied_before_any_preparation(
    originals, orchestration_probe, change
):
    value = request(originals)
    if change == "tier":
        value = replace(value, initial_cash=D(101))
    elif change == "reviews":
        value = replace(value, weekly_review_sessions=(originals.start, originals.start))
    elif change == "flag":
        object.__setattr__(value, "source_qualified", True)
    else:
        value = replace(value, instruments=value.instruments[:4])
    with pytest.raises(ValueError):
        run(value)
    assert orchestration_probe.preparations == []


def test_fold_source_must_cover_frozen_adaptive_window(short_originals):
    with pytest.raises(ValueError):
        run(request(short_originals))


def test_public_trajectory_v1_literal_preimages_survive_private_preparation_reuse(short_originals):
    from trading_bot.simulation.etf_capital_trajectory import replay_capital_trajectory

    result = replay_capital_trajectory(trajectory_request(short_originals, count=2))
    # Independently recorded from unchanged parent0c972, not current helper.
    assert result.input_hash == "747e3c36eec53b3b17e7b62dd5fb96531b22504ce0ac2eb36ceced58a9280100"
    assert (
        result.account.economic_hash
        == "c616c58b72b4f6f74af79b85c8a754f8757df5a7f5ce68eda2fef84ef52aaee5"
    )


def kernel(source, *, cash_at_second_close=False):
    from trading_bot.config.loader import restore_loaded_config
    from trading_bot.market_data.etf_capital_owned import _own_capital_source
    from trading_bot.research.etf_capital_prepared import _prepare_capital_days
    from trading_bot.simulation.etf_capital_daily_owner import _CapitalOwnerTerms
    from trading_bot.simulation.etf_capital_trajectory import _replay_prepared_capital_trajectory

    value = trajectory_request(source)
    owned = _own_capital_source(source)
    prepared = _prepare_capital_days(owned.dataset, sessions=tuple(d.session for d in value.days))
    days = tuple(replace(d, entry_decision_allowed=True) for d in value.days)
    replacement = None if cash_at_second_close else capital_candidates()[-1]
    days = (
        days[0],
        *(replace(d, candidate=replacement, entry_decision_allowed=False) for d in days[1:]),
    )
    opening = (None, value.days[0].candidate, *(replacement for _ in days[2:]))
    terms = _CapitalOwnerTerms(
        restore_loaded_config(source.canonical_config, source.config_hash),
        value.initial_cash,
        value.episode_fee_bound,
        value.entry_fee,
        value.exit_fee,
        value.roundtrip_friction_pct,
        source.calendar,
        value.entry_outcome,
        value.entry_fill_fraction,
        value.exit_outcome,
        value.exit_fill_fraction,
    )
    return _replay_prepared_capital_trajectory(
        source=owned.dataset,
        source_hash=owned.source_hash,
        prepared=prepared,
        terms=terms,
        instruments=value.instruments,
        schedule=days,
        opening_candidates=opening,
    )


@pytest.mark.parametrize("cash", (False, True))
def test_real_kernel_old_opening_fills_and_held_policy_survives_new_close(short_originals, cash):
    value = kernel(short_originals, cash_at_second_close=cash)
    assert value.points[0].account.quantity == 0
    assert value.points[1].account.quantity == D(".05")
    assert value.points[1].account.cash == D("84.9825")
    assert value.points[2].policy.reason == "maximum_hold"
    assert value.points[2].opening.candidate.hold_sessions == 2
    assert value.account.cash == D("100.05495") and value.account.complete
