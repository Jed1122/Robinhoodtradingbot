"""Hand-derived statistics from synthetic values, never economic acceptance."""

import random
from dataclasses import FrozenInstanceError
from decimal import ROUND_DOWN, Decimal, Inexact, Rounded, localcontext

import pytest


@pytest.mark.parametrize("value", [Decimal("0.125"), Decimal("-0.125"), Decimal("0")])
def test_constant_series_has_exact_interval_and_separate_observation_count(value):
    from trading_bot.research.etf_resampling import dependent_mean_intervals

    intervals = dependent_mean_intervals((value,) * 100, seed=7)

    assert type(intervals) is tuple
    assert [(i.block_length, i.samples, i.observations, i.lower, i.upper) for i in intervals] == [
        (20, 1000, 100, value, value),
        (100, 1000, 100, value, value),
    ]


@pytest.mark.parametrize(
    ("draws", "expected"),
    [
        (40, (Decimal("28.5"), Decimal("80.3"))),
        (41, (Decimal("33.1"), Decimal("67.3"))),
    ],
)
def test_varied_series_uses_conservative_noninterpolated_order_statistics(draws, expected):
    from trading_bot.research.etf_resampling import dependent_mean_intervals

    # For values 1..100, a 20-value block at zero-based s has sum 20*s + 210.
    # Five blocks give mean sum(starts)/5 + 10.5. Random(7+20)'s 41
    # draws have second-smallest start-sum 113 and second-largest 284.
    # Conservative ranks on 0..40 are exactly 1 and 39. With 40 draws,
    # fractional ranks 0.975/38.025 round outward to 0/39, with sums 90/349.
    (interval,) = dependent_mean_intervals(
        tuple(Decimal(i) for i in range(1, 101)), seed=7, block_lengths=(20,), draws=draws
    )

    assert (interval.lower, interval.upper) == expected
    assert (interval.samples, interval.observations) == (draws, 100)


def test_nondivisible_sample_keeps_first_values_of_final_contiguous_block():
    from trading_bot.research.etf_resampling import dependent_mean_intervals

    # Both admissible 20-value blocks total 10. Random(0+20) starts are
    # (0,1), (0,1), (0,0). The one-value tail therefore totals 10,10,0;
    # resample means are 20/21,20/21,10/21, not means of 40 observations.
    (interval,) = dependent_mean_intervals(
        (Decimal("0"), Decimal("10")) + (Decimal("0"),) * 19,
        seed=0,
        block_lengths=(20,),
        draws=3,
    )

    assert (interval.lower, interval.upper) == (
        Decimal("0.4761904761904761904761904762"),
        Decimal("0.9523809523809523809523809524"),
    )
    assert interval.observations == 21


def test_block_equal_to_sample_length_retains_entire_observation_order():
    from trading_bot.research.etf_resampling import dependent_mean_intervals

    (interval,) = dependent_mean_intervals(
        (Decimal("0"),) * 19 + (Decimal("100"),),
        seed=28,
        block_lengths=(20,),
        draws=41,
    )

    assert interval.lower == interval.upper == Decimal("5")


def test_summation_preserves_small_cash_flow_between_offsetting_large_values():
    from trading_bot.research.etf_resampling import dependent_mean_intervals

    large = Decimal("1e500")
    (interval,) = dependent_mean_intervals(
        (large, Decimal("1e-500"), large.copy_negate()) + (Decimal("0"),) * 17,
        seed=9,
        block_lengths=(20,),
        draws=1,
    )

    assert interval.lower == interval.upper == Decimal("5e-502")


@pytest.mark.parametrize(
    "bad_values",
    [
        (),
        (Decimal("1"),) * 19,
        (Decimal("1"),) * 10001,
        [Decimal("1")] * 100,
        None,
        (True,) * 100,
        (1,) * 100,
        (0.1,) * 100,
        ("private-value-never-echo",) * 100,
        (Decimal("NaN"),) * 100,
        (Decimal("sNaN"),) * 100,
        (Decimal("Infinity"),) * 100,
        (Decimal("-Infinity"),) * 100,
        (Decimal("1e513"),) * 100,
        (Decimal("1e-513"),) * 100,
        (Decimal("1" * 513),) * 100,
        (Decimal("0e999999"),) * 100,
        (Decimal("0e-999999"),) * 100,
    ],
    ids=[
        "empty",
        "short",
        "oversized",
        "mutable",
        "none",
        "boolean",
        "integer",
        "float",
        "string",
        "nan",
        "signaling-nan",
        "positive-infinity",
        "negative-infinity",
        "huge-exponent",
        "tiny-exponent",
        "too-many-digits",
        "huge-zero",
        "tiny-zero",
    ],
)
def test_invalid_values_fail_with_fixed_sanitized_error(bad_values):
    from trading_bot.research.etf_resampling import dependent_mean_intervals

    with pytest.raises(ValueError, match=r"^etf_resampling_invalid$"):
        dependent_mean_intervals(bad_values, seed=7, block_lengths=(20,), draws=1)


@pytest.mark.parametrize(
    "overrides",
    [
        {"seed": True},
        {"seed": -1},
        {"seed": 2**63},
        {"seed": 1.0},
        {"seed": "private-value-never-echo"},
        {"draws": True},
        {"draws": 0},
        {"draws": -1},
        {"draws": 10001},
        {"draws": 1.0},
        {"draws": "private-value-never-echo"},
        {"block_lengths": ()},
        {"block_lengths": []},
        {"block_lengths": (True,)},
        {"block_lengths": (20.0,)},
        {"block_lengths": ("private-value-never-echo",)},
        {"block_lengths": (1,)},
        {"block_lengths": (0,)},
        {"block_lengths": (-20,)},
        {"block_lengths": (21,)},
        {"block_lengths": (20, 20)},
        {"block_lengths": (100, 100)},
    ],
    ids=[
        "bool-seed",
        "negative-seed",
        "oversized-seed",
        "float-seed",
        "string-seed",
        "bool-draws",
        "zero-draws",
        "negative-draws",
        "oversized-draws",
        "float-draws",
        "string-draws",
        "empty-lengths",
        "mutable-lengths",
        "bool-length",
        "float-length",
        "string-length",
        "iid-length",
        "zero-length",
        "negative-length",
        "unregistered-length",
        "duplicate-20",
        "duplicate-100",
    ],
)
def test_invalid_resampling_controls_fail_with_fixed_sanitized_error(overrides):
    from trading_bot.research.etf_resampling import dependent_mean_intervals

    args = dict(seed=7, draws=1, block_lengths=(20,))
    args.update(overrides)
    with pytest.raises(ValueError, match=r"^etf_resampling_invalid$"):
        dependent_mean_intervals((Decimal("1"),) * 100, **args)


def test_short_sample_rejects_default_hundred_session_block():
    from trading_bot.research.etf_resampling import dependent_mean_intervals

    with pytest.raises(ValueError, match=r"^etf_resampling_invalid$"):
        dependent_mean_intervals((Decimal("1"),) * 99, seed=7)


def test_caller_decimal_precision_rounding_traps_and_flags_are_unchanged():
    from trading_bot.research.etf_resampling import dependent_mean_intervals

    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.Emin = -3
        context.Emax = 3
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        before = (str(context), context.flags.copy())
        (interval,) = dependent_mean_intervals(
            (Decimal("0"), Decimal("10")) + (Decimal("0"),) * 19,
            seed=0,
            block_lengths=(20,),
            draws=1,
        )
        assert (str(context), context.flags.copy()) == before

    assert interval.lower == interval.upper == Decimal("0.9523809523809523809523809524")


def test_block_streams_are_deterministic_independent_of_order_and_global_rng():
    from trading_bot.research.etf_resampling import dependent_mean_intervals

    values = tuple(Decimal(i) for i in range(1, 101))
    state = random.getstate()
    first = dependent_mean_intervals(values, seed=7, draws=41)
    assert random.getstate() == state
    assert first == dependent_mean_intervals(values, seed=7, draws=41)
    assert first[::-1] == dependent_mean_intervals(
        values, seed=7, block_lengths=(100, 20), draws=41
    )
    assert first[:1] == dependent_mean_intervals(values, seed=7, block_lengths=(20,), draws=41)
    assert first[1:] == dependent_mean_intervals(values, seed=7, block_lengths=(100,), draws=41)


def test_limits_are_inclusive_without_counting_draws_as_observations():
    from trading_bot.research.etf_resampling import dependent_mean_intervals

    (large,) = dependent_mean_intervals(
        (Decimal("-1.25"),) * 10000, seed=2**63 - 1, block_lengths=(20,), draws=1
    )
    (many,) = dependent_mean_intervals(
        (Decimal("-1.25"),) * 20, seed=0, block_lengths=(20,), draws=10000
    )

    assert (large.samples, large.observations, large.lower, large.upper) == (
        1,
        10000,
        Decimal("-1.25"),
        Decimal("-1.25"),
    )
    assert (many.samples, many.observations, many.lower, many.upper) == (
        10000,
        20,
        Decimal("-1.25"),
        Decimal("-1.25"),
    )
    with pytest.raises(FrozenInstanceError):
        many.observations = 10000
