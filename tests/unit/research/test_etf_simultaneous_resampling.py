"""Hand-checked joint draws; intervals are not independent-support evidence."""

from decimal import ROUND_DOWN, Inexact, Rounded, localcontext
from decimal import Decimal as D

import pytest


def joint(series, **changes):
    from trading_bot.research.etf_resampling import dependent_simultaneous_mean_intervals

    return dependent_simultaneous_mean_intervals(series, **(dict(seed=0) | changes))


def test_constant_comparisons_have_exact_zero_radius_without_claiming_independence():
    value = joint(((D(".125"),) * 100, (D("-.25"),) * 100))
    assert tuple(v.radius for v in value) == (D(0), D(0))
    for item in value:
        assert item.comparisons == 2
        assert tuple((v.lower, v.upper) for v in item.intervals) == (
            (D(".125"), D(".125")),
            (D("-.25"), D("-.25")),
        )
        assert item.independent_opportunities is None


def test_shared_nondivisible_draws_preserve_opposite_column_dependence():
    # Original sum0. The same12 block/tail starts as the old literal fixture
    # give totals -1,-1,-2,1,-2,-1,1,0,-1,1,0,1. Opposite column has opposite
    # totals, so joint absolute errors are identical, radius2/21 rounded up.
    values = (D(-1),) + (D(0),) * 19 + (D(1),)
    (value,) = joint((values, tuple(-v for v in values)), block_lengths=(20,), draws=12)
    assert value.radius == D(".09523809523809523809523809524")
    assert tuple((v.lower, v.upper) for v in value.intervals) == (
        (D("-.09523809523809523809523809524"), D(".09523809523809523809523809524")),
        (D("-.09523809523809523809523809524"), D(".09523809523809523809523809524")),
    )


def test_worse_comparison_expands_every_simultaneous_band():
    values = (D(-1),) + (D(0),) * 19 + (D(1),)
    (value,) = joint((values, tuple(2 * v for v in values)), block_lengths=(20,), draws=12)
    assert value.radius == D(".1904761904761904761904761905")
    assert value.intervals[0].lower == D("-.1904761904761904761904761905")


def test_duplicate_comparison_does_not_change_the_joint_critical_value():
    values = tuple(D(i) for i in range(101))
    alone = joint((values,))
    duplicate = joint((values, values))
    assert tuple(v.radius for v in alone) == tuple(v.radius for v in duplicate)
    assert tuple(v.intervals[0] for v in alone) == tuple(v.intervals[1] for v in duplicate)


def test_joint_statistics_ignore_hostile_context_and_order_only_permutes_columns():
    values = tuple(D(i) for i in range(101))
    opposite = tuple(-v for v in values)
    baseline = joint((values, opposite))
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.Emin, context.Emax = -3, 3
        context.traps[Inexact] = context.traps[Rounded] = True
        before = str(context), context.flags.copy()
        assert joint((values, opposite)) == baseline
        assert (str(context), context.flags.copy()) == before
    reversed_columns = joint((opposite, values))
    for first, second in zip(baseline, reversed_columns, strict=True):
        assert first.radius == second.radius
        assert first.intervals[::-1] == second.intervals


@pytest.mark.parametrize(
    "series",
    ((), [], ((D(0),) * 100, (D(0),) * 101), ((True,) * 100,), ((D("NaN"),) * 100,)),
)
def test_malformed_or_unaligned_panel_is_not_partial_evidence(series):
    with pytest.raises(ValueError):
        joint(series)


def test_simultaneous_bounds_include_small_offsets_between_huge_values():
    values = (D("1e500"), D("1e-500"), D("-1e500")) + (D(0),) * 97
    (_, value) = joint((values,))
    assert value.radius == 0
    assert value.intervals[0].lower == D("1e-502")
    assert value.intervals[0].upper == D("1e-502")
