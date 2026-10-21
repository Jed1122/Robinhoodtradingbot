"""Pure bounded individual-stock enrichment requests; no transport or investment authority."""

import re
from datetime import UTC, datetime, time, timedelta

from trading_bot.clock import require_utc
from trading_bot.config.stock_research import StockResearchSettings


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("stock_requests_invalid")


def _batches(symbols: tuple[str, ...], maximum: int) -> tuple[list[str], ...]:
    return tuple(
        list(symbols[index : index + maximum]) for index in range(0, len(symbols), maximum)
    )


def _request(tool: str, arguments: dict[str, object]) -> dict[str, object]:
    return {"tool": tool, "arguments": arguments}


def enrichment_requests(
    *, symbols: tuple[str, ...], as_of: datetime, policy: StockResearchSettings
) -> tuple[dict[str, object], ...]:
    """Build a complete plan or deny; the caller must freeze/validate it before any call."""
    _check(isinstance(policy, StockResearchSettings))
    try:
        # Reuse canonical validation even if a caller used model_copy/model_construct.
        checked_policy = StockResearchSettings.model_validate(policy.model_dump(mode="python"))
        cutoff = require_utc(as_of)
        end = datetime.combine(cutoff.date(), time.min, tzinfo=UTC)
        start = end - timedelta(days=400)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("stock_requests_invalid") from None
    _check(type(symbols) is tuple and 1 <= len(symbols) <= checked_policy.shortlist_count)
    _check(
        all(
            type(symbol) is str and re.fullmatch(r"[A-Z][A-Z0-9.\-/]{0,14}", symbol) is not None
            for symbol in symbols
        )
    )
    _check(len(set(symbols)) == len(symbols))

    requests: list[dict[str, object]] = []
    requests.extend(
        _request("get_equity_fundamentals", {"symbols": group, "bounds": "regular"})
        for group in _batches(symbols, 10)
    )
    for period, limit in (("annual", 8), ("quarterly", 12)):
        requests.extend(
            _request("get_financials", {"symbols": group, "period": period, "limit": limit})
            for group in _batches(symbols, 20)
        )
    requests.extend(
        _request("get_equity_quotes", {"symbols": group}) for group in _batches(symbols, 20)
    )
    requests.extend(
        _request(
            "get_equity_historicals",
            {
                "symbols": group,
                "start_time": start.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "end_time": end.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "interval": "day",
                "bounds": "regular",
                "adjustment_type": "none",
            },
        )
        for group in _batches(symbols, 10)
    )
    requests.extend(_request("get_earnings_results", {"symbol": symbol}) for symbol in symbols)
    # The reviewed SEC index schema has no limit. Do not invent a ten-row argument.
    requests.extend(_request("get_sec_filing_index", {"symbol": symbol}) for symbol in symbols)
    _check(len(requests) <= checked_policy.max_calls_per_cycle)
    return tuple(requests)
