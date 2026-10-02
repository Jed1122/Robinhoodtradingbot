"""Independent paired-return arithmetic; no data qualification or acceptance."""

import importlib
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Context, Decimal, Inexact, Rounded, localcontext
from fractions import Fraction
from random import Random

import pytest

from trading_bot.research.etf_resampling import EtfBlockInterval, EtfBlockRisk

D = Decimal
SHA = "a" * 64


def api():
    try:
        return importlib.import_module("trading_bot.research.etf_paired_economics")
    except ModuleNotFoundError:
        pytest.fail("paired ETF after-cost analytics is missing")


def dates(count=100):
    return tuple(date(2020, 1, 1) + timedelta(days=i) for i in range(count))


def inputs(count=100, **changes):
    values = {
        "session_dates": dates(count),
        "candidate": (D(".02"),) * count,
        "constrained_benchmark": (D(".01"),) * count,
        "cash_benchmark": (D("0"),) * count,
        "input_hash": SHA,
    }
    return api().EtfMatchedReturns(**(values | changes))


def test_already_after_cost_returns_are_subtracted_once_in_fraction_units():
    # .02 - .01 = .01 and .02 - 0 = .02, not 1%/2% or another fee debit.
    result = api().analyze_etf_matched_returns(inputs(), seed=7)
    assert result.candidate_mean == D(".02")
    assert result.candidate_vs_constrained == tuple(
        EtfBlockRisk(EtfBlockInterval(n, 1000, 100, D(".01"), D(".01")), 0, 0, D(0), D(0))
        for n in (20, 100)
    )
    assert result.candidate_vs_cash == tuple(
        EtfBlockRisk(EtfBlockInterval(n, 1000, 100, D(".02"), D(".02")), 0, 0, D(0), D(0))
        for n in (20, 100)
    )
    assert result.constrained_lower_bound == D(".01")
    assert result.cash_lower_bound == D(".02")
    assert result.units == "fraction"
    assert result.verdict == "ECONOMIC_NO_GO"
    assert result.execution_enabled is False and result.evidence_promotable is False
    with pytest.raises(FrozenInstanceError):
        result.candidate_mean = D(1)


def test_negative_cash_and_zero_excess_are_valid_and_not_accepted():
    result = api().analyze_etf_matched_returns(
        inputs(
            candidate=(D("-.25"),) * 100,
            constrained_benchmark=(D("-.25"),) * 100,
            cash_benchmark=(D("-.125"),) * 100,
        ),
        seed=0,
    )
    assert result.candidate_mean == D("-.25")
    for risk in result.candidate_vs_constrained:
        assert (risk.loss_samples, risk.nonpositive_samples) == (0, 1000)
        assert (risk.loss_probability, risk.nonpositive_probability) == (D(0), D(1))
    for risk in result.candidate_vs_cash:
        assert (risk.interval.lower, risk.interval.upper) == (D("-.125"), D("-.125"))
        assert (risk.loss_samples, risk.nonpositive_samples) == (1000, 1000)
    assert result.verdict == "ECONOMIC_NO_GO"


def oracle(values, seed, length):
    """Independent Fraction sums over materialized chronological blocks."""
    rng = Random(seed + length)
    fractions = tuple(Fraction(value) for value in values)
    totals = []
    for _ in range(1000):
        draw = []
        while len(draw) < len(values):
            start = rng.randrange(len(values) - length + 1)
            draw.extend(fractions[start : start + length])
        totals.append(sum(draw[: len(values)], Fraction(0)))
    means = sorted(total / len(values) for total in totals)
    with localcontext(Context(prec=28)):
        lower = D(means[24].numerator) / D(means[24].denominator)
        upper = D(means[975].numerator) / D(means[975].denominator)
        loss = sum(total < 0 for total in totals)
        nonpositive = sum(total <= 0 for total in totals)
        return EtfBlockRisk(
            EtfBlockInterval(length, 1000, len(values), lower, upper),
            loss,
            nonpositive,
            D(loss) / D(1000),
            D(nonpositive) / D(1000),
        )


def test_paired_chronological_differences_match_fraction_oracle_and_worst_bounds():
    candidate = (D(".01"), D("-.005"), D(".003")) * 34 + (D("-.002"),)
    benchmark = (D(".004"), D("-.002"), D(".001")) * 34 + (D(".002"),)
    excess = (D(".006"), D("-.003"), D(".002")) * 34 + (D("-.004"),)
    package = inputs(103, candidate=candidate, constrained_benchmark=benchmark)
    result = api().analyze_etf_matched_returns(package, seed=11)
    expected_constrained = tuple(oracle(excess, 11, n) for n in (20, 100))
    expected_cash = tuple(oracle(candidate, 11, n) for n in (20, 100))
    assert result.candidate_vs_constrained == expected_constrained
    assert result.candidate_vs_cash == expected_cash
    assert result.candidate_mean == D(".002621359223300970873786407767")
    assert result.constrained_lower_bound == min(r.interval.lower for r in expected_constrained)
    assert result.cash_lower_bound == min(r.interval.lower for r in expected_cash)
    assert api().analyze_etf_matched_returns(package, seed=11) == result


def test_subtraction_and_mean_preserve_tiny_offsets_in_hostile_context():
    baseline = D("1e100")
    # The literal differs from 1e100 by exactly .01; caller precision must not erase it.
    candidate = D("1" + "0" * 100 + ".01")
    package = inputs(
        candidate=(candidate,) * 100,
        constrained_benchmark=(baseline,) * 100,
        cash_benchmark=(candidate,) * 100,
    )
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        context.Emin = -2
        context.Emax = 2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        before = (str(context), context.flags.copy())
        result = api().analyze_etf_matched_returns(package, seed=0)
        assert (str(context), context.flags.copy()) == before
    assert result.candidate_mean == baseline  # Fixed 28-digit arithmetic mean.
    assert result.constrained_lower_bound == D(".01")
    assert result.cash_lower_bound == 0
    assert result.candidate_vs_constrained[0].interval.lower == D(".01")


@pytest.mark.parametrize("count", [99, 10001])
def test_observation_bounds_are_not_shortened_or_truncated(count):
    with pytest.raises(ValueError, match=r"^etf_paired_economics_invalid$"):
        inputs(count)


def test_upper_observation_boundary_remains_supported():
    package = inputs(10000)
    result = api().analyze_etf_matched_returns(package, seed=7)
    assert result.candidate_mean == D(".02")
    assert all(r.interval.observations == 10000 for r in result.candidate_vs_cash)


@pytest.mark.parametrize(
    "changes",
    [
        {"session_dates": list(dates())},
        {"session_dates": (*dates()[:-1], dates()[-2])},
        {"session_dates": tuple(reversed(dates()))},
        {"session_dates": (datetime(2020, 1, 1), *dates()[1:])},
        {"candidate": [D("0")] * 100},
        {"candidate": (D("0"),) * 99},
        {"constrained_benchmark": (D("0"),) * 101},
        {"cash_benchmark": ()},
        {"input_hash": "A" * 64},
        {"input_hash": "raw/private/path"},
        {"input_hash": 123},
    ],
)
def test_invalid_alignment_and_exact_builtin_inputs_are_sanitized(changes):
    with pytest.raises(ValueError, match=r"^etf_paired_economics_invalid$"):
        inputs(**changes)


@pytest.mark.parametrize("series", ["candidate", "constrained_benchmark", "cash_benchmark"])
@pytest.mark.parametrize(
    "bad",
    [
        D("-1"),
        D("-1.01"),
        D("NaN"),
        D("sNaN"),
        D("Infinity"),
        D("1e513"),
        D("0e999999"),
        True,
        0,
        0.01,
        "0.01",
    ],
)
def test_all_return_series_reject_invalid_values(series, bad):
    with pytest.raises(ValueError, match=r"^etf_paired_economics_invalid$"):
        inputs(**{series: (bad, *([D("0")] * 99))})


@pytest.mark.parametrize("seed", [-1, 2**63, True, D(1), "private-data", None])
def test_invalid_seed_is_not_coerced_or_exposed(seed):
    with pytest.raises(ValueError, match=r"^etf_paired_economics_invalid$"):
        api().analyze_etf_matched_returns(inputs(), seed=seed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_dates", (date(2020, 1, 1),) * 100),
        ("candidate", (D("-1"),) * 100),
        ("cash_benchmark", (D("0"),) * 99),
        ("input_hash", "private-input"),
    ],
)
def test_analyzer_revalidates_unsafe_mutation_of_frozen_inputs(field, value):
    package = inputs()
    object.__setattr__(package, field, value)
    with pytest.raises(ValueError, match=r"^etf_paired_economics_invalid$"):
        api().analyze_etf_matched_returns(package, seed=0)


def test_analyzer_rejects_nonrecord_and_subclass_without_calling_user_methods():
    class Hostile:
        def __repr__(self):
            raise AssertionError("private text must not be rendered")

    class Subclass(api().EtfMatchedReturns):
        pass

    for value in (Hostile(), Subclass(dates(), (D(0),) * 100, (D(0),) * 100, (D(0),) * 100, SHA)):
        with pytest.raises(ValueError, match=r"^etf_paired_economics_invalid$"):
            api().analyze_etf_matched_returns(value, seed=0)


def test_report_identity_binds_input_dates_benchmarks_and_seed():
    package = inputs()
    first = api().analyze_etf_matched_returns(package, seed=7)
    for altered in (
        replace(package, input_hash="b" * 64),
        replace(package, session_dates=(*dates()[1:], date(2020, 4, 10))),
        replace(package, constrained_benchmark=(D(".011"),) * 100),
        replace(package, cash_benchmark=(D(".001"),) * 100),
    ):
        assert api().analyze_etf_matched_returns(altered, seed=7).report_hash != first.report_hash
    assert api().analyze_etf_matched_returns(package, seed=8).report_hash != first.report_hash
    assert len(first.report_hash) == 64
