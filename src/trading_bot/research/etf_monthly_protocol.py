"""Frozen monthly research inputs. Nothing here is qualified or live capable."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import EtfBenchmarkDistribution, _money_context
from trading_bot.research.etf_daily_protocol import EtfDailyBar
from trading_bot.research.etf_monthly_study import (
    HOLDOUT,
    POLICY_ID,
    START,
    EtfMonthlyStudy,
    monthly_policy,
)

ANCHOR = date(2016, 10, 31)
MAX_ROWS = 10000
LIMITATIONS = (
    "adaptive_development_already_examined_not_fresh_oos",
    "monthly_raw_close_and_calendar_availability_assumed",
    "daily_ohlc_is_not_quotes_or_fill_evidence",
    "fractional_order_and_fill_terms_hypothetical",
    "raw_unadjusted_and_no_splits_assumed_not_verified",
    "publication_corrections_and_historical_controls_unobserved",
    "costs_and_fee_rounding_uncalibrated",
    "adverse_daily_ordering_and_t_plus_two_assumed",
    "legacy_750_bar_admission_boundary_unchanged",
    "old_momentum_attempts_retained_no_independent_confirmation",
    "final_holdout_not_evaluated_external_exposure_unknown",
)


class EtfMonthlyError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_monthly_invalid")


def _check(ok: bool) -> None:
    if not ok:
        raise EtfMonthlyError()


@dataclass(frozen=True, slots=True)
class _MonthlyRecord:
    source_qualified: Literal[False] = field(default=False, init=False)
    cost_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    economic_admitted: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)


def _markers(record: _MonthlyRecord) -> None:
    _check(
        record.source_qualified is False
        and record.cost_qualified is False
        and record.execution_enabled is False
        and record.economic_admitted is False
        and record.evidence_promotable is False
        and record.live_authorized is False
    )


def select_etf_month_ends(sessions: tuple[date, ...]) -> tuple[date, ...]:
    """Use the frozen declared calendar, never the last observed price row."""
    try:
        _check(type(sessions) is tuple and 0 < len(sessions) <= MAX_ROWS)
        _check(
            all(
                type(day) is date and START.date() <= day < HOLDOUT.date() and day.weekday() < 5
                for day in sessions
            )
        )
        _check(sessions == tuple(sorted(set(sessions))))
        result = tuple(
            day
            for i, day in enumerate(sessions)
            if i == len(sessions) - 1
            or (day.year, day.month) != (sessions[i + 1].year, sessions[i + 1].month)
        )
        _check(len(result) <= 96)
        return result
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfMonthlyError() from None


@dataclass(frozen=True, slots=True)
class EtfMonthObservation:
    month: date
    session_date: date
    ends_at: datetime
    close: Decimal
    source_hash: str

    def __post_init__(self) -> None:
        try:
            _check(type(self.month) is date and self.month.day == 1)
            _check(type(self.session_date) is date and self.session_date.weekday() < 5)
            _check(START.date() <= self.session_date < HOLDOUT.date())
            _check(self.session_date.replace(day=1) == self.month)
            _check(require_utc(self.ends_at).date() == self.session_date)
            require_bounded_decimal(self.close, "monthly close", positive=True)
            _require_sha256_hex(self.source_hash, "monthly source")
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfMonthlyError() from None


def _signal_values(
    observations: tuple[EtfMonthObservation, ...], decision_at: datetime
) -> tuple[Decimal, Decimal, Literal["LONG_ELIGIBLE", "CASH"], tuple[str, ...]]:
    _check(type(observations) is tuple and len(observations) == 10)
    require_utc(decision_at)
    previous = None
    for observation in observations:
        _check(type(observation) is EtfMonthObservation)
        observation.__post_init__()
        _check(observation.ends_at < decision_at)
        month = observation.month.year * 12 + observation.month.month
        _check(previous is None or month == previous + 1)
        previous = month
    _check(decision_at == observations[-1].ends_at + timedelta(microseconds=1))
    with localcontext(_money_context()):
        average = sum((o.close for o in observations), Decimal("0")) / 10
    latest = observations[-1].close
    regime: Literal["LONG_ELIGIBLE", "CASH"] = "LONG_ELIGIBLE" if latest > average else "CASH"
    return average, latest, regime, tuple(o.source_hash for o in observations)


def _signal_hash(observations: tuple[EtfMonthObservation, ...], decision_at: datetime) -> str:
    return content_hash(("etf-monthly-sma10-signal-v1", decision_at, observations))


@dataclass(frozen=True, slots=True)
class EtfMonthlySignal(_MonthlyRecord):
    decision_at: datetime
    month_ends: tuple[EtfMonthObservation, ...]
    average_close: Decimal
    latest_close: Decimal
    regime: Literal["LONG_ELIGIBLE", "CASH"]
    source_hashes: tuple[str, ...]
    signal_hash: str

    def __post_init__(self) -> None:
        try:
            _markers(self)
            values = _signal_values(self.month_ends, self.decision_at)
            _check(
                (self.average_close, self.latest_close, self.regime, self.source_hashes) == values
            )
            _check(type(self.average_close) is Decimal and type(self.latest_close) is Decimal)
            _check(self.signal_hash == _signal_hash(self.month_ends, self.decision_at))
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfMonthlyError() from None


@dataclass(frozen=True, slots=True)
class EtfMonthlyProtocol(_MonthlyRecord):
    study: EtfMonthlyStudy
    sessions: tuple[date, ...]
    calendar_hash: str
    source_hash: str
    distribution_hash: str
    per_side_cost_bps: Decimal
    side_fee: Decimal
    episode_fee_bound: Decimal
    price_basis: Literal["raw-unadjusted-assumption", "unknown"] = "raw-unadjusted-assumption"
    protocol_id: str = field(default=POLICY_ID, init=False)
    first_rebalance: date = field(default=ANCHOR, init=False)
    months: int = field(default=10, init=False)
    warmup_bars: int = field(default=100, init=False)
    settlement_sessions: int = field(default=2, init=False)
    quantity_increment: Decimal = field(default=Decimal(".001"), init=False)
    price_increment: Decimal = field(default=Decimal(".000001"), init=False)
    minimum_notional: Decimal = field(default=Decimal("1"), init=False)
    fractional_terms_verified: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=LIMITATIONS, init=False)

    def __post_init__(self) -> None:
        try:
            _markers(self)
            monthly_policy(self.study)
            months = select_etf_month_ends(self.sessions)
            _check(len(months) >= 10 and months[9] == ANCHOR)
            _check(months[0].replace(day=1) == date(2016, 1, 1))
            _check(ANCHOR in self.sessions and self.sessions.index(ANCHOR) >= 99)
            _check(
                self.protocol_id == POLICY_ID
                and type(self.first_rebalance) is date
                and self.first_rebalance == ANCHOR
            )
            _check(type(self.months) is int and self.months == 10)
            _check(type(self.warmup_bars) is int and self.warmup_bars == 100)
            _check(type(self.settlement_sessions) is int and self.settlement_sessions == 2)
            _check(
                type(self.quantity_increment) is Decimal
                and self.quantity_increment == Decimal(".001")
            )
            _check(
                type(self.price_increment) is Decimal and self.price_increment == Decimal(".000001")
            )
            _check(type(self.minimum_notional) is Decimal and self.minimum_notional == Decimal("1"))
            _check(self.fractional_terms_verified is False and self.limitations == LIMITATIONS)
            _check(type(self.limitations) is tuple)
            _check(self.price_basis in ("raw-unadjusted-assumption", "unknown"))
            for digest in (self.calendar_hash, self.source_hash, self.distribution_hash):
                _require_sha256_hex(digest, "monthly protocol identity")
            for amount in (self.per_side_cost_bps, self.side_fee, self.episode_fee_bound):
                require_bounded_decimal(amount, "monthly cost assumption", nonnegative=True)
            with localcontext(_money_context()):
                _check(
                    self.per_side_cost_bps <= 100 and self.side_fee * 2 <= self.episode_fee_bound
                )
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfMonthlyError() from None

    @property
    def month_end_sessions(self) -> tuple[date, ...]:
        return select_etf_month_ends(self.sessions)

    @property
    def first_evaluation_session(self) -> date | None:
        i = self.sessions.index(ANCHOR) + 1
        return self.sessions[i] if i < len(self.sessions) else None

    @property
    def protocol_hash(self) -> str:
        return content_hash({"schema": self.protocol_id, "protocol": self})


@dataclass(frozen=True, slots=True)
class EtfMonthlyRequest(_MonthlyRecord):
    protocol: EtfMonthlyProtocol
    bars: tuple[EtfDailyBar, ...]
    distributions: tuple[EtfBenchmarkDistribution, ...]
    initial_cash: Decimal

    def __post_init__(self) -> None:
        try:
            _markers(self)
            _check(type(self.protocol) is EtfMonthlyProtocol)
            self.protocol.__post_init__()
            _check(type(self.bars) is tuple and len(self.bars) <= MAX_ROWS)
            _check(type(self.distributions) is tuple and len(self.distributions) <= MAX_ROWS)
            previous = None
            for row in self.bars:
                _check(type(row) is EtfDailyBar)
                row.__post_init__()
                _check(row.session_date in self.protocol.sessions)
                _check(previous is None or row.session_date > previous)
                previous = row.session_date
            previous = None
            for distribution in self.distributions:
                _check(type(distribution) is EtfBenchmarkDistribution)
                distribution.__post_init__()
                _check(distribution.ex_date in self.protocol.sessions)
                _check(previous is None or distribution.ex_date > previous)
                previous = distribution.ex_date
            require_bounded_decimal(self.initial_cash, "monthly initial cash", positive=True)
            _check(self.initial_cash in self.protocol.study.capital_tiers)
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfMonthlyError() from None

    @property
    def request_hash(self) -> str:
        return content_hash({"schema": "etf-monthly-request-v1", "request": self})


def monthly_atr_inputs(request: EtfMonthlyRequest, day: date) -> tuple[EtfDailyBar, ...]:
    """The canonical feature pipeline consumes exactly these completed 100 rows."""
    try:
        _check(type(request) is EtfMonthlyRequest)
        request.__post_init__()
        _check(type(day) is date and day in request.protocol.month_end_sessions)
        index = request.protocol.sessions.index(day)
        _check(index >= 99)
        by_day = {row.session_date: row for row in request.bars}
        expected = request.protocol.sessions[index - 99 : index + 1]
        _check(all(value in by_day for value in expected))
        return tuple(by_day[value] for value in expected)
    except (ValueError, TypeError, ArithmeticError, AttributeError, KeyError):
        raise EtfMonthlyError() from None
