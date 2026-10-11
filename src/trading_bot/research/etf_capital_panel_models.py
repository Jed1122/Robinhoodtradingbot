"""Immutable compact development records, never saved-outcome authority."""

from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache
from types import MappingProxyType, UnionType
from typing import Any, Literal, Union, cast, get_args, get_origin, get_type_hints

from trading_bot.code_identity import CodeIdentity
from trading_bot.domain import require_bounded_decimal
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_economic_window import CapitalEconomicWindow
from trading_bot.research.etf_capital_selection import (
    CapitalTrainingOutcome,
    CapitalTrainingSelection,
)
from trading_bot.research.etf_capital_signals import (
    CapitalCandidate,
    CapitalWalkForwardFold,
)
from trading_bot.research.etf_resampling import EtfBlockRisk, EtfSimultaneousBlockIntervals
from trading_bot.simulation.etf_capital_daily_entry import _Offline

_FLAGS = (
    "source_qualified",
    "cost_qualified",
    "execution_enabled",
    "economic_admitted",
    "evidence_promotable",
)
_ROLES = ("full_spy", "managed_spy", "matched_spy", "cash")
_KEYS = (
    "observed_operating_positive",
    "positive_folds",
    "stress_drawdown",
    "observed_benchmark_excess",
    "conditional_lower_bounds",
    "conditional_loss_probability",
    "independent_opportunities",
    "independent_profit_concentration",
    "net_expectancy_support",
    "adaptive_selection_coverage",
)
_CAPITALS = tuple(map(Decimal, ("100", "250", "500", "1000", "5000", "10000")))
_TAGS: dict[type, str] = {}


def _check(ok: bool) -> None:
    if not ok:
        raise ValueError("capital_economic_panel_invalid")


@lru_cache
def _hints(cls: Hashable) -> dict[str, Any]:
    # Schema metadata only, never source/account/result state.
    return get_type_hints(cast(type, cls))


def _typed(value: Any, expected: Any) -> None:
    """Local record admission; this does not replace the canonical encoder."""
    if hasattr(expected, "__supertype__"):
        expected = expected.__supertype__
    origin, args = get_origin(expected), get_args(expected)
    if origin in (UnionType, Union):
        for option in args:
            try:
                _typed(value, option)
                return
            except ValueError:
                pass
        _check(False)
    elif origin is Literal:
        _check(any(type(value) is type(item) and value == item for item in args))
    elif origin is tuple:
        _check(type(value) is tuple)
        if len(args) == 2 and args[1] is Ellipsis:
            for item in value:
                _typed(item, args[0])
        else:
            _check(len(value) == len(args))
            for item, schema in zip(value, args, strict=True):
                _typed(item, schema)
    else:
        _check(type(value) is expected)
        if expected is Decimal:
            require_bounded_decimal(value, "panel value")
        elif expected is datetime:
            _check(value.tzinfo is UTC)
        elif is_dataclass(value):
            _admit_fields(value)
            if type(value) in _TAGS:
                _check(_identity(value) == _panel_hash(_TAGS[type(value)], *_values(value)))
            elif type(value) is CapitalCandidate or type(value) is CodeIdentity:
                value.__post_init__()


# Closed data-field capability: schema names select only literal attribute reads.
# No original values are cached and no unknown-name reflection fallback exists.
_FIELD_READERS: Mapping[str, Callable[[Any], Any]] = MappingProxyType(
    {
        "account_hash": lambda value: value.account_hash,
        "actions_hash": lambda value: value.actions_hash,
        "actual_tax_usd": lambda value: value.actual_tax_usd,
        "annualized_volatility_pct": lambda value: value.annualized_volatility_pct,
        "available_cash": lambda value: value.available_cash,
        "average_drawdown_pct": lambda value: value.average_drawdown_pct,
        "average_gross_exposure": lambda value: value.average_gross_exposure,
        "average_loss": lambda value: value.average_loss,
        "average_net_exposure": lambda value: value.average_net_exposure,
        "average_win": lambda value: value.average_win,
        "bands": lambda value: value.bands,
        "baseline_nav": lambda value: value.baseline_nav,
        "baseline_session": lambda value: value.baseline_session,
        "block_length": lambda value: value.block_length,
        "cagr_pct": lambda value: value.cagr_pct,
        "calendar_hash": lambda value: value.calendar_hash,
        "calmar": lambda value: value.calmar,
        "candidate": lambda value: value.candidate,
        "capital": lambda value: value.capital,
        "cash": lambda value: value.cash,
        "cash_change": lambda value: value.cash_change,
        "cash_nav": lambda value: value.cash_nav,
        "cash_risks": lambda value: value.cash_risks,
        "code_hash": lambda value: value.code_hash,
        "column_hashes": lambda value: value.column_hashes,
        "columns": lambda value: value.columns,
        "comparisons": lambda value: value.comparisons,
        "complete": lambda value: value.complete,
        "completed_episode_pnl": lambda value: value.completed_episode_pnl,
        "config_hash": lambda value: value.config_hash,
        "cost_hash": lambda value: value.cost_hash,
        "cost_qualified": lambda value: value.cost_qualified,
        "criteria": lambda value: value.criteria,
        "criteria_hash": lambda value: value.criteria_hash,
        "decisions": lambda value: value.decisions,
        "dirty": lambda value: value.dirty,
        "distribution_receivable": lambda value: value.distribution_receivable,
        "distributions_paid": lambda value: value.distributions_paid,
        "economic_admitted": lambda value: value.economic_admitted,
        "embargo_sessions": lambda value: value.embargo_sessions,
        "event_count": lambda value: value.event_count,
        "evidence_hashes": lambda value: value.evidence_hashes,
        "evidence_promotable": lambda value: value.evidence_promotable,
        "excluded": lambda value: value.excluded,
        "execution_enabled": lambda value: value.execution_enabled,
        "exit_only_sessions": lambda value: value.exit_only_sessions,
        "expectancy": lambda value: value.expectancy,
        "exposures": lambda value: value.exposures,
        "family": lambda value: value.family,
        "fees": lambda value: value.fees,
        "fees_paid": lambda value: value.fees_paid,
        "final": lambda value: value.final,
        "final_account_hash": lambda value: value.final_account_hash,
        "final_risk_hash": lambda value: value.final_risk_hash,
        "fold": lambda value: value.fold,
        "folds": lambda value: value.folds,
        "friction_pct": lambda value: value.friction_pct,
        "full_spy": lambda value: value.full_spy,
        "git_commit": lambda value: value.git_commit,
        "hold_sessions": lambda value: value.hold_sessions,
        "image_digest": lambda value: value.image_digest,
        "implementation": lambda value: value.implementation,
        "independent_opportunities": lambda value: value.independent_opportunities,
        "initial_cash": lambda value: value.initial_cash,
        "input_hash": lambda value: value.input_hash,
        "interval": lambda value: value.interval,
        "intervals": lambda value: value.intervals,
        "kernel_hash": lambda value: value.kernel_hash,
        "key": lambda value: value.key,
        "kind": lambda value: value.kind,
        "labels": lambda value: value.labels,
        "last_outcome_at": lambda value: value.last_outcome_at,
        "limitations": lambda value: value.limitations,
        "long_window": lambda value: value.long_window,
        "longest_losing_streak": lambda value: value.longest_losing_streak,
        "loss_probability": lambda value: value.loss_probability,
        "loss_samples": lambda value: value.loss_samples,
        "lower": lambda value: value.lower,
        "managed_spy": lambda value: value.managed_spy,
        "managed_spy_final": lambda value: value.managed_spy_final,
        "marked_equity": lambda value: value.marked_equity,
        "marked_nav": lambda value: value.marked_nav,
        "marked_operating_profit": lambda value: value.marked_operating_profit,
        "marked_pnl": lambda value: value.marked_pnl,
        "matched_spy": lambda value: value.matched_spy,
        "maximum_drawdown_duration": lambda value: value.maximum_drawdown_duration,
        "maximum_drawdown_pct": lambda value: value.maximum_drawdown_pct,
        "mean_exposure": lambda value: value.mean_exposure,
        "median_trade": lambda value: value.median_trade,
        "net_nav": lambda value: value.net_nav,
        "net_pnl": lambda value: value.net_pnl,
        "non_promotable": lambda value: value.non_promotable,
        "nonpositive_probability": lambda value: value.nonpositive_probability,
        "nonpositive_samples": lambda value: value.nonpositive_samples,
        "observations": lambda value: value.observations,
        "operating": lambda value: value.operating,
        "operating_metrics": lambda value: value.operating_metrics,
        "operating_prior_nav_returns": lambda value: value.operating_prior_nav_returns,
        "operating_profit": lambda value: value.operating_profit,
        "outcome": lambda value: value.outcome,
        "panel_hash": lambda value: value.panel_hash,
        "path_index": lambda value: value.path_index,
        "paths": lambda value: value.paths,
        "payoff_ratio": lambda value: value.payoff_ratio,
        "point_count": lambda value: value.point_count,
        "preparation_hash": lambda value: value.preparation_hash,
        "profit_factor": lambda value: value.profit_factor,
        "protocol_hash": lambda value: value.protocol_hash,
        "quantity": lambda value: value.quantity,
        "radius": lambda value: value.radius,
        "raw_quantities": lambda value: value.raw_quantities,
        "reason": lambda value: value.reason,
        "reasons": lambda value: value.reasons,
        "recurring_cost": lambda value: value.recurring_cost,
        "reference_hash": lambda value: value.reference_hash,
        "residual_quantity": lambda value: value.residual_quantity,
        "risk_hash": lambda value: value.risk_hash,
        "role": lambda value: value.role,
        "roundtrip_friction_pct": lambda value: value.roundtrip_friction_pct,
        "samples": lambda value: value.samples,
        "scenarios": lambda value: value.scenarios,
        "selected": lambda value: value.selected,
        "selected_net_pnl": lambda value: value.selected_net_pnl,
        "selection": lambda value: value.selection,
        "selection_at": lambda value: value.selection_at,
        "selection_hash": lambda value: value.selection_hash,
        "selection_sessions": lambda value: value.selection_sessions,
        "session_dates": lambda value: value.session_dates,
        "sharpe": lambda value: value.sharpe,
        "slippage_cost": lambda value: value.slippage_cost,
        "sortino": lambda value: value.sortino,
        "source_hash": lambda value: value.source_hash,
        "source_qualified": lambda value: value.source_qualified,
        "spread_cost": lambda value: value.spread_cost,
        "statistics_hash": lambda value: value.statistics_hash,
        "status": lambda value: value.status,
        "sunk_research_cost": lambda value: value.sunk_research_cost,
        "tail_cash_change": lambda value: value.tail_cash_change,
        "tail_fee_change": lambda value: value.tail_fee_change,
        "tail_loss": lambda value: value.tail_loss,
        "tail_sessions": lambda value: value.tail_sessions,
        "terms_hash": lambda value: value.terms_hash,
        "test_sessions": lambda value: value.test_sessions,
        "threshold": lambda value: value.threshold,
        "time_in_market_pct": lambda value: value.time_in_market_pct,
        "total_return_pct": lambda value: value.total_return_pct,
        "trading": lambda value: value.trading,
        "trading_metrics": lambda value: value.trading_metrics,
        "trading_pnl": lambda value: value.trading_pnl,
        "trading_prior_nav_returns": lambda value: value.trading_prior_nav_returns,
        "train_sessions": lambda value: value.train_sessions,
        "training": lambda value: value.training,
        "training_cutoff": lambda value: value.training_cutoff,
        "trajectory_hash": lambda value: value.trajectory_hash,
        "turnover": lambda value: value.turnover,
        "turnover_notional": lambda value: value.turnover_notional,
        "unsettled_proceeds": lambda value: value.unsettled_proceeds,
        "unused_sessions": lambda value: value.unused_sessions,
        "upper": lambda value: value.upper,
        "used_sessions": lambda value: value.used_sessions,
        "value": lambda value: value.value,
        "verdict": lambda value: value.verdict,
        "walker_hash": lambda value: value.walker_hash,
        "win_rate_pct": lambda value: value.win_rate_pct,
        "window": lambda value: value.window,
    }
)


def _field_value(value: Any, name: str) -> Any:
    _check(type(name) is str and name in _FIELD_READERS)
    return _FIELD_READERS[name](value)


def _false_flags(value: Any) -> bool:
    return all(
        flag is False
        for flag in (
            value.source_qualified,
            value.cost_qualified,
            value.execution_enabled,
            value.economic_admitted,
            value.evidence_promotable,
        )
    )


def _admit_fields(value: Any) -> None:
    hints = _hints(cast(Hashable, type(value)))
    for item in fields(value):
        current = _field_value(value, item.name)
        _typed(current, hints[item.name])
        if item.name.endswith("_hash") and type(current) is str:
            _require_sha256_hex(current, "panel identity")
        if item.name in ("column_hashes", "evidence_hashes"):
            for identity in current:
                _require_sha256_hex(identity, "panel identities")
        if item.name in _FLAGS:
            _check(current is False)


def _values(value: Any) -> tuple[object, ...]:
    return tuple(
        _field_value(value, item.name)
        for item in fields(value)
        if item.name not in (*_FLAGS, "input_hash")
    )


def _identity(value: Any) -> str:
    return cast(str, value.input_hash)


def _panel_hash(name: str, *values: object) -> str:
    return content_hash(("capital-panel-" + name + "-v1", *values, (False,) * 5))


@dataclass(frozen=True, slots=True)
class _PanelRecord(_Offline):
    def __post_init__(self) -> None:
        try:
            _check(type(self) in _TAGS)
            _admit_fields(self)
            _check(_identity(self) == _panel_hash(_TAGS[type(self)], *_values(self)))
            if type(self) is CapitalPanelTraining:
                _check(self.candidate == self.outcome.candidate)
                _check(self.trajectory_hash == self.outcome.input_hash)
                _check(self.outcome.complete == (self.outcome.net_pnl is not None))
                _check(self.outcome.roundtrip_friction_pct == Decimal(".40"))
                _check(self.point_count == 750 and self.event_count >= 0)
            elif type(self) is CapitalPanelCriterion:
                _check(self.key in _KEYS)
                _check((self.status == "unknown") == (self.value is None))
                for identity in self.evidence_hashes:
                    _require_sha256_hex(identity, "criterion evidence")
            elif type(self) is CapitalPanelDecision:
                _check(self.capital in _CAPITALS and 0 <= self.path_index <= 28)
                _check(tuple(c.key for c in self.criteria) == _KEYS)
                failed = any(c.status == "fails_declared_screen" for c in self.criteria)
                _check(self.verdict == ("REJECT" if failed else "INSUFFICIENT_EVIDENCE"))
        except (ValueError, TypeError, AttributeError, ArithmeticError, KeyError):
            raise ValueError("capital_economic_panel_invalid") from None


@dataclass(frozen=True, slots=True)
class CapitalPanelTraining(_PanelRecord):
    candidate: CapitalCandidate
    outcome: CapitalTrainingOutcome
    trajectory_hash: str
    final_account_hash: str
    final_risk_hash: str
    point_count: int
    event_count: int
    input_hash: str


@dataclass(frozen=True, slots=True)
class CapitalPanelFold(_PanelRecord):
    fold: CapitalWalkForwardFold
    training_cutoff: datetime
    selection_at: datetime
    training: tuple[CapitalPanelTraining, ...]
    selection: CapitalTrainingSelection
    input_hash: str


@dataclass(frozen=True, slots=True)
class CapitalPanelFinal(_PanelRecord):
    trajectory_hash: str
    account_hash: str
    risk_hash: str
    complete: bool
    cash: Decimal
    available_cash: Decimal
    quantity: Decimal
    unsettled_proceeds: Decimal
    distribution_receivable: Decimal
    fees: Decimal
    marked_equity: Decimal
    trading_pnl: Decimal | None
    tail_cash_change: Decimal
    tail_fee_change: Decimal
    reasons: tuple[str, ...]
    input_hash: str


@dataclass(frozen=True, slots=True)
class CapitalPanelMathematical(_PanelRecord):
    reference_hash: str
    kernel_hash: str
    baseline_nav: Decimal
    marked_nav: tuple[Decimal, ...]
    raw_quantities: tuple[Decimal, ...]
    mean_exposure: Decimal | None
    exposures: tuple[Decimal, ...] | None
    limitations: tuple[str, ...]
    input_hash: str


@dataclass(frozen=True, slots=True)
class CapitalPanelPath(_PanelRecord):
    path_index: int
    candidate: CapitalCandidate | None
    trajectory_hash: str
    window: CapitalEconomicWindow
    final: CapitalPanelFinal
    matched_spy: CapitalPanelMathematical
    input_hash: str


@dataclass(frozen=True, slots=True)
class CapitalPanelScenario(_PanelRecord):
    capital: Decimal
    friction_pct: Decimal
    walker_hash: str
    folds: tuple[CapitalPanelFold, ...]
    paths: tuple[CapitalPanelPath, ...]
    full_spy: CapitalPanelMathematical
    managed_spy: CapitalEconomicWindow
    managed_spy_final: CapitalPanelFinal
    cash_nav: tuple[Decimal, ...]
    input_hash: str


@dataclass(frozen=True, slots=True)
class CapitalPanelLabel:
    capital: Decimal
    friction_pct: Decimal
    path_index: int
    role: Literal["full_spy", "managed_spy", "matched_spy", "cash"]

    def __post_init__(self) -> None:
        try:
            _check(type(self) is CapitalPanelLabel)
            _admit_fields(self)
            _check(self.capital in _CAPITALS and 0 <= self.path_index <= 28)
            _check(self.friction_pct in tuple(map(Decimal, (".05", ".10", ".20", ".40"))))
        except (ValueError, TypeError, AttributeError, ArithmeticError):
            raise ValueError("capital_economic_panel_invalid") from None


@dataclass(frozen=True, slots=True)
class CapitalPanelFamily(_PanelRecord):
    kind: Literal["trading", "operating"]
    session_dates: tuple[date, ...]
    labels: tuple[CapitalPanelLabel, ...]
    columns: tuple[tuple[Decimal, ...], ...]
    column_hashes: tuple[str, ...]
    bands: tuple[EtfSimultaneousBlockIntervals, ...]
    input_hash: str


@dataclass(frozen=True, slots=True)
class CapitalPanelCriterion(_PanelRecord):
    key: str
    status: Literal["passes_declared_screen", "fails_declared_screen", "unknown"]
    value: Decimal | None
    threshold: Decimal | None
    reason: str
    evidence_hashes: tuple[str, ...]
    input_hash: str


@dataclass(frozen=True, slots=True)
class CapitalPanelDecision(_PanelRecord):
    capital: Decimal
    path_index: int
    criteria: tuple[CapitalPanelCriterion, ...]
    verdict: Literal["REJECT", "INSUFFICIENT_EVIDENCE"]
    input_hash: str


@dataclass(frozen=True, slots=True)
class CapitalEconomicPanelReport(_PanelRecord):
    implementation: CodeIdentity
    source_hash: str
    config_hash: str
    preparation_hash: str
    calendar_hash: str
    actions_hash: str
    terms_hash: str
    cost_hash: str
    protocol_hash: str
    selection_hash: str
    statistics_hash: str
    criteria_hash: str
    used_sessions: tuple[date, ...]
    unused_sessions: tuple[date, ...]
    baseline_session: date
    test_sessions: tuple[date, ...]
    tail_sessions: tuple[date, ...]
    scenarios: tuple[CapitalPanelScenario, ...]
    trading: CapitalPanelFamily
    operating: CapitalPanelFamily | None
    cash_risks: tuple[tuple[EtfBlockRisk, ...], ...] | None
    decisions: tuple[CapitalPanelDecision, ...]
    limitations: tuple[str, ...]
    input_hash: str


_TAGS.update(
    {
        CapitalPanelTraining: "training",
        CapitalPanelFold: "fold",
        CapitalPanelFinal: "final",
        CapitalPanelMathematical: "mathematical",
        CapitalPanelPath: "path",
        CapitalPanelScenario: "scenario",
        CapitalPanelFamily: "family",
        CapitalPanelCriterion: "criterion",
        CapitalPanelDecision: "decision",
        CapitalEconomicPanelReport: "report",
    }
)
