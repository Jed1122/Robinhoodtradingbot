"""Development-only, current-access cash/buy-hold reference screen.

Real saved daily prices and issuer cash distributions can support an exploratory
mark-based reference, not a strategy execution backtest. No order, fill, risk
approval or final sale is constructed. Original timeline waiver is retained;
intraday controls, fractional terms and calibrated costs remain unmet.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal
from zoneinfo import ZoneInfo

from trading_bot.market_data.etf_calendar import EtfCalendarArchive, compare_etf_calendar_bars
from trading_bot.market_data.etf_issuer_distributions import EtfIssuerDistributionArchive
from trading_bot.market_data.etf_native_archive import EtfNativeBarsArchive
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import (
    EtfBenchmarkBar,
    EtfBenchmarkDistribution,
    EtfBenchmarkRequest,
    run_etf_benchmark,
)
from trading_bot.research.etf_latest_vintage import (
    EtfLatestVintageRequest,
    latest_vintage_source_plan_hash,
)
from trading_bot.research.etf_resampling import EtfBlockInterval, dependent_mean_intervals
from trading_bot.research.etf_study import EtfStudy
from trading_bot.simulation.etf_history import _policy
from trading_bot.simulation.lifecycle_accounting import _context

_NEW_YORK = ZoneInfo("America/New_York")
_COSTS = (
    ("zero_cost_mathematical_reference", Decimal("0"), Decimal("0")),
    ("five_bps_uncalibrated", Decimal("5"), Decimal(".01")),
    ("twenty_five_bps_uncalibrated", Decimal("25"), Decimal(".01")),
)


class EtfBenchmarkScreenError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_benchmark_screen_invalid")


def _check(value: bool) -> None:
    if not value:
        raise EtfBenchmarkScreenError()


def etf_benchmark_screen_plan_hash(
    archive: EtfNativeBarsArchive,
    calendar: EtfCalendarArchive,
    issuer: EtfIssuerDistributionArchive,
) -> str:
    return content_hash(
        {
            "schema": "etf-daily-reference-screen-protocol-v1",
            "bar_archive": archive.archive_hash,
            "calendar": calendar.archive_hash,
            "issuer": issuer.archive_hash,
            "evaluation": "750-bar-warmup-development-only-before-2024",
            "cost_scenarios": _COSTS,
            "references": ("exposure_capped_buy_hold", "fully_invested_unauthorized_reference"),
            "zero_yield_cash": True,
            "terminal": "open-shares-mark-and-liquidation-proxy-no-sale",
            "uncertainty": "descriptive-20-100-session-blocks-1000-draws",
            "orders": "none-risk-admission-not-verified",
            "scenario_selection": False,
        }
    )


@dataclass(frozen=True, slots=True)
class EtfBenchmarkScreenRequest:
    study: EtfStudy
    archive: EtfNativeBarsArchive
    calendar: EtfCalendarArchive
    issuer: EtfIssuerDistributionArchive

    def __post_init__(self) -> None:
        try:
            _policy(self.study)
            _check(type(self.archive) is EtfNativeBarsArchive)
            _check(type(self.calendar) is EtfCalendarArchive)
            _check(type(self.issuer) is EtfIssuerDistributionArchive)
            replace(self.issuer)
            coverage = compare_etf_calendar_bars(self.archive, self.calendar)
            _check(coverage.dates_match)
            sessions = tuple(row.session_date for row in self.calendar.sessions)
            # Coarse full-request sanity, not an independent exchange closure
            # qualification. Matching two equally truncated packages is insufficient.
            _check(sessions[0] <= date(2016, 1, 7) and sessions[-1] >= date(2025, 12, 27))
            _check(
                all(
                    240 <= sum(day.year == year for day in sessions) <= 262
                    for year in range(2016, 2026)
                )
            )
            _check("requested_window_incomplete" not in self.issuer.limitations)
            _check(len(self.issuer.distributions) == 40)
            _check(
                {
                    (row.ex_date.year, (row.ex_date.month - 1) // 3)
                    for row in self.issuer.distributions
                }
                == {(year, quarter) for year in range(2016, 2026) for quarter in range(4)}
            )
            _check(all(row.ex_date in sessions for row in self.issuer.distributions))
            _check(
                self.study.source_plan_hash
                == etf_benchmark_screen_plan_hash(self.archive, self.calendar, self.issuer)
            )
            # Reuse the native price-window/completion validation without changing
            # the historical source or falsely granting it executable provenance.
            checked = replace(
                self.study,
                policy=_policy(self.study),
                source_plan_hash=latest_vintage_source_plan_hash(self.archive),
            )
            EtfLatestVintageRequest(checked, self.archive)
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise EtfBenchmarkScreenError() from None


@dataclass(frozen=True, slots=True)
class EtfBenchmarkScenarioScreen:
    initial_cash: Decimal
    reference: str
    cost_scenario: str
    entry_notional: Decimal
    per_side_cost_bps: Decimal
    fees_paid: Decimal
    embedded_entry_cost: Decimal
    estimated_terminal_liquidation_cost: Decimal
    terminal_cash: Decimal
    terminal_shares: Decimal
    dividend_cash_received: Decimal
    dividend_receivable: Decimal
    close_mark_nav: Decimal
    liquidation_proxy: Decimal
    marked_pnl: Decimal
    break_even_monthly_operating_cost_proxy: Decimal
    intervals: tuple[EtfBlockInterval, ...]
    reference_result_hash: str
    realized_trading_pnl: None = field(default=None, init=False)
    risk_admission_verified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class EtfBenchmarkScreenResult:
    study_hash: str
    protocol_hash: str
    calendar_sessions: int
    issuer_distributions: int
    excluded_issuer_rows: int
    evaluation_records: int
    retained_holdout_records: int
    evaluation_start: date
    evaluation_end: date
    scenarios: tuple[EtfBenchmarkScenarioScreen, ...]
    reasons: tuple[str, ...]
    source_kind: Literal["daily-price-exploratory-benchmark-screen-v1"] = field(
        default="daily-price-exploratory-benchmark-screen-v1", init=False
    )
    economic_verdict: Literal["ECONOMIC_NO_GO"] = field(default="ECONOMIC_NO_GO", init=False)
    admitted_orders: Literal[0] = field(default=0, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    @property
    def result_hash(self) -> str:
        return content_hash(("etf-benchmark-screen-result-v1", self))


def run_etf_benchmark_screen(request: EtfBenchmarkScreenRequest) -> EtfBenchmarkScreenResult:
    try:
        _check(type(request) is EtfBenchmarkScreenRequest)
        replace(request)
        cfg = _policy(request.study).config
        development = tuple(
            row
            for row in request.archive.bars
            if row.timestamp_ns < _ns(request.study.holdout_start)
        )
        rows = development[cfg.research.minimum_history_bars :]
        _check(bool(rows))
        bars = tuple(
            EtfBenchmarkBar(
                _ceil_time(row.timestamp_ns).astimezone(_NEW_YORK).date(),
                row.open,
                row.close,
                row.record_hash,
            )
            for row in rows
        )
        distributions = tuple(
            EtfBenchmarkDistribution(row.ex_date, row.pay_date, row.amount, row.row_hash)
            for row in request.issuer.distributions
            if row.ex_date <= bars[-1].session_date
        )
        scenarios = []
        with localcontext(_context(exact=False)):
            months = (
                Decimal((bars[-1].session_date - bars[0].session_date).days + 1)
                * 12
                / Decimal("365.25")
            )
            for capital in request.study.capital_tiers:
                for name, bps, fee in _COSTS:
                    cap = min(
                        cfg.activity.max_order_notional_usd,
                        cfg.portfolio.max_gross_exposure_usd,
                        request.study.risk_equity_reference
                        * cfg.position_risk.max_position_notional_pct
                        / 100,
                        request.study.risk_equity_reference
                        * cfg.position_risk.max_correlated_group_exposure_pct
                        / 100,
                        request.study.risk_equity_reference
                        * cfg.portfolio.max_total_gross_exposure_pct
                        / 100,
                        capital * (100 - cfg.options.min_unencumbered_cash_pct) / 100 - fee,
                        cfg.options.cumulative_trial_loss_limit_usd - fee,
                    )
                    _check(cap >= 0)
                    # Notional bounds only: absent stop/quotes/fractional metadata
                    # prevent an order/risk approval. Fully invested is explicitly
                    # an unauthorized reference, not a permitted allocation.
                    for reference, notional in (
                        ("exposure_capped_buy_hold", cap),
                        ("fully_invested_unauthorized_reference", capital - fee),
                    ):
                        outcome = run_etf_benchmark(
                            EtfBenchmarkRequest(
                                bars, distributions, capital, notional, bps, fee, fee
                            )
                        )
                        final = outcome.points[-1]
                        changes = tuple(
                            (b.close_midpoint_nav - a.close_midpoint_nav) / capital
                            for a, b in zip(outcome.points[:-1], outcome.points[1:], strict=True)
                        )
                        intervals = (
                            dependent_mean_intervals(changes, seed=request.study.seed)
                            if len(changes) >= 100
                            else ()
                        )
                        scenarios.append(
                            EtfBenchmarkScenarioScreen(
                                capital,
                                reference,
                                name,
                                notional,
                                bps,
                                outcome.fees_paid,
                                outcome.embedded_entry_cost,
                                outcome.estimated_terminal_liquidation_cost,
                                final.cash,
                                outcome.shares,
                                outcome.dividends_received,
                                outcome.dividends_receivable,
                                final.close_midpoint_nav,
                                final.liquidation_proxy,
                                final.marked_pnl,
                                max(Decimal(0), final.liquidation_proxy - capital) / months,
                                intervals,
                                outcome.result_hash,
                            )
                        )
        return EtfBenchmarkScreenResult(
            request.study.study_hash,
            request.study.source_plan_hash,
            len(request.calendar.sessions),
            len(request.issuer.distributions),
            request.issuer.excluded_spy_rows,
            len(bars),
            len(request.archive.bars) - len(development),
            bars[0].session_date,
            bars[-1].session_date,
            tuple(scenarios),
            (
                *request.archive.limitations,
                *request.calendar.limitations,
                *request.issuer.limitations,
                "candidate_after_cost_outcomes_unavailable",
                "daily_aggregate_open_close_not_verified_core_session_prices",
                "benchmark_marks_are_not_fills_or_realized_profit",
                "cost_scenarios_and_fractional_terms_uncalibrated",
                "full_canonical_risk_admission_not_verified",
                "dependent_reference_intervals_not_effective_strategy_opportunities",
                "actual_operating_cost_history_and_cash_yield_unavailable",
                "purged_folds_and_parameter_stability_unmeasured",
                "holdout_not_evaluated",
            ),
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfBenchmarkScreenError() from None
