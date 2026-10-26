"""Fictional nine-symbol source graphs; no retained financial values or network."""

import csv
import hashlib
import importlib
import io
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal, DefaultContext, localcontext

import pytest

from trading_bot.market_data.stock_daily_series import parse_stock_daily_calendar
from trading_bot.market_data.stock_economic_evidence import (
    parse_cash_dividend_panel,
    parse_dated_stock_identity,
)
from trading_bot.market_data.stock_split_comparison import (
    StockSplitRequest,
    parse_stock_split_series,
)
from trading_bot.research.hybrid_strategies import FAMILIES as STRATEGY_FAMILIES

SYMBOLS = ("AXP", "AAPL", "BAC", "CVX", "KO", "KHC", "MCO", "OXY", "SPY")
FAMILIES = (
    "momentum",
    "trend",
    "breakout",
    "quality_momentum",
    "mean_reversion",
    "pead",
    "revision_momentum",
)
RECEIVED = datetime(2026, 10, 26, 12, tzinfo=UTC)
IDENTITY_HEADERS = (
    "ticker",
    "name",
    "market",
    "locale",
    "primary_exchange",
    "type",
    "active",
    "currency_name",
    "cik",
    "composite_figi",
    "share_class_figi",
    "list_date",
)
DIVIDEND_HEADERS = (
    "id",
    "ticker",
    "record_date",
    "pay_date",
    "declaration_date",
    "ex_dividend_date",
    "frequency",
    "cash_amount",
    "currency",
    "distribution_type",
)


def _module():
    return importlib.import_module("trading_bot.research.stock_monetary_admission")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _csv(headers, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def _json(value):
    return json.dumps(value, separators=(",", ":")).encode()


def _dates(count):
    days, day = [], date(2024, 1, 2)
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _identity(symbol, number, day, **changes):
    m = _module()
    row = {
        "ticker": symbol,
        "name": "Fictional issuer",
        "market": "stocks",
        "locale": "us",
        "primary_exchange": "XNAS",
        "type": "ETF" if symbol == "SPY" else "CS",
        "active": "true",
        "currency_name": "usd",
        "cik": f"{number + 1:010d}",
        "composite_figi": f"BBG{number + 1:09d}",
        "share_class_figi": f"CLS{number + 1:09d}",
        "list_date": "2000-01-01",
        **changes,
    }
    body = _csv(IDENTITY_HEADERS, [row])
    identity = parse_dated_stock_identity(
        body,
        expected_sha256=_sha(body),
        symbol=symbol,
        requested_date=day,
        received_at=RECEIVED,
    )
    return m.StockMonetaryIdentitySource(identity, body)


def _bindings(slots, calendar, dividends):
    m = _module()
    observations = []
    for slot in slots:
        for source in (slot.raw, slot.split):
            observations.append(
                (
                    f"price:{source.request.symbol}:{source.request.adjustment_type}",
                    source.content_sha256,
                    source.received_at,
                )
            )
        for label, source in zip(("start", "end"), slot.identities, strict=True):
            observations.append(
                (
                    f"identity:{source.identity.symbol}:{label}",
                    source.identity.original_csv_sha256,
                    source.identity.received_at,
                )
            )
    observations += [
        ("calendar", calendar.content_sha256, calendar.received_at),
        ("dividends", dividends[0].original_csv_sha256, dividends[0].received_at),
    ]
    return tuple(
        m.StockMonetarySourceBinding(
            role,
            digest,
            _sha(("fictional receipt " + role).encode()),
            stamp - timedelta(seconds=2),
            stamp,
        )
        for role, digest, stamp in observations
    )


def _event(symbol, identifier, ex, pay):
    return {
        "id": identifier,
        "ticker": symbol,
        "record_date": ex.isoformat(),
        "pay_date": "" if pay is None else pay.isoformat(),
        "declaration_date": (ex - timedelta(days=7)).isoformat(),
        "ex_dividend_date": ex.isoformat(),
        "frequency": "4",
        "cash_amount": "0.375",
        "currency": "USD",
        "distribution_type": "recurring",
    }


def _request(count=204, *, events=None):
    m = _module()
    days = _dates(count)
    calendar_body = _json(
        {
            "request": {"start_date": days[0].isoformat(), "end_date": days[-1].isoformat()},
            "calendar": [
                {
                    "date": d.isoformat(),
                    "open": d.isoformat() + "T09:30:00",
                    "close": d.isoformat() + "T16:00:00",
                }
                for d in days
            ],
        }
    )
    calendar = parse_stock_daily_calendar(
        calendar_body,
        expected_sha256=_sha(calendar_body),
        received_at=RECEIVED,
        market_timezone="America/New_York",
    )
    slots = []
    for number, symbol in enumerate(SYMBOLS):
        sources = []
        for adjustment in ("none", "split"):
            body = _json(
                {
                    "data": {
                        "results": [
                            {
                                "symbol": symbol,
                                "interval": "day",
                                "bounds": "regular",
                                "bars": [
                                    {
                                        "begins_at": d.isoformat() + "T00:00:00Z",
                                        "open_price": "75.125",
                                        "high_price": "76",
                                        "low_price": "74",
                                        "close_price": "75.5",
                                        "volume": 500000,
                                        "session": "reg",
                                    }
                                    for d in days
                                ],
                            }
                        ]
                    },
                    "guide": "Fictional untrusted source narrative.",
                }
            )
            req = StockSplitRequest(
                symbol,
                datetime.combine(days[0], datetime.min.time(), UTC),
                datetime.combine(days[-1] + timedelta(days=1), datetime.min.time(), UTC),
                adjustment,
            )
            sources.append(
                parse_stock_split_series(
                    body,
                    expected_sha256=_sha(body),
                    request=req,
                    received_at=RECEIVED,
                )
            )
        slots.append(
            m.StockMonetarySymbolSources(
                *sources,
                (_identity(symbol, number, days[0]), _identity(symbol, number, days[-1])),
            )
        )
    rows = (
        events
        if events is not None
        else [
            _event("AXP", "early", days[199], days[201]),
            _event("AXP", "activation", days[200], days[202]),
            _event("AXP", "unpaid", days[201], days[-1] + timedelta(days=10)),
            _event("SPY", "unknown-pay", days[202], None),
        ]
    )
    body = _csv(DIVIDEND_HEADERS, rows)
    dividends = parse_cash_dividend_panel(
        body,
        expected_sha256=_sha(body),
        symbols=SYMBOLS,
        ex_start=days[0],
        ex_end=days[-1],
        received_at=RECEIVED,
    )
    return m.StockMonetaryRequest(
        tuple(slots),
        calendar,
        dividends,
        body,
        "a" * 64,
        _bindings(slots, calendar, dividends),
        m.StockMonetaryAssumptions(),
    )


def _prepare(request=None):
    return _module().prepare_retrospective_monetary_inputs(
        _request() if request is None else request
    )


def _rebind(request, **changes):
    value = replace(request, **changes)
    return replace(value, source_bindings=_bindings(value.slots, value.calendar, value.dividends))


def test_prepares_all_original_slots_without_claiming_constrained_family_success():
    m = _module()
    request = _request(260)
    result = _prepare(request)
    assert isinstance(result, m.PreparedRetrospectiveMonetaryInputs)
    assert result.status == "conditionally_prepared_observed_event_inputs"
    assert result.request is request
    assert tuple(slot.symbol for slot in result.symbols) == SYMBOLS
    assert tuple(slot.role for slot in result.symbols) == ("stock_candidate",) * 8 + ("benchmark",)
    assert result.symbols[0].sources is request.slots[0]
    assert result.families == STRATEGY_FAMILIES == FAMILIES and len(result.cases) == 56
    assert all(case.symbol != "SPY" for case in result.cases)
    assert all(case.evaluation_status == "unavailable" for case in result.cases)
    trend = next(case for case in result.cases if case.symbol == "AXP" and case.family == "trend")
    quality = next(
        case for case in result.cases if case.symbol == "AXP" and case.family == "quality_momentum"
    )
    assert trend.signal_inputs_status == "conditionally_prepared"
    assert quality.signal_inputs_status == "unavailable"
    assert "publication_aware_annual_quality_unavailable" in quality.reason_codes
    assert "causal_risk_metadata_unavailable" in trend.reason_codes
    assert result.calendar_padding == () and result.calendar_padding_status == "unavailable"
    assert result.complete_action_coverage is False
    assert result.full_constrained_portfolio_status == "unavailable"
    assert result.symbols[0].native_quote_currency is None
    assert result.symbols[0].interpreted_account_currency == "USD"
    assert request.slots[0].raw.bars[0].interpolated is None
    assert request.slots[0].raw.received_at == RECEIVED
    assert len(result.source_graph_sha256) == 64
    assert m.revalidate_monetary_inputs(result) is result
    assert len(result.evidence_hash) == 64


def test_activation_events_cannot_be_earned_and_terminal_events_cannot_be_cash():
    result = _prepare()
    axp, spy = result.symbols[0], result.symbols[-1]
    assert tuple(event.id for event in axp.not_earned_events) == ("early", "activation")
    assert tuple(event.id for event in axp.holding_dependent_events) == ("unpaid",)
    assert tuple(event.id for event in axp.unpaid_terminal_events) == ("unpaid",)
    assert tuple(event.id for event in spy.unpaid_terminal_events) == ("unknown-pay",)
    assert axp.cash_available is spy.cash_available is False
    assert axp.entitlement_calculated is spy.entitlement_calculated is False
    assert (
        axp.holding_dependent_events[0].source_csv_sha256
        == result.request.dividends[0].original_csv_sha256
    )


def test_empty_symbol_inventory_is_preserved_without_asserting_no_actions():
    result = _prepare()
    oxy = result.symbols[7]
    assert oxy.symbol == "OXY" and oxy.holding_dependent_events == ()
    assert oxy.cash_inventory_complete is False
    assert result.complete_action_coverage is False


def test_nonprice_families_and_insufficient_momentum_remain_named_unavailable():
    result = _prepare()
    cases = {case.family: case for case in result.cases if case.symbol == "AXP"}
    assert cases["momentum"].signal_inputs_status == "unavailable"
    assert "insufficient_history" in cases["momentum"].reason_codes
    assert "publication_aware_earnings_unavailable" in cases["pead"].reason_codes
    assert "historical_estimate_vintages_unavailable" in cases["revision_momentum"].reason_codes


@pytest.mark.parametrize(
    "change", ["missing_slot", "wrong_order", "wrong_manifest", "extra_binding"]
)
def test_bad_graph_retains_every_requested_denominator(change):
    m = _module()
    request = _request()
    if change == "missing_slot":
        request = replace(request, slots=request.slots[:-1])
    elif change == "wrong_order":
        request = replace(request, slots=tuple(reversed(request.slots)))
    elif change == "wrong_manifest":
        request = replace(request, handoff_manifest_sha256="missing")
    else:
        request = replace(
            request, source_bindings=(*request.source_bindings, request.source_bindings[0])
        )
    result = _prepare(request)
    assert isinstance(result, m.UnavailableRetrospectiveMonetaryInputs)
    assert tuple(slot.symbol for slot in result.symbols) == SYMBOLS
    assert result.families == FAMILIES and len(result.cases) == 56
    assert result.reason_codes
    assert all(case.signal_inputs_status == "unavailable" for case in result.cases)


@pytest.mark.parametrize(
    "change",
    ["bytes", "derived_bar", "request", "flag", "missing", "null", "zero_volume", "synthetic"],
)
def test_price_whole_source_is_reparsed_instead_of_trusting_normalized_rows(change):
    m = _module()
    request = _request()
    source = request.slots[0].raw
    if change == "bytes":
        source = replace(source, original_content_json=source.original_content_json + b" ")
    elif change == "derived_bar":
        source = replace(
            source, bars=(replace(source.bars[0], close_price=Decimal("75.25")), *source.bars[1:])
        )
    elif change == "request":
        source = replace(source, request=replace(source.request, symbol="OTHER"))
    elif change == "flag":
        object.__setattr__(source, "source_qualified", True)
    else:
        payload = json.loads(source.original_content_json)
        bars = payload["data"]["results"][0]["bars"]
        if change == "missing":
            bars.pop()
        elif change == "null":
            bars[10] = None
        else:
            bars[10]["volume"] = 0
            if change == "synthetic":
                bars[10]["interpolated"] = True
        body = _json(payload)
        source = parse_stock_split_series(
            body, expected_sha256=_sha(body), request=source.request, received_at=RECEIVED
        )
    first = replace(request.slots[0], raw=source)
    request = _rebind(request, slots=(first, *request.slots[1:]))
    result = _prepare(request)
    assert isinstance(result, m.UnavailableRetrospectiveMonetaryInputs)
    assert result.reason_codes


def test_split_price_unit_change_is_unavailable_without_inventing_action_conversion():
    m = _module()
    request = _request()
    source = request.slots[3].split
    payload = json.loads(source.original_content_json)
    payload["data"]["results"][0]["bars"][0]["close_price"] = "75.25"
    body = _json(payload)
    split = parse_stock_split_series(
        body, expected_sha256=_sha(body), request=source.request, received_at=RECEIVED
    )
    slots = (*request.slots[:3], replace(request.slots[3], split=split), *request.slots[4:])
    result = _prepare(_rebind(request, slots=slots))
    assert isinstance(result, m.UnavailableRetrospectiveMonetaryInputs)
    assert "raw_split_units_not_supported" in result.reason_codes


@pytest.mark.parametrize(
    "field,value",
    [
        ("cik", "0000888888"),
        ("composite_figi", "BBG999999999"),
        ("share_class_figi", "CLS999999999"),
        ("type", "ETF"),
        ("active", "false"),
    ],
)
def test_endpoint_core_identity_conflict_is_not_a_ticker_mapping_repair(field, value):
    m = _module()
    request = _request()
    first = request.slots[0]
    changed = _identity("AXP", 0, request.calendar.sessions[-1].session_date, **{field: value})
    slots = (replace(first, identities=(first.identities[0], changed)), *request.slots[1:])
    result = _prepare(_rebind(request, slots=slots))
    assert isinstance(result, m.UnavailableRetrospectiveMonetaryInputs)
    assert "identity_core_conflict" in result.reason_codes


def test_incidental_identity_changes_stay_native_with_no_invented_effective_date():
    request = _request()
    end = _identity(
        "AXP",
        0,
        request.calendar.sessions[-1].session_date,
        name="Fictional new label",
        primary_exchange="XNYS",
        list_date="2001-01-01",
    )
    first = replace(request.slots[0], identities=(request.slots[0].identities[0], end))
    result = _prepare(_rebind(request, slots=(first, *request.slots[1:])))
    assert isinstance(result, _module().PreparedRetrospectiveMonetaryInputs)
    assert result.symbols[0].sources.identities[1].identity.name == "Fictional new label"
    assert result.symbols[0].incidental_identity_changes == (
        "name",
        "primary_exchange",
        "list_date",
    )


@pytest.mark.parametrize("change", ["csv", "endpoint", "missing_core", "derived_identity"])
def test_identity_whole_bytes_endpoint_dates_and_native_values_are_bound(change):
    request = _request()
    first = request.slots[0]
    end = first.identities[1]
    if change == "csv":
        end = replace(end, original_csv=end.original_csv + b" ")
    elif change == "endpoint":
        end = replace(end, identity=replace(end.identity, requested_date=date(2024, 2, 1)))
    elif change == "missing_core":
        end = _identity("AXP", 0, request.calendar.sessions[-1].session_date, cik="")
    else:
        end = replace(end, identity=replace(end.identity, name="Unrecorded label"))
    result = _prepare(
        _rebind(
            request,
            slots=(replace(first, identities=(first.identities[0], end)), *request.slots[1:]),
        )
    )
    assert isinstance(result, _module().UnavailableRetrospectiveMonetaryInputs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("observation_sha256", "b" * 64),
        ("receipt_sha256", "bad"),
        ("received_at", RECEIVED + timedelta(seconds=1)),
        ("requested_at", RECEIVED + timedelta(seconds=1)),
        ("requested_at", RECEIVED.replace(tzinfo=None)),
    ],
)
def test_original_receipt_binding_clock_and_hash_mismatches_are_unavailable(field, value):
    request = _request()
    binding = replace(request.source_bindings[0], **{field: value})
    result = _prepare(replace(request, source_bindings=(binding, *request.source_bindings[1:])))
    assert isinstance(result, _module().UnavailableRetrospectiveMonetaryInputs)
    assert "source_binding_invalid" in result.reason_codes


def test_calendar_is_rebuilt_and_missing_padding_is_not_generated_from_weekdays():
    request = _request()
    calendar = replace(request.calendar, sessions=request.calendar.sessions[:-1])
    result = _prepare(replace(request, calendar=calendar))
    assert isinstance(result, _module().UnavailableRetrospectiveMonetaryInputs)
    good = _prepare(request)
    assert good.calendar_padding == ()
    assert good.calendar_padding_status == "unavailable"


def test_global_cash_panel_contamination_cannot_hide_behind_per_symbol_views():
    request = _request()
    rows = list(csv.DictReader(io.StringIO(request.original_dividend_csv.decode())))
    # The bad row is after otherwise-valid AXP/SPY rows, in another symbol.
    rows.append(_event("OTHER", "outside-panel", _dates(204)[201], None))
    body = _csv(DIVIDEND_HEADERS, rows)
    digest = _sha(body)
    inventory = tuple(
        replace(
            item,
            original_csv_sha256=digest,
            events=tuple(replace(event, source_csv_sha256=digest) for event in item.events),
        )
        for item in request.dividends
    )
    result = _prepare(_rebind(request, dividends=inventory, original_dividend_csv=body))
    assert isinstance(result, _module().UnavailableRetrospectiveMonetaryInputs)
    assert "cash_panel_source_graph_invalid" in result.reason_codes


def test_global_duplicate_cash_id_and_forged_inventory_are_unavailable():
    request = _request()
    rows = list(csv.DictReader(io.StringIO(request.original_dividend_csv.decode())))
    rows.append(_event("OXY", "unpaid", _dates(204)[202], None))
    body = _csv(DIVIDEND_HEADERS, rows)
    result = _prepare(replace(request, original_dividend_csv=body))
    assert isinstance(result, _module().UnavailableRetrospectiveMonetaryInputs)
    first = replace(request.dividends[0], events=request.dividends[0].events[:-1])
    result = _prepare(replace(request, dividends=(first, *request.dividends[1:])))
    assert isinstance(result, _module().UnavailableRetrospectiveMonetaryInputs)


def test_all_scope_flags_are_permanently_false_and_public_construction_cannot_promote():
    m = _module()
    request = _request()
    result = _prepare(request)
    for flag in (
        "qualified",
        "source_qualified",
        "strategy_qualified",
        "investment_eligible",
        "trading_enabled",
        "live_authorized",
    ):
        assert getattr(result, flag) is False
        with pytest.raises((ValueError, TypeError)):
            replace(result, **{flag: True})
    with pytest.raises(FrozenInstanceError):
        result.status = "qualified"
    with pytest.raises(m.StockMonetaryAdmissionError):
        m.UnavailableRetrospectiveMonetaryInputs(request)
    with pytest.raises(m.StockMonetaryAdmissionError):
        m.PreparedRetrospectiveMonetaryInputs(replace(request, slots=()))
    object.__setattr__(result, "qualified", True)
    with pytest.raises(m.StockMonetaryAdmissionError):
        m.revalidate_monetary_inputs(result)


def test_new_preparation_and_fresh_revalidation_detect_mutated_unused_source_guide():
    m = _module()
    request = _request()
    result = _prepare(request)
    previous = result.evidence_hash
    source = request.slots[0].raw
    payload = json.loads(source.original_content_json)
    payload["guide"] = "Changed but still untrusted unused source text."
    body = _json(payload)
    fresh = parse_stock_split_series(
        body, expected_sha256=_sha(body), request=source.request, received_at=RECEIVED
    )
    first = replace(request.slots[0], raw=fresh)
    newer = _prepare(_rebind(request, slots=(first, *request.slots[1:])))
    assert newer.evidence_hash != previous
    object.__setattr__(source, "original_content_json", body)
    object.__setattr__(source, "content_sha256", _sha(body))
    with pytest.raises(m.StockMonetaryAdmissionError):
        m.revalidate_monetary_inputs(result)


def test_derived_case_or_digest_tampering_cannot_change_unavailability_into_clearance():
    m = _module()
    result = _prepare()
    object.__setattr__(result.cases[0], "evaluation_status", "qualified")
    with pytest.raises(m.StockMonetaryAdmissionError):
        m.revalidate_monetary_inputs(result)
    result = _prepare()
    object.__setattr__(result, "source_graph_sha256", "0" * 64)
    with pytest.raises(m.StockMonetaryAdmissionError):
        m.revalidate_monetary_inputs(result)


def test_complete_graph_hash_and_preparation_ignore_ambient_decimal_context():
    request = _request()
    original = DefaultContext.copy()
    try:
        values = []
        for rounding in (ROUND_DOWN, ROUND_UP):
            DefaultContext.prec = 3
            DefaultContext.rounding = rounding
            with localcontext() as context:
                context.prec = 2
                context.rounding = rounding
                result = _prepare(request)
                values.append((result.source_graph_sha256, result.evidence_hash))
        assert values[0] == values[1]
    finally:
        DefaultContext.prec = original.prec
        DefaultContext.rounding = original.rounding
        DefaultContext.Emin = original.Emin
        DefaultContext.Emax = original.Emax
        DefaultContext.capitals = original.capitals
        DefaultContext.clamp = original.clamp
        DefaultContext.flags = original.flags.copy()
        DefaultContext.traps = original.traps.copy()


def test_exponent_price_source_hash_ignores_decimal_capitals_in_both_contexts():
    request = _request()
    pair = []
    for source in (request.slots[0].raw, request.slots[0].split):
        payload = json.loads(source.original_content_json)
        bar = payload["data"]["results"][0]["bars"][0]
        for field in ("open_price", "high_price", "low_price", "close_price"):
            bar[field] = "1e2"
        body = _json(payload)
        pair.append(
            parse_stock_split_series(
                body,
                expected_sha256=_sha(body),
                request=source.request,
                received_at=RECEIVED,
            )
        )
    first = replace(request.slots[0], raw=pair[0], split=pair[1])
    request = _rebind(request, slots=(first, *request.slots[1:]))
    previous = DefaultContext.capitals
    try:
        outputs = []
        for capitals in (0, 1):
            DefaultContext.capitals = capitals
            with localcontext() as context:
                context.capitals = capitals
                result = _prepare(request)
                outputs.append((result.source_graph_sha256, result.evidence_hash))
        assert outputs[0] == outputs[1]
        with localcontext() as context:
            context.capitals = 0
            assert _module().revalidate_monetary_inputs(result) is result
    finally:
        DefaultContext.capitals = previous


@pytest.mark.parametrize("sessions", [None, False, 7])
def test_malformed_derived_calendar_remains_typed_unavailable(sessions):
    request = _request()
    malformed = replace(request.calendar, sessions=sessions)
    result = _prepare(replace(request, calendar=malformed))
    assert isinstance(result, _module().UnavailableRetrospectiveMonetaryInputs)
    assert result.reason_codes == ("calendar_source_graph_invalid",)
    assert len(result.symbols) == 9 and len(result.cases) == 56
    assert all(case.evaluation_status == "unavailable" for case in result.cases)


def test_dividend_pay_date_on_final_session_stays_unpaid_under_next_open_funding():
    days = _dates(204)
    request = _request(events=[_event("AXP", "last-day-pay", days[201], days[-1])])
    result = _prepare(request)
    axp = result.symbols[0]
    assert tuple(event.id for event in axp.holding_dependent_events) == ("last-day-pay",)
    assert tuple(event.id for event in axp.unpaid_terminal_events) == ("last-day-pay",)
    assert axp.cash_available is False and axp.entitlement_calculated is False
    assert result.calendar_padding == ()
