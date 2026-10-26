"""Fictional panels verify the frozen study composition without empirical claims."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext

import pytest

from trading_bot.research.hybrid_policies import (
    CalendarSession,
    PolicyInput,
    SessionObservation,
    StrategyProposal,
    UnavailablePolicy,
    UniverseMembership,
    evaluate_policies,
)
from trading_bot.research.hybrid_strategies import PriceBar

D = Decimal
START = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)


def panel_fixture(count=261, *, membership_index=10):
    from trading_bot.research.stock_price_study import StockStudyPanel

    opens = tuple(START + timedelta(days=i) for i in range(count))
    series = tuple(
        tuple(
            PriceBar(
                opened + timedelta(hours=6, minutes=30),
                D(1000 + symbol * 10 + (i - 1) * (1 if symbol % 2 == 0 else -1)),
                D(1000 + symbol * 10 + i * (1 if symbol % 2 == 0 else -1)),
            )
            for i, opened in enumerate(opens)
        )
        for symbol in range(9)
    )
    return StockStudyPanel(series, opens, opens[membership_index])


def run(panel=None, *, cut=240, **changes):
    from trading_bot.research.stock_price_study import run_stock_price_study

    return run_stock_price_study(
        panel_fixture() if panel is None else panel,
        training_last_session=cut,
        bootstrap_replicates=100,
        **changes,
    )


@pytest.fixture(scope="module")
def study():
    return run()


def test_panel_retains_all_nine_positions_without_broker_authority():
    panel = panel_fixture()
    assert len(panel.bars) == len(panel.symbols) == 9
    assert panel.quote_currency is None
    assert panel.source_qualified is False


def test_all_slots_and_frozen_cost_control_family_are_preserved(study):
    from trading_bot.research.stock_price_study import STUDY_SYMBOLS

    assert STUDY_SYMBOLS == ("AXP", "AAPL", "BAC", "CVX", "KO", "KHC", "MCO", "OXY", "SPY")
    assert len(study.trend_targets) == 8
    assert tuple(s.round_trip_cost_bps for s in study.scenarios) == tuple(map(D, (10, 25, 50, 100)))
    assert tuple(s.one_way_cost_bps for s in study.scenarios) == tuple(
        map(D, ("5", "12.5", "25", "50"))
    )
    for scenario in study.scenarios:
        assert len(scenario.trend_traces) == len(scenario.cohort_buy_hold_traces) == 8
        assert tuple(c.name for c in scenario.controls) == (
            "cohort_buy_hold",
            "spy_buy_hold",
            "passive_90_cohort_10_cash",
            "causal_exposure_spy",
        )
    assert len(study.holdout_log_difference_names) == 16
    assert len(set(study.holdout_log_difference_names)) == 16
    assert len(study.holdout_log_differences) == 16
    assert all(len(column) == 20 for column in study.holdout_log_differences)


def test_first_eligible_signal_and_buy_hold_entries_have_next_open_delay(study):
    assert all(all(target == 0 for target in series[:199]) for series in study.trend_targets)
    assert study.trend_targets[0][199] == 1
    assert study.trend_targets[1][199] == 0
    for scenario in study.scenarios:
        for path in (
            *scenario.trend_traces,
            *scenario.cohort_buy_hold_traces,
            scenario.spy_buy_hold_trace,
            scenario.exposure_control_trace,
        ):
            assert all(row.nav == 1 and row.cost == 0 for row in path.rows[:200])
            assert path.rows[200].executed_target == path.rows[199].target
        assert scenario.cohort_buy_hold_traces[0].rows[199].target == 1
        assert scenario.cohort_buy_hold_traces[0].rows[-1].terminal_cost > 0


def test_training_holdout_metrics_use_prior_close_and_carry_existing_state(study):
    for scenario in study.scenarios:
        strategy = scenario.strategy
        assert strategy.train.first_session == 200
        assert strategy.train.last_session == 240
        assert strategy.train.baseline_nav == strategy.nav[199]
        assert strategy.holdout.first_session == 241
        assert strategy.holdout.baseline_nav == strategy.nav[240]
        assert strategy.holdout.summary.period_count == 20
        for path in scenario.trend_traces:
            assert path.rows[240].terminal_cost == 0
        assert strategy.holdout.inherited_high_watermark >= strategy.holdout.baseline_nav
        with localcontext() as ctx:
            ctx.prec = 50
            assert strategy.holdout.summary.total_return == strategy.nav[-1] / strategy.nav[240] - 1


def test_equal_initial_sleeves_and_passive_cash_reserve_are_explicit(study):
    with localcontext() as ctx:
        ctx.prec = 50
        for scenario in study.scenarios:
            for i in (0, 199, 200, 240, 260):
                assert (
                    scenario.strategy.nav[i]
                    == sum((t.rows[i].nav for t in scenario.trend_traces), D(0)) / 8
                )
                cohort = scenario.controls[0].nav[i]
                assert scenario.controls[2].nav[i] == D("0.9") * cohort + D("0.1")


def test_causal_control_uses_current_preterminal_nav_and_target_weights(study):
    with localcontext() as ctx:
        ctx.prec = 50
        for scenario in study.scenarios:
            for i in (199, 200, 240, 260):
                numerator = sum(
                    (
                        t.rows[i].target * t.rows[i].closing_nav_before_terminal
                        for t in scenario.trend_traces
                    ),
                    D(0),
                )
                denominator = sum(
                    (t.rows[i].closing_nav_before_terminal for t in scenario.trend_traces), D(0)
                )
                assert scenario.exposure_targets[i] == numerator / denominator
            assert scenario.exposure_control_trace.rows[200].executed_target == D("0.5")
            assert scenario.exposure_targets[240] > D("0.5")


def test_actual_50_200_policy_agrees_with_baseline_targets(study):
    from trading_bot.research.stock_price_study import STUDY_SYMBOLS

    panel = panel_fixture()
    index = 199
    data = PolicyInput(
        sessions=tuple(
            CalendarSession(i, panel.opens_at[i], panel.bars[0][i].completed_at)
            for i in range(index + 2)
        ),
        observations=tuple(
            SessionObservation(symbol, i, series[i], None)
            for symbol, series in zip(STUDY_SYMBOLS[:8], panel.bars[:8], strict=True)
            for i in range(index + 1)
        ),
        universe=tuple(
            UniverseMembership(
                symbol,
                panel.membership_use_not_before,
                panel.membership_use_not_before,
                True,
                "fixture-" + symbol,
            )
            for symbol in STUDY_SYMBOLS[:8]
        ),
        information_at=panel.bars[0][index].completed_at,
        calendar_verified=True,
    )
    trends = {value.symbol: value for value in evaluate_policies(data) if value.family == "trend"}
    for i, symbol in enumerate(STUDY_SYMBOLS[:8]):
        assert isinstance(trends[symbol], StrategyProposal)
        assert study.trend_targets[i][index] == (1 if trends[symbol].decision == "enter" else 0)


def test_policy_is_actually_called_with_observed_prefix_and_one_next_calendar_session(monkeypatch):
    from trading_bot.research import stock_price_study

    calls = []

    def observed_prefix(data):
        assert all(row.bar.completed_at <= data.information_at for row in data.observations)
        current = max(row.session_index for row in data.observations)
        assert data.sessions[-1].index == current + 1
        assert data.sessions[-1].opens_at > data.information_at
        assert data.facts == data.events == ()
        calls.append(data)
        return evaluate_policies(data)

    monkeypatch.setattr(stock_price_study, "evaluate_policies", observed_prefix)
    run()
    assert len(calls) == 61  # 199..259;260 is the final unexecutable close.
    assert calls[0].held_positions == ()
    assert set(calls[1].held_positions) == {
        ("AXP", "trend"),
        ("BAC", "trend"),
        ("KO", "trend"),
        ("MCO", "trend"),
    }


def test_flat_prices_keep_all_cash_targets_and_exact_passive_cost_drag():
    panel = panel_fixture()
    flat = tuple(
        tuple(replace(bar, open=D(100), close=D(100)) for bar in series) for series in panel.bars
    )
    result = run(replace(panel, bars=flat))
    first = result.scenarios[0]
    assert all(all(target == 0 for target in series) for series in result.trend_targets)
    assert first.strategy.nav == (D(1),) * 261
    assert first.controls[0].nav[-1] == first.controls[1].nav[-1] == D("0.99900025")
    assert first.controls[2].nav[-1] == D("0.999100225")
    assert first.controls[3].nav == (D(1),) * 261
    assert first.strategy.train.summary.sharpe is None
    assert first.strategy.train.summary.sortino is None
    assert first.exposure_targets == (D(0),) * 261


def test_longer_fictional_holdout_includes_all_declared_block_lengths():
    result = run(panel_fixture(count=281), cut=220)
    assert tuple(value.block_length for value in result.holdout_intervals) == (20, 5, 60)
    assert result.unavailable_block_lengths == ()
    assert all(value.observation_count == 60 for value in result.holdout_intervals)


def test_neighbor_sensitivity_uses_only_training_prefix_and_common_220_window(study):
    assert tuple((value.fast_window, value.slow_window) for value in study.sensitivities) == (
        (40, 180),
        (40, 200),
        (40, 220),
        (50, 180),
        (50, 200),
        (50, 220),
        (60, 180),
        (60, 200),
        (60, 220),
    )
    baseline = next(
        value
        for value in study.sensitivities
        if (value.fast_window, value.slow_window) == (50, 200)
    )
    assert baseline.targets == tuple(values[:241] for values in study.trend_targets)
    for sensitivity in study.sensitivities:
        assert all(len(values) == 241 for values in sensitivity.targets)
        for scenario in sensitivity.scenarios:
            assert scenario.common_window.first_session == 220
            assert scenario.own_window.first_session == sensitivity.first_possible_execution_session
            assert scenario.common_window.last_session == 240
            assert all(t.terminal_policy == "mark" for t in scenario.sleeve_traces)
            assert all(t.rows[-1].terminal_cost == 0 for t in scenario.sleeve_traces)


def test_paired_intervals_keep_full_family_and_explicit_missing_long_block(study):
    assert tuple(group.block_length for group in study.holdout_intervals) == (20, 5)
    assert study.unavailable_block_lengths == (60,)
    for group in study.holdout_intervals:
        assert group.column_count == group.family_size == 16
        assert group.replicates == 100
        assert group.seed == 20261026
        assert len(group.intervals) == 16


def test_future_suffix_cannot_change_earlier_targets_controls_or_training_sensitivity(study):
    panel = panel_fixture()
    mutated_bars = tuple(
        tuple(
            replace(bar, open=D("1"), close=D("2")) if i >= 241 else bar
            for i, bar in enumerate(series)
        )
        for series in panel.bars
    )
    mutated = run(replace(panel, bars=mutated_bars))
    assert mutated.panel_evidence_hash != study.panel_evidence_hash
    assert mutated.evidence_hash != study.evidence_hash
    assert mutated.protocol_hash == study.protocol_hash
    assert mutated.sensitivities == study.sensitivities
    for original, revised in zip(study.scenarios, mutated.scenarios, strict=True):
        assert original.exposure_targets[:241] == revised.exposure_targets[:241]
        assert original.strategy.train == revised.strategy.train
        assert all(
            a.rows[:241] == b.rows[:241]
            for a, b in zip(original.trend_traces, revised.trend_traces, strict=True)
        )


def test_study_and_protocol_hashes_are_reproducible_across_hostile_decimal_context(study):
    with localcontext() as ctx:
        ctx.prec = 3
        ctx.rounding = ROUND_DOWN
        ctx.traps[Inexact] = True
        repeated = run()
    assert repeated == study
    assert len(study.evidence_hash) == len(study.protocol_hash) == 64


@pytest.mark.parametrize(
    "field",
    [
        "qualified",
        "source_qualified",
        "strategy_qualified",
        "investment_eligible",
        "trading_enabled",
        "live_authorized",
        "full_task5_complete",
    ],
)
def test_study_cannot_grant_promotion_or_full_task_completion(study, field):
    assert getattr(study, field) is False
    with pytest.raises((ValueError, TypeError)):
        replace(study, **{field: True})
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        setattr(study, field, True)
    assert study.quote_currency is None


@pytest.mark.parametrize(
    "change",
    [
        "missing_slot",
        "extra_slot",
        "non_tuple",
        "short_series",
        "missing_row",
        "clock_mismatch",
        "overlap",
        "naive_membership",
        "mutable_series",
        "bad_price",
    ],
)
def test_invalid_panels_fail_without_substitution(change):
    from trading_bot.research.stock_price_study import StockStudyPanel

    panel = panel_fixture()
    args = {
        "bars": panel.bars,
        "opens_at": panel.opens_at,
        "membership_use_not_before": panel.membership_use_not_before,
    }
    if change == "missing_slot":
        args["bars"] = panel.bars[:-1]
    elif change == "extra_slot":
        args["bars"] = (*panel.bars, panel.bars[-1])
    elif change == "non_tuple":
        args["bars"] = list(panel.bars)
    elif change == "short_series":
        args["bars"] = tuple(series[:220] for series in panel.bars)
        args["opens_at"] = panel.opens_at[:220]
    elif change == "missing_row":
        args["bars"] = (panel.bars[0][:-1], *panel.bars[1:])
    elif change == "clock_mismatch":
        args["bars"] = (
            (
                replace(panel.bars[0][0], completed_at=START + timedelta(hours=7)),
                *panel.bars[0][1:],
            ),
            *panel.bars[1:],
        )
    elif change == "overlap":
        args["opens_at"] = (panel.opens_at[0], panel.opens_at[0], *panel.opens_at[2:])
    elif change == "naive_membership":
        args["membership_use_not_before"] = START.replace(tzinfo=None)
    elif change == "mutable_series":
        args["bars"] = (list(panel.bars[0]), *panel.bars[1:])
    else:
        object.__setattr__(panel.bars[0][0], "close", D("NaN"))
    with pytest.raises(ValueError):
        StockStudyPanel(**args)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"training_last_session": True},
        {"training_last_session": 219},
        {"training_last_session": 241},
        {"training_last_session": 261},
        {"first_execution_session": 199},
        {"first_execution_session": True},
        {"first_execution_session": 250},
        {"bootstrap_replicates": 99},
        {"bootstrap_replicates": True},
        {"bootstrap_replicates": 50001},
    ],
)
def test_invalid_study_boundaries_and_bootstrap_settings_fail_closed(kwargs):
    from trading_bot.research.stock_price_study import run_stock_price_study

    values = {"training_last_session": 240, "bootstrap_replicates": 100} | kwargs
    with pytest.raises(ValueError):
        run_stock_price_study(panel_fixture(), **values)


def test_membership_must_be_available_before_declared_first_passive_entry():
    with pytest.raises(ValueError):
        run(panel_fixture(membership_index=200))


def test_unexpected_trend_unavailability_cannot_silently_drop_a_member(monkeypatch):
    from trading_bot.research import stock_price_study

    def unavailable(data):
        actual = evaluate_policies(data)
        return tuple(
            UnavailablePolicy(
                v.symbol, v.family, v.information_at, "fixture missing", "missing_history"
            )
            if v.family == "trend" and v.symbol == "AXP"
            else v
            for v in actual
        )

    monkeypatch.setattr(stock_price_study, "evaluate_policies", unavailable)
    with pytest.raises(ValueError):
        run()
