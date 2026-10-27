"""Refresh priorities from an explicitly supplied current portfolio snapshot.

This adapter does not acquire account data. Its hash identifies the caller's
validated context, without claiming that this process authenticated the account.
"""

from __future__ import annotations

from datetime import datetime

from trading_bot.clock import require_utc
from trading_bot.portfolio.stock_allocation import StockAllocationContext, plan_stock_allocations
from trading_bot.runtime.stock_research_worker import StockResearchWatch


def stock_research_watch_from_portfolio(
    context: StockAllocationContext,
    *,
    now: datetime,
    maximum_symbols: int,
    watch_symbols: tuple[str, ...] = (),
) -> StockResearchWatch:
    """Retain original owner clocks; reject unknown ownership and excess capacity."""
    if type(maximum_symbols) is not int or not 1 <= maximum_symbols <= 20:
        raise ValueError("stock_watch_context_unavailable")
    checked = plan_stock_allocations(context, (), now=require_utc(now))
    if checked.status != "planned":
        raise ValueError("stock_watch_context_unavailable")
    held = tuple(sorted(row.symbol for row in context.exposures if row.origin == "position"))
    original = StockResearchWatch(
        held_symbols=held,
        watch_symbols=watch_symbols,
        as_of=context.as_of,
        expires_at=context.expires_at,
        source_sha256=context.evidence_hash,
    )
    selected = tuple(symbol for symbol in original.watch_symbols if symbol not in held)
    if len(held) + len(selected) > maximum_symbols:
        raise ValueError("stock_watch_capacity_exceeded")
    return StockResearchWatch(
        held_symbols=held,
        watch_symbols=selected,
        as_of=original.as_of,
        expires_at=original.expires_at,
        source_sha256=original.source_sha256,
    )
