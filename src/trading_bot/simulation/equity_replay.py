"""Finite value-only equity replay; no live, provider, ledger or promotion composition."""

from dataclasses import replace

from trading_bot.market_data.bundle_models import BundleError
from trading_bot.simulation.equity_replay_cycle import ReplayCycleComposition
from trading_bot.simulation.equity_replay_models import EquityStrategyReplayRequest, checked, deny
from trading_bot.simulation.equity_replay_records import (
    EquityStrategyReplayResult,
    ReplayCycleRecord,
)
from trading_bot.simulation.equity_replay_state import ReplayState


async def replay_equity_strategy(
    request: EquityStrategyReplayRequest,
) -> EquityStrategyReplayResult:
    """Replay declared decisions and configured events without inventing an end liquidation.

    Cancel continuation needs another declared decision: once the entry is terminal, that
    decision recomputes the current policy, position and quote before proposing any exit.
    Missing market/history/accounting contracts raise a sanitized error, not a completed run.
    """
    with checked():
        if type(request) is not EquityStrategyReplayRequest:
            deny()
        request = replace(request)
        state = ReplayState(request)
        composition = ReplayCycleComposition(state)
        times = sorted(
            {
                request.starts_at,
                request.end_at,
                *(e.cursor.occurred_at for e in state.markets),
                *(d.cursor.occurred_at for d in request.decisions),
            }
        )
        index = 0
        cycles: list[ReplayCycleRecord] = []
        while index < len(times) or state.next_order_key() is not None:
            key = state.next_order_key()
            now = min(
                (
                    *(() if index == len(times) else (times[index],)),
                    *(() if key is None else (key[0],)),
                )
            )
            state.drain(now)
            state.observe(now)
            state.cancel_loss_blocked_entries(now)
            state.drain(now)
            if index < len(times) and times[index] == now:
                for decision in request.decisions:
                    if decision.cursor.occurred_at != now:
                        continue
                    try:
                        cycles.append(await composition.run(decision))
                    except BundleError as exc:
                        deny(exc.code)
                    state.drain(now)
                    state.observe(now)
                    state.cancel_loss_blocked_entries(now)
                    state.drain(now)
                index += 1
        state.observe(request.end_at)
        return EquityStrategyReplayResult._from_book(
            request,
            state.book,
            tuple(cycles),
            tuple(state.transitions),
            tuple(state.cancellations),
            state.quotes(request.end_at),
        )


__all__ = ["EquityStrategyReplayResult", "replay_equity_strategy"]
