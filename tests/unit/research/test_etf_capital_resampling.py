"""Four-reference math capacity; supplied columns never authenticate evidence."""

from dataclasses import FrozenInstanceError
from decimal import ROUND_DOWN, Inexact, Rounded, localcontext
from decimal import Decimal as D
from random import getstate

import pytest

from trading_bot.research.etf_resampling import dependent_simultaneous_mean_intervals


def capital(series, **changes):
    from trading_bot.research.etf_resampling import dependent_capital_simultaneous_mean_intervals

    return dependent_capital_simultaneous_mean_intervals(series, **(dict(seed=0) | changes))


def test_complete_four_reference_capacity_has_literal_constant_bands_not_support():
    # 29 paths * 6 capitals * 4 costs * 4 reference roles = 2784 columns.
    values = ((D(".125"),) * 20,) * 2784
    (result,) = capital(values, block_lengths=(20,), draws=1)
    assert (result.comparisons, result.observations, result.samples) == (2784, 20, 1)
    assert result.radius == D(0)
    assert len(result.intervals) == 2784
    assert all((row.lower, row.upper) == (D(".125"), D(".125")) for row in result.intervals)
    assert result.independent_opportunities is None
    with pytest.raises(FrozenInstanceError):
        result.comparisons = 1
    with pytest.raises(FrozenInstanceError):
        result.intervals[0].lower = D(0)


def test_capital_capacity_does_not_widen_legacy_admission():
    row = (D(0),) * 20
    (legacy,) = dependent_simultaneous_mean_intervals(
        (row,) * 2088, seed=0, block_lengths=(20,), draws=1
    )
    assert legacy.comparisons == 2088
    with pytest.raises(ValueError):
        dependent_simultaneous_mean_intervals(
            (row,) * 2089, seed=0, block_lengths=(20,), draws=1
        )
    with pytest.raises(ValueError):
        capital((row,) * 2785, block_lengths=(20,), draws=1)


def test_shared_seeded_single_draw_does_not_consume_rng_between_columns():
    values = (D(-1),) + (D(0),) * 19 + (D(1),)
    (result,) = capital(
        (values, tuple(-v for v in values), values), block_lengths=(20,), draws=1
    )
    assert result.radius == D(".04761904761904761904761904762")
    assert tuple((row.lower, row.upper) for row in result.intervals) == (
        (D("-.04761904761904761904761904762"), D(".04761904761904761904761904762")),
    ) * 3


def test_positive_shift_preserves_outward_endpoints_after_rounded_radius():
    # Original total10; seed0/block20/draws3 totals20,20,10 -> radius10/21.
    values = (D(0), D(10)) + (D(0),) * 19
    (result,) = capital((values, tuple(-v for v in values)), block_lengths=(20,), draws=3)
    assert result.radius == D(".4761904761904761904761904762")
    assert tuple((row.lower, row.upper) for row in result.intervals) == (
        (D("-9.523809523809523809523809524E-30"), D(".9523809523809523809523809524")),
        (D("-.9523809523809523809523809524"), D("9.523809523809523809523809524E-30")),
    )


def test_small_capital_and_legacy_results_match_exactly_without_global_rng_or_context():
    values = tuple(D(i) for i in range(101))
    series = (values, tuple(-v for v in values))
    baseline = dependent_simultaneous_mean_intervals(series, seed=29, draws=13)
    rng_before = getstate()
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.Emin, context.Emax = -3, 3
        context.traps[Inexact] = context.traps[Rounded] = True
        before = str(context), context.flags.copy()
        assert capital(series, seed=29, draws=13) == baseline
        assert (str(context), context.flags.copy()) == before
    assert getstate() == rng_before
    reversed_result = capital(series[::-1], seed=29, block_lengths=(100, 20), draws=13)
    for first, second in zip(baseline, reversed_result[::-1], strict=True):
        assert first.radius == second.radius
        assert first.intervals == second.intervals[::-1]


def test_adding_worse_column_expands_every_band_without_inventing_opportunities():
    values = (D(-1),) + (D(0),) * 19 + (D(1),)
    (result,) = capital((values, tuple(2 * v for v in values)), block_lengths=(20,), draws=12)
    assert result.radius == D(".1904761904761904761904761905")
    assert result.intervals[0].lower == D("-.1904761904761904761904761905")
    assert result.independent_opportunities is None


@pytest.mark.parametrize(
    "series",
    ((), [], ((D(0),) * 100, (D(0),) * 101), ((True,) * 100,),
     ((0.0,) * 100,), ((D("NaN"),) * 100,), ((D("Infinity"),) * 100,),
     ((D(0),) * 2049,), ([D(0)] * 100,)),
)
def test_invalid_supplied_math_columns_cannot_produce_partial_bands(series):
    with pytest.raises(ValueError):
        capital(series)


@pytest.mark.parametrize(
    "changes", ({"seed": True}, {"seed": -1}, {"seed": 2**63}, {"draws": True},
                {"draws": 0}, {"draws": 10001}, {"block_lengths": ()},
                {"block_lengths": (20, 20)}, {"block_lengths": (21,)},
                {"block_lengths": (True,)}, {"block_lengths": [20]}),
)
def test_invalid_controls_remain_fail_closed(changes):
    with pytest.raises(ValueError):
        capital(((D(0),) * 100,), **changes)
