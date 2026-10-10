"""Prior-close research policy instructions, never account/risk authority."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Literal, cast
from zoneinfo import ZoneInfo

from trading_bot.config import LoadedConfig
from trading_bot.domain import DataHash, require_bounded_decimal
from trading_bot.market_data.etf_capital_features import CapitalFeatureProjection
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_feasibility import _config
from trading_bot.research.etf_capital_signals import CapitalCandidate, capital_strategy_signal
from trading_bot.strategies.features import FeaturePipeline
from trading_bot.strategies.protocol import HistoricalSlice

_CONTEXT = Context(prec=64, rounding=ROUND_HALF_EVEN)
_ZONE = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class CapitalOpeningPolicy:
    """Declared immutable opening policy; an owner must bind original BUY facts."""

    candidate: CapitalCandidate
    symbol: str
    entry_session: date
    stop_distance: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.candidate) is not CapitalCandidate
            or type(self.symbol) is not str
            or self.symbol not in ("SPY", "QQQ", "IWM", "SHY", "IEF")
            or type(self.entry_session) is not date
        ):
            raise ValueError("capital_daily_policy_invalid")
        self.candidate.__post_init__()
        require_bounded_decimal(self.stop_distance, "original stop distance", positive=True)


@dataclass(frozen=True, slots=True)
class CapitalDailyPolicy:
    candidate: CapitalCandidate
    action: Literal["wait", "entry", "hold", "exit"]
    symbol: str | None
    stop_distance: Decimal | None
    reason: str
    signal_hash: str
    policy_hash: str
    source_qualified: Literal[False] = field(default=False, init=False)
    cost_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    economic_admitted: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


def _capital_entry_distance(
    projection: CapitalFeatureProjection,
    *,
    as_of: datetime,
    multiplier: Decimal,
    signal_hash: str,
) -> Decimal:
    """Shared original100-bar ATR arithmetic; not account/risk permission."""
    bars = projection.feature_bars[-100:]
    with localcontext(_CONTEXT):
        features = FeaturePipeline().compute(
            HistoricalSlice(bars[-1].instrument_id, bars, None, DataHash(signal_hash)),
            as_of=as_of,
        )
        atr = dict(features.values)["average_true_range"]
        if type(atr) is not Decimal:
            raise ValueError("capital_daily_policy_invalid")
        distance = atr * multiplier * projection.raw_bars[-1].close / bars[-1].close
        if distance > 0:
            require_bounded_decimal(distance, "raw stop distance", positive=True)
        return distance


def capital_daily_policy(
    *,
    loaded: LoadedConfig,
    candidate: CapitalCandidate,
    projections: tuple[CapitalFeatureProjection, ...],
    as_of: datetime,
    opening: CapitalOpeningPolicy | None = None,
) -> CapitalDailyPolicy:
    """Recompute original-policy signals; emit no order or risk permission."""
    cfg = _config(loaded)
    if type(candidate) is not CapitalCandidate:
        raise ValueError("capital_daily_policy_invalid")
    candidate.__post_init__()
    if opening is not None:
        if type(opening) is not CapitalOpeningPolicy:
            raise ValueError("capital_daily_policy_invalid")
        opening.__post_init__()
    effective = opening.candidate if opening else candidate
    signal = capital_strategy_signal(
        effective, projections, config_hash=loaded.config_hash, as_of=as_of
    )
    symbol = opening.symbol if opening else signal.entry_symbol
    distance = opening.stop_distance if opening else None
    action: Literal["wait", "entry", "hold", "exit"] = "wait"
    reason = "no_entry_signal"
    elapsed = 0
    target = next((p for p in projections if str(p.raw_bars[-1].instrument_id) == symbol), None)
    if opening:
        if target is None:
            raise ValueError("capital_daily_policy_invalid")
        dates = tuple(b.ends_at.astimezone(_ZONE).date() for b in target.raw_bars)
        if opening.entry_session not in dates:
            raise ValueError("capital_daily_policy_invalid")
        elapsed = sum(day >= opening.entry_session for day in dates)
    with localcontext(_CONTEXT):
        if opening and elapsed >= effective.hold_sessions:
            action, reason = "exit", "maximum_hold"
        elif any(len(p.feature_bars) < 200 for p in projections):
            reason = "insufficient_history"
        elif opening:
            action, reason = "hold", "opening_policy_retained"
            target = cast(CapitalFeatureProjection, target)
            closes = tuple(b.close for b in target.feature_bars[-200:])
            invalidated = (
                (effective.family == "momentum" and symbol not in signal.eligible_symbols)
                or (
                    effective.family == "mean_reversion"
                    and (
                        symbol in signal.exit_symbols or closes[-1] <= sum(closes, Decimal(0)) / 200
                    )
                )
                or (effective.family == "rotation" and signal.entry_symbol != symbol)
            )
            if cfg.equity_strategies.exit_on_regime_change and invalidated:
                action, reason = "exit", "regime_exit"
        elif target is not None:
            distance = _capital_entry_distance(
                target,
                as_of=as_of,
                multiplier=cfg.equity_strategies.stop_loss_atr_multiplier,
                signal_hash=signal.input_hash,
            )
            if distance > 0:
                action, reason = "entry", "prior_close_signal"
            else:
                distance, reason = None, "zero_atr"
    identity = content_hash(
        (
            "capital-daily-policy-v1",
            loaded.config_hash,
            candidate,
            opening,
            signal.input_hash,
            action,
            symbol,
            distance,
            reason,
        )
    )
    return CapitalDailyPolicy(
        effective, action, symbol, distance, reason, signal.input_hash, identity
    )
