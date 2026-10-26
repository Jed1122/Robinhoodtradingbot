"""Fictional arithmetic fixtures; these are not stock-study findings."""

import importlib
import importlib.util
from dataclasses import FrozenInstanceError
from decimal import ROUND_DOWN, Decimal, localcontext
from types import ModuleType

import pytest


def statistics_module() -> ModuleType:
    name = "trading_bot.research.stock_study_statistics"
    assert importlib.util.find_spec(name) is not None, "stock study statistics is not implemented"
    return importlib.import_module(name)


def test_path_uses_sample_volatility_and_all_period_downside_rms() -> None:
    # Returns +10%, -10%, +10% imply sample annual vol20%, Sharpe0.5,
    # Sortino1.0 at three periods/year. Negative-only deviation is incorrect.
    result = statistics_module().summarize_price_path(
        (Decimal("100"), Decimal("110"), Decimal("99"), Decimal("108.9")),
        periods_per_year=3,
        elapsed_years=Decimal("1"),
    )
    assert result.total_return == Decimal("0.089")
    assert result.cagr == Decimal("0.089")
    assert abs(
        result.mean_return - Decimal("0.033333333333333333333333333333333333333333333333333")
    ) < Decimal("1e-48")
    assert abs(result.annualized_volatility - Decimal("0.2")) < Decimal("1e-48")
    assert abs(result.sharpe - Decimal("0.5")) < Decimal("1e-48")
    assert abs(result.sortino - Decimal("1")) < Decimal("1e-48")
    assert result.max_drawdown == Decimal("0.1")
    assert result.inherited_max_drawdown == Decimal("0.1")
    assert result.period_count == 3
    assert result.undefined_reasons == ()


def test_inherited_peak_includes_baseline_drawdown_separately_from_segment() -> None:
    result = statistics_module().summarize_price_path(
        (Decimal("80"), Decimal("90"), Decimal("85")),
        inherited_peak=Decimal("100"),
    )
    assert abs(result.max_drawdown - Decimal("0.05555555555555555555555555556")) < Decimal("1e-28")
    assert result.inherited_max_drawdown == Decimal("0.2")


def test_flat_path_preserves_undefined_ratios_and_defined_zero_metrics() -> None:
    result = statistics_module().summarize_price_path((Decimal("1"),) * 4)
    assert result.total_return == result.cagr == result.mean_return == Decimal("0")
    assert result.annualized_volatility == result.max_drawdown == Decimal("0")
    assert result.sharpe is None
    assert result.sortino is None
    assert "sharpe:zero_return_variance" in result.undefined_reasons
    assert "sortino:no_downside_returns" in result.undefined_reasons
    assert not result.qualified
    assert not result.investment_recommendation
    assert not result.live_activation_allowed
    with pytest.raises(FrozenInstanceError):
        result.qualified = True


def test_single_return_has_no_sample_volatility_but_downside_ratio_is_defined() -> None:
    result = statistics_module().summarize_price_path(
        (Decimal("100"), Decimal("90")), periods_per_year=1
    )
    assert result.period_count == 1
    assert result.annualized_volatility is None
    assert result.sharpe is None
    assert result.sortino == Decimal("-1")
    assert "annualized_volatility:fewer_than_two_returns" in result.undefined_reasons
    assert "sharpe:fewer_than_two_returns" in result.undefined_reasons


def test_explicit_elapsed_years_changes_cagr_and_is_labeled() -> None:
    summarize = statistics_module().summarize_price_path
    curve = (Decimal("100"), Decimal("110"), Decimal("121"))
    explicit = summarize(curve, periods_per_year=2, elapsed_years=Decimal("2"))
    implied = summarize(curve, periods_per_year=2)
    assert abs(explicit.cagr - Decimal("0.1")) < Decimal("1e-48")
    assert implied.cagr == Decimal("0.21")
    assert explicit.elapsed_years == Decimal("2")
    assert explicit.elapsed_years_basis == "explicit"
    assert implied.elapsed_years == Decimal("1")
    assert implied.elapsed_years_basis == "period_count/periods_per_year"
    assert explicit.evidence_hash != implied.evidence_hash


def test_summary_is_independent_of_ambient_decimal_precision_rounding_and_traps() -> None:
    summarize = statistics_module().summarize_price_path
    curve = (Decimal("3"), Decimal("4"), Decimal("2"), Decimal("5"))
    expected = summarize(curve)
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_DOWN
        context.Emax = 9
        context.Emin = -9
        for signal in context.traps:
            context.traps[signal] = True
        observed = summarize(curve)
    assert observed == expected
    assert len(observed.evidence_hash) == 64
    changed = summarize(curve, inherited_peak=Decimal("6"))
    assert changed.evidence_hash != observed.evidence_hash


@pytest.mark.parametrize(
    "equity",
    [
        (),
        (Decimal("1"),),
        (Decimal("1"),) * 10001,
        [Decimal("1"), Decimal("2")],
        (True, Decimal("1")),
        (1, Decimal("1")),
        (Decimal("1"), 1.0),
        (Decimal("0"), Decimal("1")),
        (Decimal("1"), Decimal("-1")),
        (Decimal("NaN"), Decimal("1")),
        (Decimal("sNaN"), Decimal("1")),
        (Decimal("1"), Decimal("Infinity")),
    ],
)
def test_summary_rejects_malformed_or_nonpositive_equity(equity: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        statistics_module().summarize_price_path(equity)


@pytest.mark.parametrize("periods_per_year", [True, False, 0, -1, Decimal("252"), 252.0])
def test_summary_rejects_invalid_period_count(periods_per_year: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        statistics_module().summarize_price_path(
            (Decimal("1"), Decimal("2")), periods_per_year=periods_per_year
        )


@pytest.mark.parametrize(
    "elapsed_years",
    [True, 1, 1.0, Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")],
)
def test_summary_rejects_invalid_elapsed_years(elapsed_years: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        statistics_module().summarize_price_path(
            (Decimal("1"), Decimal("2")), elapsed_years=elapsed_years
        )


@pytest.mark.parametrize(
    "peak", [True, 1, Decimal("0"), Decimal("0.5"), Decimal("NaN"), Decimal("Infinity")]
)
def test_summary_rejects_impossible_inherited_peak(peak: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        statistics_module().summarize_price_path((Decimal("1"), Decimal("2")), inherited_peak=peak)


def test_constant_paired_log_differences_have_point_intervals() -> None:
    result = statistics_module().paired_block_intervals(
        ((Decimal("0.001"),) * 40, (Decimal("0"),) * 40), replicates=100
    )
    first, second = result.intervals
    assert first.observed_mean == first.lower_mean == first.upper_mean == Decimal("0.001")
    assert second.observed_mean == second.lower_mean == second.upper_mean == Decimal("0")
    assert result.tail_probability == Decimal("0.0015625")
    assert result.family_size == 16
    assert result.observation_count == 40
    assert result.column_count == 2
    assert not result.qualified
    assert not result.investment_recommendation
    assert not result.live_activation_allowed
    with pytest.raises(FrozenInstanceError):
        result.qualified = True


def test_shared_block_draws_preserve_cross_column_dependence() -> None:
    result = statistics_module().paired_block_intervals(
        (
            (Decimal("-2"), Decimal("-1"), Decimal("0"), Decimal("1"), Decimal("4")),
            (Decimal("-4"), Decimal("-2"), Decimal("0"), Decimal("2"), Decimal("8")),
        ),
        block_length=2,
        replicates=500,
        family_size=2,
        alpha=Decimal("0.2"),
    )
    first, second = result.intervals
    assert first.observed_mean == Decimal("0.4")
    assert second.observed_mean == Decimal("0.8")
    assert second.lower_mean == 2 * first.lower_mean
    assert second.upper_mean == 2 * first.upper_mean


def test_quantiles_use_type7_interpolation_and_bonferroni_family() -> None:
    # Seed5 produces25 zero,41 half and34 one means for these100 two-draw
    # samples. Type7 at p=.25 lies75% between order statistics24 and25.
    bootstrap = statistics_module().paired_block_intervals
    narrow = bootstrap(
        ((Decimal("0"), Decimal("1")),),
        block_length=1,
        replicates=100,
        seed=5,
        family_size=1,
        alpha=Decimal("0.5"),
    )
    wide = bootstrap(
        ((Decimal("0"), Decimal("1")),),
        block_length=1,
        replicates=100,
        seed=5,
        family_size=2,
        alpha=Decimal("0.5"),
    )
    assert narrow.intervals[0].lower_mean == Decimal("0.375")
    assert narrow.intervals[0].upper_mean == Decimal("1")
    assert wide.intervals[0].lower_mean == Decimal("0")
    assert wide.intervals[0].upper_mean == Decimal("1")
    assert wide.tail_probability == Decimal("0.125")


def test_circular_blocks_truncate_final_block_at_original_observation_count() -> None:
    # Independent integer/Fraction enumeration for seed5,N3,L2,B100 gives
    # lower2/3 and upper34 at the25th/75th Type7 percentiles.
    result = statistics_module().paired_block_intervals(
        ((Decimal("0"), Decimal("1"), Decimal("100")),),
        block_length=2,
        replicates=100,
        seed=5,
        family_size=1,
        alpha=Decimal("0.5"),
    )
    interval = result.intervals[0]
    assert abs(interval.observed_mean - Decimal("33.66666666666666666666666667")) < Decimal("1e-26")
    assert abs(interval.lower_mean - Decimal("0.6666666666666666666666666667")) < Decimal("1e-28")
    assert interval.upper_mean == Decimal("34")


def test_same_seed_reproduces_results_and_different_seed_changes_uncertainty() -> None:
    bootstrap = statistics_module().paired_block_intervals
    columns = (tuple(Decimal(value) for value in (2, -5, 1, 7, -2, 0, 4, 12, -4, 3, 8, 1, -1)),)
    first = bootstrap(columns, block_length=3, replicates=200, seed=17, family_size=1)
    assert first == bootstrap(columns, block_length=3, replicates=200, seed=17, family_size=1)
    changed = bootstrap(columns, block_length=3, replicates=200, seed=18, family_size=1)
    assert first.intervals != changed.intervals
    assert first.evidence_hash != changed.evidence_hash
    assert len(first.evidence_hash) == 64


def test_bootstrap_warns_when_blocks_or_adjusted_tail_are_sparse() -> None:
    bootstrap = statistics_module().paired_block_intervals
    sparse = bootstrap(((Decimal("0"), Decimal("1")),), block_length=2, replicates=100)
    assert "few_effective_blocks:observation_count/block_length<10" in sparse.warnings
    assert "limited_tail_resolution:replicates*tail_probability<10" in sparse.warnings
    rich = bootstrap(
        ((Decimal("0"), Decimal("1")) * 10,),
        block_length=1,
        replicates=100,
        family_size=1,
        alpha=Decimal("0.5"),
    )
    assert rich.warnings == ()


def test_bootstrap_is_independent_of_ambient_decimal_context() -> None:
    bootstrap = statistics_module().paired_block_intervals
    columns = ((Decimal("0.001"), Decimal("-0.004"), Decimal("0.009")),)
    expected = bootstrap(columns, block_length=2, replicates=100)
    with localcontext() as context:
        context.prec = 5
        context.rounding = ROUND_DOWN
        context.Emax = 9
        context.Emin = -9
        for signal in context.traps:
            context.traps[signal] = True
        observed = bootstrap(columns, block_length=2, replicates=100)
    assert observed == expected


@pytest.mark.parametrize(
    "columns",
    [
        (),
        ((Decimal("1"),),),
        ((Decimal("1"),) * 10001,),
        ((Decimal("1"), Decimal("2")),) * 129,
        [[Decimal("1"), Decimal("2")]],
        ([Decimal("1"), Decimal("2")],),
        ((Decimal("1"), Decimal("2")), (Decimal("1"), Decimal("2"), Decimal("3"))),
        ((True, Decimal("1")),),
        ((1, Decimal("1")),),
        ((1.0, Decimal("1")),),
        ((Decimal("NaN"), Decimal("1")),),
        ((Decimal("sNaN"), Decimal("1")),),
        ((Decimal("1"), Decimal("Infinity")),),
    ],
)
def test_bootstrap_rejects_malformed_or_unaligned_columns(columns: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        statistics_module().paired_block_intervals(columns)


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("block_length", True),
        ("block_length", 0),
        ("block_length", 3),
        ("block_length", 1.0),
        ("replicates", True),
        ("replicates", 99),
        ("replicates", 50001),
        ("replicates", 100.0),
        ("seed", True),
        ("seed", -1),
        ("seed", 2**64),
        ("seed", Decimal("1")),
        ("family_size", True),
        ("family_size", 0),
        ("family_size", 1.0),
        ("alpha", True),
        ("alpha", 0.05),
        ("alpha", Decimal("0")),
        ("alpha", Decimal("1")),
        ("alpha", Decimal("NaN")),
        ("alpha", Decimal("Infinity")),
    ],
)
def test_bootstrap_rejects_invalid_configuration(parameter: str, value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        statistics_module().paired_block_intervals(
            ((Decimal("0"), Decimal("1")),), **{parameter: value}
        )


def test_bootstrap_rejects_omitted_comparisons_from_family_size() -> None:
    with pytest.raises(ValueError):
        statistics_module().paired_block_intervals(
            ((Decimal("0"), Decimal("1")),) * 2, family_size=1
        )


def test_bootstrap_accepts_upper_data_and_seed_bounds_without_promotion() -> None:
    result = statistics_module().paired_block_intervals(
        ((Decimal("0"),) * 10000,),
        block_length=10000,
        replicates=100,
        seed=2**64 - 1,
    )
    assert result.intervals[0].lower_mean == result.intervals[0].upper_mean == Decimal("0")
    assert not result.qualified


def test_constant_high_precision_differences_do_not_acquire_bootstrap_noise() -> None:
    value = Decimal("0.12345678901234567890123456789012345678901234567891")
    result = statistics_module().paired_block_intervals(
        ((value,) * 37,),
        block_length=13,
        replicates=100,
        family_size=1,
    )
    interval = result.intervals[0]
    assert interval.lower_mean == interval.observed_mean == interval.upper_mean == value


def test_full_length_circular_block_is_exactly_the_original_mean() -> None:
    column = (
        Decimal("0.12345678901234567890123456789012345678901234567891"),
        Decimal("-0.000012345678901234567890123456789012345678901234567891"),
        Decimal("0.23"),
    )
    result = statistics_module().paired_block_intervals(
        (column,),
        block_length=3,
        replicates=100,
        family_size=1,
    )
    interval = result.intervals[0]
    assert interval.lower_mean == interval.observed_mean == interval.upper_mean
