"""Fictional economic observations; no licensed provider rows or network calls."""

import csv
import hashlib
import io
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, ROUND_UP, Decimal, DefaultContext, localcontext

import pytest

from trading_bot.market_data.stock_economic_evidence import (
    StockEconomicEvidenceError,
    dividend_entitlement,
    parse_cash_dividend_panel,
    parse_cash_dividends,
    parse_dated_stock_identity,
)

RECEIVED = datetime(2026, 6, 15, 12, tzinfo=UTC)
IDENTITY_FIELDS = (
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
    "market_cap",
    "description",
)
DIVIDEND_FIELDS = (
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
    "historical_adjustment_factor",
    "split_adjusted_cash_amount",
)


def _csv(fields: tuple[str, ...], rows: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def _identity_row(**changes: str) -> dict[str, str]:
    return {
        "ticker": "FICT",
        "name": "Fictional, Incorporated",
        "market": "stocks",
        "locale": "us",
        "primary_exchange": "XNAS",
        "type": "CS",
        "active": "true",
        "currency_name": "usd",
        "cik": "0000999999",
        "composite_figi": "BBG00FICTION",
        "share_class_figi": "BBG00CLASSXX",
        "list_date": "2001-02-03",
        "market_cap": "99999999",
        "description": "Untrusted financial narrative",
        **changes,
    }


def _dividend_row(**changes: str) -> dict[str, str]:
    return {
        "id": "fictional-event-1",
        "ticker": "FICT",
        "record_date": "2026-06-01",
        "pay_date": "2026-06-20",
        "declaration_date": "2026-05-15",
        "ex_dividend_date": "2026-06-02",
        "frequency": "4",
        "cash_amount": "0.375",
        "currency": "USD",
        "distribution_type": "recurring",
        "historical_adjustment_factor": "",
        "split_adjusted_cash_amount": "99",
        **changes,
    }


def _identity(blob: bytes | None = None, **kwargs: object):
    data = _csv(IDENTITY_FIELDS, [_identity_row()]) if blob is None else blob
    options = {
        "expected_sha256": hashlib.sha256(data).hexdigest(),
        "symbol": "FICT",
        "requested_date": date(2024, 1, 2),
        "received_at": RECEIVED,
        **kwargs,
    }
    return parse_dated_stock_identity(data, **options)


def _dividends(blob: bytes | None = None, **kwargs: object):
    data = _csv(DIVIDEND_FIELDS, [_dividend_row()]) if blob is None else blob
    options = {
        "expected_sha256": hashlib.sha256(data).hexdigest(),
        "symbol": "FICT",
        "ex_start": date(2026, 1, 1),
        "ex_end": date(2026, 6, 15),
        "received_at": RECEIVED,
        **kwargs,
    }
    return parse_cash_dividends(data, **options)


def _accrual(**kwargs: object):
    options = {
        "shares_before_ex": Decimal("8"),
        "held_at": date(2026, 6, 1),
        "as_of": date(2026, 6, 15),
        **kwargs,
    }
    return dividend_entitlement(_dividends().events[0], **options)


def test_identity_keeps_only_security_information_and_binds_request() -> None:
    blob = _csv(IDENTITY_FIELDS, [_identity_row()])
    item = _identity(blob)
    assert item.symbol == "FICT"
    assert item.name == "Fictional, Incorporated"
    assert item.currency_name == "usd" and item.currency == "USD"
    assert item.cik == "0000999999"
    assert item.composite_figi == "BBG00FICTION"
    assert item.share_class_figi == "BBG00CLASSXX"
    assert item.security_type == "CS" and item.primary_exchange == "XNAS"
    assert item.list_date == date(2001, 2, 3)
    assert item.active is True and item.market == "stocks" and item.locale == "us"
    assert item.requested_date == date(2024, 1, 2) and item.received_at == RECEIVED
    assert item.original_csv_sha256 == hashlib.sha256(blob).hexdigest()
    assert not hasattr(item, "market_cap") and not hasattr(item, "description")


@pytest.mark.parametrize("currency", ["USD", "usd"])
def test_identity_preserves_native_currency_casing(currency: str) -> None:
    item = _identity(_csv(IDENTITY_FIELDS, [_identity_row(currency_name=currency)]))
    assert item.currency_name == currency and item.currency == "USD"


def test_identity_preserves_inactive_and_missing_identifiers() -> None:
    item = _identity(
        _csv(
            IDENTITY_FIELDS,
            [
                _identity_row(
                    active="false",
                    cik="",
                    composite_figi="",
                    share_class_figi="",
                    list_date="",
                )
            ],
        )
    )
    assert item.active is False
    assert (item.cik, item.composite_figi, item.share_class_figi, item.list_date) == (
        None,
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ticker", "OTHER"),
        ("market", "crypto"),
        ("locale", "gb"),
        ("active", "True"),
        ("active", "1"),
        ("currency_name", "CAD"),
        ("currency_name", ""),
        ("currency_name", " USD"),
        ("cik", "not-cik"),
        ("list_date", "2024-02-30"),
        ("list_date", "2025-01-01"),
    ],
)
def test_identity_rejects_invalid_scope_or_security_fields(field: str, value: str) -> None:
    with pytest.raises(StockEconomicEvidenceError):
        _identity(_csv(IDENTITY_FIELDS, [_identity_row(**{field: value})]))


@pytest.mark.parametrize(
    "rows",
    [[], [_identity_row(), _identity_row()], [_identity_row(), _identity_row(ticker="OTHER")]],
)
def test_identity_requires_exactly_one_matching_row(rows: list[dict[str, str]]) -> None:
    with pytest.raises(StockEconomicEvidenceError):
        _identity(_csv(IDENTITY_FIELDS, rows))


def test_dividends_keep_original_cash_amount_dates_and_unknowns() -> None:
    data = _csv(DIVIDEND_FIELDS, [_dividend_row()])
    result = _dividends(data)
    event = result.events[0]
    assert event.id == "fictional-event-1" and event.ticker == event.symbol == "FICT"
    assert event.cash_amount == Decimal("0.375") and event.currency == "USD"
    assert event.ex_dividend_date == event.ex_date == date(2026, 6, 2)
    assert event.record_date == date(2026, 6, 1)  # Deliberately before ex-date.
    assert event.pay_date == date(2026, 6, 20)
    assert event.declaration_date == date(2026, 5, 15)
    assert event.frequency == 4 and event.distribution_type == "recurring"
    assert not hasattr(event, "historical_adjustment_factor")
    assert result.original_csv_sha256 == hashlib.sha256(data).hexdigest()
    assert result.received_at == RECEIVED and result.symbol == "FICT"
    assert (result.ex_start, result.ex_end) == (date(2026, 1, 1), date(2026, 6, 15))


def test_dividend_optional_fields_stay_unknown() -> None:
    result = _dividends(
        _csv(
            DIVIDEND_FIELDS,
            [
                _dividend_row(
                    pay_date="",
                    record_date="",
                    declaration_date="",
                    frequency="",
                    distribution_type="",
                )
            ],
        )
    )
    event = result.events[0]
    assert (
        event.pay_date,
        event.record_date,
        event.declaration_date,
        event.frequency,
        event.distribution_type,
    ) == (None, None, None, None, None)


def test_empty_cash_observation_does_not_claim_zero_distributions_or_completeness() -> None:
    result = _dividends(_csv(DIVIDEND_FIELDS, []))
    assert result.events == ()
    assert result.qualified is False
    assert "no_http_status_or_pagination_proof" in result.limitations


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", ""),
        ("ticker", "OTHER"),
        ("cash_amount", "0"),
        ("cash_amount", "-1"),
        ("cash_amount", "NaN"),
        ("cash_amount", "Infinity"),
        ("cash_amount", "1e999999"),
        ("cash_amount", "true"),
        ("cash_amount", ""),
        ("currency", "CAD"),
        ("currency", ""),
        ("ex_dividend_date", ""),
        ("ex_dividend_date", "2025-12-31"),
        ("ex_dividend_date", "2026-06-16"),
        ("ex_dividend_date", "2026-6-2"),
        ("declaration_date", "2026-06-16"),
        ("declaration_date", "2026-06-03"),
        ("pay_date", "2026-06-01"),
        ("frequency", "-1"),
        ("frequency", "1.5"),
        ("frequency", "true"),
        ("distribution_type", "made-up"),
    ],
)
def test_dividends_reject_invalid_economics_or_dates(field: str, value: str) -> None:
    with pytest.raises(StockEconomicEvidenceError):
        _dividends(_csv(DIVIDEND_FIELDS, [_dividend_row(**{field: value})]))


@pytest.mark.parametrize(
    "second",
    [
        _dividend_row(),
        _dividend_row(cash_amount="0.5"),
        _dividend_row(id="different-native-id"),
        _dividend_row(id="different-native-id", cash_amount="0.3750"),
    ],
)
def test_dividends_reject_duplicate_ids_and_economic_events(second: dict[str, str]) -> None:
    with pytest.raises(StockEconomicEvidenceError):
        _dividends(_csv(DIVIDEND_FIELDS, [_dividend_row(), second]))


@pytest.mark.parametrize("kind", ["identity", "dividends"])
@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_header",
        "missing_header",
        "extra_cell",
        "missing_cell",
        "quote_tail",
        "unclosed_quote",
        "quote_inside_unquoted",
        "blank_row",
        "non_utf8",
        "nul",
        "oversized",
    ],
)
def test_strict_csv_rejects_ambiguous_or_unbounded_input(kind: str, fault: str) -> None:
    fields = IDENTITY_FIELDS if kind == "identity" else DIVIDEND_FIELDS
    row = _identity_row() if kind == "identity" else _dividend_row()
    data = _csv(fields, [row])
    header, body = data.split(b"\n", 1)
    cases = {
        "duplicate_header": header + b"," + fields[0].encode() + b"\n" + body,
        "missing_header": _csv(fields[1:], [{k: v for k, v in row.items() if k != fields[0]}]),
        "extra_cell": header + b"\n" + body.rstrip(b"\n") + b",extra\n",
        "missing_cell": header + b"\n" + b"FICT\n",
        "quote_tail": header + b'\n"bad"tail\n',
        "unclosed_quote": header + b'\n"unfinished\n',
        "quote_inside_unquoted": data.replace(b"FICT", b'FI"CT', 1),
        "blank_row": data + b"\n",
        "non_utf8": data + b"\xff",
        "nul": data.replace(b"FICT", b"FI\x00CT", 1),
        "oversized": data + b"x" * 1_048_577,
    }
    with pytest.raises(StockEconomicEvidenceError):
        (_identity if kind == "identity" else _dividends)(cases[fault])


@pytest.mark.parametrize("parser", [_identity, _dividends])
def test_hash_clock_and_symbol_request_cannot_be_forged(parser) -> None:
    for kwargs in (
        {"expected_sha256": "0" * 64},
        {"expected_sha256": "invalid"},
        {"received_at": RECEIVED.replace(tzinfo=None)},
        {"received_at": RECEIVED.astimezone(timezone(timedelta(hours=1)))},
        {"symbol": "fict"},
        {"symbol": True},
    ):
        with pytest.raises(StockEconomicEvidenceError):
            parser(**kwargs)


def test_request_dates_are_bounded_by_receipt_and_exact_dates() -> None:
    for kwargs in ({"requested_date": date(2027, 1, 1)}, {"requested_date": RECEIVED}):
        with pytest.raises(StockEconomicEvidenceError):
            _identity(**kwargs)
    for kwargs in ({"ex_start": date(2026, 7, 1)}, {"ex_start": RECEIVED}):
        with pytest.raises(StockEconomicEvidenceError):
            _dividends(**kwargs)


def test_known_future_ex_date_is_not_early_cash() -> None:
    event = _dividends(
        _csv(
            DIVIDEND_FIELDS,
            [
                _dividend_row(
                    ex_dividend_date="2026-06-18",
                    pay_date="2026-06-25",
                    declaration_date="2026-06-01",
                )
            ],
        ),
        ex_end=date(2026, 6, 30),
    ).events[0]
    result = dividend_entitlement(
        event, shares_before_ex=Decimal("8"), held_at=date(2026, 6, 14), as_of=date(2026, 6, 15)
    )
    assert result.accrued_amount == result.receivable == result.cash_available == 0


@pytest.mark.parametrize("maker", [_identity, _dividends, _accrual])
def test_observations_do_not_grant_investment_or_live_authorization(maker) -> None:
    result = maker()
    assert result.qualified is result.investment_eligible is result.live_authorized is False
    with pytest.raises(FrozenInstanceError):
        result.live_authorized = True
    with pytest.raises((TypeError, ValueError)):
        replace(result, qualified=True)


@pytest.mark.parametrize(
    ("day", "receivable", "cash"),
    [
        (date(2026, 6, 1), "0", "0"),
        (date(2026, 6, 2), "3", "0"),
        (date(2026, 6, 19), "3", "0"),
        (date(2026, 6, 20), "0", "3"),
        (date(2026, 6, 21), "0", "3"),
    ],
)
def test_accrual_separates_entitlement_receivable_and_cash(day, receivable, cash) -> None:
    result = _accrual(as_of=day)
    assert result.receivable == Decimal(receivable)
    assert result.cash_available == Decimal(cash)
    assert result.accrued_amount == Decimal("0" if day < date(2026, 6, 2) else "3")


@pytest.mark.parametrize("held_at", [date(2026, 6, 2), date(2026, 6, 3)])
def test_same_day_or_later_purchase_has_no_dividend_entitlement(held_at: date) -> None:
    result = _accrual(held_at=held_at, as_of=date(2026, 6, 21))
    assert result.accrued_amount == result.receivable == result.cash_available == 0


def test_unknown_pay_date_stays_receivable_without_forecast() -> None:
    event = _dividends(_csv(DIVIDEND_FIELDS, [_dividend_row(pay_date="")])).events[0]
    result = dividend_entitlement(
        event, shares_before_ex=Decimal("8"), held_at=date(2026, 6, 1), as_of=date(2028, 1, 1)
    )
    assert result.receivable == Decimal("3") and result.cash_available == 0


def test_accrual_arithmetic_uses_precision_50_independent_of_callers_context() -> None:
    with localcontext() as context:
        context.prec = 3
        result = _accrual(shares_before_ex=Decimal("123456789.123456789"))
    assert result.accrued_amount == Decimal("46296295.921296295875")


@pytest.mark.parametrize("rounding", [ROUND_DOWN, ROUND_UP])
def test_accrual_rounding_is_independent_of_mutable_default_and_ambient_contexts(rounding) -> None:
    event = _dividends().events[0]
    original = DefaultContext.copy()
    try:
        DefaultContext.rounding = rounding
        with localcontext() as ambient:
            ambient.prec = 2
            ambient.rounding = rounding
            result = dividend_entitlement(
                event,
                shares_before_ex=Decimal("1." + "1" * 60),
                held_at=date(2026, 6, 1),
                as_of=date(2026, 6, 15),
            )
            assert ambient.prec == 2 and ambient.rounding == rounding
        assert result.accrued_amount == Decimal(
            "0.41666666666666666666666666666666666666666666666667"
        )
    finally:
        DefaultContext.rounding = original.rounding


def test_accrual_ignores_default_exponents_flags_and_traps_without_mutating_them() -> None:
    event = _dividends().events[0]
    original = DefaultContext.copy()
    try:
        DefaultContext.prec = 2
        DefaultContext.rounding = ROUND_DOWN
        DefaultContext.Emin = -2
        DefaultContext.Emax = 2
        DefaultContext.capitals = 0
        DefaultContext.clamp = 1
        for signal in DefaultContext.flags:
            DefaultContext.flags[signal] = True
            DefaultContext.traps[signal] = True
        changed = DefaultContext.copy()
        with localcontext() as ambient:
            ambient.prec = 2
            ambient.Emax = 2
            ambient.Emin = -2
            ambient.rounding = ROUND_UP
            for signal in ambient.flags:
                ambient.flags[signal] = True
                ambient.traps[signal] = True
            result = dividend_entitlement(
                event,
                shares_before_ex=Decimal("123456789.123456789"),
                held_at=date(2026, 6, 1),
                as_of=date(2026, 6, 15),
            )
            assert ambient.Emax == 2 and ambient.rounding == ROUND_UP
            assert all(ambient.flags.values()) and all(ambient.traps.values())
        assert result.accrued_amount == Decimal("46296295.921296295875")
        assert str(DefaultContext) == str(changed)
    finally:
        for attribute in ("prec", "rounding", "Emin", "Emax", "capitals", "clamp"):
            setattr(DefaultContext, attribute, getattr(original, attribute))
        DefaultContext.flags = original.flags.copy()
        DefaultContext.traps = original.traps.copy()


def test_zero_shares_do_not_create_cash() -> None:
    result = _accrual(shares_before_ex=Decimal("0"), as_of=date(2026, 6, 21))
    assert result.accrued_amount == result.receivable == result.cash_available == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"cash_available": Decimal("3")},
        {"receivable": Decimal("-1")},
        {"shares_before_ex": True},
        {"held_at": date(2026, 6, 16)},
    ],
)
def test_accrual_value_rejects_double_counting_or_invalid_balances(changes) -> None:
    with pytest.raises(StockEconomicEvidenceError):
        replace(_accrual(), **changes)


@pytest.mark.parametrize(
    "shares",
    [True, -1, 0.5, Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), Decimal("1e999999")],
)
def test_invalid_holdings_do_not_create_entitlement(shares: object) -> None:
    with pytest.raises(StockEconomicEvidenceError):
        _accrual(shares_before_ex=shares)


def test_accrual_rejects_invalid_dates_and_tampered_event() -> None:
    with pytest.raises(StockEconomicEvidenceError):
        _accrual(held_at=RECEIVED)
    with pytest.raises(StockEconomicEvidenceError):
        _accrual(as_of=RECEIVED)
    event = _dividends().events[0]
    object.__setattr__(event, "cash_amount", Decimal("NaN"))
    with pytest.raises(StockEconomicEvidenceError):
        dividend_entitlement(
            event, shares_before_ex=Decimal("1"), held_at=date(2026, 6, 1), as_of=date(2026, 6, 15)
        )


def _panel(blob: bytes | None = None, **kwargs: object):
    data = _csv(DIVIDEND_FIELDS, [_dividend_row()]) if blob is None else blob
    options = {
        "expected_sha256": hashlib.sha256(data).hexdigest(),
        "symbols": ("FICT", "ALTN"),
        "ex_start": date(2026, 1, 1),
        "ex_end": date(2026, 6, 15),
        "received_at": RECEIVED,
        **kwargs,
    }
    return parse_cash_dividend_panel(data, **options)


def test_panel_preserves_caller_order_and_full_original_hash_for_every_view() -> None:
    rows = [
        _dividend_row(),
        _dividend_row(id="fictional-alternative-1", ticker="ALTN", cash_amount="1.25"),
        _dividend_row(id="fictional-event-2", ex_dividend_date="2026-06-09"),
    ]
    data = _csv(DIVIDEND_FIELDS, rows)
    original_hash = hashlib.sha256(data).hexdigest()
    views = _panel(data, symbols=("ALTN", "FICT", "EMPTY"))
    assert type(views) is tuple
    assert tuple(view.symbol for view in views) == ("ALTN", "FICT", "EMPTY")
    assert tuple(event.id for event in views[0].events) == ("fictional-alternative-1",)
    assert tuple(event.id for event in views[1].events) == (
        "fictional-event-1",
        "fictional-event-2",
    )
    assert views[0].events[0].cash_amount == Decimal("1.25")
    assert views[2].events == ()
    assert sum(len(view.events) for view in views) == 3
    for view in views:
        assert view.original_csv_sha256 == original_hash
        assert view.received_at == RECEIVED
        assert (view.ex_start, view.ex_end) == (date(2026, 1, 1), date(2026, 6, 15))
        assert all(event.source_csv_sha256 == original_hash for event in view.events)
    filtered_bytes = _csv(DIVIDEND_FIELDS, [rows[1]])
    assert views[0].original_csv_sha256 != hashlib.sha256(filtered_bytes).hexdigest()
    with pytest.raises(StockEconomicEvidenceError):
        _panel(filtered_bytes, expected_sha256=original_hash)


@pytest.mark.parametrize(
    "symbols",
    [
        (),
        ["FICT"],
        "FICT",
        {"FICT"},
        ("FICT", "FICT"),
        ("fict",),
        (True,),
        ("FICT", ""),
        tuple(f"S{number:02}" for number in range(33)),
    ],
)
def test_panel_requires_one_to_32_exact_unique_valid_symbols(symbols: object) -> None:
    with pytest.raises(StockEconomicEvidenceError):
        _panel(_csv(DIVIDEND_FIELDS, []), symbols=symbols)


def test_panel_includes_32_empty_views_without_claiming_no_distributions() -> None:
    symbols = tuple(f"S{number:02}" for number in range(32))
    views = _panel(_csv(DIVIDEND_FIELDS, []), symbols=symbols)
    assert tuple(view.symbol for view in views) == symbols
    assert all(view.events == () for view in views)
    for view in views:
        assert view.qualified is view.investment_eligible is view.live_authorized is False
        assert "no_http_status_or_pagination_proof" in view.limitations
        assert "no_api_wide_or_corporate_action_completeness_assertion" in view.limitations


@pytest.mark.parametrize(
    "second",
    [
        _dividend_row(ticker="ALTN"),
        _dividend_row(ticker="ALTN", cash_amount="0.5"),
        _dividend_row(cash_amount="0.5"),
        _dividend_row(id="another-native-id"),
        _dividend_row(id="another-native-id", cash_amount="0.3750"),
        _dividend_row(id="another-native-id", record_date="2026-06-02"),
    ],
)
def test_panel_checks_ids_conflicts_and_economic_duplicates_globally(second) -> None:
    with pytest.raises(StockEconomicEvidenceError):
        _panel(_csv(DIVIDEND_FIELDS, [_dividend_row(), second]))


def test_distinct_regular_and_special_payments_on_same_ex_date_remain_distinct() -> None:
    data = _csv(
        DIVIDEND_FIELDS,
        [
            _dividend_row(),
            _dividend_row(id="fictional-special", cash_amount="1", distribution_type="special"),
        ],
    )
    views = _panel(data)
    assert len(views[0].events) == 2 and views[1].events == ()
    assert tuple(event.distribution_type for event in views[0].events) == ("recurring", "special")


@pytest.mark.parametrize(
    "changes",
    [
        {"ticker": "UNKNOWN"},
        {"currency": "CAD"},
        {"cash_amount": "NaN"},
        {"cash_amount": "0"},
        {"ex_dividend_date": "2027-01-01"},
        {"ex_dividend_date": ""},
        {"declaration_date": "2026-06-16"},
        {"pay_date": "2026-06-01"},
    ],
)
def test_panel_rejects_entire_input_when_a_later_other_symbol_row_is_invalid(changes) -> None:
    late = _dividend_row(**{"id": "fictional-last", "ticker": "ALTN", **changes})
    with pytest.raises(StockEconomicEvidenceError):
        _panel(_csv(DIVIDEND_FIELDS, [_dividend_row(), late]))


def test_panel_rejects_malformed_late_row_and_wrong_receipt_or_hash() -> None:
    data = _csv(DIVIDEND_FIELDS, [_dividend_row()]) + b'"unfinished-other-symbol\n'
    with pytest.raises(StockEconomicEvidenceError):
        _panel(data)
    for options in (
        {"expected_sha256": "0" * 64},
        {"received_at": RECEIVED.replace(tzinfo=None)},
        {"ex_start": date(2026, 7, 1)},
    ):
        with pytest.raises(StockEconomicEvidenceError):
            _panel(**options)


def test_panel_retains_original_amount_unknowns_and_precision_without_granting_authority() -> None:
    native_amount = "0.12345678901234567890123456789012345678901234567890123456789"
    data = _csv(
        DIVIDEND_FIELDS,
        [
            _dividend_row(),
            _dividend_row(
                id="fictional-alternative-1",
                ticker="ALTN",
                cash_amount=native_amount,
                pay_date="",
                record_date="",
                declaration_date="",
                frequency="",
                distribution_type="",
                split_adjusted_cash_amount="99",
            ),
        ],
    )
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        views = _panel(data)
    event = views[1].events[0]
    assert event.cash_amount == Decimal(native_amount)
    assert (
        event.pay_date,
        event.record_date,
        event.declaration_date,
        event.frequency,
        event.distribution_type,
    ) == (None, None, None, None, None)
    for view in views:
        assert view.qualified is view.investment_eligible is view.live_authorized is False
        with pytest.raises(FrozenInstanceError):
            view.live_authorized = True
        assert all(
            item.qualified is item.investment_eligible is item.live_authorized is False
            for item in view.events
        )


def test_single_symbol_entry_point_preserves_semantics_and_rejects_mixed_panel() -> None:
    data = _csv(DIVIDEND_FIELDS, [_dividend_row()])
    standalone = _dividends(data)
    singleton_panel = _panel(data, symbols=("FICT",))
    assert singleton_panel == (standalone,)
    assert standalone.events[0].cash_amount == Decimal("0.375")
    mixed_data = _csv(
        DIVIDEND_FIELDS,
        [
            _dividend_row(),
            _dividend_row(id="fictional-alternative-1", ticker="ALTN"),
        ],
    )
    with pytest.raises(StockEconomicEvidenceError):
        _dividends(mixed_data)
