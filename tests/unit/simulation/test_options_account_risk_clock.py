"""Exact journal-bound loss history survives research-clock recovery."""

from dataclasses import replace
from decimal import Decimal

import pytest

from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from tests.unit.simulation.test_options_historical_clock import closing, setup, submit
from tests.unit.simulation.test_options_historical_restart import resume
from trading_bot.market_data.options_source_verify import ceil_available_at
from trading_bot.research.options_account_journal import initial_account_path
from trading_bot.risk.options_loss_history import OptionsLossObservation, OptionsLossPoint

D = Decimal


def test_journal_reconstruct_reduces_loss_observations_once(tmp_path, monkeypatch):
    from trading_bot.research.options_account_journal import reconstruct_account_journal
    from trading_bot.risk import options_loss_history as loss_api

    clock, order, _ = setup(tmp_path, monkeypatch)
    for index in range(12):
        clock.advance_time(clock.initial.start_ns + index)
        observe(clock, order)
    original = loss_api._breached
    calls = []

    def count(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(loss_api, "_breached", count)
    assert (
        reconstruct_account_journal(
            clock.initial, clock.journal, loaded=clock.loaded, scenario=clock.scenario
        )
        == clock.state
    )
    assert len(calls) == 3 * 12


def observe(clock, order, *, complete=True, **changes):
    session = order.structure.legs[0].contract.eligible_sessions[0]
    # These are deliberately fabricated session/mark facts, never provider evidence.
    p = OptionsLossPoint(
        event_id="risk-" + str(len(clock.journal)),
        account_id=clock.state.path_id,
        config_hash=str(clock.loaded.config_hash),
        observed_at=ceil_available_at(clock.now_ns),
        session_id=session.session_id,
        session_open=ceil_available_at(clock.initial.start_ns),
        session_close=session.closes_at,
        previous_session_close=None,
        liquidation_equity=clock.state.marked_equity,
        cumulative_external_flows=clock.state.cumulative_external_flows,
        source_hash=clock.state.journal_hash,
        complete=complete,
    )
    clock.observe_loss(
        OptionsLossObservation(replace(p, **changes), clock.now_ns, len(clock.journal))
    )


def test_mark_and_flow_roundtrip_preserves_separate_cash_and_trading_pnl(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    observe(clock, order)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    clock.mark("episode-1", D("0.20"), available_ns=clock.now_ns)
    observe(clock, order)
    clock.external_flow(D("500"), available_ns=clock.now_ns)
    observe(clock, order)
    restored = resume(clock)
    assert restored.result() == clock.result()
    assert restored.loss_report() == clock.loss_report()
    assert restored.state.marked_equity == D("10494.50")
    assert restored.state.risk_capital == D("9994.50")
    assert restored.result().net_cash_flow == D("-25.50")
    assert restored.result().reconciliation_reasons == ()
    submit(restored, closing(order, events[1].available_ns))
    restored.advance(events[2])
    restored.advance(events[3])
    restored.advance_time(events[3].available_ns + 10)
    assert restored.state.trial.consumed_loss == D("6")
    assert restored.state.cash == D("10494")
    assert restored.result().net_cash_flow == D("-6")
    assert restored.result().reconciliation_reasons == ()


def test_incomplete_mark_latch_does_not_prevent_protective_close_or_settlement(
    tmp_path, monkeypatch
):
    clock, order, events = setup(tmp_path, monkeypatch)
    observe(clock, order)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    clock.mark("episode-1", None, available_ns=clock.now_ns)
    with pytest.raises(ValueError):
        observe(clock, order)
    observe(clock, order, complete=False)
    assert clock.state.latched_halts == ("risk_history_incomplete",)
    assert clock.state.incidents == ()
    clock = resume(clock)
    clock.mark("episode-1", D("0.20"), available_ns=clock.now_ns)
    observe(clock, order)
    assert "risk_history_incomplete" in clock.loss_report().entry_reasons
    submit(clock, closing(order, events[1].available_ns))
    clock.advance(events[2])
    clock.advance(events[3])
    clock.advance_time(events[3].available_ns + 10)
    assert clock.state.episodes[0].finalized
    assert clock.state.trial.consumed_loss == D("6")
    assert not clock.state.incidents
    assert clock.state.latched_halts == ("risk_history_incomplete",)
    assert "risk_history_incomplete" in clock.result().reasons


@pytest.mark.parametrize(
    "change",
    [
        {"liquidation_equity": D("10001")},
        {"cumulative_external_flows": D("1")},
        {"source_hash": "a" * 64},
        {"account_id": "synthetic:another"},
        {"config_hash": "a" * 64},
    ],
)
def test_loss_fact_must_bind_exact_journal_state(tmp_path, monkeypatch, change):
    clock, order, _ = setup(tmp_path, monkeypatch)
    before = clock.result()
    with pytest.raises(ValueError):
        observe(clock, order, **change)
    assert clock.result() == before


def test_risk_history_cannot_start_after_trading_or_use_stale_book(tmp_path, monkeypatch):
    clock, order, _ = setup(tmp_path, monkeypatch)
    submit(clock, order)
    with pytest.raises(ValueError):
        observe(clock, order)
    (tmp_path / "other").mkdir(mode=0o700)
    other, order, _ = setup(tmp_path / "other", monkeypatch)
    observe(other, order)
    other.external_flow(D("1"), available_ns=other.now_ns)
    assert "risk_state_changed" in other.loss_report().entry_reasons
    with pytest.raises(ValueError):
        submit(other, order)
    observe(other, order)
    submit(other, order)


@pytest.mark.parametrize("action", ["mark", "flow", "loss"])
def test_invalid_command_is_atomic_and_not_added_to_checkpoint(tmp_path, monkeypatch, action):
    clock, order, _ = setup(tmp_path, monkeypatch)
    before = resume(clock).result()
    with pytest.raises(ValueError):
        if action == "mark":
            clock.mark("unowned", D("1"), available_ns=clock.now_ns)
        elif action == "flow":
            clock.external_flow(D("0"), available_ns=clock.now_ns)
        else:
            observe(clock, order, source_hash="b" * 64)
    assert clock.result() == before == resume(clock).result()


def test_transient_mark_loss_is_persistent_but_protective_exit_can_complete(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    initial = initial_account_path(
        study_hash=clock.initial.study_hash,
        capital=D("100"),
        start_ns=clock.initial.start_ns,
        loaded=clock.loaded,
        scenario=clock.scenario,
    )
    clock = type(clock)(initial, (), loaded=clock.loaded, scenario=clock.scenario, seed=clock.seed)
    order = replace(order, account_scope=initial.path_id)
    observe(clock, order)
    # This internal accounting test deliberately bypasses the strategy entry
    # feasibility helper; it is not an admissible $100-account trading example.
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    clock.mark("episode-1", D("0"), available_ns=clock.now_ns)
    observe(clock, order)
    clock.mark("episode-1", D("0.25"), available_ns=clock.now_ns)
    observe(clock, order)
    clock.external_flow(D("500"), available_ns=clock.now_ns)
    observe(clock, order)
    restored = resume(clock)
    report = restored.loss_report()
    assert report.daily_halt and report.weekly_halt and report.drawdown_halt
    assert report.flow_adjusted_equity == D("99.50")
    assert report.drawdown_loss_usd == D("0.50")
    assert restored.state.latched_halts == ("drawdown_latched", "weekly_loss_latched")
    assert restored.state.incidents == ()
    with pytest.raises(ValueError):
        restored.submit(
            "new-exposure",
            "new-session",
            replace(order, intent_id="new"),
            available_ns=restored.now_ns,
        )
    submit(restored, closing(order, events[1].available_ns))
    restored.advance(events[2])
    restored.advance(events[3])
    restored.advance_time(events[3].available_ns + 10)
    assert restored.state.episodes[0].finalized
    assert restored.state.trial.consumed_loss == D("6")
    assert restored.result().net_cash_flow == D("-6")
    assert restored.state.cash == D("594")
    assert restored.result().reconciliation_reasons == ()
    assert resume(restored).state.latched_halts == ("drawdown_latched", "weekly_loss_latched")


@pytest.mark.parametrize("second", ["mark", "flow"])
def test_unobserved_mark_cannot_be_hidden_by_next_monetary_fact(tmp_path, monkeypatch, second):
    clock, order, events = setup(tmp_path, monkeypatch)
    observe(clock, order)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    clock.mark("episode-1", D("0"), available_ns=clock.now_ns)
    before = clock.result()
    with pytest.raises(ValueError):
        if second == "mark":
            clock.mark("episode-1", D("1"), available_ns=clock.now_ns)
        else:
            clock.external_flow(D("500"), available_ns=clock.now_ns)
    assert clock.result() == before == resume(clock).result()


def test_delayed_observation_cannot_hide_unobserved_fill_or_mark(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    observe(clock, order)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    clock.advance_time(clock.now_ns + 1)
    with pytest.raises(ValueError):
        clock.mark("episode-1", D("1"), available_ns=clock.now_ns)
    with pytest.raises(ValueError):
        observe(clock, order, complete=False)


def test_partial_fill_cannot_replace_existing_valuation_before_risk_observation(
    tmp_path, monkeypatch
):
    clock, order, events = setup(tmp_path, monkeypatch, units=5)
    observe(clock, order)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    clock.mark("episode-1", D("0.20"), available_ns=clock.now_ns)
    observe(clock, order)
    clock.advance(events[2])
    assert clock.state.positions[0].units == 5
    with pytest.raises(ValueError):
        clock.mark("episode-1", D("1"), available_ns=clock.now_ns)
    observe(clock, order)
    clock.mark("episode-1", D("1"), available_ns=clock.now_ns)
    observe(clock, order)
    assert resume(clock).result() == clock.result()


@pytest.mark.parametrize("observe_final", [False, True])
def test_terminal_flat_book_is_not_complete_with_missing_final_risk_observation(
    tmp_path, monkeypatch, observe_final
):
    clock, order, events = setup(tmp_path, monkeypatch)
    observe(clock, order)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    clock.mark("episode-1", D("0.20"), available_ns=clock.now_ns)
    observe(clock, order)
    submit(clock, closing(order, events[1].available_ns))
    clock.advance(events[2])
    clock.advance(events[3])
    if observe_final:
        observe(clock, order)
    clock.advance_time(events[3].available_ns + 10)
    if observe_final:
        observe(clock, order)
    result = clock.result()
    assert result.state.positions == result.state.unsettled == ()
    assert result.state.episodes[0].finalized
    assert result.state.trial.consumed_loss == D("6")
    assert result.status == ("completed" if observe_final else "incomplete")
    assert ("risk_state_changed" in result.reasons) is not observe_final
    assert resume(clock).result() == result


def test_stale_initialized_risk_history_cannot_report_complete(tmp_path, monkeypatch):
    clock, order, _ = setup(tmp_path, monkeypatch)
    observe(clock, order)
    age = clock.loaded.config.freshness.max_account_snapshot_age_seconds
    clock.advance_time(clock.now_ns + int(age * 10**9) + 1)
    assert clock.result().status == "incomplete"
    assert "risk_observation_stale" in clock.result().reasons


def test_daily_only_loss_halt_is_reported_without_permanent_weekly_latch(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    initial = initial_account_path(
        study_hash=clock.initial.study_hash,
        capital=D("100"),
        start_ns=clock.initial.start_ns,
        loaded=clock.loaded,
        scenario=clock.scenario,
    )
    clock = type(clock)(initial, (), loaded=clock.loaded, scenario=clock.scenario, seed=7)
    order = replace(order, account_scope=initial.path_id)
    observe(clock, order)
    # Internal accounting only, not an admissible strategy entry at this capital.
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    clock.mark("episode-1", D("0.22"), available_ns=clock.now_ns)
    observe(clock, order)
    assert clock.state.marked_equity == D("96.50")
    assert clock.state.latched_halts == ()
    assert clock.loss_report().daily_halt and not clock.loss_report().weekly_halt
    assert "daily_loss_latched" in clock.result().reasons
    assert resume(clock).result() == clock.result()
