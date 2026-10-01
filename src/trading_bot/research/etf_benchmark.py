"""Pure daily-price SPY/cash mathematical references, never execution evidence.

The caller supplies the notional; this module selects no allocation or risk policy.
Entry is hypothetical at the first supplied opening plus the declared one-way cost.
Daily closes are midpoint-like marks, not quotes or executable prices. Fractional
shares use fixed-context exact ratios where representable and explicitly
approximate 28-digit ratios otherwise, not broker lot/minimum rounding.
Cash-flow and valuation sums remain exact over those mathematical estimates.
Cash is debited by the explicit notional and entry fee, not a rounded quantity
multiplied back into a fabricated fill. Nothing sells or settles at end-of-input.

Unadjusted prices and complete distributions/instrument continuity must be checked
upstream. Input hashes bind supplied records; they do not qualify a source, prove
licensing, original availability, sessions, quotes, or settlement.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Context, Decimal, Inexact, localcontext
from typing import Literal

from trading_bot.domain.decimal_utils import (
    MAX_CANONICAL_DECIMAL_TEXT_LENGTH,
    _require_sha256_hex,
    require_bounded_decimal,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.lifecycle_accounting import _context

_MAX_ROWS = 10000
_ZERO = Decimal("0")
_SOURCE_KIND = "daily-price-exploratory-benchmark-v1"
_LIMITATIONS = (
    "daily_bars_are_not_executable_fills",
    "costs_and_fractional_terms_uncalibrated",
    "sessions_quotes_and_settlement_unverified",
    "original_publication_chronology_waived_upstream",
    "mathematical_ratios_exceeding_exact_context_rounded_to_28_digits",
    "unadjusted_price_and_action_completeness_required_upstream",
    "liquidation_proxy_is_not_a_sale_or_settlement",
)


class EtfBenchmarkError(ValueError):
    """Sanitized invalid mathematical benchmark input or inconsistent output."""

    def __init__(self) -> None:
        super().__init__("etf_benchmark_invalid")


@dataclass(frozen=True, slots=True)
class _BenchmarkRecord:
    source_kind: Literal["daily-price-exploratory-benchmark-v1"] = field(
        default="daily-price-exploratory-benchmark-v1", init=False
    )
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


def _markers(record: _BenchmarkRecord) -> None:
    if (
        type(record.source_kind) is not str
        or record.source_kind != _SOURCE_KIND
        or record.execution_enabled is not False
        or record.evidence_promotable is not False
    ):
        raise EtfBenchmarkError()


def _date(value: date) -> None:
    if type(value) is not date:
        raise EtfBenchmarkError()


def _money_context() -> Context:
    """Exact arithmetic over the shared bounded Decimal representation."""

    context = _context(exact=True)
    # Two input coefficients/scales may each span 512 digits; 16 extra
    # digits cover bounded row accumulation. Oversized results still deny.
    context.prec = 2 * MAX_CANONICAL_DECIMAL_TEXT_LENGTH + 16
    return context


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Keep representable ratios exact; explicitly approximate wider ratios."""

    try:
        with localcontext(_money_context()):
            return numerator / denominator
    except Inexact:
        with localcontext(_context(exact=False)):
            return numerator / denominator


@dataclass(frozen=True, slots=True)
class EtfBenchmarkBar(_BenchmarkRecord):
    session_date: date
    open: Decimal
    close: Decimal
    source_hash: str

    def __post_init__(self) -> None:
        try:
            _markers(self)
            _date(self.session_date)
            require_bounded_decimal(self.open, "opening", positive=True)
            require_bounded_decimal(self.close, "close", positive=True)
            _require_sha256_hex(self.source_hash, "source hash")
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfBenchmarkError() from None


@dataclass(frozen=True, slots=True)
class EtfBenchmarkDistribution(_BenchmarkRecord):
    ex_date: date
    pay_date: date
    cash_per_share: Decimal
    source_hash: str

    def __post_init__(self) -> None:
        try:
            _markers(self)
            _date(self.ex_date)
            _date(self.pay_date)
            if self.pay_date < self.ex_date:
                raise EtfBenchmarkError()
            require_bounded_decimal(self.cash_per_share, "distribution", nonnegative=True)
            _require_sha256_hex(self.source_hash, "source hash")
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfBenchmarkError() from None


@dataclass(frozen=True, slots=True)
class EtfBenchmarkRequest(_BenchmarkRecord):
    bars: tuple[EtfBenchmarkBar, ...]
    distributions: tuple[EtfBenchmarkDistribution, ...]
    initial_cash: Decimal
    entry_notional: Decimal
    per_side_cost_bps: Decimal
    entry_fee: Decimal
    estimated_exit_fee: Decimal

    def __post_init__(self) -> None:
        try:
            _markers(self)
            if (
                type(self.bars) is not tuple
                or not 0 < len(self.bars) <= _MAX_ROWS
                or type(self.distributions) is not tuple
                or len(self.distributions) > _MAX_ROWS
            ):
                raise EtfBenchmarkError()
            previous_date = None
            for bar in self.bars:
                if type(bar) is not EtfBenchmarkBar:
                    raise EtfBenchmarkError()
                bar.__post_init__()
                if previous_date is not None and bar.session_date <= previous_date:
                    raise EtfBenchmarkError()
                previous_date = bar.session_date
            previous_date = None
            for distribution in self.distributions:
                if type(distribution) is not EtfBenchmarkDistribution:
                    raise EtfBenchmarkError()
                distribution.__post_init__()
                # SPY distribution identity is its ex-date: revised amounts or
                # pay-dates are conflicts, not another entitlement.
                if previous_date is not None and distribution.ex_date <= previous_date:
                    raise EtfBenchmarkError()
                previous_date = distribution.ex_date
            for value in (
                self.initial_cash,
                self.entry_notional,
                self.per_side_cost_bps,
                self.entry_fee,
                self.estimated_exit_fee,
            ):
                require_bounded_decimal(value, "benchmark amount", nonnegative=True)
            with localcontext(_money_context()):
                if (
                    self.per_side_cost_bps > Decimal("100")
                    or self.entry_notional + self.entry_fee > self.initial_cash
                ):
                    raise EtfBenchmarkError()
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfBenchmarkError() from None


@dataclass(frozen=True, slots=True)
class EtfBenchmarkDividendPayment(_BenchmarkRecord):
    """Hypothetical eligible cash credited on its pay-date, including no-bar days."""

    ex_date: date
    pay_date: date
    amount: Decimal
    source_hash: str

    def __post_init__(self) -> None:
        try:
            _markers(self)
            _date(self.ex_date)
            _date(self.pay_date)
            if self.pay_date < self.ex_date:
                raise EtfBenchmarkError()
            require_bounded_decimal(self.amount, "dividend payment", nonnegative=True)
            _require_sha256_hex(self.source_hash, "source hash")
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfBenchmarkError() from None


@dataclass(frozen=True, slots=True)
class EtfBenchmarkPoint(_BenchmarkRecord):
    """One supplied daily close mark; no synthetic marks for missing price dates."""

    session_date: date
    cash: Decimal
    shares: Decimal
    dividend_receivable: Decimal
    dividends_received: Decimal
    close_midpoint_nav: Decimal
    liquidation_proxy: Decimal
    marked_pnl: Decimal
    estimated_liquidation_cost: Decimal
    cash_reference_nav: Decimal
    price_source_hash: str
    input_hash: str

    def __post_init__(self) -> None:
        try:
            _markers(self)
            _date(self.session_date)
            for value in (
                self.cash,
                self.shares,
                self.dividend_receivable,
                self.dividends_received,
                self.close_midpoint_nav,
                self.estimated_liquidation_cost,
                self.cash_reference_nav,
            ):
                require_bounded_decimal(value, "benchmark balance", nonnegative=True)
            for value in (self.liquidation_proxy, self.marked_pnl):
                require_bounded_decimal(value, "benchmark mark")
            _require_sha256_hex(self.price_source_hash, "price source hash")
            _require_sha256_hex(self.input_hash, "point input hash")
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfBenchmarkError() from None


@dataclass(frozen=True, slots=True)
class EtfBenchmarkResult(_BenchmarkRecord):
    request: EtfBenchmarkRequest
    points: tuple[EtfBenchmarkPoint, ...]
    dividend_payments: tuple[EtfBenchmarkDividendPayment, ...]
    entry_price: Decimal | None
    shares: Decimal
    fees_paid: Decimal
    embedded_entry_cost: Decimal
    estimated_terminal_liquidation_cost: Decimal
    dividends_received: Decimal
    dividends_receivable: Decimal
    input_hash: str
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)
    realized_trading_pnl: None = field(default=None, init=False)

    def __post_init__(self) -> None:
        try:
            _markers(self)
            if type(self.request) is not EtfBenchmarkRequest:
                raise EtfBenchmarkError()
            self.request.__post_init__()
            if (
                type(self.points) is not tuple
                or len(self.points) != len(self.request.bars)
                or type(self.dividend_payments) is not tuple
                or len(self.dividend_payments) > _MAX_ROWS
                or type(self.limitations) is not tuple
                or self.limitations != _LIMITATIONS
                or self.realized_trading_pnl is not None
            ):
                raise EtfBenchmarkError()
            for point in self.points:
                if type(point) is not EtfBenchmarkPoint:
                    raise EtfBenchmarkError()
                point.__post_init__()
            for payment in self.dividend_payments:
                if type(payment) is not EtfBenchmarkDividendPayment:
                    raise EtfBenchmarkError()
                payment.__post_init__()
            if self.entry_price is not None:
                require_bounded_decimal(self.entry_price, "entry price", positive=True)
            for value in (
                self.shares,
                self.fees_paid,
                self.embedded_entry_cost,
                self.estimated_terminal_liquidation_cost,
                self.dividends_received,
                self.dividends_receivable,
            ):
                require_bounded_decimal(value, "benchmark total", nonnegative=True)
            _require_sha256_hex(self.input_hash, "benchmark input hash")
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfBenchmarkError() from None

    @property
    def result_hash(self) -> str:
        return content_hash({"schema": "etf-benchmark-result-v1", "result": self})


def _protocol_hash(request: EtfBenchmarkRequest) -> str:
    return content_hash(
        {
            "schema": _SOURCE_KIND,
            "initial_cash": request.initial_cash,
            "entry_notional": request.entry_notional,
            "per_side_cost_bps": request.per_side_cost_bps,
            "entry_fee": request.entry_fee,
            "estimated_exit_fee": request.estimated_exit_fee,
            "limitations": _LIMITATIONS,
        }
    )


def _calculate(request: EtfBenchmarkRequest) -> EtfBenchmarkResult:
    # Exact finite cash debits are checked independently of rounded mathematical
    # fractional-share valuation. Ambient context cannot change either contract.
    with localcontext(_money_context()):
        fees = request.entry_fee if request.entry_notional else _ZERO
        starting_cash = request.initial_cash - request.entry_notional - fees
        rate = request.per_side_cost_bps / Decimal("10000")
        first = request.bars[0]
        entry_price = first.open * (Decimal("1") + rate) if request.entry_notional else None
        shares = _ratio(request.entry_notional, entry_price) if entry_price is not None else _ZERO
        # Compute cost/mark from the notional ratio directly; multiplying an
        # already rounded display quantity back into its entry price could
        # manufacture a tiny cost or P&L when the declared cost is zero.
        entry_midpoint_value = (
            _ratio(request.entry_notional * first.open, entry_price)
            if entry_price is not None
            else _ZERO
        )
        embedded = request.entry_notional - entry_midpoint_value
        # This bounded exploratory module denies unsupported precision rather
        # than silently erasing a positive declared entry cost.
        if request.entry_notional and rate and embedded <= 0:
            raise EtfBenchmarkError()
        eligible = tuple(
            row
            for row in request.distributions
            if first.session_date < row.ex_date <= request.bars[-1].session_date and shares
        )
        amounts = tuple(
            (row, _ratio(request.entry_notional * row.cash_per_share, entry_price))
            for row in eligible
            if entry_price is not None
        )
        payments = tuple(
            EtfBenchmarkDividendPayment(row.ex_date, row.pay_date, amount, row.source_hash)
            for row, amount in sorted(amounts, key=lambda item: (item[0].pay_date, item[0].ex_date))
            if row.pay_date <= request.bars[-1].session_date
        )
        points = []
        prefix_hash = _protocol_hash(request)
        previously_visible: set[date] = set()
        for bar in request.bars:
            visible = tuple(row for row, _ in amounts if row.ex_date <= bar.session_date)
            new_rows = tuple(row for row in visible if row.ex_date not in previously_visible)
            previously_visible.update(row.ex_date for row in new_rows)
            prefix_hash = content_hash({"prior": prefix_hash, "bar": bar, "actions": new_rows})
            received = sum(
                (payment.amount for payment in payments if payment.pay_date <= bar.session_date),
                _ZERO,
            )
            receivable = sum(
                (
                    amount
                    for row, amount in amounts
                    if row.ex_date <= bar.session_date < row.pay_date
                ),
                _ZERO,
            )
            cash = starting_cash + received
            midpoint_value = (
                _ratio(request.entry_notional * bar.close, entry_price)
                if entry_price is not None
                else _ZERO
            )
            nav = cash + midpoint_value + receivable
            exit_cost = midpoint_value * rate + request.estimated_exit_fee if shares else _ZERO
            proxy = nav - exit_cost
            for amount in (cash, shares, received, receivable, midpoint_value, nav, exit_cost):
                require_bounded_decimal(amount, "benchmark result", nonnegative=True)
            for amount in (proxy, nav - request.initial_cash):
                require_bounded_decimal(amount, "benchmark mark")
            points.append(
                EtfBenchmarkPoint(
                    bar.session_date,
                    cash,
                    shares,
                    receivable,
                    received,
                    nav,
                    proxy,
                    nav - request.initial_cash,
                    exit_cost,
                    request.initial_cash,
                    bar.source_hash,
                    prefix_hash,
                )
            )
        final = points[-1]
        return EtfBenchmarkResult(
            request,
            tuple(points),
            payments,
            entry_price,
            shares,
            fees,
            embedded,
            final.estimated_liquidation_cost,
            final.dividends_received,
            final.dividend_receivable,
            content_hash({"schema": _SOURCE_KIND, "request": request}),
        )


def run_etf_benchmark(request: EtfBenchmarkRequest) -> EtfBenchmarkResult:
    """Compute an open buy-and-hold/cash reference without choosing exposure."""

    try:
        if type(request) is not EtfBenchmarkRequest:
            raise EtfBenchmarkError()
        request.__post_init__()
        return _calculate(request)
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfBenchmarkError() from None


def verify_etf_benchmark_result(result: EtfBenchmarkResult) -> None:
    """Reconstruct mathematical output before trusting its balances or bindings."""

    try:
        if type(result) is not EtfBenchmarkResult:
            raise EtfBenchmarkError()
        result.__post_init__()
        expected = run_etf_benchmark(result.request)
        if result != expected:
            raise EtfBenchmarkError()
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfBenchmarkError() from None
