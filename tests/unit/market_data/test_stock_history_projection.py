"""Fictional histories isolate known-company quality failures without repairing bars."""

import copy
import hashlib
import importlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

RECEIVED = datetime(2026, 10, 21, 18, tzinfo=UTC)
SOURCE_HASH = "a" * 64


def api():
    try:
        return importlib.import_module("trading_bot.market_data.stock_history_projection")
    except ModuleNotFoundError:
        pytest.fail("per-symbol history projection is missing")


def bar(**changes):
    return {
        "begins_at": "2026-10-19T04:00:00Z",
        "open_price": "20",
        "high_price": "22",
        "low_price": "19",
        "close_price": "21",
        "volume": 1000,
        "interpolated": False,
        "session": "reg",
        **changes,
    }


def row(symbol, bars=None, **changes):
    return {
        "symbol": symbol,
        "interval": "day",
        "bounds": "regular",
        "bars": [bar()] if bars is None else bars,
        **changes,
    }


def envelope(rows, not_found=None):
    return {"data": {"results": rows, "not_found": not_found}, "guide": "Fictional fixture"}


def project(payload, requested_symbols=("ALFA", "BETA", "GAMMA"), **kwargs):
    return api().normalize_history_by_symbol(
        payload,
        received_at=RECEIVED,
        observation_sha256=SOURCE_HASH,
        requested_symbols=requested_symbols,
        **kwargs,
    )


def digest(payload):
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_bad_ohlc_quarantines_whole_company_while_two_good_companies_survive():
    bad = row("BETA", [bar(), bar(begins_at="2026-10-20T04:00:00Z", close_price="23")])
    payload = envelope([row("GAMMA"), bad, row("ALFA")])
    original = copy.deepcopy(payload)
    result = project(payload)
    assert tuple(item.symbol for item in result.outcomes) == ("ALFA", "BETA", "GAMMA")
    alfa, beta, gamma = result.outcomes
    assert alfa.status == gamma.status == "normalized"
    assert beta.status == "quarantined" and beta.normalized is None
    assert beta.reason_codes == ("daily_history_validation_failed",)
    assert len(alfa.normalized.records) == len(gamma.normalized.records) == 1
    assert alfa.normalized.records[0].close == Decimal("21")
    assert alfa.original_result_index == 2 and gamma.original_result_index == 0
    assert beta.original_result_index == 1 and not beta.explicit_not_found
    assert beta.context.source_path == ("data", "results", 1)
    assert beta.original_source_sha256 == SOURCE_HASH
    assert beta.context.original_requested_symbols == ("ALFA", "BETA", "GAMMA")
    expected = {"data": {"results": [bad]}, "guide": "Fictional fixture"}
    assert beta.projected_payload_sha256 == digest(expected)
    assert alfa.normalized.receipt.observation_sha256 == alfa.projected_payload_sha256
    assert alfa.normalized.receipt.observation_sha256 != SOURCE_HASH
    assert result.receipt.observation_sha256 == SOURCE_HASH
    assert payload == original
    assert result.is_local_projection and not result.is_native_provider_payload
    assert all(item.context.is_local_projection for item in result.outcomes)
    assert all(
        item.is_local_projection and not item.is_native_provider_payload for item in result.outcomes
    )
    assert not any(
        item.qualified or item.trading_enabled or item.live_authorized for item in result.outcomes
    )
    assert not result.qualified and not result.live_authorized
    with pytest.raises(AttributeError):
        beta.context.original_result_index = 0
    with pytest.raises(AttributeError):
        result.outcomes = ()


def test_explicit_not_found_retains_its_original_path_and_unavailable_outcome():
    result = project(envelope([row("BETA")], ["GAMMA", "ALFA"]))
    alfa, beta, gamma = result.outcomes
    assert beta.status == "normalized"
    assert alfa.status == gamma.status == "unavailable"
    assert alfa.explicit_not_found and alfa.original_result_index is None
    assert alfa.context.source_path == ("data", "not_found", 1)
    assert alfa.reason_codes == ("source_symbol_not_found",)
    assert alfa.normalized.records == () and alfa.normalized.not_found == ("ALFA",)
    assert alfa.projected_payload_sha256 == digest(
        {
            "data": {"results": [], "not_found": ["ALFA"]},
            "guide": "Fictional fixture",
        }
    )


def test_interpolated_omission_provenance_and_history_gaps_survive_projection():
    rows = [
        bar(begins_at="2026-10-16T04:00:00Z"),
        bar(interpolated=True),
        bar(begins_at="2026-10-20T04:00:00Z"),
    ]
    result = project(envelope([row("ALFA", rows)]), ("ALFA",))
    outcome = result.outcomes[0]
    assert outcome.status == "normalized"
    normalized = outcome.normalized
    assert tuple(item.left_edge_date for item in normalized.records) == (
        date(2026, 10, 16),
        date(2026, 10, 20),
    )
    assert normalized.omitted_interpolated_count == 1
    omission = normalized.omitted_interpolated_bars[0]
    assert omission.symbol == "ALFA"
    assert omission.begins_at == datetime(2026, 10, 19, 4, tzinfo=UTC)
    assert all(
        item.price_basis == "unknown" and item.completion_status == "unknown"
        for item in normalized.records
    )
    assert normalized.records[0].available_at == RECEIVED
    assert "coverage_and_calendar_completeness_unverified" in result.limitations


@pytest.mark.parametrize("bars", [[], [bar(interpolated=True)], [None]])
def test_no_usable_bars_are_unavailable_without_fabricated_prices(bars):
    outcome = project(envelope([row("ALFA", bars)]), ("ALFA",)).outcomes[0]
    assert outcome.status == "unavailable" and outcome.normalized.records == ()
    assert outcome.reason_codes == ("no_normalized_daily_bars",)
    assert not outcome.explicit_not_found


@pytest.mark.parametrize(
    "bad_row",
    [
        row("BETA", [bar(begins_at="2026-10-22T04:00:00Z")]),
        row("BETA", [bar(session="pre")]),
        row("BETA", [bar(), bar()]),
        row("BETA", bounds="extended"),
        row("BETA", [bar(close_price=21.5)]),
    ],
)
def test_company_quality_failures_do_not_return_partial_series_or_erase_good_company(bad_row):
    result = project(envelope([row("ALFA"), bad_row]), ("ALFA", "BETA"))
    assert result.outcomes[0].status == "normalized"
    bad = result.outcomes[1]
    assert bad.status == "quarantined" and bad.normalized is None
    assert bad.reason_codes == ("daily_history_validation_failed",)


@pytest.mark.parametrize(
    "payload,requested",
    [
        (envelope([row("ALFA"), row("WRONG")]), ("ALFA", "BETA")),
        (envelope([row("ALFA"), row("ALFA")]), ("ALFA",)),
        (envelope([row("ALFA")], ["ALFA"]), ("ALFA",)),
        (envelope([], ["ALFA", "ALFA"]), ("ALFA",)),
        (envelope([row("ALFA"), None]), ("ALFA", "BETA")),
        (envelope([row("ALFA"), {"bars": []}]), ("ALFA", "BETA")),
        (envelope([row("ALFA")]), ("ALFA", "BETA")),
        (envelope(None, ["ALFA"]), ("ALFA",)),
        (envelope([row("ALFA")]), ("ALFA", "ALFA")),
        (envelope([row("ALFA")]), ("alfa",)),
        (envelope([]), ()),
    ],
)
def test_unknown_or_conflicting_batch_scope_fails_entire_projection(payload, requested):
    with pytest.raises(ValueError, match=r"^stock_history_projection_invalid_batch$"):
        project(payload, requested)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"request_adjustment_type": "split"},
        {"request_adjustment_type": "raw"},
        {"completed_before": datetime(2026, 10, 22, tzinfo=UTC)},
        {"completed_before": datetime(2026, 10, 20)},
    ],
)
def test_invalid_global_declarations_fail_batch_instead_of_quarantining_each_company(kwargs):
    with pytest.raises(ValueError, match=r"^stock_history_projection_invalid_batch$"):
        project(envelope([row("ALFA")]), ("ALFA",), **kwargs)


def test_raw_and_completion_declarations_remain_explicit_and_unqualified():
    cutoff = datetime(2026, 10, 20, tzinfo=UTC)
    outcome = project(
        envelope([row("ALFA")]),
        ("ALFA",),
        request_adjustment_type="none",
        completed_before=cutoff,
    ).outcomes[0]
    normalized = outcome.normalized
    assert normalized.request_adjustment_type == "none" and normalized.completed_before == cutoff
    record = normalized.records[0]
    assert record.raw_basis_caller_declared and record.price_basis == "raw"
    assert record.completion_status == "caller_declared_complete" and record.completed_at is None
    assert not normalized.qualified and not outcome.source_qualified


def test_hashes_bind_projected_prices_and_original_source_context():
    payload = envelope([row("ALFA")])
    original = project(payload, ("ALFA",))
    changed = project(envelope([row("ALFA", [bar(close_price="20.5")])]), ("ALFA",))
    assert (
        original.outcomes[0].projected_payload_sha256
        != changed.outcomes[0].projected_payload_sha256
    )
    assert original.observation_hash != changed.observation_hash
    assert original.observation_hash == project(payload, ("ALFA",)).observation_hash
