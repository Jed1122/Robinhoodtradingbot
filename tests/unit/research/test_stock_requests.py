"""Fictional request plans validate through the real parser without any provider call."""

import importlib
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_bot.config.stock_research import StockResearchSettings
from trading_bot.runtime.stock_capture import parse_stock_capture_plan

NOW = datetime(2026, 10, 21, 18, 45, tzinfo=UTC)
TEN = tuple(f"ALFA{index}" for index in range(10))


def api():
    try:
        return importlib.import_module("trading_bot.research.stock_requests")
    except ModuleNotFoundError:
        pytest.fail("pure stock enrichment planner is missing")


def policy(**changes):
    return StockResearchSettings(market_cap_boundaries_usd=(Decimal("2000000000"),), **changes)


def plan(symbols=TEN, *, as_of=NOW, settings=None):
    result = api().enrichment_requests(symbols=symbols, as_of=as_of, policy=settings or policy())
    assert type(result) is tuple
    # This is schema/semantic validation only. It constructs no transport and calls no provider.
    frozen = parse_stock_capture_plan(list(result))
    assert len(frozen) == len(result)
    assert [{"tool": item.tool, "arguments": item.arguments} for item in frozen] == list(result)
    return result


def test_ten_symbols_produce_exact_complete_25_call_allowlisted_plan():
    result = plan()
    assert len(result) == 25
    assert Counter(item["tool"] for item in result) == {
        "get_equity_fundamentals": 1,
        "get_financials": 2,
        "get_equity_quotes": 1,
        "get_equity_historicals": 1,
        "get_earnings_results": 10,
        "get_sec_filing_index": 10,
    }
    assert all(set(item) == {"tool", "arguments"} for item in result)
    assert result[0] == {
        "tool": "get_equity_fundamentals",
        "arguments": {"symbols": list(TEN), "bounds": "regular"},
    }
    financials = [item["arguments"] for item in result if item["tool"] == "get_financials"]
    assert financials == [
        {"symbols": list(TEN), "period": "annual", "limit": 8},
        {"symbols": list(TEN), "period": "quarterly", "limit": 12},
    ]
    assert [item["arguments"] for item in result if item["tool"] == "get_equity_quotes"] == [
        {"symbols": list(TEN)}
    ]
    assert [item["arguments"] for item in result if item["tool"] == "get_earnings_results"] == [
        {"symbol": symbol} for symbol in TEN
    ]
    # The reviewed SEC index input schema has no limit; do not invent one.
    assert [item["arguments"] for item in result if item["tool"] == "get_sec_filing_index"] == [
        {"symbol": symbol} for symbol in TEN
    ]


def test_twelve_symbols_batch_by_tool_without_dropping_or_reordering_names():
    symbols = tuple(f"ALFA{index}" for index in range(12))
    result = plan(symbols, settings=policy(shortlist_count=20))
    assert len(result) == 31
    for tool, sizes in (
        ("get_equity_fundamentals", [10, 2]),
        ("get_equity_historicals", [10, 2]),
        ("get_equity_quotes", [12]),
    ):
        groups = [item["arguments"]["symbols"] for item in result if item["tool"] == tool]
        assert [len(group) for group in groups] == sizes
        assert tuple(symbol for group in groups for symbol in group) == symbols
    financials = [item["arguments"] for item in result if item["tool"] == "get_financials"]
    assert len(financials) == 2 and all(item["symbols"] == list(symbols) for item in financials)


@pytest.mark.parametrize(
    "as_of,start,end",
    [
        (NOW, "2025-09-16T00:00:00Z", "2026-10-21T00:00:00Z"),
        (datetime(2024, 2, 29, 23, 59, tzinfo=UTC), "2023-01-25T00:00:00Z", "2024-02-29T00:00:00Z"),
        (datetime(2026, 1, 1, tzinfo=UTC), "2024-11-27T00:00:00Z", "2026-01-01T00:00:00Z"),
    ],
)
def test_history_uses_only_past_utc_days_with_explicit_daily_raw_regular_arguments(
    as_of, start, end
):
    result = plan(("ALFA",), as_of=as_of)
    historical = next(
        item["arguments"] for item in result if item["tool"] == "get_equity_historicals"
    )
    assert historical == {
        "symbols": ["ALFA"],
        "start_time": start,
        "end_time": end,
        "interval": "day",
        "bounds": "regular",
        "adjustment_type": "none",
    }
    assert datetime.fromisoformat(end) <= as_of
    assert datetime.fromisoformat(end) - datetime.fromisoformat(start) == timedelta(days=400)


def test_exact_budget_accepts_and_one_less_budget_rejects_entire_plan():
    assert len(plan(settings=policy(max_calls_per_cycle=25))) == 25
    with pytest.raises(ValueError, match=r"^stock_requests_invalid$"):
        plan(settings=policy(max_calls_per_cycle=24))


@pytest.mark.parametrize("count", [13, 20])
def test_policy_shortlist_capacity_does_not_bypass_whole_cycle_call_cap(count):
    symbols = tuple(f"ALFA{index}" for index in range(count))
    with pytest.raises(ValueError, match=r"^stock_requests_invalid$"):
        plan(symbols, settings=policy(shortlist_count=20))


@pytest.mark.parametrize(
    "symbols",
    [
        (),
        ["ALFA"],
        ("ALFA", "ALFA"),
        ("alfa",),
        ("ALFA ",),
        (" ALFA",),
        ("1ALFA",),
        ("ALFA_",),
        ("ALFA+",),
        ("A" * 16,),
        (None,),
        (True,),
        tuple(f"ALFA{index}" for index in range(11)),
    ],
)
def test_noncanonical_duplicate_mutable_or_oversized_symbol_inputs_deny(symbols):
    with pytest.raises(ValueError, match=r"^stock_requests_invalid$"):
        plan(symbols)


@pytest.mark.parametrize(
    "as_of",
    [
        NOW.replace(tzinfo=None),
        NOW.astimezone(timezone(timedelta(hours=-4))),
        datetime(1, 1, 1, tzinfo=UTC),
        None,
    ],
)
def test_naive_non_utc_and_unrepresentable_history_windows_deny(as_of):
    with pytest.raises(ValueError, match=r"^stock_requests_invalid$"):
        plan(("ALFA",), as_of=as_of)


def test_supported_canonical_class_share_symbols_keep_exact_spelling():
    symbols = ("BRK.B", "ABC-A", "ABC/B")
    result = plan(symbols)
    assert result[0]["arguments"]["symbols"] == list(symbols)


def test_each_call_and_each_plan_owns_its_symbol_list_for_runtime_freezing():
    first = plan()
    first[0]["arguments"]["symbols"].append("OTHER")
    assert next(
        item["arguments"]["symbols"] for item in first if item["tool"] == "get_equity_historicals"
    ) == list(TEN)
    assert plan()[0]["arguments"]["symbols"] == list(TEN)


def test_canonical_policy_is_revalidated_instead_of_trusting_bypassed_model_construction():
    unsafe = policy().model_copy(update={"max_calls_per_cycle": 100})
    with pytest.raises(ValueError, match=r"^stock_requests_invalid$"):
        plan(settings=unsafe)
