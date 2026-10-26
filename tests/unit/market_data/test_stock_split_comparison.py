"""Fictional original MCP content; no provider, file, or credential operations."""

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from decimal import localcontext
from fractions import Fraction

import pytest

from trading_bot.market_data.stock_split_comparison import (
    StockSplitComparisonError,
    StockSplitRequest,
    compare_stock_split_series,
    parse_stock_split_series,
)

START = datetime(2024, 6, 6, tzinfo=UTC)
END = datetime(2024, 6, 12, tzinfo=UTC)
RECEIVED = datetime(2026, 10, 25, 12, tzinfo=UTC)
AS_OF = datetime(2026, 10, 25, 13, tzinfo=UTC)
EVENT = date(2024, 6, 10)
PRICES = ("open_price", "high_price", "low_price", "close_price")


def payload(adjustment="none"):
    before = ("1200", "1220", "1180", "1210", 100)
    if adjustment == "split":
        before = ("120", "122", "118", "121", 1000)
    bars = []
    for stamp, values in (
        ("2024-06-07T00:00:00Z", before),
        ("2024-06-10T00:00:00Z", ("120", "122", "118", "121", 200)),
    ):
        bars.append(
            dict(zip(PRICES, values[:4], strict=True))
            | {"begins_at": stamp, "volume": values[4], "session": "reg"}
        )
    return {
        "data": {
            "results": [{"symbol": "NVDA", "interval": "day", "bounds": "regular", "bars": bars}]
        },
        "guide": "Fictional source text; never instructions.",
    }


def encoded(value):
    return json.dumps(value, separators=(",", ":")).encode()


def request(adjustment="none", **changes):
    return StockSplitRequest("NVDA", START, END, adjustment, **changes)


def series(adjustment="none", *, value=None, raw=None, received_at=RECEIVED, req=None):
    body = raw if raw is not None else encoded(payload(adjustment) if value is None else value)
    return parse_stock_split_series(
        body,
        expected_sha256=hashlib.sha256(body).hexdigest(),
        request=request(adjustment) if req is None else req,
        received_at=received_at,
    )


def compare(raw=None, split=None, **changes):
    return compare_stock_split_series(
        raw=series() if raw is None else raw,
        split=series("split") if split is None else split,
        event_date=EVENT,
        new_shares_per_old_share=Fraction(10),
        as_of=AS_OF,
        **changes,
    )


def test_exact_split_pair_retains_original_bytes_unknown_flags_and_no_promotion():
    raw, split = series(), series("split")
    result = compare(raw, split)
    assert result.status == "sample_consistent"
    assert result.reason_codes == ()
    assert result.pre_event_price_factor == Fraction(1, 10)
    assert result.post_event_price_factor == Fraction(1)
    assert result.pre_event_volume_factor == Fraction(10)
    assert result.post_event_volume_factor == Fraction(1)
    assert result.raw == raw and result.split == split
    assert raw.original_content_json == encoded(payload())
    assert all(bar.interpolated is None for bar in raw.bars + split.bars)
    assert result.available_at == RECEIVED
    assert len(result.evidence_hash) == 64
    for obj in (raw, split, result):
        for flag in (
            "qualified",
            "source_qualified",
            "strategy_qualified",
            "investment_eligible",
            "trading_enabled",
            "live_authorized",
            "is_original_upstream_wire",
        ):
            assert getattr(obj, flag) is False
    assert result.calendar_authenticated is result.issuer_authenticated is False
    with pytest.raises(FrozenInstanceError):
        raw.bars = ()


def test_common_later_adjustment_is_removed_by_exact_event_cross_ratios():
    value = payload("split")
    for row in value["data"]["results"][0]["bars"]:
        row.update(dict(zip(PRICES, ("60", "61", "59", "60.5"), strict=True)))
        row["volume"] *= 2
    result = compare(split=series("split", value=value))
    assert result.status == "sample_consistent"
    assert result.pre_event_price_factor == Fraction(1, 20)
    assert result.post_event_price_factor == Fraction(1, 2)


def test_price_or_volume_prediction_mismatch_is_inconsistent_not_unresolved():
    value = payload("split")
    value["data"]["results"][0]["bars"][0]["volume"] = 900
    result = compare(split=series("split", value=value))
    assert result.status == "sample_inconsistent"
    assert result.reason_codes == ("event_factor_mismatch",)


@pytest.mark.parametrize(
    "kind",
    [
        "empty",
        "missing_results",
        "missing_bars",
        "null_slot",
        "timestamp",
        "varying",
        "one_side",
        "zero",
        "synthetic",
    ],
)
def test_well_formed_incomplete_or_unstable_comparisons_remain_unresolved(kind):
    value = payload("split")
    bars = value["data"]["results"][0]["bars"]
    if kind == "empty":
        bars.clear()
    elif kind == "missing_results":
        value["data"]["results"] = None
    elif kind == "missing_bars":
        value["data"]["results"][0]["bars"] = None
    elif kind == "null_slot":
        bars.insert(1, None)
    elif kind == "timestamp":
        bars[0]["begins_at"] = "2024-06-06T00:00:00Z"
    elif kind == "varying":
        bars[0]["open_price"] = "119"
    elif kind == "one_side":
        bars.pop(0)
    elif kind == "zero":
        bars[0]["volume"] = 0
    else:
        bars[0].update(volume=0, interpolated=True)
    parsed = series("split", value=value)
    result = compare(split=parsed)
    assert result.status == "unresolved" and result.reason_codes
    if kind == "zero":
        assert parsed.bars[0].interpolated is None
        assert result.reason_codes == ("zero_volume",)
    if kind == "null_slot":
        assert parsed.null_bar_count == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("open_price", "0"),
        ("high_price", "100"),
        ("close_price", "NaN"),
        ("low_price", 1180),
        ("volume", -1),
        ("volume", True),
        ("volume", 1.5),
        ("interpolated", None),
        ("interpolated", True),
        ("session", "pre"),
        ("begins_at", "2024-06-07T00:00:00"),
    ],
)
def test_invalid_native_rows_and_positive_volume_synthetic_contradiction_deny(field, value):
    data = payload()
    data["data"]["results"][0]["bars"][0][field] = value
    with pytest.raises(StockSplitComparisonError, match=r"^stock_split_comparison_invalid$"):
        series(value=data)


@pytest.mark.parametrize(
    "kind",
    [
        "hash",
        "extra",
        "duplicate_key",
        "duplicate_time",
        "reverse",
        "symbol",
        "interval",
        "bounds",
        "multiple",
        "not_found_conflict",
    ],
)
def test_corrupt_evidence_scope_and_chronology_fail_closed(kind):
    value = payload()
    item = value["data"]["results"][0]
    if kind == "hash":
        with pytest.raises(StockSplitComparisonError):
            parse_stock_split_series(
                encoded(value), expected_sha256="0" * 64, request=request(), received_at=RECEIVED
            )
        return
    if kind == "duplicate_key":
        body = encoded(value).replace(b'"guide":', b'"guide":"first","guide":')
        with pytest.raises(StockSplitComparisonError):
            series(raw=body)
        return
    if kind == "extra":
        item["currency"] = "USD"
    elif kind == "duplicate_time":
        item["bars"].append(dict(item["bars"][-1]))
    elif kind == "reverse":
        item["bars"].reverse()
    elif kind in {"symbol", "interval", "bounds"}:
        item[kind] = {"symbol": "OTHER", "interval": "week", "bounds": "extended"}[kind]
    elif kind == "multiple":
        value["data"]["results"].append(dict(item))
    else:
        value["data"]["not_found"] = ["NVDA"]
    with pytest.raises(StockSplitComparisonError):
        series(value=value)


def test_not_found_and_unknown_session_are_retained_without_fabricating_evidence():
    missing = series(value={"data": {"results": [], "not_found": ["NVDA"]}, "guide": ""})
    assert missing.not_found is True and missing.bars == ()
    assert compare(raw=missing).status == "unresolved"
    value = payload()
    value["data"]["results"][0]["bars"][0].pop("session")
    assert series(value=value).bars[0].session is None


@pytest.mark.parametrize(
    "kind", ["request", "received", "as_of", "event", "ratio", "flags", "bar", "bytes"]
)
def test_comparison_revalidates_inputs_and_rejects_future_or_changed_evidence(kind):
    raw, split = series(), series("split")
    kwargs = dict(
        raw=raw, split=split, event_date=EVENT, new_shares_per_old_share=Fraction(10), as_of=AS_OF
    )
    if kind == "request":
        object.__setattr__(split.request, "start_time", datetime(2024, 6, 5, tzinfo=UTC))
    elif kind == "received":
        object.__setattr__(split, "received_at", datetime(2027, 1, 1, tzinfo=UTC))
    elif kind == "as_of":
        kwargs["as_of"] = AS_OF.replace(tzinfo=None)
    elif kind == "event":
        kwargs["event_date"] = datetime(2024, 6, 10, tzinfo=UTC)
    elif kind == "ratio":
        kwargs["new_shares_per_old_share"] = 10
    elif kind == "flags":
        object.__setattr__(raw, "source_qualified", 0)
    elif kind == "bar":
        object.__setattr__(raw.bars[0], "close_price", raw.bars[0].open_price)
    else:
        object.__setattr__(raw, "original_content_json", b"{}")
    with pytest.raises(StockSplitComparisonError):
        compare_stock_split_series(**kwargs)


def test_hashes_bind_receipts_requests_event_ratio_and_unchanged_exact_arithmetic():
    result = compare()
    later = series("split", received_at=datetime(2026, 10, 25, 12, 1, tzinfo=UTC))
    assert compare(split=later).evidence_hash != result.evidence_hash
    changed = compare_stock_split_series(
        raw=result.raw,
        split=result.split,
        event_date=EVENT,
        new_shares_per_old_share=Fraction(9),
        as_of=AS_OF,
    )
    assert changed.evidence_hash != result.evidence_hash
    assert changed.status == "sample_inconsistent"
    with localcontext() as context:
        context.prec = 2
        assert compare().evidence_hash == result.evidence_hash
    assert (
        replace(result.raw.request, adjustment_type="split").request_sha256
        != result.raw.request.request_sha256
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "nvda"},
        {"adjustment_type": "all"},
        {"start_time": END},
        {"start_time": START.replace(tzinfo=None)},
    ],
)
def test_request_validation_denies_unsupported_or_ambiguous_scope(changes):
    values = dict(symbol="NVDA", start_time=START, end_time=END, adjustment_type="none") | changes
    with pytest.raises(StockSplitComparisonError):
        StockSplitRequest(**values)


@pytest.mark.parametrize(
    "field,value", [("interval", "day"), ("bounds", "regular"), ("tool", "get_equity_historicals")]
)
def test_mutated_request_literals_cannot_bypass_exact_typed_scope(field, value):
    class UntrustedText(str):
        pass

    raw = series()
    object.__setattr__(raw.request, field, UntrustedText(value))
    with pytest.raises(StockSplitComparisonError):
        compare(raw=raw)


def test_reverse_split_uses_the_callers_exact_share_ratio():
    result = compare_stock_split_series(
        raw=series(value=payload("split")),
        split=series("split", value=payload("none")),
        event_date=EVENT,
        new_shares_per_old_share=Fraction(1, 10),
        as_of=AS_OF,
    )
    assert result.status == "sample_consistent"
    assert result.pre_event_price_factor == Fraction(10)
    assert result.pre_event_volume_factor == Fraction(1, 10)


def test_one_sided_aligned_history_cannot_verify_an_event_factor():
    raw, split = payload(), payload("split")
    raw["data"]["results"][0]["bars"].pop(0)
    split["data"]["results"][0]["bars"].pop(0)
    result = compare(raw=series(value=raw), split=series("split", value=split))
    assert result.status == "unresolved"
    assert result.reason_codes == ("event_sides_missing",)


def test_nonfinite_json_and_equality_equivalent_bar_type_mutation_are_denied():
    with pytest.raises(StockSplitComparisonError):
        series(raw=encoded(payload()).replace(b'"guide":', b'"untrusted":NaN,"guide":'))
    value = payload()
    value["data"]["results"][0]["bars"][0]["volume"] = 1
    raw = series(value=value)
    object.__setattr__(raw.bars[0], "volume", True)
    with pytest.raises(StockSplitComparisonError):
        compare(raw=raw)
