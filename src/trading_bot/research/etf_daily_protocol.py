"""Separately identified daily-price assumptions, never qualified execution data.

The first projection uses the same raw values for features and assumed execution
under an explicit unadjusted/no-splits hypothesis. Unsupported normalization and
unknown basis remain unknown; this does not alter any legacy source factory.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.domain import Bar, BarInterval
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import EtfBenchmarkDistribution
from trading_bot.research.etf_study import EtfStudy
from trading_bot.simulation.etf_history import _policy
from trading_bot.simulation.lifecycle_accounting import _context

ANCHOR = date(2016, 5, 26)
HOLDOUT_START = date(2024, 1, 1)
MAX_ROWS = 10000
_LIMITATIONS = (
    "daily_ohlc_is_not_quotes_or_fill_evidence",
    "fractional_order_and_fill_terms_hypothetical",
    "raw_unadjusted_and_no_splits_assumed_not_verified",
    "publication_corrections_and_historical_controls_unobserved",
    "costs_and_fee_rounding_uncalibrated",
    "adverse_daily_ordering_and_t_plus_two_assumed",
    "legacy_750_bar_admission_boundary_unchanged",
)


class EtfDailyError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_daily_invalid")


def _check(ok: bool) -> None:
    if not ok:
        raise EtfDailyError()


@dataclass(frozen=True, slots=True)
class _DailyRecord:
    source_qualified: Literal[False] = field(default=False, init=False)
    cost_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    economic_admitted: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


def _markers(record: _DailyRecord) -> None:
    _check(
        all(
            getattr(record, name) is False
            for name in (
                "source_qualified",
                "cost_qualified",
                "execution_enabled",
                "economic_admitted",
                "evidence_promotable",
            )
        )
    )


@dataclass(frozen=True, slots=True)
class EtfDailyProtocol(_DailyRecord):
    study: EtfStudy
    sessions: tuple[date, ...]
    calendar_hash: str
    source_hash: str
    distribution_hash: str
    per_side_cost_bps: Decimal
    side_fee: Decimal
    episode_fee_bound: Decimal
    price_basis: Literal["raw-unadjusted-assumption", "unknown"] = "raw-unadjusted-assumption"
    protocol_id: Literal["spy-cash-daily-development-v1"] = field(
        default="spy-cash-daily-development-v1", init=False
    )
    first_rebalance: date = field(default=ANCHOR, init=False)
    warmup_bars: int = field(default=100, init=False)
    rebalance_sessions: int = field(default=5, init=False)
    settlement_sessions: int = field(default=2, init=False)
    quantity_increment: Decimal = field(default=Decimal(".001"), init=False)
    price_increment: Decimal = field(default=Decimal(".000001"), init=False)
    minimum_notional: Decimal = field(default=Decimal("1"), init=False)
    fractional_terms_verified: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)

    def __post_init__(self) -> None:
        try:
            _markers(self)
            cfg = _policy(self.study).config
            _check(
                self.study.execution_enabled is False and self.study.evidence_promotable is False
            )
            _check(type(self.limitations) is tuple and self.limitations == _LIMITATIONS)
            _check(type(self.sessions) is tuple and 101 <= len(self.sessions) <= MAX_ROWS)
            _check(
                all(
                    type(day) is date
                    and self.study.requested_start.date() <= day < HOLDOUT_START
                    and day.weekday() < 5
                    for day in self.sessions
                )
            )
            _check(all(a < b for a, b in zip(self.sessions, self.sessions[1:], strict=False)))
            _check(ANCHOR in self.sessions and self.sessions.index(ANCHOR) >= 100)
            _check(self.protocol_id == "spy-cash-daily-development-v1")
            _check(type(self.first_rebalance) is date and self.first_rebalance == ANCHOR)
            _check(type(self.warmup_bars) is int and self.warmup_bars == 100)
            _check(type(self.rebalance_sessions) is int and self.rebalance_sessions == 5)
            _check(type(self.settlement_sessions) is int and self.settlement_sessions == 2)
            _check(
                type(self.quantity_increment) is Decimal
                and self.quantity_increment == Decimal(".001")
            )
            _check(
                type(self.price_increment) is Decimal and self.price_increment == Decimal(".000001")
            )
            _check(type(self.minimum_notional) is Decimal and self.minimum_notional == Decimal("1"))
            _check(self.fractional_terms_verified is False)
            _check(self.price_basis in ("raw-unadjusted-assumption", "unknown"))
            _check(self.study.windows == (20, 100))
            equity = cfg.equity_strategies
            _check(equity.research_rebalance_bars == 5 and equity.maximum_holding_bars == 100)
            _check(equity.stop_loss_atr_multiplier == Decimal("2.0"))
            _check(equity.exit_reward_to_initial_risk == Decimal("2.0"))
            _check(equity.exit_on_regime_change and equity.research_unselected_symbols_exit_to_cash)
            for digest in (self.calendar_hash, self.source_hash, self.distribution_hash):
                _require_sha256_hex(digest, "daily protocol identity")
            for amount in (self.per_side_cost_bps, self.side_fee, self.episode_fee_bound):
                require_bounded_decimal(amount, "assumed daily cost", nonnegative=True)
            with localcontext(_context(exact=True)):
                _check(self.per_side_cost_bps <= 100)
                _check(self.side_fee * 2 <= self.episode_fee_bound)
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfDailyError() from None

    @property
    def protocol_hash(self) -> str:
        return content_hash({"schema": self.protocol_id, "protocol": self})


@dataclass(frozen=True, slots=True)
class EtfDailyBar(_DailyRecord):
    session_date: date
    raw: Bar
    feature: Bar

    def __post_init__(self) -> None:
        try:
            _markers(self)
            _check(type(self.session_date) is date and self.session_date < HOLDOUT_START)
            _check(type(self.raw) is Bar and type(self.feature) is Bar)
            replace(self.raw)
            replace(self.feature)
            _check(self.raw == self.feature)  # Only explicitly raw/no-split projection supported.
            _check(self.raw.instrument_id == "SPY" and self.raw.interval is BarInterval.ONE_DAY)
            _check(not self.raw.interpolated)
            _check(self.raw.starts_at.date() == self.raw.ends_at.date() == self.session_date)
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfDailyError() from None


@dataclass(frozen=True, slots=True)
class EtfDailyRequest(_DailyRecord):
    protocol: EtfDailyProtocol
    bars: tuple[EtfDailyBar, ...]
    distributions: tuple[EtfBenchmarkDistribution, ...]
    initial_cash: Decimal

    def __post_init__(self) -> None:
        try:
            _markers(self)
            _check(type(self.protocol) is EtfDailyProtocol)
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
                _check(distribution.ex_date < HOLDOUT_START)
                _check(distribution.ex_date in self.protocol.sessions)
                _check(previous is None or distribution.ex_date > previous)
                previous = distribution.ex_date
            require_bounded_decimal(self.initial_cash, "daily initial cash", positive=True)
            _check(self.initial_cash in self.protocol.study.capital_tiers)
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfDailyError() from None

    @property
    def request_hash(self) -> str:
        return content_hash({"schema": "etf-daily-request-v1", "request": self})
