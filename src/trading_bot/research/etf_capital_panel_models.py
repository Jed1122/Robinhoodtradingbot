"""Immutable compact development records, never saved-outcome authority."""

from collections.abc import Hashable
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache
from types import UnionType
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


def _admit_fields(value: Any) -> None:
    hints = _hints(cast(Hashable, type(value)))
    for item in fields(value):
        current = getattr(value, item.name)
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
        getattr(value, item.name)
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
