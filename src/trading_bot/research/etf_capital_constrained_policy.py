"""Private SPY benchmark instructions, never a fabricated strategy candidate."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from trading_bot.config import LoadedConfig
from trading_bot.domain import require_bounded_decimal
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_prepared import _PreparationOnly, _PreparedCapitalInput


@dataclass(frozen=True, slots=True)
class _CapitalConstrainedOpening:
    symbol: str
    entry_session: date
    stop_distance: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.symbol) is not str
            or self.symbol != "SPY"
            or type(self.entry_session) is not date
        ):
            raise ValueError("capital_constrained_invalid")
        require_bounded_decimal(self.stop_distance, "opening stop distance", positive=True)


@dataclass(frozen=True, slots=True)
class _CapitalConstrainedPolicy(_PreparationOnly):
    action: Literal["wait", "entry", "hold", "exit"]
    symbol: str | None
    stop_distance: Decimal | None
    reason: str
    policy_hash: str


def _capital_constrained_policy(
    *,
    loaded: LoadedConfig,
    prepared: _PreparedCapitalInput,
    day_index: int,
    opening: _CapitalConstrainedOpening | None,
) -> _CapitalConstrainedPolicy:
    if (
        type(prepared) is not _PreparedCapitalInput
        or prepared.config_hash != loaded.config_hash
        or type(day_index) is not int
        or not 0 <= day_index < len(prepared.days)
    ):
        raise ValueError("capital_constrained_invalid")
    day = prepared.days[day_index]
    elapsed = 0
    if opening is not None:
        if type(opening) is not _CapitalConstrainedOpening:
            raise ValueError("capital_constrained_invalid")
        opening.__post_init__()
        entry = prepared.session_dates.index(opening.entry_session)
        if entry > day.session_ordinal:
            raise ValueError("capital_constrained_invalid")
        elapsed = day.session_ordinal - entry + 1
    action: Literal["wait", "entry", "hold", "exit"] = "wait"
    symbol = opening.symbol if opening else None
    distance = opening.stop_distance if opening else None
    reason = "insufficient_history"
    if opening:
        action, reason = (
            ("exit", "maximum_hold") if elapsed >= 20 else ("hold", "constrained_opening_retained")
        )
    elif day.history_ready:
        distance = dict(day.stop_distances)["SPY"]
        if distance is not None:
            action, symbol, reason = "entry", "SPY", "constrained_prior_close"
        else:
            reason = "zero_atr"
    return _CapitalConstrainedPolicy(
        action,
        symbol,
        distance,
        reason,
        content_hash(
            (
                "capital-constrained-spy-policy-v1",
                loaded.config_hash,
                day.input_hash,
                opening,
                20,
                "no_strategy_regime_predicate",
                action,
                symbol,
                distance,
                reason,
            )
        ),
    )
