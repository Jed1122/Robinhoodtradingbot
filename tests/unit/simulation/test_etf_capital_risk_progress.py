"""Invocation-owned continuation must equal original batch risk, never authority."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_feasibility import loaded
from tests.unit.simulation._lifecycle_fixtures import ORIGIN
from tests.unit.simulation.test_etf_capital_account import script
from tests.unit.simulation.test_etf_capital_action_account import action
from tests.unit.simulation.test_etf_capital_risk import losing_episodes, point
from trading_bot.domain import OrderPurpose
from trading_bot.simulation.events import EventCursor


def progress_points(progress, events, observations, *, purpose=OrderPurpose.ENTRY, capital=D(100)):
    from trading_bot.simulation.etf_capital_risk import _replay_risk_points

    return _replay_risk_points(
        loaded=loaded(),
        initial_cash=capital,
        events=events,
        observations=observations,
        purpose=purpose,
        actions=True,
        _progress=progress,
    )


def test_real_loss_kernel_processes_each_owned_observation_only_once(monkeypatch):
    import trading_bot.simulation.etf_capital_risk as module

    progress = module._RiskProgress()
    calls = []
    calculate = module._loss_pct

    def observed(*args):
        calls.append(1)
        return calculate(*args)

    monkeypatch.setattr(module, "_loss_pct", observed)
    observations = tuple(
        replace(point(i, 0), cursor=EventCursor(i, ORIGIN + timedelta(hours=i))) for i in range(12)
    )
    for count in range(1, 13):
        current = progress_points(progress, (), observations[:count])
        assert current[-1].equity == D(100)
    assert len(calls) == 36  # daily, weekly, drawdown once per original observation


@pytest.mark.parametrize("purpose", tuple(OrderPurpose))
def test_growing_action_prefixes_equal_complete_batch_for_every_purpose(purpose):
    import trading_bot.simulation.etf_capital_risk as module

    progress = module._RiskProgress()
    events = (*script()[:5], action(ex_mark=D(80)))
    observations = (
        point(0, 0),
        point(1, 5, "99"),
        point(2, 6),
        replace(point(3, 6, "101", day=7), daily_reset_reconciled=False),
    )
    for count in range(1, len(observations) + 1):
        tape = events[: observations[count - 1].source_count]
        current = progress_points(progress, tape, observations[:count], purpose=purpose)
        expected = module.replay_capital_action_risk(
            loaded=loaded(),
            initial_cash=D(100),
            events=tape,
            observations=observations[:count],
            purpose=purpose,
        )
        assert current == expected.points
    assert current[2].snapshot.daily_loss_pct == D("1.84")
    assert current[-1].snapshot.weekly_loss_pct == D("0")
    assert current[-1].snapshot.peak_to_trough_drawdown_pct == D("1.84")


def test_progress_cannot_hide_newly_appended_event_before_prior_observation():
    import trading_bot.simulation.etf_capital_risk as module

    progress = module._RiskProgress()
    later = replace(point(0, 0), cursor=EventCursor(0, ORIGIN + timedelta(seconds=10)))
    progress_points(progress, (), (later,))
    with pytest.raises(ValueError, match="capital_risk_invalid"):
        progress_points(progress, script(), (later, point(1, 10)))


def test_changed_observation_rebuilds_original_state_not_saved_latch():
    import trading_bot.simulation.etf_capital_risk as module

    progress = module._RiskProgress()
    tape = script()[:3]
    old = (point(0, 0), point(1, 3, "89"))
    assert not progress_points(progress, tape, old)[-1].decision.allowed
    revised = (point(0, 0), point(1, 3, "99"))
    current = progress_points(progress, tape, revised)
    assert current[-1].snapshot.daily_loss_pct == D(".04")
    assert current[-1].decision.allowed
    assert (
        current
        == module.replay_capital_action_risk(
            loaded=loaded(),
            initial_cash=D(100),
            events=tape,
            observations=revised,
        ).points
    )


def test_invalid_late_observation_does_not_publish_partial_continuation():
    import trading_bot.simulation.etf_capital_risk as module

    progress = module._RiskProgress()
    genesis = (point(0, 0),)
    progress_points(progress, (), genesis)
    later = replace(point(1, 0), cursor=EventCursor(1, ORIGIN + timedelta(days=1)))
    broken = replace(later)
    object.__setattr__(broken, "daily_reset_reconciled", 1)
    with pytest.raises(ValueError, match="capital_risk_invalid"):
        progress_points(progress, (), (*genesis, broken))
    current = progress_points(progress, (), (*genesis, later))
    assert current[-1].equity == D(100)
    assert current[-1].snapshot.daily_reset_reconciled


def test_full_episode_losses_are_not_recounted_by_later_observations():
    import trading_bot.simulation.etf_capital_risk as module

    progress = module._RiskProgress()
    tape = losing_episodes(3)
    observations = (
        point(0, 0),
        point(1, 30),
        replace(point(2, 30), cursor=EventCursor(2, ORIGIN + timedelta(minutes=1))),
    )
    progress_points(progress, tape, observations[:2])
    current = progress_points(progress, tape, observations)
    assert current[-1].snapshot.consecutive_loss_count == 3
    assert current[-1].decision.entry_pause_until == ORIGIN + timedelta(seconds=29, minutes=240)
    assert (
        current
        == module.replay_capital_action_risk(
            loaded=loaded(),
            initial_cash=D(100),
            events=tape,
            observations=observations,
        ).points
    )


def test_changed_original_event_prefix_cannot_adopt_old_account_or_loss_state():
    import trading_bot.simulation.etf_capital_risk as module

    progress = module._RiskProgress()
    observations = (point(0, 0), point(1, 3, "99"))
    original = script()[:3]
    progress_points(progress, original, observations)
    revised = (*original[:2], replace(original[2], fill=replace(original[2].fill, fee=D(".05"))))
    current = progress_points(progress, revised, observations)
    assert current[-1].equity == D("99.95")
    assert current[-1].snapshot.daily_loss_pct == D(".05")
    assert (
        current
        == module.replay_capital_action_risk(
            loaded=loaded(),
            initial_cash=D(100),
            events=revised,
            observations=observations,
        ).points
    )


def test_shortened_and_changed_capital_inputs_reconstruct_from_genesis():
    import trading_bot.simulation.etf_capital_risk as module

    progress = module._RiskProgress()
    observations = (
        point(0, 0),
        replace(point(1, 0), cursor=EventCursor(1, ORIGIN + timedelta(days=1))),
    )
    progress_points(progress, (), observations)
    current = progress_points(progress, (), observations[:1], capital=D(250))
    assert len(current) == 1 and current[0].equity == D(250)
    assert current[0].snapshot.daily_loss_pct == D(0)


def test_public_risk_frontends_have_no_progress_or_saved_state_input():
    import trading_bot.simulation.etf_capital_risk as module

    with pytest.raises(TypeError):
        module.replay_capital_action_risk(
            loaded=loaded(),
            initial_cash=D(100),
            events=(),
            observations=(point(0, 0),),
            _progress=module._RiskProgress(),
        )


def test_old_observation_mutation_is_not_equal_to_independently_copied_values():
    import trading_bot.simulation.etf_capital_risk as module

    progress = module._RiskProgress()
    observations = (point(0, 0), point(1, 3, "89"))
    progress_points(progress, script()[:3], observations)
    object.__setattr__(observations[1], "mark", D(99))
    current = progress_points(progress, script()[:3], observations)
    assert current[-1].equity == D("99.96")
    assert current[-1].snapshot.daily_loss_pct == D(".04")
