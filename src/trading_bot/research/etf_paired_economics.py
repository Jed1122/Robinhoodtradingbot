"""Pure paired statistics of supplied, already after-cost daily return fractions.

No costs are allocated or deducted here. Dates and hashes bind supplied inputs,
not verified sessions, source quality, calibration, independence or acceptance.
Both comparisons retain chronological pairing and the same seeded 20/100-session
moving-block protocol: 1,000 draws, with existing outward 95% endpoints.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Literal

from trading_bot.domain.decimal_utils import (
    MAX_CANONICAL_DECIMAL_TEXT_LENGTH,
    _require_sha256_hex,
    require_bounded_decimal,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_resampling import EtfBlockRisk, dependent_mean_risks

# Two bounded Decimal operands and at most 10,000 summands fit exactly in
# 1,100 digits. Only the final arithmetic mean rounds, once, to 28 digits.
_EXACT_CONTEXT = Context(
    prec=1100,
    rounding=ROUND_HALF_EVEN,
    Emin=-999999,
    Emax=999999,
    traps=[InvalidOperation, DivisionByZero, Overflow, Inexact],
)
_MEAN_CONTEXT = _EXACT_CONTEXT.copy()
_MEAN_CONTEXT.prec = 28
_MEAN_CONTEXT.traps[Inexact] = False


class EtfPairedEconomicsError(ValueError):
    """Stable failure without caller-supplied values or provenance text."""

    def __init__(self) -> None:
        super().__init__("etf_paired_economics_invalid")


def _require(ok: bool) -> None:
    if not ok:
        raise EtfPairedEconomicsError()


@dataclass(frozen=True, slots=True)
class EtfMatchedReturns:
    session_dates: tuple[date, ...]
    candidate: tuple[Decimal, ...]
    constrained_benchmark: tuple[Decimal, ...]
    cash_benchmark: tuple[Decimal, ...]
    input_hash: str

    def __post_init__(self) -> None:
        try:
            _require(type(self.session_dates) is tuple and 100 <= len(self.session_dates) <= 10000)
            _require(all(type(day) is date for day in self.session_dates))
            _require(
                all(a < b for a, b in zip(self.session_dates, self.session_dates[1:], strict=False))
            )
            _require_sha256_hex(self.input_hash, "paired input identity")
            for series in (self.candidate, self.constrained_benchmark, self.cash_benchmark):
                _require(type(series) is tuple and len(series) == len(self.session_dates))
                for value in series:
                    require_bounded_decimal(value, "daily return")
                    parts = value.as_tuple()
                    _require(len(parts.digits) <= MAX_CANONICAL_DECIMAL_TEXT_LENGTH)
                    _require(
                        type(parts.exponent) is int
                        and abs(parts.exponent) <= MAX_CANONICAL_DECIMAL_TEXT_LENGTH
                    )
                    _require(value > Decimal("-1"))
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfPairedEconomicsError() from None


@dataclass(frozen=True, slots=True)
class EtfPairedEconomicsReport:
    inputs: EtfMatchedReturns
    seed: int
    candidate_mean: Decimal
    candidate_vs_constrained: tuple[EtfBlockRisk, ...]
    candidate_vs_cash: tuple[EtfBlockRisk, ...]
    units: Literal["fraction"] = field(default="fraction", init=False)
    verdict: Literal["ECONOMIC_NO_GO"] = field(default="ECONOMIC_NO_GO", init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    @property
    def constrained_lower_bound(self) -> Decimal:
        """Less favorable supported lower endpoint across both block lengths."""
        return min(risk.interval.lower for risk in self.candidate_vs_constrained)

    @property
    def cash_lower_bound(self) -> Decimal:
        return min(risk.interval.lower for risk in self.candidate_vs_cash)

    @property
    def report_hash(self) -> str:
        return content_hash({"schema": "etf-paired-economics-report-v1", "report": self})


def analyze_etf_matched_returns(
    inputs: EtfMatchedReturns, *, seed: int
) -> EtfPairedEconomicsReport:
    """Subtract already after-cost returns once; report descriptive fractions.

    Observation count and bootstrap draw count are not effective sample size or
    completed opportunities. Positive endpoints cannot accept research or enable
    execution. Geometric return, annualization and accounting stay with the owner.
    """
    try:
        _require(type(inputs) is EtfMatchedReturns)
        checked = replace(inputs)  # Revalidate records changed by unsafe construction/mutation.
        _require(type(seed) is int and 0 <= seed < 2**63)
        with localcontext(_EXACT_CONTEXT):
            constrained_excess = tuple(
                value - benchmark
                for value, benchmark in zip(
                    checked.candidate, checked.constrained_benchmark, strict=True
                )
            )
            cash_excess = tuple(
                value - benchmark
                for value, benchmark in zip(checked.candidate, checked.cash_benchmark, strict=True)
            )
            total = sum(checked.candidate, Decimal("0"))
            mean = _MEAN_CONTEXT.divide(total, Decimal(len(checked.candidate)))
        return EtfPairedEconomicsReport(
            checked,
            seed,
            mean,
            dependent_mean_risks(
                constrained_excess, seed=seed, block_lengths=(20, 100), draws=1000
            ),
            dependent_mean_risks(cash_excess, seed=seed, block_lengths=(20, 100), draws=1000),
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfPairedEconomicsError() from None
