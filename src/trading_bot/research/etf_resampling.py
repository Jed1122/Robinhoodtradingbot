"""Pure dependent-outcome descriptive statistics; never promotion evidence."""

from dataclasses import dataclass
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from random import Random

from trading_bot.domain.decimal_utils import (
    MAX_CANONICAL_DECIMAL_TEXT_LENGTH,
    require_bounded_decimal,
)

_MEAN_CONTEXT = Context(
    prec=28,
    rounding=ROUND_HALF_EVEN,
    Emin=-999999,
    Emax=999999,
    capitals=1,
    clamp=0,
    flags=[],
    traps=[InvalidOperation, DivisionByZero, Overflow],
)
# Canonical inputs span at most 512 integer/fractional places. Even 10,000
# additions fit exactly in 1,100 digits; only the final mean rounds to 28.
_SUM_CONTEXT = _MEAN_CONTEXT.copy()
_SUM_CONTEXT.prec = 1100


def _require(ok: bool) -> None:
    if not ok:
        raise ValueError("etf_resampling_invalid")


def _validate(
    values: tuple[Decimal, ...], seed: int, block_lengths: tuple[int, ...], draws: int
) -> None:
    _require(type(values) is tuple and 1 <= len(values) <= 10000)
    _require(type(seed) is int and 0 <= seed < 2**63)
    _require(type(draws) is int and 1 <= draws <= 10000)
    _require(type(block_lengths) is tuple and 1 <= len(block_lengths) <= 2)
    _require(all(type(length) is int and length in (20, 100) for length in block_lengths))
    _require(len(set(block_lengths)) == len(block_lengths))
    _require(all(length <= len(values) for length in block_lengths))
    for value in values:
        require_bounded_decimal(value, "resampling value")
        parts = value.as_tuple()
        _require(len(parts.digits) <= MAX_CANONICAL_DECIMAL_TEXT_LENGTH)
        _require(
            isinstance(parts.exponent, int)
            and abs(parts.exponent) <= MAX_CANONICAL_DECIMAL_TEXT_LENGTH
        )


@dataclass(frozen=True, slots=True)
class EtfBlockInterval:
    block_length: int
    samples: int
    observations: int
    lower: Decimal
    upper: Decimal


@dataclass(frozen=True, slots=True)
class EtfBlockRisk:
    interval: EtfBlockInterval
    loss_samples: int
    nonpositive_samples: int
    loss_probability: Decimal
    nonpositive_probability: Decimal


@dataclass(frozen=True, slots=True)
class EtfSimultaneousBlockIntervals:
    """Conditional joint-bootstrap bands, not opportunity or source evidence."""

    block_length: int
    samples: int
    observations: int
    comparisons: int
    radius: Decimal
    intervals: tuple[EtfBlockInterval, ...]
    independent_opportunities: None = None


def _draw_totals(
    values: tuple[Decimal, ...], *, seed: int, length: int, draws: int
) -> tuple[Decimal, ...]:
    """Exact original draw engine, shared by individual and joint intervals."""
    with localcontext(_SUM_CONTEXT):
        prefix = [Decimal(0)]
        for value in values:
            prefix.append(prefix[-1] + value)
        # Every equal-length column receives the SAME starts; never global RNG.
        rng = Random(seed + length)  # nosec B311
        starts = len(values) - length + 1
        full_blocks, remainder = divmod(len(values), length)
        sums = tuple(prefix[start + length] - prefix[start] for start in range(starts))
        tails = tuple(prefix[start + remainder] - prefix[start] for start in range(starts))
        totals = []
        for _ in range(draws):
            total = sum((sums[rng.randrange(starts)] for _ in range(full_blocks)), Decimal(0))
            if remainder:
                total += tails[rng.randrange(starts)]
            totals.append(total)
        return tuple(totals)


def dependent_mean_risks(
    values: tuple[Decimal, ...],
    *,
    seed: int,
    block_lengths: tuple[int, ...] = (20, 100),
    draws: int = 1000,
) -> tuple[EtfBlockRisk, ...]:
    """Resample moving, noncircular 20/100-session blocks into mean risks.

    The immutable chronological input must contain at most 10,000 exact bounded
    Decimal observations. The preregistered block tuple is nonempty and unique;
    sample size must support every selected length. Draws are in [1,10,000] and
    seeds in [0,2**63). Each length has an independent Random(seed + length), so
    result tuple ordering cannot change another length's draws.

    Sample starts are uniform on [0,n-length], and each chosen contiguous block
    retains its original order. Concatenation is truncated to exactly n values;
    the final block contributes its leading remainder, never circular wrapping.
    Exact prefix sums bound draw generation by n plus draws*ceil(n/length), without
    allocating all resampled series. Sums use a fixed 1,100-digit context; means round once
    to 28 significant digits, ROUND_HALF_EVEN, independently of caller context.

    Sorted zero-based 95% endpoint ranks are floor((draws-1)/40) and
    ceil(39*(draws-1)/40), with no interpolation. These are descriptive bootstrap
    intervals, not an effective-sample-size, independence or economic-acceptance
    claim. observations counts original values, while samples counts draws.

    Loss (<0) and nonpositive (<=0) counts use each exact resampled total,
    before mean rounding. Their probabilities are counts divided by draws,
    in [0,1], rounded once in the same fixed 28-digit context. These are
    descriptive bootstrap frequencies, not market-risk or acceptance evidence.
    """
    try:
        _validate(values, seed, block_lengths, draws)
        risks = []
        observations = len(values)
        denominator = Decimal(observations)
        mean_context = _MEAN_CONTEXT.copy()
        with localcontext(_SUM_CONTEXT):
            for length in block_lengths:
                means = []
                loss_samples = nonpositive_samples = 0
                for total in _draw_totals(values, seed=seed, length=length, draws=draws):
                    loss_samples += total < 0
                    nonpositive_samples += total <= 0
                    means.append(mean_context.divide(total, denominator))
                # Round percentile ranks outward without interpolating financial values.
                means.sort()
                risks.append(
                    EtfBlockRisk(
                        EtfBlockInterval(
                            length,
                            draws,
                            observations,
                            means[(draws - 1) // 40],
                            means[(39 * (draws - 1) + 39) // 40],
                        ),
                        loss_samples,
                        nonpositive_samples,
                        mean_context.divide(Decimal(loss_samples), Decimal(draws)),
                        mean_context.divide(Decimal(nonpositive_samples), Decimal(draws)),
                    )
                )
        return tuple(risks)
    except (ValueError, TypeError, ArithmeticError):
        raise ValueError("etf_resampling_invalid") from None


def dependent_simultaneous_mean_intervals(
    series: tuple[tuple[Decimal, ...], ...],
    *,
    seed: int,
    block_lengths: tuple[int, ...] = (20, 100),
    draws: int = 1000,
) -> tuple[EtfSimultaneousBlockIntervals, ...]:
    """Joint noncircular block-bootstrap max-error bands over supplied columns.

    Columns must be aligned original after-cost paired increments, not NAV
    returns. For each draw, all columns use identical block starts. The maximum
    absolute centered mean error across columns supplies a common radius at
    ceil(.95*(draws-1)); division and interval endpoints round outward to28
    digits. This is conditional/model-based uncertainty, NOT guaranteed market
    coverage or a proof of independent opportunities. Dates, grid completeness,
    labels and selection provenance belong to the owning evaluator; this math
    function cannot authenticate them or approve a candidate.

    Bounds:1..2088 columns (29paths*6capital*4friction*3references), at most2048
    aligned sessions; existing Decimal/seed/draw/block bounds also apply.
    Every original legacy individual interval and seeded preimage is preserved.
    """
    return _simultaneous_mean_intervals(
        series, seed=seed, block_lengths=block_lengths, draws=draws, maximum_columns=2088
    )


def dependent_capital_simultaneous_mean_intervals(
    series: tuple[tuple[Decimal, ...], ...],
    *,
    seed: int,
    block_lengths: tuple[int, ...] = (20, 100),
    draws: int = 1000,
) -> tuple[EtfSimultaneousBlockIntervals, ...]:
    """Same joint kernel, bounded for four capital-study reference roles.

    Accept1..2784 aligned columns (29paths*6capitals*4costs*4roles), at most2048
    observations each. This capacity does NOT authenticate a complete family,
    role/date identities, source qualification, independent opportunities or
    economic admission. The original2088-column API remains unchanged.
    """
    return _simultaneous_mean_intervals(
        series, seed=seed, block_lengths=block_lengths, draws=draws, maximum_columns=2784
    )


def _simultaneous_mean_intervals(
    series: tuple[tuple[Decimal, ...], ...],
    *,
    seed: int,
    block_lengths: tuple[int, ...],
    draws: int,
    maximum_columns: int,
) -> tuple[EtfSimultaneousBlockIntervals, ...]:
    """Private shared math; callers bind fixed namespace-specific admission bounds."""
    try:
        _require(type(series) is tuple and 1 <= len(series) <= maximum_columns)
        for values in series:
            _validate(values, seed, block_lengths, draws)
        count = len(series[0])
        _require(count <= 2048 and all(len(values) == count for values in series))
        upward, downward = _MEAN_CONTEXT.copy(), _MEAN_CONTEXT.copy()
        upward.rounding, downward.rounding = ROUND_CEILING, ROUND_FLOOR
        denominator = Decimal(count)
        result = []
        with localcontext(_SUM_CONTEXT):
            original_totals = tuple(sum(values, Decimal(0)) for values in series)
            for length in block_lengths:
                maximum_errors = [Decimal(0)] * draws
                for values, original in zip(series, original_totals, strict=True):
                    totals = _draw_totals(values, seed=seed, length=length, draws=draws)
                    for index, total in enumerate(totals):
                        maximum_errors[index] = max(maximum_errors[index], abs(total - original))
                maximum_errors.sort()
                radius = upward.divide(
                    maximum_errors[(95 * (draws - 1) + 99) // 100], denominator
                )
                result.append(
                    EtfSimultaneousBlockIntervals(
                        length,
                        draws,
                        count,
                        len(series),
                        radius,
                        tuple(
                            EtfBlockInterval(
                                length,
                                draws,
                                count,
                                downward.divide(original - denominator * radius, denominator),
                                upward.divide(original + denominator * radius, denominator),
                            )
                            for original in original_totals
                        ),
                    )
                )
        return tuple(result)
    except (ValueError, TypeError, ArithmeticError):
        raise ValueError("etf_resampling_invalid") from None


def dependent_mean_intervals(
    values: tuple[Decimal, ...],
    *,
    seed: int,
    block_lengths: tuple[int, ...] = (20, 100),
    draws: int = 1000,
) -> tuple[EtfBlockInterval, ...]:
    """Return the value-compatible legacy intervals from the same block draws.

    The interval record, input bounds, seeded draws and fixed-context endpoints
    are unchanged. Descriptive loss frequencies are available separately through
    ``dependent_mean_risks``; neither API supplies economic acceptance evidence.
    """
    return tuple(
        risk.interval
        for risk in dependent_mean_risks(
            values, seed=seed, block_lengths=block_lengths, draws=draws
        )
    )
