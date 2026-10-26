"""Fictional original MCP action strings; no account, provider or file I/O."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

RECEIVED = datetime(2026, 10, 26, tzinfo=UTC)


def payload():
    return {
        "request": {
            "ca_types": None,
            "start": "2024-06-01",
            "end": "2024-06-30",
            "symbols": ["AAPL", "NVDA"],
            "cusips": None,
            "ids": None,
            "limit": 1000,
            "sort": "asc",
        },
        "announcements": {
            "cash_dividends": [
                {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "corporate_action_type": "cash_dividends",
                    "symbol": "AAPL",
                    "cusip": "037833100",
                    "rate": 0.125,
                    "special": False,
                    "foreign": False,
                    "process_date": "2024-06-15",
                    "ex_date": "2024-06-10",
                    "record_date": "2024-06-11",
                    "payable_date": "2024-06-15",
                    "due_bill_on_date": None,
                    "due_bill_off_date": None,
                }
            ],
            "forward_splits": [
                {
                    "id": "00000000-0000-0000-0000-000000000002",
                    "corporate_action_type": "forward_splits",
                    "symbol": "NVDA",
                    "cusip": "67066G104",
                    "new_rate": 10.0,
                    "old_rate": 1.0,
                    "process_date": "2024-06-10",
                    "ex_date": "2024-06-10",
                    "record_date": "2024-06-07",
                    "payable_date": "2024-06-10",
                    "due_bill_redemption_date": "2024-06-10",
                }
            ],
        },
    }


def encode(value):
    return json.dumps(value, separators=(",", ":")).encode()


def request(**changes):
    from trading_bot.market_data.stock_corporate_actions import StockCorporateActionsRequest

    args = {"symbols": ("AAPL", "NVDA"), "start": date(2024, 6, 1), "end": date(2024, 6, 30)}
    return StockCorporateActionsRequest(**(args | changes))


def parse(value=None, *, raw=None, req=None, **changes):
    from trading_bot.market_data.stock_corporate_actions import parse_stock_corporate_actions

    body = raw if raw is not None else encode(payload() if value is None else value)
    args = {
        "expected_sha256": hashlib.sha256(body).hexdigest(),
        "request": request() if req is None else req,
        "received_at": RECEIVED,
    }
    return parse_stock_corporate_actions(body, **(args | changes))


def audit(value=None, **changes):
    from trading_bot.market_data.stock_corporate_actions import audit_stock_corporate_actions

    return audit_stock_corporate_actions(
        parse() if value is None else value, as_of=changes.get("as_of", RECEIVED)
    )


def test_original_exact_rates_dates_cusip_and_native_missingness_are_preserved():
    value = parse()
    assert value.original_content_json == encode(payload())
    cash, split = value.actions
    assert cash.rate == Decimal("0.125") and cash.cusip == "037833100"
    assert split.old_rate == Decimal("1.0") and split.new_rate == Decimal("10.0")
    assert split.record_date == date(2024, 6, 7)
    assert split.payable_date == split.ex_date == date(2024, 6, 10)
    assert cash.currency is None and "currency" in cash.missing_native_fields
    assert "due_bill_on_date" in cash.null_native_fields
    assert value.pagination_status == "not_exposed" and value.native_data_quality is None
    assert value.available_at == RECEIVED
    result = audit(value)
    assert result.status == "structural_checks_passed"
    assert result.action_count == 2
    assert result.counts_by_symbol == (("AAPL", 1, 0), ("NVDA", 0, 1))
    assert result.currency_unreported_count == 2
    for obj in (value, result):
        for flag in (
            "qualified",
            "source_qualified",
            "strategy_qualified",
            "investment_eligible",
            "trading_enabled",
            "live_authorized",
            "authenticated",
            "complete_action_book",
            "point_in_time_verified",
            "cashflow_qualified",
            "is_original_upstream_wire",
        ):
            assert getattr(obj, flag) is False


def test_long_numeric_rate_is_exact_decimal_independent_of_ambient_context():
    text = "0.123456789012345678901234567890123456789012345678901234"
    raw = encode(payload()).replace(b"0.125", text.encode())
    with localcontext() as ctx:
        ctx.prec = 6
        value = parse(raw=raw)
        observed_hash = audit(value).evidence_hash
    assert value.actions[0].rate == Decimal(text)
    assert audit(value).evidence_hash == observed_hash


@pytest.mark.parametrize("key", ["ex_date", "cusip", "rate", "process_date"])
def test_processed_incomplete_native_fields_remain_missing_without_repair(key):
    body = payload()
    cash = body["announcements"]["cash_dividends"][0]
    cash.pop(key)
    value = parse(body)
    row = value.actions[0]
    assert getattr(row, key) is None and key in row.missing_native_fields
    assert (row.action_id, key) in audit(value).unresolved_native_fields


def test_process_date_scope_does_not_silently_filter_by_ex_record_or_payment_date():
    body = payload()
    cash = body["announcements"]["cash_dividends"][0]
    cash["ex_date"], cash["record_date"], cash["payable_date"] = (
        "2024-05-31",
        "2024-05-31",
        "2024-07-01",
    )
    value = parse(body)
    assert value.actions[0].ex_date == date(2024, 5, 31)
    assert value.actions[0].payable_date == date(2024, 7, 1)
    assert audit(value).action_count == 2


@pytest.mark.parametrize(
    "kind",
    [
        "hash",
        "duplicate_key",
        "unknown_group",
        "unknown_field",
        "null_group",
        "duplicate_id",
        "type",
        "symbol",
        "cusip",
        "date",
        "process_range",
        "rate_string",
        "rate_negative",
        "rate_bool",
        "old_zero",
        "nonfinite",
        "request",
        "limit",
    ],
)
def test_corrupt_unsupported_or_cross_scope_original_data_is_rejected(kind):
    from trading_bot.market_data.stock_corporate_actions import StockCorporateActionsError

    body = payload()
    cash = body["announcements"]["cash_dividends"][0]
    split = body["announcements"]["forward_splits"][0]
    changes = {}
    if kind == "hash":
        changes["expected_sha256"] = "0" * 64
    elif kind == "duplicate_key":
        with pytest.raises(StockCorporateActionsError):
            parse(
                raw=encode(body).replace(
                    b'"announcements":', b'"announcements":{},"announcements":'
                )
            )
        return
    elif kind == "unknown_group":
        body["announcements"]["reverse_splits"] = []
    elif kind == "unknown_field":
        cash["authenticated"] = True
    elif kind == "null_group":
        body["announcements"]["cash_dividends"] = None
    elif kind == "duplicate_id":
        split["id"] = cash["id"]
    elif kind == "type":
        split["corporate_action_type"] = "cash_dividends"
    elif kind == "symbol":
        cash["symbol"] = "OTHER"
    elif kind == "cusip":
        cash["cusip"] = "37833100"
    elif kind == "date":
        cash["record_date"] = "2024-02-30"
    elif kind == "process_range":
        cash["process_date"] = "2024-07-01"
    elif kind == "rate_string":
        cash["rate"] = "0.125"
    elif kind == "rate_negative":
        cash["rate"] = -1
    elif kind == "rate_bool":
        cash["rate"] = True
    elif kind == "old_zero":
        split["old_rate"] = 0
    elif kind == "nonfinite":
        cash["rate"] = float("nan")
    elif kind == "request":
        body["request"]["symbols"] = ["NVDA", "AAPL"]
    elif kind == "limit":
        body["request"]["limit"] = 1
        changes["req"] = request(limit=1)
    with pytest.raises(StockCorporateActionsError):
        parse(body, **changes)


@pytest.mark.parametrize(
    "token,status",
    [(None, "not_exposed"), ("next", "continuation_reported"), ("", "no_continuation_reported")],
)
def test_pagination_unknown_or_reported_token_never_establishes_complete_book(token, status):
    body = payload()
    if token is not None:
        body["next_page_token"] = token or None
    value = parse(body)
    assert value.pagination_status == status
    assert audit(value).complete_action_book is False


def test_small_or_empty_response_and_limit_boundary_are_not_completeness_evidence():
    body = payload()
    body["announcements"] = {}
    result = audit(parse(body))
    assert result.action_count == 0 and result.complete_action_book is False
    assert result.counts_by_symbol == (("AAPL", 0, 0), ("NVDA", 0, 0))
    full = payload()
    full["request"]["limit"] = 2
    assert audit(parse(full, req=request(limit=2))).response_limit_reached is True


def test_future_receipt_and_naive_asof_cannot_claim_available_action_evidence():
    from trading_bot.market_data.stock_corporate_actions import StockCorporateActionsError

    with pytest.raises(StockCorporateActionsError):
        audit(as_of=RECEIVED - timedelta(seconds=1))
    with pytest.raises(StockCorporateActionsError):
        audit(as_of=RECEIVED.replace(tzinfo=None))


@pytest.mark.parametrize("kind", ["rate", "bytes", "currency", "promotion", "request"])
def test_audit_reparses_and_rejects_frozen_dataclass_mutation(kind):
    from trading_bot.market_data.stock_corporate_actions import StockCorporateActionsError

    value = parse()
    if kind == "rate":
        object.__setattr__(value.actions[0], "rate", Decimal("1"))
    elif kind == "bytes":
        object.__setattr__(value, "original_content_json", b"{}")
    elif kind == "currency":
        object.__setattr__(value.actions[0], "currency", "USD")
    elif kind == "promotion":
        object.__setattr__(value, "complete_action_book", 0)
    else:
        object.__setattr__(value.request, "limit", 999)
    with pytest.raises(StockCorporateActionsError):
        audit(value)
    with pytest.raises(StockCorporateActionsError):
        _ = value.evidence_hash


def test_receipt_bytes_and_asof_are_bound_in_audit_provenance():
    first = parse()
    changed = parse(raw=first.original_content_json + b"\n")
    later = replace(first, received_at=RECEIVED + timedelta(seconds=1))
    results = (audit(first), audit(changed), audit(later, as_of=later.received_at))
    assert len({r.evidence_hash for r in results}) == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"symbols": ["AAPL"]},
        {"symbols": ("AAPL", "AAPL")},
        {"symbols": ()},
        {"limit": True},
        {"limit": 0},
        {"limit": 1001},
        {"sort": "ASC"},
        {"start": datetime(2024, 6, 1, tzinfo=UTC)},
        {"end": date(2024, 5, 31)},
    ],
)
def test_request_shape_and_finite_scope_are_validated_before_parsing(changes):
    from trading_bot.market_data.stock_corporate_actions import StockCorporateActionsError

    with pytest.raises(StockCorporateActionsError):
        request(**changes)


def test_native_null_and_reported_currency_are_not_assumed_or_replaced():
    body = payload()
    cash = body["announcements"]["cash_dividends"][0]
    cash.update(currency="EUR", ex_date=None)
    value = parse(body)
    assert value.actions[0].currency == "EUR"
    assert value.actions[0].ex_date is None
    assert "ex_date" in value.actions[0].null_native_fields
    assert "ex_date" not in value.actions[0].missing_native_fields
    assert audit(value).currency_unreported_count == 1
    assert audit(value).cashflow_qualified is False


def test_formatter_order_is_reported_without_reordering_records():
    value = parse()
    result = audit(value)
    assert result.global_process_order_matches_requested is False
    assert result.source.actions[0].action_type == "cash_dividends"
    assert result.source.actions[0].process_date == date(2024, 6, 15)
    assert result.source.actions[1].process_date == date(2024, 6, 10)
    assert "formatted_order_not_global_process_order" in result.reason_codes
