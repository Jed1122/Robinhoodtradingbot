"""Native-shaped public fixtures retain provenance and unresolved execution gates."""

import importlib
from dataclasses import replace
from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from tests.unit.market_data.test_etf_issuer_distributions import _pack, _parse, _parts
from trading_bot.market_data.alpaca_native import (
    AlpacaBarRecord,
    AlpacaQuoteRecord,
    AlpacaStockRequest,
    parse_timestamp_ns,
)
from trading_bot.market_data.etf_calendar import EtfCalendarArchive, EtfCalendarSession
from trading_bot.market_data.etf_native_archive import EtfNativeBarsArchive
from trading_bot.market_data.etf_source import _ns

_NY = ZoneInfo("America/New_York")
_DAYS = (
    date(2016, 3, 17),
    date(2016, 3, 18),
    date(2016, 3, 21),
    date(2016, 3, 29),
    date(2024, 1, 2),
    date(2025, 11, 4),
    date(2025, 12, 31),
)


def api():
    try:
        return importlib.import_module("trading_bot.market_data.etf_replay_adapter")
    except ModuleNotFoundError:
        pytest.fail("Native-source replay adapter is missing")


def quote(stamp="2016-03-18T13:30:01.123456789Z", **changes):
    return AlpacaQuoteRecord(
        **(
            dict(
                body_sha256="a" * 64,
                page_index=0,
                row_index=0,
                timestamp_ns=parse_timestamp_ns(stamp),
                bid=Decimal("100.01"),
                ask=Decimal("100.02"),
                bid_size=3,
                ask_size=7,
                bid_exchange="P",
                ask_exchange="N",
                conditions=("R", "Y"),
                tape="B",
            )
            | changes
        )
    )


@pytest.fixture
def inputs():
    sessions = tuple(
        EtfCalendarSession(
            day,
            datetime.combine(day, time(9, 30), _NY).astimezone(UTC),
            datetime.combine(day, time(16), _NY).astimezone(UTC),
        )
        for day in _DAYS
    )
    bars = tuple(
        AlpacaBarRecord(
            "b" * 64,
            0,
            index,
            _ns(datetime.combine(day, time(), _NY).astimezone(UTC)),
            Decimal("100"),
            Decimal("102"),
            Decimal("99"),
            Decimal("101"),
            1000,
            100,
            Decimal("100.5"),
        )
        for index, day in enumerate(_DAYS)
    )
    return dict(
        bars=EtfNativeBarsArchive(
            "c" * 64,
            AlpacaStockRequest(
                "bars",
                parse_timestamp_ns("2016-01-01T00:00:00Z"),
                parse_timestamp_ns("2026-01-01T00:00:00Z"),
            ),
            ("d" * 64,),
            bars,
            datetime(2026, 10, 1, tzinfo=UTC),
        ),
        quotes=(quote(),),
        calendar=EtfCalendarArchive("e" * 64, sessions),
        distributions=_parse(_pack(_parts())),
        quote_provenance_hash="f" * 64,
    )


def test_original_native_hashes_and_prices_survive_without_synthetic_relabeling(inputs):
    result = api().native_etf_dataset(**inputs)
    observed = next(event for event in result.events if event.kind == "quote")
    native = inputs["quotes"][0]
    assert observed.source_hash == native.record_hash
    assert observed.event_at_ns == observed.available_at_ns == 1458307801123456789
    assert (observed.bid, observed.ask) == (Decimal("100.01"), Decimal("100.02"))
    assert observed.bid_size is None and observed.ask_size is None
    assert {
        "historical_availability_unverified",
        "condition_eligibility_unverified",
        "control_coverage_unverified",
        "fractional_terms_unverified",
        "round_lot_conversion_unverified",
    } <= set(observed.execution_reasons)
    projected = [event for event in result.events if event.kind == "bar"]
    assert [event.source_hash for event in projected] == [
        record.record_hash for record in inputs["bars"].bars
    ]
    assert all(event.bar.source == "alpaca-sip-latest-vintage" for event in projected)
    assert projected[0].bar.ends_at == datetime(2016, 3, 18, 4, tzinfo=UTC)
    assert projected[0].event_at_ns == projected[0].available_at_ns
    assert result.source_kind == "native-latest-vintage" and result.source_qualified is False
    assert native.executable is False and native.publication_at_ns is None
    assert inputs["bars"].source_qualified is False


def test_native_share_era_sizes_are_descriptive_not_execution_capacity_authority(inputs):
    inputs["quotes"] = (quote("2025-11-04T14:30:01Z", bid_size=0, ask_size=4294967295),)
    result = api().native_etf_dataset(**inputs)
    observed = next(event for event in result.events if event.kind == "quote")
    assert observed.bid_size == Decimal("0") and observed.ask_size == Decimal("4294967295")
    assert "condition_eligibility_unverified" in observed.execution_reasons
    assert "control_coverage_unverified" in observed.execution_reasons


def test_transition_era_does_not_guess_share_capacity_or_drop_invalid_market_reasons(inputs):
    inputs["quotes"] = (
        quote("2025-11-03T16:00:00Z", bid=Decimal("102"), ask=Decimal("100"), conditions=()),
    )
    result = api().native_etf_dataset(**inputs)
    observed = next(event for event in result.events if event.kind == "quote")
    assert observed.bid_size is observed.ask_size is None
    assert {
        "size_transition_unverified",
        "crossed_quote",
        "condition_interpretation_unverified",
        "condition_eligibility_unverified",
    } <= set(observed.execution_reasons)


@pytest.mark.parametrize("field,count", [("bars", 10001), ("quotes", 128001)])
def test_bounded_intake_rejects_oversized_sources_before_projection(inputs, field, count):
    if field == "bars":
        inputs["bars"] = replace(inputs["bars"], bars=(inputs["bars"].bars[0],) * count)
    else:
        inputs["quotes"] = (inputs["quotes"][0],) * count
    with pytest.raises(ValueError, match=r"^etf_replay_adapter_invalid$"):
        api().native_etf_dataset(**inputs)


def test_bar_cannot_complete_after_actual_capture_time(inputs):
    inputs["bars"] = replace(inputs["bars"], captured_at=datetime(2025, 12, 31, 20, tzinfo=UTC))
    with pytest.raises(ValueError, match=r"^etf_replay_adapter_invalid$"):
        api().native_etf_dataset(**inputs)


def test_daylight_saving_projection_is_session_local_and_early_close_remains_exact(inputs):
    spring = date(2016, 3, 11)
    first = inputs["bars"].bars[0]
    inputs["bars"] = replace(
        inputs["bars"],
        bars=(replace(first, timestamp_ns=parse_timestamp_ns("2016-03-11T05:00:00Z")),),
    )
    extra = EtfCalendarSession(
        spring,
        datetime(2016, 3, 11, 14, 30, tzinfo=UTC),
        datetime(2016, 3, 11, 18, tzinfo=UTC),
    )
    inputs["calendar"] = replace(inputs["calendar"], sessions=(extra, *inputs["calendar"].sessions))
    result = api().native_etf_dataset(**inputs)
    bar = next(event for event in result.events if event.kind == "bar")
    assert bar.bar.ends_at == datetime(2016, 3, 12, 5, tzinfo=UTC)
    opened = next(event for event in result.events if event.kind == "session")
    assert opened.clock.next_close_at == datetime(2016, 3, 11, 18, tzinfo=UTC)
    assert opened.clock.next_open_at == datetime(2016, 3, 17, 13, 30, tzinfo=UTC)


def test_holdout_and_final_bar_retained_with_actual_next_midnight_completion(inputs):
    result = api().native_etf_dataset(**inputs)
    bars = [event for event in result.events if event.kind == "bar"]
    assert len(bars) == 7
    assert bars[-1].source_hash == inputs["bars"].bars[-1].record_hash
    assert bars[-1].bar.ends_at == datetime(2026, 1, 1, 5, tzinfo=UTC)
    assert "latest_vintage_bar_completion_following_new_york_midnight" in result.limitations
    assert "native_quote_timestamp_replay_availability_unverified" in result.limitations
    assert "distribution_date_to_session_open_assumption" in result.limitations


def test_calendar_open_close_use_exact_boundaries_but_cannot_certify_halt_coverage(inputs):
    result = api().native_etf_dataset(**inputs)
    clocks = [event for event in result.events if event.kind in ("session", "control")]
    assert len(clocks) == 14
    assert clocks[0].kind == "session" and clocks[0].clock.is_open
    assert clocks[0].clock.next_close_at == datetime(2016, 3, 17, 20, tzinfo=UTC)
    assert clocks[1].kind == "control" and not clocks[1].clock.is_open
    assert clocks[1].event_at_ns == parse_timestamp_ns("2016-03-17T20:00:00Z")
    assert all("control_coverage_unverified" in event.execution_reasons for event in clocks)
    assert clocks[-1].clock.next_open_at is None


def test_dividend_entitlement_and_payment_precede_quotes_at_exact_session_open(inputs):
    inputs["quotes"] = (quote("2016-03-18T13:30:00Z"),)
    result = api().native_etf_dataset(**inputs)
    distribution = inputs["distributions"].distributions[0]
    ex = next(event for event in result.events if event.kind == "dividend_ex")
    pay = next(event for event in result.events if event.kind == "dividend_pay")
    observation = next(event for event in result.events if event.kind == "quote")
    assert ex.action_id == pay.action_id == distribution.row_hash
    assert ex.source_hash == pay.source_hash == distribution.row_hash
    assert ex.cash_per_share == Decimal("1.234567890123456789")
    assert ex.event_at_ns == parse_timestamp_ns("2016-03-18T13:30:00Z")
    assert pay.event_at_ns == parse_timestamp_ns("2016-03-29T13:30:00Z")
    assert ex.ordinal < observation.ordinal
    assert ex.execution_reasons == pay.execution_reasons == ()


def test_equal_time_duplicate_and_conflicting_native_quotes_remain_observable(inputs):
    original = inputs["quotes"][0]
    inputs["quotes"] = (original, original, replace(original, row_index=1, bid=Decimal("99")))
    result = api().native_etf_dataset(**inputs)
    quotes = [event for event in result.events if event.kind == "quote"]
    assert len(quotes) == 3
    assert len({event.event_at_ns for event in quotes}) == 1
    assert quotes[0].source_hash == quotes[1].source_hash == original.record_hash
    assert quotes[0].ordinal < quotes[1].ordinal < quotes[2].ordinal
    assert quotes[2].bid == Decimal("99")


def test_missing_ex_or_payment_session_is_not_silently_shifted(inputs):
    inputs["calendar"] = replace(
        inputs["calendar"],
        sessions=tuple(
            s for s in inputs["calendar"].sessions if s.session_date != date(2016, 3, 29)
        ),
    )
    with pytest.raises(ValueError, match=r"^etf_replay_adapter_invalid$"):
        api().native_etf_dataset(**inputs)


def test_payment_beyond_calendar_horizon_retains_entitlement_without_inventing_cash(inputs):
    row = (
        "State Street SPDR S&P 500 ETF Trust",
        "SPY",
        "78462F103",
        "12/31/2025",
        "12/31/2025",
        "01/30/2026",
        "1.25",
        "",
        "0.000000",
        "Quarterly",
    )
    inputs["distributions"] = _parse(_pack(_parts((row,))))
    result = api().native_etf_dataset(**inputs)
    actions = [event for event in result.events if event.kind.startswith("dividend_")]
    assert len(actions) == 1 and actions[0].kind == "dividend_ex"
    assert actions[0].cash_per_share == Decimal("1.25")
    assert actions[0].action_id == inputs["distributions"].distributions[0].row_hash
    assert actions[0].source_hash == actions[0].action_id
    assert actions[0].event_at_ns == parse_timestamp_ns("2025-12-31T14:30:00Z")
    assert "payable_after_input_horizon" in result.limitations


def test_identity_binds_original_quote_provenance_and_raw_source_changes(inputs):
    first = api().native_etf_dataset(**inputs)
    inputs["quote_provenance_hash"] = "1" * 64
    changed = api().native_etf_dataset(**inputs)
    assert first.provenance_hash != changed.provenance_hash
    assert first.dataset_hash != changed.dataset_hash
    assert first.events == changed.events
    inputs["quotes"] = (replace(inputs["quotes"][0], body_sha256="2" * 64),)
    assert api().native_etf_dataset(**inputs).dataset_hash != changed.dataset_hash


@pytest.mark.parametrize(
    "field", ["bars", "quotes", "calendar", "distributions", "quote_provenance_hash"]
)
def test_invalid_top_level_inputs_have_sanitized_errors(inputs, field):
    inputs[field] = "sensitive-source-placeholder"
    with pytest.raises(ValueError, match=r"^etf_replay_adapter_invalid$"):
        api().native_etf_dataset(**inputs)


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("bars", "source_qualified", True),
        ("bars", "evidence_promotable", True),
        ("calendar", "source_qualified", True),
        ("distributions", "production_pretrade_eligible", True),
        ("quote", "executable", True),
        ("quote", "publication_at_ns", 1),
        ("bar", "publication_at_ns", 1),
        ("bar", "volume", -1),
    ],
)
def test_unsafe_nested_or_flag_mutations_cannot_be_reset_into_accepted_input(
    inputs, target, field, value
):
    item = (
        inputs["quotes"][0]
        if target == "quote"
        else inputs["bars"].bars[0]
        if target == "bar"
        else inputs[target]
    )
    object.__setattr__(item, field, value)
    with pytest.raises(ValueError, match=r"^etf_replay_adapter_invalid$"):
        api().native_etf_dataset(**inputs)


@pytest.mark.parametrize(
    "case",
    [
        "unsorted_quotes",
        "wrong_kind",
        "not_midnight",
        "out_of_request",
        "empty_receipts",
        "duplicate_bars",
        "empty_quotes",
    ],
)
def test_invalid_chronology_and_source_envelopes_fail_closed(inputs, case):
    source = inputs["bars"]
    if case == "unsorted_quotes":
        inputs["quotes"] = (quote("2016-03-18T13:30:02Z"), quote())
    elif case == "wrong_kind":
        inputs["bars"] = replace(source, request=replace(source.request, kind="quotes"))
    elif case == "not_midnight":
        inputs["bars"] = replace(
            source,
            bars=(
                replace(source.bars[0], timestamp_ns=source.bars[0].timestamp_ns + 1),
                *source.bars[1:],
            ),
        )
    elif case == "out_of_request":
        inputs["bars"] = replace(
            source, request=replace(source.request, start_ns=source.bars[0].timestamp_ns + 1)
        )
    elif case == "empty_receipts":
        inputs["bars"] = replace(source, receipt_hashes=())
    elif case == "duplicate_bars":
        inputs["bars"] = replace(source, bars=(source.bars[0], *source.bars))
    else:
        inputs["quotes"] = ()
    with pytest.raises(ValueError, match=r"^etf_replay_adapter_invalid$"):
        api().native_etf_dataset(**inputs)
