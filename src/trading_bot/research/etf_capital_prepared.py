"""Private compact daily calculations from owned originals, never admission."""

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import Bar
from trading_bot.market_data.etf_capital_dataset import (
    CapitalResearchDataset,
    capital_dataset_features,
)
from trading_bot.market_data.etf_capital_owned import _own_capital_source
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_daily_policy import _capital_entry_distance
from trading_bot.research.etf_capital_feasibility import _CONTEXT, _config
from trading_bot.research.etf_capital_signals import (
    CapitalSignal,
    _calculate_capital_signal,
    _validate_capital_signal_projections,
    capital_candidates,
)


@dataclass(frozen=True, slots=True)
class _PreparationOnly:
    source_qualified: Literal[False] = field(default=False, init=False)
    cost_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    economic_admitted: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class _PreparedCapitalDay(_PreparationOnly):
    session: date
    as_of: datetime
    session_ordinal: int
    raw_bars: tuple[Bar, ...]
    signals: tuple[CapitalSignal, ...]
    stop_distances: tuple[tuple[str, Decimal | None], ...]
    input_hash: str


@dataclass(frozen=True, slots=True)
class _PreparedCapitalInput(_PreparationOnly):
    source_hash: str
    days: tuple[_PreparedCapitalDay, ...]
    input_hash: str


def _prepare_capital_days(
    dataset: CapitalResearchDataset, *, sessions: tuple[date, ...]
) -> _PreparedCapitalInput:
    """Own original inputs internally; never accept a cached preparation token.

    Full as-of validation/digests precede truncation. A terminal-valid inverse
    split cannot hide invalid old values at a requested intermediate basis.
    """
    try:
        if (
            type(sessions) is not tuple
            or not 0 < len(sessions) <= 4000
            or any(type(day) is not date for day in sessions)
            or sessions != tuple(sorted(set(sessions)))
        ):
            raise ValueError("capital_prepared_input_invalid")
        with localcontext(_CONTEXT):
            owned = _own_capital_source(dataset)
            source = owned.dataset
            loaded = restore_loaded_config(source.canonical_config, source.config_hash)
            multiplier = _config(loaded).equity_strategies.stop_loss_atr_multiplier
            dates = tuple(
                row.session_date
                for row in source.calendar.sessions
                if source.start <= row.session_date < source.end
            )
            ordinals = {day: index for index, day in enumerate(dates)}
            if any(day not in ordinals for day in sessions):
                raise ValueError("capital_prepared_input_invalid")
            result = []
            for day in sessions:
                full = capital_dataset_features(source, as_of_session=day)
                as_of, hashes = _validate_capital_signal_projections(
                    full, source.config_hash, full[0].raw_bars[-1].ends_at
                )
                compact = tuple(
                    replace(p, raw_bars=p.raw_bars[-200:], feature_bars=p.feature_bars[-200:])
                    for p in full
                )
                signals = tuple(
                    _calculate_capital_signal(c, compact, source.config_hash, as_of, hashes)
                    for c in capital_candidates()
                )
                digest_by_symbol = dict(hashes)
                distances = []
                for projection in compact:
                    symbol = str(projection.raw_bars[-1].instrument_id)
                    distance = None
                    if len(projection.feature_bars) >= 200:
                        calculated = _capital_entry_distance(
                            projection,
                            as_of=as_of,
                            multiplier=multiplier,
                            signal_hash=digest_by_symbol[symbol],
                        )
                        distance = calculated if calculated > 0 else None
                    distances.append((symbol, distance))
                stops = tuple(distances)
                raw = tuple(p.raw_bars[-1] for p in compact)
                identity = content_hash(
                    (
                        "capital-prepared-day-v1",
                        owned.source_hash,
                        source.config_hash,
                        day,
                        as_of,
                        ordinals[day],
                        hashes,
                        raw,
                        signals,
                        stops,
                    )
                )
                result.append(
                    _PreparedCapitalDay(day, as_of, ordinals[day], raw, signals, stops, identity)
                )
            days = tuple(result)
            return _PreparedCapitalInput(
                owned.source_hash,
                days,
                content_hash(
                    (
                        "capital-prepared-input-v1",
                        owned.source_hash,
                        tuple(d.input_hash for d in days),
                    )
                ),
            )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise ValueError("capital_prepared_input_invalid") from None
