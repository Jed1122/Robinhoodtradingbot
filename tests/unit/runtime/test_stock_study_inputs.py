"""Fictional source receipts; never a market data or brokerage call."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.runtime.stock_study_inputs import load_stock_study_inputs

SYMBOLS = ("AXP", "AAPL", "BAC", "CVX", "KO", "KHC", "MCO", "OXY", "SPY")


def encoded(value):
    return (json.dumps(value, sort_keys=True) + "\n").encode()


def fixture(tmp_path):
    days = []
    day = datetime(2024, 1, 2, tzinfo=UTC)
    while len(days) < 221:
        if day.weekday() < 5:
            days.append(day.date().isoformat())
        day += timedelta(days=1)
    source = tmp_path / "inputs"
    source.mkdir()
    files = {}

    def save(name, value):
        raw = encoded(value)
        (source / name).write_bytes(raw)
        ref = {"file": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        files[name] = {k: ref[k] for k in ("bytes", "sha256")}
        return ref

    def receipt(request, native, wrapped=False):
        text = json.dumps(native)
        return {
            "request": request,
            "started_at": "2026-10-26T01:00:00Z",
            "received_at": "2026-10-26T01:01:00Z",
            "result": {
                "isError": False,
                "content": [{"type": "text", "text": text}],
                "structuredContent": {"result": text} if wrapped else native,
            },
        }

    cal_native = {
        "request": {"start_date": days[0], "end_date": days[-1]},
        "calendar": [{"date": d, "open": d + "T09:30:00", "close": d + "T16:00:00"} for d in days],
    }
    cal = save(
        "calendar.json",
        receipt(
            {"tool": "mcp__codex_apps__alpaca_get_calendar", "args": cal_native["request"]},
            cal_native,
            True,
        ),
    )
    cal["content_text_utf8_sha256"] = hashlib.sha256(json.dumps(cal_native).encode()).hexdigest()
    cal["explicit_interpretation_timezone"] = "America/New_York"
    cal["sessions"] = len(days)
    frame = save("frame.json", {"membership_use_not_before": "2024-02-15"})
    symbols = []
    for symbol in SYMBOLS:
        refs = []
        for adjustment in ("none", "split"):
            args = {
                "symbols": [symbol],
                "start_time": days[0] + "T00:00:00Z",
                "end_time": (datetime.fromisoformat(days[-1]) + timedelta(days=1))
                .date()
                .isoformat()
                + "T00:00:00Z",
                "interval": "day",
                "bounds": "regular",
                "adjustment_type": adjustment,
            }
            native = {
                "data": {
                    "results": [
                        {
                            "symbol": symbol,
                            "interval": "day",
                            "bounds": "regular",
                            "bars": [
                                {
                                    "begins_at": d + "T00:00:00Z",
                                    "open_price": "100",
                                    "close_price": "101",
                                    "high_price": "102",
                                    "low_price": "99",
                                    "volume": 100,
                                    "session": "reg",
                                }
                                for d in days
                            ],
                        }
                    ]
                },
                "guide": "Fictional data",
            }
            ref = save(
                symbol.lower() + "-" + adjustment + ".json",
                receipt({"tool": "mcp__robinhood_2__get_equity_historicals", "args": args}, native),
            )
            ref["content_text_utf8_sha256"] = hashlib.sha256(
                json.dumps(native).encode()
            ).hexdigest()
            refs.append(ref)
        symbols.append({"symbol": symbol, "original_receipts": refs})
    manifest = {
        "schema_version": 1,
        "kind": "primary_common_nine_original_input_handoff",
        "qualified": False,
        "source_qualified": False,
        "investment_eligible": False,
        "live_enabled": False,
        "all_original_input_bindings": files,
        "calendar": cal,
        "primary_frame": frame,
        "symbols": symbols,
        "as_of": "2026-10-26T01:02:00Z",
    }
    path = tmp_path / "manifest.json"
    path.write_bytes(encoded(manifest))
    return source, path, manifest


def load(source, path):
    return load_stock_study_inputs(
        source, path, expected_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest()
    )


def test_original_receipts_bound_without_backdating_currency_or_eligibility(tmp_path):
    source, path, _ = fixture(tmp_path)
    value = load(source, path)
    assert len(value.bars) == 9 and all(len(rows) == 221 for rows in value.bars)
    assert value.bars[0][0].completed_at == datetime(2024, 1, 2, 21, tzinfo=UTC)
    assert value.membership_use_not_before == datetime(2024, 2, 15, tzinfo=UTC)
    assert value.source_available_at == datetime(2026, 10, 26, 1, 1, tzinfo=UTC)
    assert value.quote_currency is None
    assert value.qualified is value.live_authorized is value.investment_eligible is False
    assert len(value.evidence_hash) == 64


@pytest.mark.parametrize(
    "mutation",
    [
        "tamper",
        "missing",
        "symlink",
        "manifest_hash",
        "path_escape",
        "duplicate_symbol",
        "missing_symbol",
        "clock",
        "tool",
        "future",
        "raw_split",
        "receipt_before_close",
    ],
)
def test_changed_ambiguous_or_unsafe_input_fails_closed(tmp_path, mutation):
    source, path, manifest = fixture(tmp_path)
    native_path = source / "axp-split.json"
    if mutation == "tamper":
        native_path.write_bytes(native_path.read_bytes() + b" ")
    elif mutation == "missing":
        native_path.unlink()
    elif mutation == "symlink":
        saved = native_path.read_bytes()
        native_path.unlink()
        (tmp_path / "other.json").write_bytes(saved)
        native_path.symlink_to(tmp_path / "other.json")
    elif mutation == "manifest_hash":
        with pytest.raises(ValueError):
            load_stock_study_inputs(source, path, expected_manifest_sha256="0" * 64)
        return
    elif mutation == "path_escape":
        manifest["all_original_input_bindings"]["../outside.json"] = {
            "bytes": 1,
            "sha256": "0" * 64,
        }
    elif mutation in {"duplicate_symbol", "missing_symbol"}:
        manifest["symbols"][-1:] = manifest["symbols"][:1] if mutation == "duplicate_symbol" else []
    else:
        receipt = json.loads(native_path.read_bytes())
        if mutation == "clock":
            receipt["received_at"] = "2023-01-01T00:00:00Z"
        elif mutation == "tool":
            receipt["request"]["tool"] = "unofficial"
        elif mutation == "future":
            manifest["as_of"] = "2024-01-01T00:00:00Z"
        elif mutation == "receipt_before_close":
            stamp = receipt["result"]["structuredContent"]["data"]["results"][0]["bars"][-1][
                "begins_at"
            ][:10]
            receipt["started_at"] = stamp + "T00:00:00Z"
            receipt["received_at"] = stamp + "T00:01:00Z"
        else:
            payload = receipt["result"]["structuredContent"]
            payload["data"]["results"][0]["bars"][0]["close_price"] = "100"
            receipt["result"]["content"][0]["text"] = json.dumps(payload)
            manifest["symbols"][0]["original_receipts"][1]["content_text_utf8_sha256"] = (
                hashlib.sha256(json.dumps(payload).encode()).hexdigest()
            )
        native_path.write_bytes(encoded(receipt))
        ref = {
            "bytes": native_path.stat().st_size,
            "sha256": hashlib.sha256(native_path.read_bytes()).hexdigest(),
        }
        manifest["all_original_input_bindings"][native_path.name] = ref
        manifest["symbols"][0]["original_receipts"][1].update(ref)
    path.write_bytes(encoded(manifest))
    with pytest.raises(ValueError):
        load(source, path)
