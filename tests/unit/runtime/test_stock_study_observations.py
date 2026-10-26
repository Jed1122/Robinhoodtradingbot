"""Reuse fictional originals, retaining native observations without computing outcomes."""

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, time
from decimal import Decimal

import pytest

from tests.unit.runtime.test_stock_study_inputs import SYMBOLS, encoded, fixture, load
from trading_bot.market_data.recording import canonical_json
from trading_bot.runtime import stock_study_inputs as runtime


def observations(source, path, *, expected=None):
    return runtime.load_stock_study_observations(
        source,
        path,
        expected_manifest_sha256=expected or hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def references(manifest, name):
    return [
        ref
        for ref in (
            manifest["primary_frame"],
            manifest["calendar"],
            *(ref for symbol in manifest["symbols"] for ref in symbol["original_receipts"]),
        )
        if ref["file"] == name
    ]


def write_original(source, path, manifest, name, value, *, native=False):
    """Explicitly repin a fictional whole original, optionally its native text."""
    if native:
        payload = value["result"]["structuredContent"]
        text = payload["result"] if name == "calendar.json" else json.dumps(payload)
        value["result"]["content"][0]["text"] = text
        for ref in references(manifest, name):
            ref["content_text_utf8_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    raw = encoded(value)
    (source / name).write_bytes(raw)
    pin = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    manifest["all_original_input_bindings"][name] = pin
    for ref in references(manifest, name):
        ref.update(pin)
    path.write_bytes(encoded(manifest))


def alter_bars(source, path, manifest, *, symbol="AXP", adjustments=("none", "split"), **fields):
    for adjustment in adjustments:
        name = symbol.lower() + "-" + adjustment + ".json"
        value = json.loads((source / name).read_bytes())
        value["result"]["structuredContent"]["data"]["results"][0]["bars"][0].update(fields)
        write_original(source, path, manifest, name, value, native=True)


def test_all_nine_native_volume_ohlc_and_calendar_align_with_legacy_prices(tmp_path):
    source, path, _ = fixture(tmp_path)
    value = observations(source, path)
    assert isinstance(value, runtime.StockStudyObservations)
    assert value.prices == load(source, path)
    assert len(value.raw_series) == len(value.split_series) == 9
    assert len(value.calendar.sessions) == len(value.prices.opens_at) == 221
    for symbol, raw, split, prices in zip(
        SYMBOLS, value.raw_series, value.split_series, value.prices.bars, strict=True
    ):
        assert raw.request.symbol == split.request.symbol == symbol
        assert raw.request.adjustment_type == "none" and split.request.adjustment_type == "split"
        assert raw.bars == split.bars and len(raw.bars) == len(prices) == 221
        assert raw.request.request_sha256 != split.request.request_sha256
        for index, (native, price, session) in enumerate(
            zip(split.bars, prices, value.calendar.sessions, strict=True)
        ):
            assert native.source_index == index
            assert native.begins_at == datetime.combine(session.session_date, time(), UTC)
            assert native.open_price == price.open == Decimal(100)
            assert native.close_price == price.close == Decimal(101)
            assert native.high_price == Decimal(102) and native.low_price == Decimal(99)
            assert native.volume == 100 and native.interpolated is None and native.session == "reg"
            assert price.completed_at == session.closes_at
            assert value.prices.opens_at[index] == session.opens_at


def test_native_bytes_receipts_requests_and_twenty_original_hashes_are_retained(tmp_path):
    source, path, manifest = fixture(tmp_path)
    value = observations(source, path)
    assert len(value.prices.original_input_sha256s) == 20
    assert (
        value.calendar.original_content_json
        == json.loads((source / "calendar.json").read_bytes())["result"]["content"][0][
            "text"
        ].encode()
    )
    assert (
        value.calendar.content_sha256
        == hashlib.sha256(value.calendar.original_content_json).hexdigest()
    )
    assert value.calendar.received_at == datetime(2026, 10, 26, 1, 1, tzinfo=UTC)
    for index, pair in enumerate(zip(value.raw_series, value.split_series, strict=True)):
        for series, ref in zip(pair, manifest["symbols"][index]["original_receipts"], strict=True):
            receipt = json.loads((source / ref["file"]).read_bytes())
            assert series.original_content_json == receipt["result"]["content"][0]["text"].encode()
            assert series.content_sha256 == hashlib.sha256(series.original_content_json).hexdigest()
            assert series.received_at == datetime(2026, 10, 26, 1, 1, tzinfo=UTC)
            assert len(series.request.request_sha256) == 64
            assert (
                dict(value.prices.original_input_sha256s)[ref["file"]]
                == hashlib.sha256((source / ref["file"]).read_bytes()).hexdigest()
            )


def test_legacy_3fc413b_fictional_fixture_remains_byte_exact(tmp_path):
    source, path, _ = fixture(tmp_path)
    legacy = load(source, path)
    assert (
        legacy.evidence_hash == "dc224278b7c54851b1c2cbff32bcf8312d3dc099dcc76ec8daed3ab28c5f05ed"
    )
    assert (
        hashlib.sha256(canonical_json(legacy).encode()).hexdigest()
        == "d7b7a8a4eadd6cb0a09077d2dc5f0fdf801a07245e2e1cf0296e3680cf450e5d"
    )
    assert observations(source, path).prices == legacy


def test_observations_have_a_distinct_stable_hash_and_no_authority(tmp_path):
    source, path, _ = fixture(tmp_path)
    value = observations(source, path)
    assert value.evidence_hash != value.prices.evidence_hash
    assert value.evidence_hash == observations(source, path).evidence_hash
    assert value.quote_currency is value.prices.quote_currency is None
    assert value.qualified is value.source_qualified is value.strategy_qualified is False
    assert value.investment_eligible is value.trading_enabled is value.live_authorized is False
    assert value.authenticated is False
    assert not hasattr(value, "signals") and not hasattr(value, "risk_approved")
    with pytest.raises(FrozenInstanceError):
        value.prices = None
    with pytest.raises((ValueError, TypeError)):
        replace(value, qualified=True)


@pytest.mark.parametrize("interpolated", (None, False))
def test_native_unknown_and_false_interpolation_stay_distinct(tmp_path, interpolated):
    source, path, manifest = fixture(tmp_path)
    if interpolated is False:
        alter_bars(source, path, manifest, interpolated=False)
    value = observations(source, path)
    assert value.raw_series[0].bars[0].interpolated is interpolated
    assert value.split_series[0].bars[0].interpolated is interpolated
    assert value.raw_series[0].bars[1].interpolated is None
    assert value.quote_currency is None


@pytest.mark.parametrize(
    ("fields", "adjustments"),
    (
        ({"interpolated": True, "volume": 0}, ("none", "split")),
        ({"interpolated": True, "volume": 100}, ("none", "split")),
        ({"interpolated": None}, ("none", "split")),
        ({"volume": 0}, ("none", "split")),
        ({"interpolated": False}, ("split",)),
    ),
)
def test_interpolated_or_ambiguous_native_rows_keep_legacy_rejections(
    tmp_path, fields, adjustments
):
    source, path, manifest = fixture(tmp_path)
    alter_bars(source, path, manifest, adjustments=adjustments, **fields)
    with pytest.raises(ValueError, match="stock_study_inputs_invalid"):
        observations(source, path)
    with pytest.raises(ValueError, match="stock_study_inputs_invalid"):
        load(source, path)


@pytest.mark.parametrize(
    "fields", ({"volume": 777}, {"high_price": "110"}, {"low_price": "90"}, {"interpolated": False})
)
def test_non_price_native_changes_are_retained_and_change_hashes(tmp_path, fields):
    source, path, manifest = fixture(tmp_path)
    before = observations(source, path)
    alter_bars(source, path, manifest, **fields)
    after = observations(source, path)
    assert before.prices.bars == after.prices.bars
    assert before.prices.evidence_hash != after.prices.evidence_hash
    assert before.evidence_hash != after.evidence_hash
    native = after.split_series[0].bars[0]
    assert native.volume == fields.get("volume", 100)
    assert native.high_price == Decimal(fields.get("high_price", "102"))
    assert native.low_price == Decimal(fields.get("low_price", "99"))
    assert native.interpolated is fields.get("interpolated")


@pytest.mark.parametrize(
    "kind", ("frame_metadata", "native_guide", "receipt_metadata", "unreferenced_original")
)
def test_whole_originals_bind_fields_excluded_from_price_and_factor_projections(tmp_path, kind):
    source, path, manifest = fixture(tmp_path)
    if kind == "unreferenced_original":
        write_original(source, path, manifest, "extra-original.json", {"native": "first"})
    before = observations(source, path)
    if kind == "unreferenced_original":
        name, updated, native = "extra-original.json", {"native": "second"}, False
    elif kind == "frame_metadata":
        name, updated, native = (
            "frame.json",
            {"membership_use_not_before": "2024-02-15", "excluded": "retained"},
            False,
        )
    else:
        name, native = "axp-split.json", kind == "native_guide"
        updated = json.loads((source / name).read_bytes())
        if native:
            updated["result"]["structuredContent"]["guide"] = "Changed fictional guide"
        else:
            updated["excluded_receipt_note"] = "retained"
    write_original(source, path, manifest, name, updated, native=native)
    after = observations(source, path)
    assert before.prices.bars == after.prices.bars
    assert before.evidence_hash != after.evidence_hash
    assert before.prices.evidence_hash != after.prices.evidence_hash


@pytest.mark.parametrize(
    "mutation",
    (
        "unbound_file",
        "unbound_excluded",
        "wrong_manifest_hash",
        "native_hash",
        "clock",
        "future_receipt",
        "tool",
        "request_symbol",
        "request_adjustment",
        "request_bounds",
        "structured_mismatch",
        "symbols_permuted",
        "symbol_missing",
        "symbol_duplicate",
        "adjustments_swapped",
        "bar_permuted",
        "bar_missing",
        "bar_duplicate",
        "calendar_mismatch",
        "raw_split_volume",
    ),
)
def test_new_api_revalidates_originals_and_rejects_ambiguous_bindings(tmp_path, mutation):
    source, path, manifest = fixture(tmp_path)
    # A successful prior load must not become an input cache for this call.
    observations(source, path)
    name = "axp-split.json"
    if mutation in {"unbound_file", "unbound_excluded"}:
        target = source / (name if mutation == "unbound_file" else "frame.json")
        target.write_bytes(target.read_bytes() + b" ")
    elif mutation == "wrong_manifest_hash":
        with pytest.raises(ValueError, match="stock_study_inputs_invalid"):
            observations(source, path, expected="0" * 64)
        return
    elif mutation == "native_hash":
        manifest["symbols"][0]["original_receipts"][1]["content_text_utf8_sha256"] = "0" * 64
    elif mutation == "symbols_permuted":
        manifest["symbols"] = list(reversed(manifest["symbols"]))
    elif mutation == "symbol_missing":
        manifest["symbols"].pop()
    elif mutation == "symbol_duplicate":
        manifest["symbols"][-1] = manifest["symbols"][0]
    elif mutation == "adjustments_swapped":
        manifest["symbols"][0]["original_receipts"].reverse()
    else:
        updated = json.loads((source / name).read_bytes())
        native = False
        args = updated["request"]["args"]
        bars = updated["result"]["structuredContent"]["data"]["results"][0]["bars"]
        if mutation == "clock":
            updated["started_at"] = "2026-10-26T01:02:00Z"
        elif mutation == "future_receipt":
            updated["received_at"] = "2026-10-27T01:01:00Z"
        elif mutation == "tool":
            updated["request"]["tool"] = "unofficial"
        elif mutation == "request_symbol":
            args["symbols"] = ["SPY"]
        elif mutation == "request_adjustment":
            args["adjustment_type"] = "none"
        elif mutation == "request_bounds":
            args["bounds"] = "extended"
        elif mutation == "structured_mismatch":
            bars[0]["volume"] = 200
        else:
            native = True
            if mutation == "bar_permuted":
                bars[:2] = reversed(bars[:2])
            elif mutation == "bar_missing":
                bars.pop()
            elif mutation == "bar_duplicate":
                bars[1] = bars[0]
            elif mutation == "calendar_mismatch":
                bars[0]["begins_at"] = "2024-01-02T01:00:00Z"
            elif mutation == "raw_split_volume":
                bars[0]["volume"] = 200
        write_original(source, path, manifest, name, updated, native=native)
    path.write_bytes(encoded(manifest))
    with pytest.raises(ValueError, match="stock_study_inputs_invalid"):
        observations(source, path)


def test_manifest_binding_permutation_preserves_native_values_but_binds_changed_bytes(tmp_path):
    source, path, manifest = fixture(tmp_path)
    first = observations(source, path)
    manifest["all_original_input_bindings"] = dict(
        reversed(tuple(manifest["all_original_input_bindings"].items()))
    )
    path.write_bytes((json.dumps(manifest) + "\n").encode())
    second = observations(source, path)
    assert first.raw_series == second.raw_series and first.split_series == second.split_series
    assert first.calendar == second.calendar and first.prices.bars == second.prices.bars
    assert first.evidence_hash != second.evidence_hash


@pytest.mark.parametrize("kind", ("missing", "symlink", "whole_receipt_hash"))
def test_new_api_has_no_missing_source_or_unsafe_file_fallback(tmp_path, kind):
    source, path, _ = fixture(tmp_path)
    file = source / "axp-split.json"
    if kind == "missing":
        file.unlink()
    elif kind == "symlink":
        other = tmp_path / "other.json"
        other.write_bytes(file.read_bytes())
        file.unlink()
        file.symlink_to(other)
    else:
        file.write_bytes(file.read_bytes() + b" ")
    with pytest.raises(ValueError, match="stock_study_inputs_invalid"):
        observations(source, path)
