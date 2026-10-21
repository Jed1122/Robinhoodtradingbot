"""Fictional stock facts preserve missingness, chronology and declared source basis."""

import importlib
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

RECEIVED = datetime(2026, 10, 21, 18, tzinfo=UTC)
DIGEST = "a" * 64


def api():
    try:
        return importlib.import_module("trading_bot.market_data.stock_facts")
    except ModuleNotFoundError:
        pytest.fail("stock facts normalizers are missing")


def envelope(rows, **data):
    return {"data": {"results": rows, **data}, "guide": "Fictional fixture"}


def fundamental(**changes):
    return {
        "symbol": "ALFA",
        "bounds": "regular",
        "market_date": "2026-10-20",
        "market_cap": "2500000000",
        "average_volume_30_days": "1000000",
        "pe_ratio": "-12.5",
        "open": "20",
        "high": "22",
        "low": "19",
        **changes,
    }


def financial(**changes):
    return {
        "fiscal_year": 2026,
        "fiscal_quarter": 2,
        "period_end_date": "2026-06-30",
        "revenue": "-5",
        "gross_profit": "-8",
        "net_income": "-12",
        "net_margin": "-2.4",
        **changes,
    }


def price(**changes):
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


def bars(rows=None, **changes):
    return envelope(
        [
            {
                "symbol": "ALFA",
                "interval": "day",
                "bounds": "regular",
                "bars": [price()] if rows is None else rows,
                **changes,
            }
        ]
    )


def normalize(name, payload, **kwargs):
    return getattr(api(), name)(payload, received_at=RECEIVED, observation_sha256=DIGEST, **kwargs)


def metric(record, name):
    return {item.name: item.value for item in record.metrics}.get(name)


def test_fundamentals_are_decimal_snapshot_metrics_without_fabricated_adv():
    result = normalize("normalize_fundamentals", envelope([fundamental(shares_outstanding=None)]))
    row = result.records[0]
    assert metric(row, "market_cap") == Decimal("2500000000")
    assert metric(row, "pe_ratio") == Decimal("-12.5")
    assert metric(row, "shares_outstanding") is None
    assert metric(row, "average_dollar_volume") is None
    assert "shares_outstanding" in row.missing_metrics
    assert row.market_date == date(2026, 10, 20)
    assert row.available_at == RECEIVED
    assert row.receipt.observation_sha256 == DIGEST
    assert row.receipt.tool == "get_equity_fundamentals"
    assert not result.scope_verified
    assert not result.qualified and not result.trading_enabled and not result.live_authorized


def test_missing_results_null_rows_and_not_found_are_explicit():
    result = normalize(
        "normalize_fundamentals", envelope([None, fundamental(market_cap=None)], not_found=["BETA"])
    )
    assert result.null_row_count == 1 and result.not_found == ("BETA",)
    assert metric(result.records[0], "market_cap") is None
    empty = normalize("normalize_fundamentals", envelope(None))
    assert empty.results_missing and empty.records == ()


def test_requested_symbol_scope_must_match_response_exactly():
    result = normalize(
        "normalize_fundamentals",
        envelope([fundamental()], not_found=["BETA"]),
        requested_symbols=("ALFA", "BETA"),
    )
    assert result.scope_verified
    for requested in [
        ("BETA",),
        ("ALFA", "ALFA"),
        ("alfa",),
        (),
        tuple(f"A{i}" for i in range(11)),
    ]:
        with pytest.raises(ValueError):
            normalize(
                "normalize_fundamentals", envelope([fundamental()]), requested_symbols=requested
            )
    with pytest.raises(ValueError):
        normalize("normalize_fundamentals", envelope([fundamental()], not_found=["ALFA"]))


@pytest.mark.parametrize(
    "changes",
    [
        {"market_cap": "NaN"},
        {"market_cap": "Infinity"},
        {"market_cap": 2.5},
        {"market_cap": True},
        {"market_cap": "1e9999"},
        {"market_date": "2026-10-22"},
        {"open": "0"},
        {"high": "18"},
        {"volume": "-1"},
        {"unknown_metric": "15"},
        {"symbol": "ALFA "},
    ],
)
def test_invalid_snapshot_values_and_future_dates_deny(changes):
    with pytest.raises(ValueError, match="stock_facts_invalid"):
        normalize("normalize_fundamentals", envelope([fundamental(**changes)]))


def test_conflicting_or_identical_symbol_duplicates_deny():
    for second in [fundamental(), fundamental(market_cap="3000000000")]:
        with pytest.raises(ValueError):
            normalize("normalize_fundamentals", envelope([fundamental(), second]))


def test_financials_preserve_signed_values_and_period_end_is_not_availability():
    result = normalize(
        "normalize_financials",
        envelope([{"symbol": "ALFA", "period": "quarterly", "financials": [financial()]}]),
        requested_symbols=("ALFA",),
    )
    row = result.records[0]
    assert metric(row, "revenue") == Decimal("-5")
    assert metric(row, "net_margin") == Decimal("-2.4")
    assert row.period_end == date(2026, 6, 30) and row.period_start is None
    assert row.available_at == RECEIVED and row.receipt.tool == "get_financials"
    assert result.scope_verified


@pytest.mark.parametrize(
    "rows",
    [
        [financial(), financial()],
        [financial(), financial(net_income="-13")],
        [financial(), financial(period_end_date="2026-09-30", fiscal_quarter=3)],
        [financial(period_end_date="2026-12-31")],
        [financial(fiscal_year=True)],
        [financial(net_income="NaN")],
    ],
)
def test_financial_duplicates_reverse_chronology_future_and_invalid_values_deny(rows):
    with pytest.raises(ValueError, match="stock_facts_invalid"):
        normalize(
            "normalize_financials",
            envelope([{"symbol": "ALFA", "period": "quarterly", "financials": rows}]),
        )


def test_null_financial_values_and_empty_series_never_become_zeros():
    result = normalize(
        "normalize_financials",
        envelope(
            [
                {
                    "symbol": "ALFA",
                    "period": "annual",
                    "financials": [financial(fiscal_quarter=None, revenue=None, gross_profit=None)],
                },
                None,
            ]
        ),
    )
    assert metric(result.records[0], "revenue") is None
    assert result.null_row_count == 1
    empty = normalize(
        "normalize_financials",
        envelope([{"symbol": "ALFA", "period": "quarterly", "financials": None}]),
    )
    assert empty.records == () and empty.unavailable_symbols == ("ALFA",)


def test_daily_bars_do_not_guess_price_basis_or_completion():
    result = normalize("normalize_daily_bars", bars())
    row = result.records[0]
    assert row.open == Decimal("20") and row.volume == Decimal(1000)
    assert row.begins_at == datetime(2026, 10, 19, 4, tzinfo=UTC)
    assert row.left_edge_date == date(2026, 10, 19)
    assert row.completed_at is None and row.completed_by is None
    assert row.completion_status == "unknown" and row.price_basis == "unknown"
    assert row.available_at == RECEIVED


def test_raw_request_and_completion_are_explicit_unqualified_declarations():
    cutoff = datetime(2026, 10, 20, tzinfo=UTC)
    result = normalize(
        "normalize_daily_bars",
        bars(),
        requested_symbols=("ALFA",),
        request_adjustment_type="none",
        completed_before=cutoff,
    )
    row = result.records[0]
    assert row.price_basis == "raw" and row.raw_basis_caller_declared
    assert row.completion_status == "caller_declared_complete"
    assert row.completed_by == cutoff and row.completed_at is None
    assert result.scope_verified and not result.qualified
    incomplete = normalize("normalize_daily_bars", bars(), completed_before=row.begins_at).records[
        0
    ]
    assert incomplete.completion_status == "unknown"


@pytest.mark.parametrize(
    "rows,changes,kwargs",
    [
        ([price(open_price="0")], {}, {}),
        ([price(low_price="23")], {}, {}),
        ([price(volume=True)], {}, {}),
        ([price(volume=-1)], {}, {}),
        ([price(interpolated=True)], {}, {}),
        ([price(session="pre")], {}, {}),
        ([price(session=None)], {}, {}),
        ([price(begins_at="2026-10-22T04:00:00Z")], {}, {}),
        ([price(begins_at="2026-10-19T04:00:00")], {}, {}),
        ([price(), price()], {}, {}),
        ([price(), price(begins_at="2026-10-18T04:00:00Z")], {}, {}),
        ([price()], {"bounds": "extended"}, {}),
        ([price()], {"interval": "hour"}, {}),
        ([price()], {}, {"request_adjustment_type": "split"}),
        ([price()], {}, {"completed_before": datetime(2026, 10, 22, tzinfo=UTC)}),
    ],
)
def test_daily_invalid_values_scope_and_lookahead_are_rejected(rows, changes, kwargs):
    with pytest.raises(ValueError, match="stock_facts_invalid"):
        normalize("normalize_daily_bars", bars(rows, **changes), **kwargs)


def test_missing_interpolation_or_session_markers_remain_unknown():
    row = price()
    del row["interpolated"]
    del row["session"]
    result = normalize("normalize_daily_bars", bars([row]))
    assert result.records[0].interpolated is None
    assert result.records[0].session is None


def test_declarations_survive_empty_and_not_yet_completed_bar_collections():
    cutoff = datetime(2026, 10, 18, tzinfo=UTC)
    result = normalize(
        "normalize_daily_bars", bars(), request_adjustment_type="none", completed_before=cutoff
    )
    assert result.completed_before == cutoff and result.request_adjustment_type == "none"
    assert result.records[0].completion_status == "unknown"
    empty = normalize("normalize_daily_bars", bars([]), completed_before=cutoff)
    assert empty.completed_before == cutoff
    assert empty.observation_hash != normalize("normalize_daily_bars", bars([])).observation_hash


def test_nullable_quarter_does_not_invent_a_quarter_or_discard_reported_values():
    result = normalize(
        "normalize_financials",
        envelope(
            [
                {
                    "symbol": "ALFA",
                    "period": "quarterly",
                    "financials": [financial(fiscal_quarter=None)],
                }
            ]
        ),
    )
    assert result.records[0].fiscal_quarter is None
    assert metric(result.records[0], "net_income") == Decimal("-12")


def test_one_annual_fiscal_identity_cannot_silently_resolve_conflicting_period_ends():
    payload = envelope(
        [
            {
                "symbol": "ALFA",
                "period": "annual",
                "financials": [
                    financial(fiscal_quarter=None),
                    financial(fiscal_quarter=None, period_end_date="2026-03-31"),
                ],
            }
        ]
    )
    with pytest.raises(ValueError, match="stock_facts_invalid"):
        normalize("normalize_financials", payload)


@pytest.mark.parametrize(
    "rows",
    [
        [financial()],
        [financial(), financial(fiscal_quarter=1, period_end_date="2026-03-31")],
    ],
)
def test_annual_records_cannot_use_quarter_labels_to_disguise_fiscal_identity(rows):
    with pytest.raises(ValueError, match="stock_facts_invalid"):
        normalize(
            "normalize_financials",
            envelope([{"symbol": "ALFA", "period": "annual", "financials": rows}]),
        )


@pytest.mark.parametrize(
    "changes", [{"open": None, "high": "18"}, {"open": None, "low": "23"}, {"market_cap": "1_000"}]
)
def test_partial_price_ranges_and_non_numeric_decimal_syntax_deny(changes):
    with pytest.raises(ValueError, match="stock_facts_invalid"):
        normalize("normalize_fundamentals", envelope([fundamental(**changes)]))


@pytest.mark.parametrize(
    "timestamp,digest",
    [(RECEIVED.replace(tzinfo=None), DIGEST), (RECEIVED, "BAD"), (RECEIVED, True)],
)
def test_receipt_clock_and_digest_are_strict(timestamp, digest):
    with pytest.raises(ValueError):
        api().normalize_fundamentals(
            envelope([fundamental()]), received_at=timestamp, observation_sha256=digest
        )
