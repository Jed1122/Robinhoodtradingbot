"""Private owned-preparation policy consumer; no account or source authority."""

from trading_bot.config import LoadedConfig
from trading_bot.research.etf_capital_daily_policy import (
    CapitalDailyPolicy,
    CapitalOpeningPolicy,
    _capital_policy_from_facts,
)
from trading_bot.research.etf_capital_prepared import _PreparedCapitalInput
from trading_bot.research.etf_capital_signals import CapitalCandidate


def _capital_prepared_policy(
    *,
    loaded: LoadedConfig,
    prepared: _PreparedCapitalInput,
    day_index: int,
    candidate: CapitalCandidate,
    opening: CapitalOpeningPolicy | None = None,
) -> CapitalDailyPolicy:
    """Only the original-input evaluator may supply this invocation-local value.

    Private dataclasses are not authenticated tokens and cannot qualify data,
    broker execution or an account. The public path still accepts originals.
    """
    try:
        if (
            type(prepared) is not _PreparedCapitalInput
            or prepared.config_hash != loaded.config_hash
            or type(day_index) is not int
            or not 0 <= day_index < len(prepared.days)
            or type(candidate) is not CapitalCandidate
        ):
            raise ValueError("capital_prepared_policy_invalid")
        candidate.__post_init__()
        day = prepared.days[day_index]
        if opening is not None:
            if type(opening) is not CapitalOpeningPolicy:
                raise ValueError("capital_prepared_policy_invalid")
            opening.__post_init__()
            entry_ordinal = prepared.session_dates.index(opening.entry_session)
            if entry_ordinal > day.session_ordinal:
                raise ValueError("capital_prepared_policy_invalid")
            elapsed = day.session_ordinal - entry_ordinal + 1
        else:
            elapsed = 0
        effective = opening.candidate if opening else candidate
        signal = next(s for s in day.signals if s.candidate == effective)
        symbol = opening.symbol if opening else signal.entry_symbol
        return _capital_policy_from_facts(
            loaded=loaded,
            candidate=candidate,
            signal=signal,
            opening=opening,
            elapsed=elapsed,
            history_ready=day.history_ready,
            below_sma200=dict(day.below_sma200).get(symbol) if symbol else None,
            entry_distance=dict(day.stop_distances).get(symbol) if symbol else None,
        )
    except (ValueError, TypeError, AttributeError, StopIteration):
        raise ValueError("capital_prepared_policy_invalid") from None
