"""Pure, nonpromoting price-path statistics for retrospective stock research.

Inputs are dimensionless positive NAV paths or aligned daily log-return
differences, never forecasts or trading instructions. Fractions are not percent
points. All arithmetic uses a private 50-digit, half-even Decimal context;
undefined ratios remain ``None`` with an explicit reason. Evidence hashes bind
the input values, conventions, configuration and output, not source authenticity.
"""

import json
from dataclasses import asdict, dataclass, field, replace
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)
from hashlib import sha256
from itertools import pairwise
from random import Random
from typing import Literal

_ZERO = Decimal("0")
_ONE = Decimal("1")
_CONTEXT = Context(
    prec=50,
    rounding=ROUND_HALF_EVEN,
    Emin=-999999,
    Emax=999999,
    capitals=1,
    clamp=0,
    traps=[InvalidOperation, DivisionByZero, Overflow, Underflow],
)


@dataclass(frozen=True, slots=True)
class PricePathSummary:
    """Simple-return statistics; every return/drawdown is a fraction."""

    total_return: Decimal
    cagr: Decimal
    annualized_volatility: Decimal | None
    mean_return: Decimal
    max_drawdown: Decimal
    inherited_max_drawdown: Decimal
    sharpe: Decimal | None
    sortino: Decimal | None
    period_count: int
    undefined_reasons: tuple[str, ...]
    periods_per_year: int
    elapsed_years: Decimal
    elapsed_years_basis: Literal["explicit", "period_count/periods_per_year"]
    evidence_hash: str
    qualified: Literal[False] = field(default=False, init=False)
    investment_recommendation: Literal[False] = field(default=False, init=False)
    live_activation_allowed: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class PairedBlockInterval:
    """Percentile interval for a retrospective mean daily log-return difference."""

    observed_mean: Decimal
    lower_mean: Decimal
    upper_mean: Decimal


@dataclass(frozen=True, slots=True)
class PairedBlockIntervals:
    """Shared circular-block draws with Bonferroni-adjusted Type7 percentiles."""

    intervals: tuple[PairedBlockInterval, ...]
    observation_count: int
    column_count: int
    block_length: int
    replicates: int
    seed: int
    family_size: int
    alpha: Decimal
    tail_probability: Decimal
    warnings: tuple[str, ...]
    evidence_hash: str
    qualified: Literal[False] = field(default=False, init=False)
    investment_recommendation: Literal[False] = field(default=False, init=False)
    live_activation_allowed: Literal[False] = field(default=False, init=False)


def _decimal(value: object, name: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite() or (positive and value <= _ZERO):
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else ""))
    return value


def _integer(value: object, name: str, *, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer, not bool")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is outside its permitted bounds")
    return value


def _vector(values: object, name: str, *, positive: bool = False) -> tuple[Decimal, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{name} must be an immutable tuple")
    if not 2 <= len(values) <= 10000:
        raise ValueError(f"{name} must contain 2 through 10000 values")
    return tuple(_decimal(value, name, positive=positive) for value in values)


def _json_decimal(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError("unsupported evidence value")


def _evidence_hash(payload: dict[str, object]) -> str:
    content = json.dumps(
        payload, default=_json_decimal, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return sha256(content.encode("utf-8")).hexdigest()


def _drawdown(equity: tuple[Decimal, ...], peak: Decimal) -> Decimal:
    worst = _ZERO
    for value in equity:
        peak = max(peak, value)
        worst = max(worst, (peak - value) / peak)
    return worst


def summarize_price_path(
    equity: tuple[Decimal, ...],
    *,
    periods_per_year: int = 252,
    elapsed_years: Decimal | None = None,
    inherited_peak: Decimal | None = None,
) -> PricePathSummary:
    """Summarize a baseline followed by marked NAVs with zero risk-free return.

    Volatility uses sample deviation of daily simple returns. Sortino uses the
    RMS of ``min(return, 0)`` over *all* daily returns, relative to zero. An
    inherited peak must be at least the baseline NAV; its drawdown includes that
    baseline. Without explicit years, duration is return-count/periods-per-year,
    a trading-period convention rather than an asserted calendar duration.
    """
    values = _vector(equity, "equity", positive=True)
    annual_periods = _integer(periods_per_year, "periods_per_year", minimum=1)
    years = (
        None if elapsed_years is None else _decimal(elapsed_years, "elapsed_years", positive=True)
    )
    peak = (
        values[0]
        if inherited_peak is None
        else _decimal(inherited_peak, "inherited_peak", positive=True)
    )
    if peak < values[0]:
        raise ValueError("inherited_peak cannot be below the baseline equity")
    try:
        with localcontext(_CONTEXT):
            count = len(values) - 1
            duration = Decimal(count) / annual_periods if years is None else years
            returns = tuple(current / previous - _ONE for previous, current in pairwise(values))
            average = sum(returns, _ZERO) / count
            annual_root = Decimal(annual_periods).sqrt()
            reasons: list[str] = []
            volatility = sharpe = None
            if count < 2:
                reasons.extend(
                    (
                        "annualized_volatility:fewer_than_two_returns",
                        "sharpe:fewer_than_two_returns",
                    )
                )
            else:
                variance = sum(((value - average) ** 2 for value in returns), _ZERO) / (count - 1)
                deviation = variance.sqrt()
                volatility = deviation * annual_root
                if deviation == _ZERO:
                    reasons.append("sharpe:zero_return_variance")
                else:
                    sharpe = average / deviation * annual_root
            downside = (sum((min(value, _ZERO) ** 2 for value in returns), _ZERO) / count).sqrt()
            sortino = None
            if downside == _ZERO:
                reasons.append("sortino:no_downside_returns")
            else:
                sortino = average / downside * annual_root
            result = PricePathSummary(
                total_return=values[-1] / values[0] - _ONE,
                cagr=(values[-1] / values[0]) ** (_ONE / duration) - _ONE,
                annualized_volatility=volatility,
                mean_return=average,
                max_drawdown=_drawdown(values, values[0]),
                inherited_max_drawdown=_drawdown(values, peak),
                sharpe=sharpe,
                sortino=sortino,
                period_count=count,
                undefined_reasons=tuple(reasons),
                periods_per_year=annual_periods,
                elapsed_years=duration,
                elapsed_years_basis="period_count/periods_per_year"
                if years is None
                else "explicit",
                evidence_hash="",
            )
            output = asdict(result)
            del output["evidence_hash"]
            return replace(
                result,
                evidence_hash=_evidence_hash(
                    {
                        "method": "stock-price-path-summary-v1",
                        "input": {
                            "equity": values,
                            "inherited_peak": inherited_peak,
                            "elapsed_years": elapsed_years,
                            "periods_per_year": annual_periods,
                        },
                        "result": output,
                    }
                ),
            )
    except DecimalException as error:
        raise ValueError("price path arithmetic exceeds the supported Decimal range") from error


def _circular_block_sums(column: tuple[Decimal, ...], length: int) -> tuple[Decimal, ...]:
    prefix = [_ZERO]
    for value in column + column[: length - 1]:
        prefix.append(prefix[-1] + value)
    return tuple(prefix[start + length] - prefix[start] for start in range(len(column)))


def _type7(ordered: list[Decimal], probability: Decimal) -> Decimal:
    position = Decimal(len(ordered) - 1) * probability
    index = int(position)
    fraction = position - index
    if fraction == _ZERO:
        return ordered[index]
    return ordered[index] + fraction * (ordered[index + 1] - ordered[index])


def paired_block_intervals(
    paired_log_differences: tuple[tuple[Decimal, ...], ...],
    *,
    block_length: int = 20,
    replicates: int = 5000,
    seed: int = 20261026,
    family_size: int = 16,
    alpha: Decimal = Decimal("0.05"),
) -> PairedBlockIntervals:
    """Bootstrap aligned *columns* of realized daily log-return differences.

    Every replicate uses the same randomly selected circular block starts for
    all columns and truncates its last block to the original observation count.
    Precomputed block sums avoid materializing resampled paths. ``Random`` is a
    seeded research PRNG, never a security or authentication primitive. Intervals
    estimate retrospective mean differences; they are not return forecasts,
    strategy reruns, calibrated investment confidence or economic qualification.

    The caller must provide already aligned differences and declare the entire
    comparison family, including comparisons not passed in this call. No numeric
    function can independently prove their timestamps or source authenticity.
    """
    if not isinstance(paired_log_differences, tuple):
        raise TypeError("paired_log_differences must be an immutable tuple of columns")
    if not 1 <= len(paired_log_differences) <= 128:
        raise ValueError("paired_log_differences must contain 1 through 128 columns")
    columns = tuple(
        _vector(column, "paired log difference column") for column in paired_log_differences
    )
    count = len(columns[0])
    if any(len(column) != count for column in columns):
        raise ValueError("all paired columns must have the same observation count")
    length = _integer(block_length, "block_length", minimum=1, maximum=count)
    draws = _integer(replicates, "replicates", minimum=100, maximum=50000)
    random_seed = _integer(seed, "seed", minimum=0, maximum=2**64 - 1)
    family = _integer(family_size, "family_size", minimum=len(columns))
    family_alpha = _decimal(alpha, "alpha", positive=True)
    if family_alpha >= _ONE:
        raise ValueError("alpha must be strictly between zero and one")
    try:
        with localcontext(_CONTEXT):
            tail = family_alpha / (2 * family)
            warnings: list[str] = []
            if count < 10 * length:
                warnings.append("few_effective_blocks:observation_count/block_length<10")
            if draws * tail < 10:
                warnings.append("limited_tail_resolution:replicates*tail_probability<10")
            whole_blocks, remainder = divmod(count, length)
            # An exactly constant column has no sampling variation. Preserve
            # its mathematical point mean instead of introducing summation
            # roundoff; still consume the same shared PRNG draws for other columns.
            constants = tuple(
                +column[0] if all(value == column[0] for value in column) else None
                for column in columns
            )
            full_sums = tuple(
                _circular_block_sums(column, length) if constant is None else ()
                for column, constant in zip(columns, constants, strict=True)
            )
            partial_sums = (
                tuple(
                    _circular_block_sums(column, remainder) if constant is None else ()
                    for column, constant in zip(columns, constants, strict=True)
                )
                if remainder
                else ()
            )
            samples: list[list[Decimal]] = [[] for _ in columns]
            # Deterministic research resampling; no security use.
            rng = Random(random_seed)  # nosec B311
            for _ in range(draws):
                starts = tuple(rng.randrange(count) for _ in range(whole_blocks))
                final_start = rng.randrange(count) if remainder else None
                for column_index, block_sums in enumerate(full_sums):
                    if constants[column_index] is not None:
                        continue
                    total = sum((block_sums[start] for start in starts), _ZERO)
                    if final_start is not None:
                        total += partial_sums[column_index][final_start]
                    samples[column_index].append(total / count)
            intervals: list[PairedBlockInterval] = []
            for column, sample, constant in zip(columns, samples, constants, strict=True):
                if constant is not None:
                    intervals.append(PairedBlockInterval(constant, constant, constant))
                    continue
                sample.sort()
                intervals.append(
                    PairedBlockInterval(
                        observed_mean=sum(column, _ZERO) / count,
                        lower_mean=_type7(sample, tail),
                        upper_mean=_type7(sample, _ONE - tail),
                    )
                )
            result = PairedBlockIntervals(
                intervals=tuple(intervals),
                observation_count=count,
                column_count=len(columns),
                block_length=length,
                replicates=draws,
                seed=random_seed,
                family_size=family,
                alpha=family_alpha,
                tail_probability=tail,
                warnings=tuple(warnings),
                evidence_hash="",
            )
            output = asdict(result)
            del output["evidence_hash"]
            return replace(
                result,
                evidence_hash=_evidence_hash(
                    {
                        "method": "stock-paired-circular-moving-block-bootstrap-v1",
                        "quantile": "type7-linear",
                        "prng": "python.random.Random-MT19937",
                        "input_kind": "aligned_daily_log_return_difference_columns",
                        "input": columns,
                        "result": output,
                    }
                ),
            )
    except DecimalException as error:
        raise ValueError(
            "paired bootstrap arithmetic exceeds the supported Decimal range"
        ) from error
