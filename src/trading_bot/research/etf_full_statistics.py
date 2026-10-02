"""Six-scenario descriptive accounting; no acceptance or execution authority.

Operating costs accrue over inclusive UTC calendar dates at supplied USD/day
rates. Cash is a separate, unverified ACT/365 simple-interest reference on initial
capital; it does not earn strategy returns or pay strategy infrastructure costs.
Trading series subtract operating costs exactly once. Daily return denominators
are preceding after-operating NAV, beginning with hypothetical initial capital.
Five contiguous development slices are descriptive, not purged validation folds.
"""

import re
from dataclasses import astuple, dataclass, field, is_dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_FLOOR, Context, Decimal, localcontext
from typing import Literal
from zoneinfo import ZoneInfo

from trading_bot.domain import Side
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.etf_source import _ceil_time, _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_costs import (
    EtfCostEvidence,
    _full_coverage,
    etf_execution_charges,
)
from trading_bot.research.etf_economics import evaluate_etf_account_economics
from trading_bot.research.etf_paired_economics import (
    EtfMatchedReturns,
    EtfPairedEconomicsReport,
    analyze_etf_matched_returns,
)
from trading_bot.research.etf_resampling import EtfBlockRisk, dependent_mean_risks
from trading_bot.research.etf_study import EtfStudy
from trading_bot.research.metrics import (
    MetricValue,
    PerformanceInput,
    PerformanceMetrics,
    calculate_performance,
)
from trading_bot.simulation.etf_account import EtfAccountRequest, replay_etf_account
from trading_bot.simulation.etf_history import _policy
from trading_bot.simulation.etf_native_models import (
    SCENARIOS,
    EtfDailyAccount,
    EtfHistoryResult,
    EtfReplayOutcome,
)
from trading_bot.simulation.lifecycle_accounting import _context

_ZERO = Decimal(0)
_ONE = Decimal(1)
_NY = ZoneInfo("America/New_York")
_REASON = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")
_LIMITATIONS = (
    "descriptive_statistics_not_research_acceptance",
    "source_qualification_unverified",
    "execution_costs_uncalibrated",
    "operating_cost_unitemized_unverified",
    "cash_act_365_simple_attainability_unverified",
    "cash_reference_excludes_strategy_operating_cost",
    "parameter_stability_unmeasured",
    "multiple_testing_unresolved",
    "fold_overlap_and_embargo_acceptance_required",
    "completed_episodes_not_proven_independent",
    "episode_operating_cost_equal_allocation_residual_last",
    "holdout_not_evaluated",
)


class EtfFullStatisticsError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_full_statistics_invalid")


def _check(condition: bool) -> None:
    if not condition:
        raise EtfFullStatisticsError()


def _required[T](value: T | None) -> T:
    if value is None:
        raise EtfFullStatisticsError()
    return value


def _reasons(values: tuple[str, ...]) -> None:
    _check(type(values) is tuple and len(values) <= 256)
    _check(all(type(value) is str and _REASON.fullmatch(value) is not None for value in values))


def _exact() -> Context:
    context = _context(exact=True)
    context.prec = 2200
    return context


def _ratio(a: Decimal, b: Decimal) -> Decimal:
    with localcontext(_context(exact=False)):
        return a / b


def _bounded_output(value: object) -> None:
    """Validate generated totals too; bounded factors can accumulate past bounds."""
    if isinstance(value, Decimal):
        require_bounded_decimal(value, "descriptive output")
    elif isinstance(value, tuple):
        for item in value:
            _bounded_output(item)
    elif is_dataclass(value) and not isinstance(value, type):
        _bounded_output(astuple(value))


@dataclass(frozen=True, slots=True)
class EtfLedgerStatistics:
    account_state_hash: str
    initial_cash: Decimal
    cash_change: Decimal
    trading_pnl: Decimal | None
    marked_pnl: Decimal | None
    operating_cost: Decimal
    operating_profit: Decimal | None
    fees_paid: Decimal
    dividends_received: Decimal
    dividend_receivable: Decimal
    residual_shares: Decimal
    reserved_cash: Decimal
    settled_cash: Decimal
    completed_opportunities: int | None
    completed_episode_pnl: tuple[Decimal, ...]
    net_episode_pnl: tuple[Decimal, ...]
    consumed_trial_loss: Decimal
    net_nav: tuple[Decimal | None, ...]
    period_returns: tuple[Decimal, ...] | None
    metrics: PerformanceMetrics | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EtfDescriptiveFold:
    first_date: date
    last_date: date
    test_observations: int
    total_return_pct: Decimal
    purged: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class EtfFullInvestedReference:
    nav: tuple[Decimal | None, ...] | None
    net_nav: tuple[Decimal | None, ...] | None
    entry_price: Decimal | None
    shares: Decimal
    fees_paid: Decimal
    dividends_received: Decimal
    dividend_receivable: Decimal
    residual_cash: Decimal
    reasons: tuple[str, ...]
    realized_trading_pnl: None = field(default=None, init=False)
    risk_admission_verified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class EtfScenarioStatistics:
    initial_cash: Decimal
    fill_scenario: str
    result_hash: str
    candidate: EtfLedgerStatistics
    constrained_benchmark: EtfLedgerStatistics
    zero_cash_nav: tuple[Decimal, ...]
    sourced_cash_nav: tuple[Decimal, ...]
    full_invested: EtfFullInvestedReference
    folds: tuple[EtfDescriptiveFold, ...]
    paired_zero: EtfPairedEconomicsReport | None
    paired_cash: EtfPairedEconomicsReport | None
    net_expectancy_risks: tuple[EtfBlockRisk, ...]
    maximum_single_opportunity_profit_contribution_pct: Decimal | None
    reasons: tuple[str, ...]
    net_expectancy_units: Literal["USD/observed_session"] = field(
        default="USD/observed_session", init=False
    )


@dataclass(frozen=True, slots=True)
class EtfFullStatisticsReport:
    study_hash: str
    dataset_hash: str
    cost_hash: str
    protocol_hash: str
    session_dates: tuple[date, ...]
    scenarios: tuple[EtfScenarioStatistics, ...]
    reasons: tuple[str, ...]
    verdict: Literal["ECONOMIC_NO_GO"] = field(default="ECONOMIC_NO_GO", init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    @property
    def report_hash(self) -> str:
        return content_hash(("etf-full-descriptive-statistics-v1", self))


def _validate_outcome(study: EtfStudy, outcome: EtfReplayOutcome, capital: Decimal) -> None:
    _check(type(outcome) is EtfReplayOutcome)
    _reasons(outcome.reasons)
    _check(type(outcome.daily) is tuple and len(outcome.daily) <= 10000)
    request = EtfAccountRequest(study, capital, outcome.account_events)
    rebuilt = replay_etf_account(request)
    _check(rebuilt == outcome.account)
    evaluate_etf_account_economics(outcome.account, operating_cost=_ZERO)
    event_times = tuple(event.at_ns for event in outcome.account_events)
    _check(all(at < _ns(study.holdout_start) for at in event_times))
    previous_date = None
    previous_at = 0
    previous_count = 0
    cache = {len(event_times): rebuilt}
    for row in outcome.daily:
        _check(type(row) is EtfDailyAccount and type(row.session_date) is date)
        _check(type(row.at_ns) is int and previous_at < row.at_ns < _ns(study.holdout_start))
        _check(_ns(study.requested_start) <= row.at_ns)
        _check(_ceil_time(row.at_ns).astimezone(_NY).date() == row.session_date)
        _check(previous_date is None or previous_date < row.session_date)
        previous_date, previous_at = row.session_date, row.at_ns
        for value in (
            row.cash,
            row.settled_cash,
            row.shares,
            row.reserved_cash,
            row.fees,
            row.dividend_receivable,
        ):
            require_bounded_decimal(value, "daily account", nonnegative=True)
        for quote in (row.bid, row.ask):
            if quote is not None:
                require_bounded_decimal(quote, "daily quote", positive=True)
        if row.ask is not None and row.bid is not None:
            _check(row.ask >= row.bid)
        if row.nav is not None:
            require_bounded_decimal(row.nav, "daily NAV", nonnegative=True)
        _require_sha256_hex(row.state_hash, "daily state")
        count = row.account_event_count
        _check(type(count) is int and previous_count <= count <= len(event_times))
        _check(not count or event_times[count - 1] <= row.at_ns)
        _check(count == len(event_times) or event_times[count] >= row.at_ns)
        previous_count = count
        if count not in cache:
            cache[count] = replay_etf_account(replace(request, events=request.events[:count]))
        state = cache[count]
        _check(
            (
                row.cash,
                row.settled_cash,
                row.shares,
                row.reserved_cash,
                row.fees,
                row.dividend_receivable,
                row.state_hash,
            )
            == (
                state.cash,
                state.settled_cash,
                state.shares,
                state.reserved_cash,
                state.fees,
                state.dividend_receivable,
                state.state_hash,
            )
        )
        expected_nav = (
            None
            if row.shares and row.bid is None
            else row.cash + row.shares * (row.bid or _ZERO) + row.dividend_receivable
        )
        _check(
            row.nav == expected_nav
            or (
                row.nav is None
                and row.bid is None
                and "input_reconciliation_incomplete" in outcome.reasons
            )
        )


def _integral(costs: EtfCostEvidence, role: str, start: datetime, end: datetime) -> Decimal:
    cursor = start
    total = _ZERO
    for row in sorted((i for i in costs.intervals if i.role == role), key=lambda i: i.starts_at):
        left, right = max(start, row.starts_at), min(end, row.ends_at)
        if left >= right:
            continue
        _check(left == cursor and row.known_at <= left)
        elapsed = right - left
        # No floating-point total_seconds conversion.
        microseconds = (elapsed.days * 86400 + elapsed.seconds) * 1000000 + elapsed.microseconds
        total += Decimal(microseconds) * row.value / Decimal(86400000000)
        cursor = right
    _check(cursor == end)
    return total


def _allocations(
    costs: EtfCostEvidence, dates: tuple[date, ...], capital: Decimal
) -> tuple[tuple[Decimal, ...], tuple[Decimal, ...]]:
    if not dates:
        return (), ()
    start = datetime.combine(dates[0], datetime.min.time(), UTC)
    operating, cash = [], []
    for day in dates:
        end = datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC)
        operating.append(_integral(costs, "operating_cost", start, end))
        interest = _ratio(capital * _integral(costs, "cash_rate", start, end), Decimal(36500))
        cash.append(capital + interest)
    return tuple(operating), tuple(cash)


def _returns(nav: tuple[Decimal | None, ...], capital: Decimal) -> tuple[Decimal, ...] | None:
    if not nav or any(value is None or value <= 0 for value in nav):
        return None
    previous = capital
    result = []
    for value in nav:
        current = _required(value)
        result.append(_ratio(current, previous) - _ONE)
        previous = current
    return tuple(result)


def _received_dividends(outcome: EtfReplayOutcome) -> Decimal:
    shares, paid = _ZERO, _ZERO
    entitlements: dict[str, Decimal] = {}
    seen: set[str] = set()
    seen_fills: set[str] = set()
    for event in outcome.account_events:
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        if event.fill is not None:
            if event.fill.id not in seen_fills:
                seen_fills.add(event.fill.id)
                shares += event.fill.quantity * (1 if event.fill.side is Side.BUY else -1)
        elif event.kind == "dividend_ex":
            entitlements[_required(event.action_id)] = shares * _required(event.cash_per_share)
        elif event.kind == "dividend_pay":
            paid += entitlements.pop(_required(event.action_id), _ZERO)
    return paid


def _ledger(
    outcome: EtfReplayOutcome, capital: Decimal, operating: tuple[Decimal, ...]
) -> EtfLedgerStatistics:
    account = outcome.account
    summary = evaluate_etf_account_economics(account, operating_cost=_ZERO)
    reasons = set(outcome.reasons)
    reconciled = "input_reconciliation_incomplete" not in reasons
    reasons.add("embedded_execution_cost_attribution_unavailable")
    operating_total = operating[-1] if operating else _ZERO
    terminal_after_mark = bool(outcome.daily) and (
        outcome.daily[-1].account_event_count < len(outcome.account_events)
    )
    if terminal_after_mark:
        reasons.add("terminal_facts_after_last_mark")
    if not outcome.daily:
        reasons.update(
            (
                "observation_window_empty",
                "warmup_incomplete",
                "operating_cost_allocation_window_unavailable",
            )
        )
    filled_episodes = {
        order.episode_id
        for order in account.orders
        if order.order.side is Side.BUY and order.order.filled_quantity > 0
    }
    pnl = tuple(
        episode.net_cash_flow
        for episode in account.trial.episodes
        if episode.complete
        and reconciled
        and episode.net_cash_flow is not None
        and episode.episode_id in filled_episodes
    )
    net_pnl: tuple[Decimal, ...] = ()
    if pnl and account.complete and operating and not terminal_after_mark:
        allocation = _ratio(operating_total, Decimal(len(pnl)))
        # Attribute any nonterminating equal-share residual to the final episode;
        # total episode operating debits remain exactly the allocated cash cost.
        allocations = (
            *(allocation for _ in pnl[:-1]),
            operating_total - allocation * (len(pnl) - 1),
        )
        net_pnl = tuple(value - cost for value, cost in zip(pnl, allocations, strict=True))
    nav = tuple(
        None if row.nav is None or not reconciled else row.nav - cost
        for row, cost in zip(outcome.daily, operating, strict=True)
    )
    if terminal_after_mark:
        nav = (*nav[:-1], None)
    returns = _returns(nav, capital)
    metrics = None
    if returns is None:
        reasons.add(
            "nonpositive_nav_returns_unavailable"
            if nav and all(v is not None for v in nav)
            else "unavailable_nav_returns_unavailable"
        )
    else:
        days = Decimal((outcome.daily[-1].session_date - outcome.daily[0].session_date).days + 1)
        exposure = tuple(_ratio(row.shares * (row.bid or _ZERO), capital) for row in outcome.daily)
        fills = {
            event.fill.id: event.fill for event in outcome.account_events if event.fill is not None
        }
        turnover = _ratio(
            sum((fill.quantity * fill.price for fill in fills.values()), _ZERO), capital
        )
        curve = (
            (_ceil_time(outcome.daily[0].at_ns) - timedelta(days=1), capital),
            *(
                (_ceil_time(row.at_ns), value)
                for row, value in zip(outcome.daily, nav, strict=True)
                if value is not None
            ),
        )
        with localcontext(_context(exact=False)):
            metrics = calculate_performance(
                PerformanceInput(
                    curve,
                    returns,
                    net_pnl,
                    252,
                    days / Decimal(365),
                    turnover,
                    exposure,
                    exposure,
                    Decimal(sum(row.shares > 0 for row in outcome.daily)) / len(nav),
                    _ZERO,
                    _ZERO,
                    account.fees,
                    len(pnl),
                )
            )
        metrics = replace(
            metrics,
            spread_cost=MetricValue(None, "embedded_in_fill_price_not_separately_attributable"),
            slippage_cost=MetricValue(None, "embedded_in_fill_price_not_separately_attributable"),
        )
    if not account.complete:
        reasons.add("account_outcome_incomplete")
    final_nav = (
        outcome.daily[-1].nav if outcome.daily and not terminal_after_mark and reconciled else None
    )
    trading_pnl = summary.trading_pnl if reconciled else None
    return EtfLedgerStatistics(
        account.state_hash,
        capital,
        account.cash - capital,
        trading_pnl,
        None if final_nav is None else final_nav - capital,
        operating_total,
        None
        if trading_pnl is None or not operating or terminal_after_mark
        else trading_pnl - operating_total,
        account.fees,
        _received_dividends(outcome),
        account.dividend_receivable,
        account.shares,
        account.reserved_cash,
        account.settled_cash,
        len(pnl) if reconciled else None,
        pnl,
        net_pnl,
        account.trial.consumed_loss,
        nav,
        returns,
        metrics,
        tuple(sorted(reasons)),
    )


def _full_reference(
    outcome: EtfReplayOutcome,
    costs: EtfCostEvidence,
    capital: Decimal,
    operating: tuple[Decimal, ...],
) -> EtfFullInvestedReference:
    reasons: tuple[str, ...] = (
        "fully_invested_unauthorized_reference",
        "daily_quote_snapshot_not_executed",
        "fractional_terms_unverified",
        "terminal_bid_mark_not_sale",
    )
    if not outcome.daily or "input_reconciliation_incomplete" in outcome.reasons:
        return EtfFullInvestedReference(
            None,
            None,
            None,
            _ZERO,
            _ZERO,
            _ZERO,
            _ZERO,
            capital,
            (
                *reasons,
                "input_reconciliation_incomplete"
                if "input_reconciliation_incomplete" in outcome.reasons
                else "observation_window_empty",
            ),
        )
    first = outcome.daily[0]
    if first.ask is None:
        return EtfFullInvestedReference(
            None,
            None,
            None,
            _ZERO,
            _ZERO,
            _ZERO,
            _ZERO,
            capital,
            (*reasons, "entry_ask_unavailable"),
        )
    at = _ceil_time(first.at_ns)
    rates = {row.role: row.value for row in costs.intervals if row.starts_at <= at < row.ends_at}
    price = first.ask * (_ONE + rates["extra_slippage"] / Decimal(10000))
    minimum = rates["minimum_commission"]
    if capital <= minimum:
        return EtfFullInvestedReference(
            None,
            None,
            price,
            _ZERO,
            _ZERO,
            _ZERO,
            _ZERO,
            capital,
            (*reasons, "entry_fees_unaffordable"),
        )
    # Solve both branches of max(minimum, per-share commission), rounding shares down.
    with localcontext(_context(exact=False)) as context:
        context.rounding = ROUND_FLOOR
        q = min(
            (capital - minimum) / (price * (_ONE + rates["regulatory_per_notional"])),
            capital
            / (price * (_ONE + rates["regulatory_per_notional"]) + rates["commission_per_share"]),
        )
    require_bounded_decimal(q, "reference shares", positive=True)
    fee = etf_execution_charges(costs, at=at, prior_quantity=_ZERO, quantity=q, price=price)
    cash = capital - q * price - fee.total_fee_usd
    _check(cash >= 0)
    paid = _ZERO
    entitlements: dict[str, Decimal] = {}
    seen: set[str] = set()
    cursor = 0
    nav: list[Decimal | None] = []
    counts = (*(row.account_event_count for row in outcome.daily), len(outcome.account_events))
    for index, count in enumerate(counts):
        while cursor < count:
            event = outcome.account_events[cursor]
            if event.event_id not in seen:
                seen.add(event.event_id)
                if event.kind == "dividend_ex" and cursor >= first.account_event_count:
                    entitlements[_required(event.action_id)] = q * _required(event.cash_per_share)
                elif event.kind == "dividend_pay":
                    amount = entitlements.pop(_required(event.action_id), _ZERO)
                    cash += amount
                    paid += amount
            cursor += 1
        if index < len(outcome.daily):
            row = outcome.daily[index]
            nav.append(
                None if row.bid is None else cash + q * row.bid + sum(entitlements.values(), _ZERO)
            )
    if outcome.daily[-1].account_event_count < len(outcome.account_events):
        nav[-1] = None
        reasons = (*reasons, "terminal_facts_after_last_mark")
    net = tuple(
        None if value is None else value - op for value, op in zip(nav, operating, strict=True)
    )
    return EtfFullInvestedReference(
        tuple(nav),
        net,
        price,
        q,
        fee.total_fee_usd,
        paid,
        sum(entitlements.values(), _ZERO),
        cash,
        reasons,
    )


def _folds(
    dates: tuple[date, ...],
    nav: tuple[Decimal | None, ...],
    capital: Decimal,
    minimum: int,
    count: int,
) -> tuple[EtfDescriptiveFold, ...]:
    if len(dates) < count * minimum or any(value is None or value <= 0 for value in nav):
        return ()
    width, remainder = divmod(len(dates), count)
    result = []
    cursor = 0
    for index in range(count):
        size = width + (index < remainder)
        initial = capital if cursor == 0 else _required(nav[cursor - 1])
        final = _required(nav[cursor + size - 1])
        result.append(
            EtfDescriptiveFold(
                dates[cursor], dates[cursor + size - 1], size, (_ratio(final, initial) - 1) * 100
            )
        )
        cursor += size
    return tuple(result)


def _scenario(
    study: EtfStudy, result: EtfHistoryResult, costs: EtfCostEvidence, dates: tuple[date, ...]
) -> EtfScenarioStatistics:
    config = _policy(study).config.research
    operating, cash = _allocations(costs, dates, result.initial_cash)
    candidate = _ledger(result.candidate, result.initial_cash, operating)
    constrained = _ledger(result.constrained_benchmark, result.initial_cash, operating)
    zero = (result.initial_cash,) * len(dates)
    paired_zero = paired_cash = None
    risks: tuple[EtfBlockRisk, ...] = ()
    reasons = set(result.reasons) | set(candidate.reasons) | set(constrained.reasons)
    if (
        len(dates) >= 100
        and candidate.period_returns is not None
        and constrained.period_returns is not None
    ):
        cash_returns = _required(_returns(cash, result.initial_cash))
        pairing_hash = content_hash((result.result_hash, costs.cost_hash, operating, cash))
        paired_zero = analyze_etf_matched_returns(
            EtfMatchedReturns(
                dates,
                candidate.period_returns,
                constrained.period_returns,
                (_ZERO,) * len(dates),
                pairing_hash,
            ),
            seed=study.seed,
        )
        paired_cash = analyze_etf_matched_returns(
            EtfMatchedReturns(
                dates,
                candidate.period_returns,
                constrained.period_returns,
                cash_returns,
                pairing_hash,
            ),
            seed=study.seed,
        )
        if (
            min(
                paired_zero.constrained_lower_bound,
                paired_zero.cash_lower_bound,
                paired_cash.cash_lower_bound,
            )
            <= 0
        ):
            reasons.add("positive_excess_interval_unsupported")
    else:
        reasons.add("dependent_statistics_unavailable")
    if len(dates) >= 100 and candidate.period_returns is not None:
        net = candidate.net_nav
        differences = tuple(
            value - previous
            for previous, value in zip((result.initial_cash, *net[:-1]), net, strict=True)
            if value is not None and previous is not None
        )
        risks = dependent_mean_risks(
            differences, seed=study.seed, block_lengths=(20, 100), draws=1000
        )
    folds = _folds(
        dates,
        candidate.net_nav,
        result.initial_cash,
        config.minimum_test_bars_per_fold,
        config.walk_forward_folds,
    )
    if not folds:
        reasons.add("walk_forward_sample_incomplete")
    elif sum(f.total_return_pct > 0 for f in folds) < config.minimum_positive_walk_forward_folds:
        reasons.add("insufficient_positive_walk_forward_folds")
    if (
        candidate.completed_opportunities is None
        or candidate.completed_opportunities < config.minimum_independent_opportunities
    ):
        reasons.add("independent_opportunities_insufficient")
    positive = tuple(value for value in candidate.net_episode_pnl if value > 0)
    concentration = _ratio(max(positive), sum(positive, _ZERO)) * 100 if positive else None
    if (
        concentration is not None
        and concentration > config.maximum_single_opportunity_profit_contribution_pct
    ):
        reasons.add("one_trade_dependence")
    if candidate.metrics is not None:
        maximum = candidate.metrics.maximum_drawdown_pct.value
        if isinstance(maximum, Decimal) and abs(maximum) > config.maximum_stressed_drawdown_pct:
            reasons.add("stressed_drawdown_breach")
    if (
        risks
        and max(r.loss_probability for r in risks) * 100
        > config.maximum_monte_carlo_loss_probability_pct
    ):
        reasons.add("monte_carlo_loss_probability_breach")
    return EtfScenarioStatistics(
        result.initial_cash,
        result.fill_scenario,
        result.result_hash,
        candidate,
        constrained,
        zero,
        cash,
        _full_reference(result.candidate, costs, result.initial_cash, operating),
        folds,
        paired_zero,
        paired_cash,
        risks,
        concentration,
        tuple(sorted(reasons)),
    )


def describe_etf_economics(
    study: EtfStudy, results: tuple[EtfHistoryResult, ...], costs: EtfCostEvidence
) -> EtfFullStatisticsReport:
    """Reconstruct and compare all six runs; never select or accept a candidate."""
    try:
        _policy(study)
        _check(type(results) is tuple and len(results) == 6)
        _check(type(costs) is EtfCostEvidence and replace(costs) == costs)
        _check(
            costs.calibration_status == "unverified"
            and costs.spread_in_fill_price is True
            and costs.execution_enabled is False
            and costs.evidence_promotable is False
        )
        _full_coverage(costs, study)
        found: set[tuple[Decimal, str]] = set()
        identity = None
        dates = None
        with localcontext(_exact()):
            for result in results:
                _check(type(result) is EtfHistoryResult)
                for digest in (
                    result.input_hash,
                    result.study_hash,
                    result.dataset_hash,
                    result.cost_hash,
                    result.protocol_hash,
                    result.source_prefix_hash,
                ):
                    _require_sha256_hex(digest, "result identity")
                require_bounded_decimal(result.initial_cash, "capital", positive=True)
                _check(type(result.fill_scenario) is str and result.fill_scenario in SCENARIOS)
                _check(result.initial_cash in study.capital_tiers)
                pair = result.initial_cash, result.fill_scenario
                _check(pair not in found)
                found.add(pair)
                _check(
                    result.study_hash == study.study_hash and result.cost_hash == costs.cost_hash
                )
                current = (
                    result.study_hash,
                    result.dataset_hash,
                    result.cost_hash,
                    result.protocol_hash,
                    result.source_count,
                    result.source_prefix_hash,
                )
                _check(identity is None or current == identity)
                identity = current
                _check(type(result.source_count) is int and 0 <= result.source_count <= 150000)
                _check(
                    result.paused is True
                    and result.execution_enabled is False
                    and result.evidence_promotable is False
                )
                _reasons(result.reasons)
                for outcome in (result.candidate, result.constrained_benchmark):
                    _validate_outcome(study, outcome, result.initial_cash)
                    observed = tuple(row.session_date for row in outcome.daily)
                    _check(dates is None or dates == observed)
                    dates = observed
            dates = _required(dates)
            ordered = sorted(
                results,
                key=lambda result: (result.initial_cash, SCENARIOS.index(result.fill_scenario)),
            )
            scenarios = tuple(_scenario(study, result, costs, dates) for result in ordered)
        report = EtfFullStatisticsReport(
            study.study_hash,
            results[0].dataset_hash,
            costs.cost_hash,
            results[0].protocol_hash,
            dates,
            scenarios,
            tuple(
                sorted(
                    set(_LIMITATIONS)
                    | (
                        {"holdout_previously_examined"}
                        if study.holdout_previously_examined
                        else set()
                    )
                )
            ),
        )
        _bounded_output(report)
        return report
    except (ValueError, TypeError, ArithmeticError, AttributeError, AssertionError, KeyError):
        raise EtfFullStatisticsError() from None
