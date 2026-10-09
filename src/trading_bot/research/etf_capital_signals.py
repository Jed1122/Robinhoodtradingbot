"""Frozen bounded daily research signals; never brokerage or economic admission."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from itertools import pairwise
from typing import Literal
from zoneinfo import ZoneInfo

from trading_bot.clock import require_utc
from trading_bot.domain import BarInterval, ConfigHash, DataHash
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.etf_capital_features import CapitalFeatureProjection
from trading_bot.market_data.recording import content_hash
from trading_bot.strategies.features import FeaturePipeline
from trading_bot.strategies.momentum import MomentumStrategy
from trading_bot.strategies.protocol import (
    FeatureSnapshot,
    HistoricalSlice,
    StrategyAction,
    StrategyContext,
)

_CONTEXT = Context(prec=64, rounding=ROUND_HALF_EVEN)
_SYMBOLS = ("IEF", "IWM", "QQQ", "SHY", "SPY")
_HOLDS = (2, 5, 10, 20)


@dataclass(frozen=True, slots=True)
class CapitalCandidate:
    family: Literal["momentum", "mean_reversion", "rotation"]
    window: int
    long_window: int
    hold_sessions: int

    def __post_init__(self) -> None:
        valid = (
            (
                self.family == "momentum"
                and (self.window, self.long_window) in ((5, 20), (10, 50), (20, 100))
            )
            or (
                self.family == "mean_reversion" and self.window in (5, 10) and self.long_window == 0
            )
            or (self.family == "rotation" and self.window in (20, 60) and self.long_window == 0)
        )
        if (
            type(self.family) is not str
            or not valid
            or self.hold_sessions not in _HOLDS
            or any(type(v) is not int for v in (self.window, self.long_window, self.hold_sessions))
        ):
            raise ValueError("capital_candidate_invalid")


def capital_candidates() -> tuple[CapitalCandidate, ...]:
    specifications: tuple[
        tuple[Literal["momentum", "mean_reversion", "rotation"], int, int], ...
    ] = (
        ("momentum", 5, 20),
        ("momentum", 10, 50),
        ("momentum", 20, 100),
        ("mean_reversion", 5, 0),
        ("mean_reversion", 10, 0),
        ("rotation", 20, 0),
        ("rotation", 60, 0),
    )
    return tuple(
        CapitalCandidate(family, window, long, hold)
        for family, window, long in specifications
        for hold in _HOLDS
    )


@dataclass(frozen=True, slots=True)
class CapitalSignal:
    candidate: CapitalCandidate
    entry_symbol: str | None
    score: Decimal | None
    eligible_symbols: tuple[str, ...]
    exit_symbols: tuple[str, ...]
    input_hash: str
    source_qualified: Literal[False] = field(default=False, init=False)
    economic_accepted: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    promotion_eligible: Literal[False] = field(default=False, init=False)


def _rsi(closes: tuple[Decimal, ...]) -> Decimal:
    changes = tuple(b - a for a, b in pairwise(closes))
    gain = sum((max(v, Decimal(0)) for v in changes[:2]), Decimal(0)) / 2
    loss = sum((max(-v, Decimal(0)) for v in changes[:2]), Decimal(0)) / 2
    for change in changes[2:]:
        gain = (gain + max(change, Decimal(0))) / 2
        loss = (loss + max(-change, Decimal(0))) / 2
    if not gain and not loss:
        return Decimal(50)
    return Decimal(100) if not loss else Decimal(100) - Decimal(100) / (1 + gain / loss)


def _rotation(projection: CapitalFeatureProjection, window: int) -> Decimal | None:
    bars = projection.feature_bars[-(window + 1) :]
    raw = projection.raw_bars[-(window + 1) :]
    # Eastern session identity is already validated by the projection contract.
    zone = ZoneInfo("America/New_York")
    dates = tuple(bar.ends_at.astimezone(zone).date() for bar in bars)
    by_date = {
        day: (feature, original) for day, feature, original in zip(dates, bars, raw, strict=True)
    }
    cash = Decimal(0)
    for distribution in projection.distributions:
        if dates[0] < distribution.ex_date <= dates[-1]:
            if distribution.ex_date not in by_date:
                raise ValueError("capital_signal_distribution_gap")
            feature, original = by_date[distribution.ex_date]
            cash += distribution.amount_per_share * feature.close / original.close
    total = (bars[-1].close - bars[0].close + cash) / bars[0].close
    closes = tuple(bar.close for bar in projection.feature_bars[-21:])
    returns = tuple(b / a - 1 for a, b in pairwise(closes))
    mean = sum(returns, Decimal(0)) / 20
    volatility = (sum(((v - mean) ** 2 for v in returns), Decimal(0)) / 19).sqrt()
    return total / volatility if total > 0 and volatility > 0 else None


def capital_strategy_signal(
    candidate: CapitalCandidate,
    projections: tuple[CapitalFeatureProjection, ...],
    *,
    config_hash: ConfigHash,
    as_of: datetime,
) -> CapitalSignal:
    if (
        type(candidate) is not CapitalCandidate
        or type(projections) is not tuple
        or len(projections) != 5
    ):
        raise ValueError("capital_signal_invalid")
    candidate.__post_init__()
    as_of = require_utc(as_of)
    _require_sha256_hex(config_hash, "config")
    symbols = []
    for projection in projections:
        if type(projection) is not CapitalFeatureProjection:
            raise ValueError("capital_signal_invalid")
        projection.__post_init__()
        session_dates = tuple(
            bar.ends_at.astimezone(ZoneInfo("America/New_York")).date()
            for bar in projection.raw_bars
        )
        ex_dates = tuple(row.ex_date for row in projection.distributions)
        record_ids = tuple(row.record_hash for row in projection.distributions)
        if (
            any(
                bar.interval != BarInterval.ONE_DAY or bar.ends_at > as_of or bar.interpolated
                for bar in (*projection.raw_bars, *projection.feature_bars)
            )
            or ex_dates != tuple(sorted(set(ex_dates)))
            or len(set(record_ids)) != len(record_ids)
            or session_dates[-1] != projection.as_of_session
            or len(set(session_dates)) != len(session_dates)
            or projection.as_of_session != projections[0].as_of_session
            or projection.raw_bars[-1].ends_at != projections[0].raw_bars[-1].ends_at
            or tuple(bar.ends_at for bar in projection.raw_bars)
            != tuple(bar.ends_at for bar in projections[0].raw_bars)
        ):
            raise ValueError("capital_signal_invalid")
        symbols.append(str(projection.raw_bars[-1].instrument_id))
    if tuple(sorted(symbols)) != _SYMBOLS:
        raise ValueError("capital_signal_invalid")
    identity = content_hash(
        (
            "capital-signals-v1",
            candidate,
            config_hash,
            as_of,
            tuple(
                sorted((str(p.raw_bars[-1].instrument_id), p.projection_hash) for p in projections)
            ),
        )
    )
    if any(len(p.feature_bars) < 200 for p in projections):
        return CapitalSignal(candidate, None, None, (), (), identity)
    scores: list[tuple[Decimal, str]] = []
    exits = []
    with localcontext(_CONTEXT):
        for projection in projections:
            symbol = str(projection.raw_bars[-1].instrument_id)
            bars = projection.feature_bars[-200:]
            closes = tuple(bar.close for bar in bars)
            score = None
            if candidate.family == "momentum":
                vector = FeaturePipeline(
                    short_window=candidate.window, long_window=candidate.long_window
                ).compute(
                    HistoricalSlice(
                        bars[-1].instrument_id,
                        bars[-candidate.long_window :],
                        None,
                        DataHash(identity),
                    ),
                    as_of=as_of,
                )
                decisions = MomentumStrategy(
                    short_window=candidate.window, long_window=candidate.long_window
                ).decide(
                    StrategyContext(
                        as_of,
                        FeatureSnapshot(as_of, (vector,), DataHash(identity)),
                        config_hash,
                        (bars[-1].instrument_id,),
                    ),
                )
                if decisions[0].action == StrategyAction.ENTER_LONG:
                    score = decisions[0].score
            elif candidate.family == "mean_reversion":
                rsi = _rsi(closes)
                if rsi >= 50:
                    exits.append(symbol)
                if rsi < candidate.window and closes[-1] > sum(closes[-200:], Decimal(0)) / 200:
                    score = 100 - rsi
            else:
                score = _rotation(projection, candidate.window)
            if score is not None:
                scores.append((score, symbol))
    # Comparison itself is exact; unary Decimal negation outside the owned
    # context can round nearby scores into a caller-precision-dependent tie.
    scores.sort(key=lambda pair: pair[1])
    winner = max(scores, key=lambda pair: pair[0]) if scores else None
    return CapitalSignal(
        candidate,
        winner[1] if winner else None,
        winner[0] if winner else None,
        tuple(sorted(pair[1] for pair in scores)),
        tuple(sorted(exits)),
        identity,
    )


@dataclass(frozen=True, slots=True)
class CapitalWalkForwardFold:
    train_sessions: tuple[date, ...]
    selection_sessions: tuple[date, ...]
    embargo_sessions: tuple[date, ...]
    test_sessions: tuple[date, ...]
    exit_only_sessions: tuple[date, ...]


def capital_walk_forward_folds(sessions: tuple[date, ...]) -> tuple[CapitalWalkForwardFold, ...]:
    if (
        type(sessions) is not tuple
        or not 1423 <= len(sessions) <= 4000
        or any(type(day) is not date for day in sessions)
        or tuple(sorted(set(sessions))) != sessions
        or sessions[0] < date(2016, 1, 1)
        or sessions[-1] >= date(2024, 1, 1)
    ):
        raise ValueError("capital_folds_invalid")
    result = []
    for i in range(5):
        first = 770 + 126 * i
        result.append(
            CapitalWalkForwardFold(
                sessions[first - 770 : first - 20],
                sessions[first - 770 : first - 40],
                sessions[first - 20 : first],
                sessions[first : first + 126],
                sessions[first + 126 : first + 149],
            )
        )
    return tuple(result)
