"""Source-independent composition of the frozen, nonpromoting price-only study.

Panel positions carry the fixed declared stock order. A separate source loader
must verify their actual security identity, public membership, source hashes and
calendar. This module cannot attest authentic data or qualify investment use.
All dates here are reconstructed decision/session timestamps, not receipt clocks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
from typing import Literal

from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research import stock_study_statistics as statistics
from trading_bot.research.hybrid_policies import (
    CalendarSession,
    PolicyInput,
    SessionObservation,
    StrategyProposal,
    UniverseMembership,
    evaluate_policies,
)
from trading_bot.research.hybrid_strategies import PriceBar
from trading_bot.research.stock_price_trace import PriceTrace, trace_price_targets

STUDY_SYMBOLS = ("AXP", "AAPL", "BAC", "CVX", "KO", "KHC", "MCO", "OXY", "SPY")
ROUND_TRIP_COST_BPS = (Decimal(10), Decimal(25), Decimal(50), Decimal(100))
CONTROL_NAMES = (
    "cohort_buy_hold",
    "spy_buy_hold",
    "passive_90_cohort_10_cash",
    "causal_exposure_spy",
)
_ZERO, _ONE = Decimal(0), Decimal(1)
_CONTEXT = Context(
    prec=50,
    rounding=ROUND_HALF_EVEN,
    Emin=-999999,
    Emax=999999,
    capitals=1,
    clamp=0,
    flags=[],
    traps=[InvalidOperation, DivisionByZero, Overflow, Underflow],
)
_LIMITATIONS = (
    "price_only_cost_ablation_not_total_return_dollar_wealth_or_after_tax_performance",
    "fixed_disclosed_cohort_does_not_establish_complete_point_in_time_universe_coverage",
    "source_identity_calendar_currency_actions_and_revisions_require_separate_admission",
    "eight_independent_equal_initial_sleeves_not_75_15_10_monetary_portfolio",
    "experimental_pre_fee_target_nav_cost_basis_not_broker_execution_notional_fees",
    "causal_spy_control_matches_prior_close_target_exposure_not_next_open_realized_exposure",
    "bootstrap_mean_log_differences_are_not_excess_cagr_or_independent_trade_samples",
    "training_grid_is_not_optimization_and_does_not_change_frozen_holdout_parameters",
    "partial_first_probe_does_not_complete_full_task5_strategy_exit_reinvestment_evaluation",
)
_PROTOCOL = (
    "stock-price-study-v1",
    STUDY_SYMBOLS,
    ROUND_TRIP_COST_BPS,
    CONTROL_NAMES,
    "strict_close_gt_sma200_and_sma50_gt_sma200_actual_hybrid_policies",
    "close_decisions_next_open_final_signal_unexecuted_terminal_liquidation_once",
    "continuous_state_prior_close_segment_baseline",
    "mean_of_8_independently_funded_equal_initial_sleeves_no_transfers",
    "causal_target_weighted_preterminal_close_nav_spy_control",
    "cash_zero_return",
    "50_digit_half_even",
    "252_simple_returns_zero_risk_free",
    "sample_volatility_all_return_downside_rms",
    ((40, 50, 60), (180, 200, 220), "training_prefix_mark_only_common_start220"),
    ("paired_circular_blocks", (20, 5, 60), 20261026, 16, Decimal(".05")),
)
PROTOCOL_HASH = str(content_hash(_PROTOCOL))


def _utc(value: datetime) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("UTC reconstructed session or public-membership timestamp required")


@dataclass(frozen=True, slots=True)
class StockStudyPanel:
    bars: tuple[tuple[PriceBar, ...], ...]
    opens_at: tuple[datetime, ...]
    membership_use_not_before: datetime
    symbols: tuple[str, ...] = field(default=STUDY_SYMBOLS, init=False)
    quote_currency: None = field(default=None, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        _validate_panel(self)

    @property
    def evidence_hash(self) -> str:
        return str(
            content_hash(
                (
                    "stock-study-panel-v1",
                    STUDY_SYMBOLS,
                    self.bars,
                    self.opens_at,
                    self.membership_use_not_before,
                )
            )
        )


@dataclass(frozen=True, slots=True)
class StudySegment:
    first_session: int
    last_session: int
    baseline_nav: Decimal
    inherited_high_watermark: Decimal
    summary: statistics.PricePathSummary


@dataclass(frozen=True, slots=True)
class StudyPath:
    name: str
    nav: tuple[Decimal, ...]
    train: StudySegment
    holdout: StudySegment


@dataclass(frozen=True, slots=True)
class StockStudyScenario:
    round_trip_cost_bps: Decimal
    one_way_cost_bps: Decimal
    trend_traces: tuple[PriceTrace, ...]
    cohort_buy_hold_traces: tuple[PriceTrace, ...]
    spy_buy_hold_trace: PriceTrace
    exposure_control_trace: PriceTrace
    exposure_targets: tuple[Decimal, ...]
    strategy: StudyPath
    controls: tuple[StudyPath, ...]
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class TrainingSensitivityScenario:
    round_trip_cost_bps: Decimal
    one_way_cost_bps: Decimal
    sleeve_traces: tuple[PriceTrace, ...]
    panel_nav: tuple[Decimal, ...]
    own_window: StudySegment
    common_window: StudySegment
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class TrainingSensitivity:
    fast_window: int
    slow_window: int
    first_possible_execution_session: int
    targets: tuple[tuple[Decimal, ...], ...]
    scenarios: tuple[TrainingSensitivityScenario, ...]
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class StockPriceStudy:
    panel_evidence_hash: str
    protocol_hash: str
    first_execution_session: int
    training_last_session: int
    bootstrap_replicates: int
    trend_targets: tuple[tuple[Decimal, ...], ...]
    scenarios: tuple[StockStudyScenario, ...]
    sensitivities: tuple[TrainingSensitivity, ...]
    holdout_log_difference_names: tuple[str, ...]
    holdout_log_differences: tuple[tuple[Decimal, ...], ...]
    holdout_intervals: tuple[statistics.PairedBlockIntervals, ...]
    unavailable_block_lengths: tuple[int, ...]
    evidence_hash: str
    status: Literal["price_only_ablation"] = field(default="price_only_ablation", init=False)
    arithmetic_precision: Literal[50] = field(default=50, init=False)
    symbols: tuple[str, ...] = field(default=STUDY_SYMBOLS, init=False)
    quote_currency: None = field(default=None, init=False)
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    full_task5_complete: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)


def _validate_panel(panel: StockStudyPanel) -> None:
    if type(panel.bars) is not tuple or len(panel.bars) != len(STUDY_SYMBOLS):
        raise ValueError("all nine fixed-order source slots required, without substitution")
    if type(panel.opens_at) is not tuple or not 221 <= len(panel.opens_at) <= 10000:
        raise ValueError("221 through 10000 immutable matched sessions required")
    _utc(panel.membership_use_not_before)
    for series in panel.bars:
        if type(series) is not tuple or len(series) != len(panel.opens_at):
            raise ValueError("all nine series must retain every calendar row")
    previous_close: datetime | None = None
    for i, opened in enumerate(panel.opens_at):
        _utc(opened)
        close = panel.bars[0][i].completed_at if type(panel.bars[0][i]) is PriceBar else None
        if close is None:
            raise ValueError("PriceBar rows required")
        _utc(close)
        if opened >= close or (previous_close is not None and opened <= previous_close):
            raise ValueError("increasing nonoverlapping matched sessions required")
        for series in panel.bars:
            bar = series[i]
            if type(bar) is not PriceBar or bar.completed_at != close:
                raise ValueError("identical completed-session calendar required for all slots")
            _utc(bar.completed_at)
            for price in (bar.open, bar.close):
                require_bounded_decimal(price, "price", positive=True)
                if not Decimal("1e-30") <= price <= Decimal("1e30"):
                    raise ValueError("bounded positive Decimal price required")
        previous_close = close


def _validate_run(
    panel: StockStudyPanel,
    training_last_session: int,
    first_execution_session: int,
    bootstrap_replicates: int,
) -> None:
    if type(panel) is not StockStudyPanel:
        raise ValueError("StockStudyPanel required")
    _validate_panel(panel)
    if (
        type(training_last_session) is not int
        or type(first_execution_session) is not int
        or not 200 <= first_execution_session <= training_last_session
        or training_last_session < 220
        or training_last_session >= len(panel.opens_at) - 20
    ):
        raise ValueError("complete warmup, common training220 and20holdout sessions required")
    if type(bootstrap_replicates) is not int or not 100 <= bootstrap_replicates <= 50000:
        raise ValueError("100 through50000 explicitly configured bootstrap replicates required")
    if panel.membership_use_not_before > panel.bars[0][first_execution_session - 1].completed_at:
        raise ValueError("public membership must precede first passive-control decision")


def _sma_target(series: tuple[PriceBar, ...], index: int, fast: int, slow: int) -> Decimal:
    if index < slow - 1:
        return _ZERO
    slow_mean = sum((bar.close for bar in series[index - slow + 1 : index + 1]), _ZERO) / slow
    fast_mean = sum((bar.close for bar in series[index - fast + 1 : index + 1]), _ZERO) / fast
    return _ONE if series[index].close > slow_mean and fast_mean > slow_mean else _ZERO


def _baseline_targets(
    panel: StockStudyPanel,
    first_execution_session: int,
) -> tuple[tuple[Decimal, ...], ...]:
    count = len(panel.opens_at)
    targets: list[list[Decimal]] = [[_ZERO] * count for _ in STUDY_SYMBOLS[:8]]
    membership = tuple(
        UniverseMembership(
            symbol,
            panel.membership_use_not_before,
            panel.membership_use_not_before,
            True,
            "stock-study-" + symbol,
        )
        for symbol in STUDY_SYMBOLS[:8]
    )
    for index in range(first_execution_session - 1, count):
        information_at = panel.bars[0][index].completed_at
        if information_at < panel.membership_use_not_before:
            continue
        if index == count - 1:
            # No fabricated next session: final close signal is retained but unexecuted.
            for slot in range(8):
                targets[slot][index] = _sma_target(panel.bars[slot], index, 50, 200)
            continue
        # 253 is the largest original policy lookback. A trailing observed prefix
        # contains every required price without quadratic unbounded history hashing.
        start = max(0, index - 252)
        data = PolicyInput(
            sessions=tuple(
                CalendarSession(i, panel.opens_at[i], panel.bars[0][i].completed_at)
                for i in range(start, index + 2)
            ),
            observations=tuple(
                SessionObservation(symbol, i, panel.bars[slot][i], None)
                for slot, symbol in enumerate(STUDY_SYMBOLS[:8])
                for i in range(start, index + 1)
            ),
            universe=membership,
            information_at=information_at,
            calendar_verified=True,
            held_positions=tuple(
                (symbol, "trend")
                for slot, symbol in enumerate(STUDY_SYMBOLS[:8])
                if targets[slot][index - 1] == _ONE
            ),
        )
        trends = tuple(value for value in evaluate_policies(data) if value.family == "trend")
        if len(trends) != 8 or {value.symbol for value in trends} != set(STUDY_SYMBOLS[:8]):
            raise ValueError("all eight actual-policy trend outcomes required")
        by_symbol = {value.symbol: value for value in trends}
        for slot, symbol in enumerate(STUDY_SYMBOLS[:8]):
            value = by_symbol[symbol]
            if (
                not isinstance(value, StrategyProposal)
                or value.information_at != information_at
                or value.execute_not_before != panel.opens_at[index + 1]
            ):
                raise ValueError("unexpected unavailable or misdated trend policy after warmup")
            previous = targets[slot][index - 1]
            targets[slot][index] = (
                _ONE
                if value.decision == "enter"
                else _ZERO
                if value.decision == "exit"
                else previous
            )
    return tuple(tuple(values) for values in targets)


def _trace_digest(trace: PriceTrace) -> str:
    """Bind exact trace rows without materializing another large nested JSON copy."""
    digest = sha256()
    header = (
        "stock-price-trace-digest-v1",
        trace.one_way_cost_bps,
        trace.terminal_policy,
        trace.pending_target,
        trace.arithmetic_precision,
        trace.limitations,
        len(trace.rows),
    )
    digest.update(canonical_json(header).encode())
    digest.update(b"\n")
    for row in trace.rows:
        digest.update(canonical_json(row).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _mean_trace_nav(traces: tuple[PriceTrace, ...]) -> tuple[Decimal, ...]:
    if len(traces) != 8 or not traces[0].rows:
        raise ValueError("exactly eight populated sleeves required")
    return tuple(
        sum((trace.rows[i].nav for trace in traces), _ZERO) / 8 for i in range(len(traces[0].rows))
    )


def _segment(nav: tuple[Decimal, ...], first: int, last: int) -> StudySegment:
    baseline = nav[first - 1]
    peak = max((_ONE, *nav[:first]))
    summary = statistics.summarize_price_path(
        (baseline, *nav[first : last + 1]), inherited_peak=peak
    )
    return StudySegment(first, last, baseline, peak, summary)


def _path(name: str, nav: tuple[Decimal, ...], first: int, cut: int) -> StudyPath:
    return StudyPath(name, nav, _segment(nav, first, cut), _segment(nav, cut + 1, len(nav) - 1))


def _scenario(
    panel: StockStudyPanel,
    targets: tuple[tuple[Decimal, ...], ...],
    round_trip_cost_bps: Decimal,
    first_execution_session: int,
    training_last_session: int,
) -> StockStudyScenario:
    one_way = round_trip_cost_bps / 2
    trends = tuple(
        trace_price_targets(series, panel.opens_at, target, one_way_cost_bps=one_way)
        for series, target in zip(panel.bars[:8], targets, strict=True)
    )
    buy_hold_targets = tuple(
        _ONE if i >= first_execution_session - 1 else _ZERO for i in range(len(panel.opens_at))
    )
    cohort = tuple(
        trace_price_targets(series, panel.opens_at, buy_hold_targets, one_way_cost_bps=one_way)
        for series in panel.bars[:8]
    )
    spy = trace_price_targets(
        panel.bars[8], panel.opens_at, buy_hold_targets, one_way_cost_bps=one_way
    )
    exposure_targets = []
    for i in range(len(panel.opens_at)):
        denominator = sum((trace.rows[i].closing_nav_before_terminal for trace in trends), _ZERO)
        if denominator <= 0:
            raise ValueError("all eight positive sleeve NAVs required for causal control")
        numerator = sum(
            (trace.rows[i].target * trace.rows[i].closing_nav_before_terminal for trace in trends),
            _ZERO,
        )
        exposure_targets.append(numerator / denominator)
    exposure = trace_price_targets(
        panel.bars[8], panel.opens_at, tuple(exposure_targets), one_way_cost_bps=one_way
    )
    cohort_nav = _mean_trace_nav(cohort)
    control_navs = (
        cohort_nav,
        tuple(row.nav for row in spy.rows),
        tuple(Decimal(".9") * nav + Decimal(".1") for nav in cohort_nav),
        tuple(row.nav for row in exposure.rows),
    )
    strategy = _path(
        "trend_50_200", _mean_trace_nav(trends), first_execution_session, training_last_session
    )
    controls = tuple(
        _path(name, nav, first_execution_session, training_last_session)
        for name, nav in zip(CONTROL_NAMES, control_navs, strict=True)
    )
    digest = str(
        content_hash(
            (
                "stock-study-scenario-v1",
                round_trip_cost_bps,
                one_way,
                strategy,
                controls,
                tuple(_trace_digest(value) for value in (*trends, *cohort, spy, exposure)),
                tuple(exposure_targets),
            )
        )
    )
    return StockStudyScenario(
        round_trip_cost_bps,
        one_way,
        trends,
        cohort,
        spy,
        exposure,
        tuple(exposure_targets),
        strategy,
        controls,
        digest,
    )


def _training_sensitivities(
    panel: StockStudyPanel,
    baseline_targets: tuple[tuple[Decimal, ...], ...],
    cut: int,
    first_execution_session: int,
) -> tuple[TrainingSensitivity, ...]:
    prefix = tuple(series[: cut + 1] for series in panel.bars[:8])
    opens = panel.opens_at[: cut + 1]
    membership_index = next(
        i for i in range(len(opens)) if prefix[0][i].completed_at >= panel.membership_use_not_before
    )
    results = []
    for fast in (40, 50, 60):
        for slow in (180, 200, 220):
            targets = tuple(
                tuple(
                    _sma_target(series, i, fast, slow) if i >= membership_index else _ZERO
                    for i in range(len(series))
                )
                for series in prefix
            )
            if (
                (fast, slow) == (50, 200)
                and first_execution_session == 200
                and targets != tuple(values[: cut + 1] for values in baseline_targets)
            ):
                raise ValueError("sensitivity baseline differs from actual50/200policy")
            own_start = max(slow, membership_index + 1)
            scenarios = []
            for round_trip in ROUND_TRIP_COST_BPS:
                one_way = round_trip / 2
                traces = tuple(
                    trace_price_targets(
                        series, opens, target, one_way_cost_bps=one_way, terminal_policy="mark"
                    )
                    for series, target in zip(prefix, targets, strict=True)
                )
                nav = _mean_trace_nav(traces)
                own, common = _segment(nav, own_start, cut), _segment(nav, 220, cut)
                digest = str(
                    content_hash(
                        (
                            "stock-study-training-scenario-v1",
                            round_trip,
                            one_way,
                            tuple(_trace_digest(t) for t in traces),
                            nav,
                            own,
                            common,
                        )
                    )
                )
                scenarios.append(
                    TrainingSensitivityScenario(
                        round_trip, one_way, traces, nav, own, common, digest
                    )
                )
            digest = str(
                content_hash(
                    (
                        "stock-study-training-sensitivity-v1",
                        fast,
                        slow,
                        own_start,
                        targets,
                        tuple(value.evidence_hash for value in scenarios),
                    )
                )
            )
            results.append(
                TrainingSensitivity(fast, slow, own_start, targets, tuple(scenarios), digest)
            )
    return tuple(results)


def run_stock_price_study(
    panel: StockStudyPanel,
    *,
    training_last_session: int,
    first_execution_session: int = 200,
    bootstrap_replicates: int = 5000,
) -> StockPriceStudy:
    """Compose a frozen chronological probe; never access a provider or real account.

    The boundary must leave a20-session primary-block holdout and training through
    common comparison session220. All sensitivity inputs end at the training cut.
    Bootstrap column order is cost-major then the frozen four-control order.
    """
    _validate_run(panel, training_last_session, first_execution_session, bootstrap_replicates)
    try:
        with localcontext(_CONTEXT):
            targets = _baseline_targets(panel, first_execution_session)
            scenarios = tuple(
                _scenario(panel, targets, cost, first_execution_session, training_last_session)
                for cost in ROUND_TRIP_COST_BPS
            )
            sensitivities = _training_sensitivities(
                panel, targets, training_last_session, first_execution_session
            )
            names, columns = [], []
            for scenario in scenarios:
                for control in scenario.controls:
                    names.append(f"roundtrip_{scenario.round_trip_cost_bps}bps:{control.name}")
                    columns.append(
                        tuple(
                            (scenario.strategy.nav[i] / scenario.strategy.nav[i - 1]).ln()
                            - (control.nav[i] / control.nav[i - 1]).ln()
                            for i in range(training_last_session + 1, len(panel.opens_at))
                        )
                    )
            differences = tuple(columns)
            if len(differences) != 16:
                raise ValueError("all16paired cost/reference comparisons required")
            intervals, unavailable = [], []
            for length in (20, 5, 60):
                if length > len(differences[0]):
                    unavailable.append(length)
                    continue
                intervals.append(
                    statistics.paired_block_intervals(
                        differences,
                        block_length=length,
                        replicates=bootstrap_replicates,
                        seed=20261026,
                        family_size=16,
                    )
                )
            panel_hash = panel.evidence_hash
            digest = str(
                content_hash(
                    (
                        "stock-price-study-output-v1",
                        panel_hash,
                        PROTOCOL_HASH,
                        first_execution_session,
                        training_last_session,
                        bootstrap_replicates,
                        targets,
                        tuple(value.evidence_hash for value in scenarios),
                        tuple(value.evidence_hash for value in sensitivities),
                        tuple(names),
                        differences,
                        tuple(value.evidence_hash for value in intervals),
                        tuple(unavailable),
                        _LIMITATIONS,
                    )
                )
            )
            return StockPriceStudy(
                panel_hash,
                PROTOCOL_HASH,
                first_execution_session,
                training_last_session,
                bootstrap_replicates,
                targets,
                scenarios,
                sensitivities,
                tuple(names),
                differences,
                tuple(intervals),
                tuple(unavailable),
                digest,
            )
    except DecimalException as exc:
        raise ValueError("price-only study arithmetic invalid") from exc
