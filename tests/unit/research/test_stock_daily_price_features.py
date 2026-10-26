"""Fictional MCP/calendar bytes exercise the separate descriptive input seam."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from trading_bot.market_data.stock_split_comparison import (
    StockSplitRequest,
    parse_stock_split_series,
)

TOOL = "mcp__robinhood_2__get_equity_historicals"
METADATA = "40b726da941850f2e4911f750ce67758668f9976019beab08126bc6dbdee8c36"


def encoded(value):
    return json.dumps(value, separators=(",", ":")).encode()


def parse_calendar(value, **changes):
    from trading_bot.market_data.stock_daily_series import parse_stock_daily_calendar

    body = value if type(value) is bytes else encoded(value)
    args = {
        "expected_sha256": hashlib.sha256(body).hexdigest(),
        "received_at": datetime(2025, 1, 2, tzinfo=UTC),
        "market_timezone": "America/New_York",
    }
    return parse_stock_daily_calendar(body, **(args | changes))


def fixture(count=201, *, closes=None, volume=100, native=None):
    # Deliberately fictional weekdays, not an authenticated exchange calendar.
    dates, day = [], date(2024, 1, 2)
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += timedelta(days=1)
    end = dates[-1] + timedelta(days=1)
    request = StockSplitRequest(
        "TEST",
        datetime.combine(dates[0], datetime.min.time(), UTC),
        datetime.combine(end, datetime.min.time(), UTC),
        "split",
    )
    bars = []
    for index, day in enumerate(dates):
        price = "100" if closes is None else str(closes[index])
        bar = {
            "begins_at": day.isoformat() + "T00:00:00Z",
            "open_price": price,
            "high_price": price,
            "low_price": price,
            "close_price": price,
            "volume": volume,
            "session": "reg",
        }
        if native is not None:
            bar["interpolated"] = native
        bars.append(bar)
    value = {
        "data": {
            "results": [
                {
                    "symbol": "TEST",
                    "interval": "day",
                    "bounds": "regular",
                    "bars": bars,
                }
            ]
        },
        "guide": "Fictional evidence, no authority.",
    }
    calendar = {
        "request": {"start_date": dates[0].isoformat(), "end_date": end.isoformat()},
        "calendar": [
            {
                "date": d.isoformat(),
                "open": d.isoformat() + "T09:30:00",
                "close": d.isoformat() + "T16:00:00",
            }
            for d in dates
        ],
    }
    # Range end is inclusive in the calendar, exclusive midnight in the bars request.
    calendar["request"]["end_date"] = dates[-1].isoformat()
    return request, value, calendar


def inputs(count=201, **changes):
    request, value, calendar = fixture(count, **changes)
    body = encoded(value)
    series = parse_stock_split_series(
        body,
        expected_sha256=hashlib.sha256(body).hexdigest(),
        request=request,
        received_at=datetime(2025, 1, 2, tzinfo=UTC),
    )
    return series, parse_calendar(calendar)


def admit(series=None, calendar=None, *, default_inputs=True, **changes):
    from trading_bot.market_data.stock_daily_series import admit_stock_daily_series

    if default_inputs:
        series, calendar = inputs() if series is None else (series, calendar)
    args = {
        "source_tool": TOOL,
        "source_metadata_sha256": METADATA,
        "as_of": datetime(2025, 1, 2, tzinfo=UTC),
        "maximum_closed_session_lag_days": 365,
    }
    return admit_stock_daily_series(series, calendar, **(args | changes))


def features(value):
    from trading_bot.research.stock_daily_price_features import calculate_stock_daily_price_features

    return calculate_stock_daily_price_features(value)


def test_calendar_preserves_naive_wire_and_explicit_external_dst_early_close_context():
    value = {
        "request": {"start_date": "2024-03-08", "end_date": "2024-03-11"},
        "calendar": [
            {"date": "2024-03-08", "open": "2024-03-08T09:30:00", "close": "2024-03-08T13:00:00"},
            {"date": "2024-03-11", "open": "2024-03-11T09:30:00", "close": "2024-03-11T16:00:00"},
        ],
    }
    result = parse_calendar(value)
    assert result.original_content_json == encoded(value)
    assert result.sessions[0].open_wire == "2024-03-08T09:30:00"
    assert result.sessions[0].opens_at == datetime(2024, 3, 8, 14, 30, tzinfo=UTC)
    assert result.sessions[0].closes_at == datetime(2024, 3, 8, 18, tzinfo=UTC)
    assert result.sessions[1].opens_at == datetime(2024, 3, 11, 13, 30, tzinfo=UTC)
    assert result.sessions[1].closes_at == datetime(2024, 3, 11, 20, tzinfo=UTC)
    assert result.market_timezone == "America/New_York"
    assert result.authenticated is False and result.source_qualified is False


@pytest.mark.parametrize(
    "kind",
    [
        "hash",
        "extra",
        "duplicate",
        "null",
        "weekend",
        "open",
        "close",
        "offset",
        "date",
        "range",
        "timezone",
        "json_duplicate",
    ],
)
def test_calendar_rejects_changed_hash_unknown_shapes_and_unsupported_market_times(kind):
    from trading_bot.market_data.stock_daily_series import StockDailySeriesError

    _, _, value = fixture(2)
    changes = {}
    if kind == "hash":
        changes["expected_sha256"] = "0" * 64
    elif kind == "extra":
        value["currency"] = "USD"
    elif kind == "duplicate":
        value["calendar"].append(value["calendar"][0])
    elif kind == "null":
        value["calendar"][0] = None
    elif kind == "weekend":
        value["calendar"][0]["date"] = "2024-01-06"
    elif kind == "open":
        value["calendar"][0]["open"] = "2024-01-02T10:00:00"
    elif kind == "close":
        value["calendar"][0]["close"] = "2024-01-02T14:00:00"
    elif kind == "offset":
        value["calendar"][0]["open"] += "-05:00"
    elif kind == "date":
        value["calendar"][0]["date"] = "20240102"
    elif kind == "range":
        value["request"]["end_date"] = "2024-01-01"
    elif kind == "timezone":
        changes["market_timezone"] = "UTC"
    elif kind == "json_duplicate":
        value = encoded(value).replace(b'"calendar":', b'"calendar":[],"calendar":')
    with pytest.raises(StockDailySeriesError):
        parse_calendar(value, **changes)


def test_admission_keeps_native_unknown_and_original_evidence_without_currency_or_promotion():
    series, calendar = inputs()
    result = admit(series, calendar)
    assert result.status == "descriptive_admissible" and result.reason_codes == ()
    assert result.series.original_content_json == series.original_content_json
    assert result.calendar.original_content_json == calendar.original_content_json
    assert all(bar.interpolated is None for bar in result.series.bars)
    assert result.non_synthetic_basis == ("positive_volume_contract_inference",) * 201
    assert result.session_dates == tuple(row.session_date for row in calendar.sessions)
    assert result.quote_currency is None and result.price_basis == "split"
    assert len(result.evidence_hash) == 64
    for flag in (
        "qualified",
        "source_qualified",
        "strategy_qualified",
        "investment_eligible",
        "trading_enabled",
        "live_authorized",
        "authenticated",
    ):
        assert getattr(result, flag) is False


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("tool", "source_contract_mismatch"),
        ("metadata", "source_contract_mismatch"),
        ("gap", "calendar_bar_dates_mismatch"),
        ("calendar_range", "calendar_request_mismatch"),
        ("raw", "split_adjustment_required"),
        ("zero", "non_synthetic_unresolved"),
        ("synthetic", "non_synthetic_unresolved"),
        ("session", "regular_session_required"),
        ("null", "incomplete_history"),
        ("empty", "incomplete_history"),
        ("label", "midnight_utc_label_required"),
        ("request_time", "midnight_utc_request_required"),
        ("future_source", "future_source_receipt"),
        ("future_calendar", "future_calendar_receipt"),
    ],
)
def test_admission_denies_scope_missingness_clocks_and_unsupported_native_evidence(kind, reason):
    request, value, cal = fixture()
    bars = value["data"]["results"][0]["bars"]
    changes = {}
    received = datetime(2025, 1, 2, tzinfo=UTC)
    if kind == "tool":
        changes["source_tool"] = "other_history"
    elif kind == "metadata":
        changes["source_metadata_sha256"] = "0" * 64
    elif kind == "gap":
        bars.pop(1)
    elif kind == "calendar_range":
        cal["request"]["start_date"] = "2024-01-01"
    elif kind == "raw":
        request = replace(request, adjustment_type="none")
    elif kind == "zero":
        bars[0]["volume"] = 0
    elif kind == "synthetic":
        bars[0].update(volume=0, interpolated=True)
    elif kind == "session":
        bars[0].pop("session")
    elif kind == "null":
        bars[0] = None
    elif kind == "empty":
        bars.clear()
    elif kind == "label":
        bars[1]["begins_at"] = "2024-01-03T01:00:00Z"
    elif kind == "request_time":
        request = replace(request, end_time=request.end_time + timedelta(hours=1))
    elif kind == "future_source":
        received += timedelta(seconds=1)
    raw = encoded(value)
    series = parse_stock_split_series(
        raw, expected_sha256=hashlib.sha256(raw).hexdigest(), request=request, received_at=received
    )
    calendar = parse_calendar(
        cal, received_at=received if kind == "future_calendar" else datetime(2025, 1, 2, tzinfo=UTC)
    )
    if kind == "future_calendar":
        calendar = replace(calendar, received_at=datetime(2025, 1, 2, 0, 0, 1, tzinfo=UTC))
    result = admit(series, calendar, **changes)
    assert result.status == "ineligible" and reason in result.reason_codes
    assert features(result).metrics is None


def test_default_coverage_and_source_lag_hypotheses_are_not_silently_relaxed():
    from trading_bot.market_data.stock_daily_series import admit_stock_daily_series

    series, calendar = inputs(200)
    assert "insufficient_observations" in admit(series, calendar).reason_codes
    source, cal = inputs(201)
    at = cal.sessions[-1].closes_at + timedelta(days=7)
    source, cal = replace(source, received_at=at), replace(cal, received_at=at)
    args = dict(source_tool=TOOL, source_metadata_sha256=METADATA, as_of=at)
    assert admit_stock_daily_series(source, cal, **args).status == "descriptive_admissible"
    assert (
        "latest_closed_session_stale"
        in admit_stock_daily_series(
            source, cal, **(args | {"as_of": at + timedelta(microseconds=1)})
        ).reason_codes
    )


def test_session_close_not_midnight_label_decides_completion():
    source, calendar = inputs(1)
    before_close = datetime(2024, 1, 2, 20, 59, tzinfo=UTC)
    source, calendar = (
        replace(source, received_at=before_close),
        replace(calendar, received_at=before_close),
    )
    result = admit(source, calendar, as_of=before_close, minimum_observations=1)
    assert result.status == "ineligible" and "session_not_closed" in result.reason_codes


@pytest.mark.parametrize(
    "changes",
    [
        {"as_of": datetime(2025, 1, 2)},
        {"minimum_observations": True},
        {"minimum_observations": 0},
        {"maximum_closed_session_lag_days": -1},
    ],
)
def test_invalid_policy_and_non_utc_clock_are_rejected(changes):
    from trading_bot.market_data.stock_daily_series import StockDailySeriesError

    with pytest.raises(StockDailySeriesError):
        admit(**changes)


def test_absent_and_mutated_inputs_cannot_acquire_metrics_or_a_valid_evidence_hash():
    from trading_bot.market_data.stock_daily_series import StockDailySeriesError

    assert features(None).status == "ineligible" and features(None).metrics is None
    assert admit(default_inputs=False).status == "ineligible"
    for field, value in (
        ("status", "descriptive_admissible"),
        ("qualified", 0),
        ("source_metadata_sha256", "0" * 64),
        ("session_dates", ()),
    ):
        result = admit()
        if field == "status":
            object.__setattr__(result.series.bars[0], "close_price", Decimal("99"))
        else:
            object.__setattr__(result, field, value)
        assert features(result).status == "ineligible" and features(result).metrics is None
        with pytest.raises(StockDailySeriesError):
            _ = result.evidence_hash


def test_constant_series_has_zero_dimensionless_metrics_and_context_independent_hash():
    admitted = admit()
    result = features(admitted)
    assert result.status == "calculated" and result.missing_metrics == ()
    assert (
        result.metrics.price_return_20
        == result.metrics.price_return_60
        == result.metrics.price_return_120
        == 0
    )
    assert result.metrics.close_to_sma_50 == result.metrics.close_to_sma_200 == 0
    assert result.metrics.realized_volatility_20 == result.metrics.series_max_drawdown == 0
    assert result.source_evidence_hash == admitted.evidence_hash
    assert not hasattr(result.metrics, "average_dollar_volume_20")
    assert result.quote_currency is None and result.source_qualified is False
    with localcontext() as context:
        context.prec = 6
        assert (
            features(admitted) == result
            and features(admitted).evidence_hash == result.evidence_hash
        )


def test_geometric_prices_have_hand_derived_price_returns_not_total_returns():
    source, calendar = inputs(closes=[2**i for i in range(201)])
    result = features(admit(source, calendar))
    assert result.metrics.price_return_20 == Decimal("1048575")
    assert result.metrics.price_return_60 == Decimal("1152921504606846975")
    assert result.metrics.price_return_120 == Decimal("1329227995784915872903807060280344575")
    assert result.metrics.series_max_drawdown == result.metrics.realized_volatility_20 == 0
    assert Decimal("24") < result.metrics.close_to_sma_50 < Decimal("24.000000000001")
    # 100*2**199/(2**200-1)-1 rounds to 99 at the specified 50 digits.
    assert result.metrics.close_to_sma_200 == Decimal("99")


def test_alternating_returns_use_sample_variance_and_peak_to_trough_drawdown():
    prices = [100] * 180 + [100, 200] * 10 + [100]
    source, calendar = inputs(closes=prices)
    result = features(admit(source, calendar))
    # Twenty returns: ten +1 and ten -1/2; mean 1/4, sample variance 45/76.
    with localcontext() as context:
        context.prec = 50
        expected = (Decimal(2835) / Decimal(19)).sqrt()
    assert result.metrics.realized_volatility_20 == expected
    assert result.metrics.series_max_drawdown == Decimal("0.5")


def test_extreme_bounded_prices_cannot_publish_unbounded_derived_metrics():
    prices = ["1e-509"] * 200 + ["1e510"]
    source, calendar = inputs(closes=prices)
    result = features(admit(source, calendar))
    assert result.status == "ineligible" and result.metrics is None
    assert result.reason_codes == ("arithmetic_invalid",)


def test_small_explicit_policy_does_not_fabricate_missing_feature_windows():
    source, calendar = inputs(2, closes=[100, 50])
    result = features(admit(source, calendar, minimum_observations=2))
    assert result.metrics.series_max_drawdown == Decimal("0.5")
    assert result.metrics.price_return_20 is None and result.metrics.close_to_sma_200 is None
    assert (
        "price_return_20" in result.missing_metrics and "close_to_sma_200" in result.missing_metrics
    )


def test_changed_receipt_and_policy_context_change_complete_feature_provenance():
    first = admit()
    changed = replace(first.series, received_at=first.series.received_at - timedelta(seconds=1))
    second = admit(changed, first.calendar)
    assert features(first).metrics == features(second).metrics
    assert first.evidence_hash != second.evidence_hash
    assert features(first).evidence_hash != features(second).evidence_hash


def test_waiting_cannot_make_a_bar_collected_before_session_close_complete():
    source, calendar = inputs(1)
    source = replace(source, received_at=datetime(2024, 1, 2, 20, 59, tzinfo=UTC))
    calendar = replace(calendar, received_at=datetime(2024, 1, 2, 22, tzinfo=UTC))
    result = admit(
        source, calendar, minimum_observations=1, as_of=datetime(2024, 1, 2, 23, tzinfo=UTC)
    )
    assert result.status == "ineligible"
    assert "session_not_closed_at_source_receipt" in result.reason_codes
    assert features(result).metrics is None


def test_whitespace_changes_in_original_source_and_calendar_still_change_provenance():
    first = admit()
    body = first.series.original_content_json + b"\n"
    source = parse_stock_split_series(
        body,
        expected_sha256=hashlib.sha256(body).hexdigest(),
        request=first.series.request,
        received_at=first.series.received_at,
    )
    source_changed = admit(source, first.calendar)
    calendar = parse_calendar(first.calendar.original_content_json + b"\n")
    calendar_changed = admit(first.series, calendar)
    assert (
        features(first).metrics
        == features(source_changed).metrics
        == features(calendar_changed).metrics
    )
    assert (
        len({first.evidence_hash, source_changed.evidence_hash, calendar_changed.evidence_hash})
        == 3
    )


@pytest.mark.parametrize(
    "kind", ["calendar_derived", "calendar_bytes", "calendar_scope", "source_bytes"]
)
def test_mutated_calendar_and_original_bytes_cannot_bypass_feature_revalidation(kind):
    value = admit()
    if kind == "calendar_derived":
        object.__setattr__(value.calendar.sessions[0], "closes_at", value.as_of)
    elif kind == "calendar_bytes":
        object.__setattr__(value.calendar, "original_content_json", b"{}")
    elif kind == "calendar_scope":
        object.__setattr__(value.calendar, "authenticated", True)
    else:
        object.__setattr__(value.series, "original_content_json", b"{}")
    assert features(value).status == "ineligible" and features(value).metrics is None
