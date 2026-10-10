"""Independent original-path matching controls, not qualified market evidence."""

from dataclasses import replace
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.research.test_etf_capital_prepared import long_source
from tests.unit.simulation.test_etf_capital_trajectory import request as trajectory
from trading_bot.market_data.etf_capital_actions import CapitalDistribution, CapitalSplit


@pytest.fixture(scope="module")
def source():
    return long_source(206)


def request(original, **changes):
    from trading_bot.research.etf_capital_matched import CapitalMatchedRequest

    path = trajectory(original)
    return replace(
        CapitalMatchedRequest(path, tuple(day.session for day in path.days[1:])), **changes
    )


def run(value):
    from trading_bot.research.etf_capital_matched import run_capital_matched_reference

    return run_capital_matched_reference(value)


def test_original_gross_close_exposure_scales_passive_without_expense_denominator(source):
    value = run(request(source))
    with localcontext() as context:
        context.prec = 64
        held = (D(15) / D("99.9825"), D("15.05") / D("100.0325"))
        mean = (held[0] + held[1]) / 5
    notional = D("6.008946205003064949806847993065519777634792134158678828450590779838")
    assert value.close_exposures == (*held, D(0), D(0), D(0))
    assert value.mean_exposure == mean
    assert value.kernel_result.request.entry_notional == notional
    assert value.kernel_result.fees_paid == D(".01")
    assert value.kernel_result.request.per_side_cost_bps == 5
    assert value.kernel_result.request.entry_fee == D(".01")
    assert value.kernel_result.request.estimated_exit_fee == D(".02")
    assert value.reference_kind == "retrospective_mean_exposure_scaled_spy"
    assert value.realized_trading_pnl is None
    assert value.cash_nav == (D(100),) * 5
    assert value.kernel_result.points[0].close_midpoint_nav == D(
        "99.986997028383306814118037556934480222365207865841321171549409220162"
    )
    assert value.kernel_result.points[-1].close_midpoint_nav == D(
        "100.067076271495125104303702697934480222365207865841321171549409220162"
    )
    assert value.kernel_result.points[-1].liquidation_proxy == D(
        "100.044033260256876009276647422588980222365207865841321171549409220162"
    )
    assert value.baseline_session == request(source).trajectory.days[0].session
    assert value.session_dates == request(source).test_sessions
    assert "future_conditioned_mean_not_causal_or_attainable_policy" in value.limitations
    assert not any(
        (
            value.source_qualified,
            value.cost_qualified,
            value.execution_enabled,
            value.economic_admitted,
            value.evidence_promotable,
        )
    )


def test_baseline_and_supplied_tail_are_not_included_in_mean(source):
    original = request(source)
    short = run(replace(original, test_sessions=original.test_sessions[:2]))
    with localcontext() as context:
        context.prec = 64
        mean = (D(15) / D("99.9825") + D("15.05") / D("100.0325")) / 2
    assert short.mean_exposure == mean
    assert len(short.kernel_result.points) == 2
    assert short.session_dates[-1] < original.trajectory.days[-1].session
    assert short.input_hash != run(original).input_hash


def test_cash_only_original_trajectory_does_not_pay_fictional_entry_or_exit_fee(source):
    original = request(source)
    path = replace(
        original.trajectory,
        days=tuple(replace(day, candidate=None) for day in original.trajectory.days),
    )
    value = run(replace(original, trajectory=path))
    assert value.mean_exposure == 0 and value.close_exposures == (D(0),) * 5
    assert value.raw_quantities == (D(0),) * 5
    assert value.kernel_result.fees_paid == 0
    assert value.kernel_result.estimated_terminal_liquidation_cost == 0
    assert value.kernel_result.entry_price is None
    assert tuple(p.liquidation_proxy for p in value.kernel_result.points) == (D(100),) * 5


@pytest.mark.parametrize("indices", ((), (0, 1), (1, 3), (2, 1), (1, 1), (2,)))
def test_missing_baseline_gap_duplicate_reversed_or_shifted_test_window_denies(source, indices):
    original = request(source)
    dates = tuple(day.session for day in original.trajectory.days)
    with pytest.raises(ValueError, match=r"^capital_matched_reference_invalid$"):
        run(replace(original, test_sessions=tuple(dates[index] for index in indices)))


@pytest.mark.parametrize(
    "field",
    (
        "source_qualified",
        "cost_qualified",
        "execution_enabled",
        "economic_admitted",
        "evidence_promotable",
    ),
)
def test_enabling_marker_cannot_authorize_matching(source, field):
    original = request(source)
    object.__setattr__(original, field, True)
    with pytest.raises(ValueError, match=r"^capital_matched_reference_invalid$"):
        run(original)


def test_supplied_result_or_missing_original_action_history_is_not_authority(source):
    from trading_bot.simulation.etf_capital_trajectory import replay_capital_trajectory

    original = request(source)
    supplied = replay_capital_trajectory(original.trajectory)
    with pytest.raises(ValueError, match=r"^capital_matched_reference_invalid$"):
        run(replace(original, trajectory=supplied))
    damaged = replace(source)
    object.__setattr__(
        damaged, "actions", (replace(source.actions[0], splits=None), *source.actions[1:])
    )
    with pytest.raises(ValueError, match=r"^capital_matched_reference_invalid$"):
        run(replace(original, trajectory=replace(original.trajectory, dataset=damaged)))


def test_ambient_precision_traps_cannot_change_matching_or_legacy_passive_identity(source):
    from tests.unit.research.test_etf_capital_passive import request as passive_request
    from tests.unit.research.test_etf_capital_passive import run as passive_run
    from tests.unit.research.test_etf_capital_passive import source as passive_source

    value = request(source)
    expected = run(value)
    with localcontext() as context:
        context.prec = 3
        assert run(value) == expected
        passive = passive_run(passive_request(passive_source()))
    assert passive.input_hash == "7f34ea0c7c9147edd5985012be73b43e4f96a4bf4bde3ee6bf63e9813c72dbe1"
    assert passive.kernel_result.input_hash == (
        "3d6ac7fd2b2150ffb24d9d50b61b2fdbceb27da7755368c6264f44e60867c8f0"
    )


@pytest.mark.parametrize("outcome", ("unfilled", "partial"))
def test_unfilled_or_partial_originals_are_not_forced_complete_for_matching(source, outcome):
    original = request(source)
    path = replace(
        original.trajectory,
        entry_outcome=outcome,
        entry_fill_fraction=D(".5") if outcome == "partial" else D(0),
        entry_fee=D(".01") if outcome == "partial" else D(0),
    )
    value = run(replace(original, trajectory=path))
    if outcome == "unfilled":
        assert value.mean_exposure == 0 and value.kernel_result.fees_paid == 0
    else:
        assert D(0) < value.mean_exposure < D(".10")
    assert value.realized_trading_pnl is None


def test_references_use_original_spy_prices_not_held_ief_prices(source):
    spy, *rest = source.archives
    page = spy.pages[0]
    spy = replace(
        spy,
        pages=(
            replace(
                page,
                records=tuple(
                    replace(
                        row,
                        bar=replace(
                            row.bar,
                            open=row.bar.open * 2,
                            high=row.bar.high * 2,
                            low=row.bar.low * 2,
                            close=row.bar.close * 2,
                            vwap=row.bar.vwap * 2,
                        ),
                    )
                    for row in page.records
                ),
            ),
        ),
    )
    changed = replace(source, archives=(spy, *rest))
    value = run(request(changed))
    assert value.close_exposures[0] == D(
        "0.1500262545945540469582176880954166979221363738654264496286850199"
    )
    assert value.kernel_result.entry_price == D("600.30")


@pytest.mark.parametrize("window", ([], (None,), (True,)))
def test_non_tuple_or_non_date_window_cannot_alias_real_session_identity(source, window):
    with pytest.raises(ValueError, match=r"^capital_matched_reference_invalid$"):
        run(replace(request(source), test_sessions=window))


def test_dictionary_and_subclass_requests_cannot_adopt_original_authority(source):
    from trading_bot.research.etf_capital_matched import CapitalMatchedRequest

    class Child(CapitalMatchedRequest):
        pass

    original = request(source)
    for value in ({}, Child(original.trajectory, original.test_sessions)):
        with pytest.raises(ValueError, match=r"^capital_matched_reference_invalid$"):
            run(value)


@pytest.mark.parametrize(
    "field",
    (
        "source_qualified",
        "cost_qualified",
        "execution_enabled",
        "economic_admitted",
        "evidence_promotable",
    ),
)
def test_mutated_inner_trajectory_markers_are_rejected_before_copy_normalization(source, field):
    original = request(source)
    object.__setattr__(original.trajectory, field, True)
    with pytest.raises(ValueError, match=r"^capital_matched_reference_invalid$"):
        run(original)


def test_held_receivable_counts_once_in_original_exposure_denominator(source):
    ex_date = source.calendar.sessions[201].session_date
    pay_date = source.calendar.sessions[203].session_date
    action = replace(
        source.actions[-1],
        distributions=(CapitalDistribution(ex_date, ex_date, pay_date, D(2), "a" * 64),),
    )
    value = run(request(replace(source, actions=(*source.actions[:-1], action))))
    with localcontext() as context:
        context.prec = 64
        expected = D("15.05") / D("100.1325")
    assert value.close_exposures[1] == expected
    assert value.close_exposures[2:] == (D(0), D(0), D(0))


def test_original_spy_distribution_pays_cash_once_without_reinvesting_matched_shares(source):
    ex_date = source.calendar.sessions[201].session_date
    pay_date = source.calendar.sessions[203].session_date
    action = replace(
        source.actions[0],
        distributions=(CapitalDistribution(ex_date, ex_date, pay_date, D(2), "b" * 64),),
    )
    value = run(request(replace(source, actions=(action, *source.actions[1:]))))
    assert value.kernel_result.dividends_received == D(".04003962155590914509283257034")
    assert value.kernel_result.dividends_receivable == 0
    assert len(value.kernel_result.dividend_payments) == 1
    assert len(set(value.raw_quantities)) == 1


def test_coincident_reference_split_and_distribution_are_not_silently_reordered(source):
    day = source.calendar.sessions[201].session_date
    action = replace(
        source.actions[0],
        splits=(CapitalSplit(day, D(2), "a" * 64),),
        distributions=(CapitalDistribution(day, day, day, D(1), "b" * 64),),
    )
    with pytest.raises(ValueError, match=r"^capital_matched_reference_invalid$"):
        run(request(replace(source, actions=(action, *source.actions[1:]))))
