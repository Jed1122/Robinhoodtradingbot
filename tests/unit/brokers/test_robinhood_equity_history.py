"""Synthetic declarations, never authenticated customer orders or calibration."""

import copy
import hashlib
import json
from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from trading_bot.brokers.robinhood_equity_history import (
    ORDER_DECLARATION_SHA256,
    EquityHistoryError,
    EquityHistoryRequest,
    parse_equity_orders_page,
)

CREATED = "2026-10-02T14:00:00.000000001Z"
RECEIPT = 1790949660000000000  # 2026-10-02 14:01 UTC, literal independent bound.
ACCOUNT = "a" * 64
ORDER = "11111111-1111-4111-8111-111111111111"
INSTRUMENT = "22222222-2222-4222-8222-222222222222"
FILL_1 = "33333333-3333-4333-8333-333333333333"
FILL_2 = "44444444-4444-4444-8444-444444444444"


def order_row() -> dict[str, object]:
    return {
        "average_price": "100.0075",
        "created_at": CREATED,
        "cumulative_quantity": "1.00",
        "dollar_based_amount": None,
        "executions": [
            {
                "fees": "0.001",
                "id": FILL_1,
                "price": "100.00",
                "quantity": "0.25",
                "timestamp": "2026-10-02T14:00:01.123456789Z",
            },
            {
                "fees": "0.002",
                "id": FILL_2,
                "price": "100.01",
                "quantity": "0.75",
                "timestamp": "2026-10-02T14:00:02Z",
            },
        ],
        "fees": "0.003",
        "id": ORDER,
        "instrument_id": INSTRUMENT,
        "last_transaction_at": "2026-10-02T14:00:02Z",
        "market_hours": "regular_hours",
        "placed_agent": "agentic",
        "price": "101.00",
        "quantity": "1.00",
        "side": "buy",
        "state": "filled",
        "stop_price": None,
        "symbol": "SPY",
        "time_in_force": "gfd",
        "trigger": "immediate",
        "type": "limit",
    }


def encoded(row: object = None, *, rows: object = None, **data: object) -> bytes:
    orders = [order_row() if row is None else row] if rows is None else rows
    return json.dumps({"data": {"orders": orders, **data}, "guide": "SYNTHETIC"}).encode()


def parse(body: bytes, **kwargs: object):  # type: ignore[no-untyped-def]
    args = {
        "request": EquityHistoryRequest(ACCOUNT),
        "requested_cursor": None,
        "received_at_ns": RECEIPT,
        "declaration_sha256": ORDER_DECLARATION_SHA256,
        **kwargs,
    }
    return parse_equity_orders_page(body, **args)  # type: ignore[arg-type]


def test_fills_retain_exact_decimal_fees_and_nanoseconds_without_granting_authority():
    body = encoded()
    page = parse(body)
    order = page.orders[0]
    assert str(order.cumulative_quantity) == "1.00"
    assert order.execution_quantity == Decimal("1.00")
    assert order.execution_fees == Decimal("0.003")
    assert order.executions[0].timestamp_ns == 1790949601123456789
    assert order.created_at_ns == 1790949600000000001
    assert page.body_sha256 == hashlib.sha256(body).hexdigest()
    assert order.issues == ()
    assert not page.authenticated and not page.execution_eligible and not page.promotable
    assert page.fees_final is None and page.history_complete is None
    with pytest.raises(FrozenInstanceError):
        page.received_at_ns = 0


def test_snapshot_pin_is_the_actual_current_namespace_declaration():
    path = Path(
        "src/trading_bot/brokers/schema_snapshots/robinhood_2_equity_orders.declaration.txt"
    )
    assert (
        hashlib.sha256(path.read_bytes().removesuffix(b"\n")).hexdigest()
        == ORDER_DECLARATION_SHA256
    )
    with pytest.raises(EquityHistoryError):
        parse(encoded(), declaration_sha256="b" * 64)


def test_dollar_order_does_not_infer_requested_shares_or_treat_null_executions_as_empty():
    row = order_row()
    row.update(
        quantity=None,
        dollar_based_amount={"amount": "100.00", "currency_code": "USD"},
        type="market",
        price=None,
        state="new",
        cumulative_quantity="0",
        average_price=None,
        executions=None,
        last_transaction_at=None,
        fees="0.00",
    )
    result = parse(encoded(row)).orders[0]
    assert result.quantity is None and result.dollar_amount == Decimal("100.00")
    assert result.executions is None and result.execution_quantity is None
    assert result.issues == ("executions_unknown",)
    row["executions"] = []
    result = parse(encoded(row)).orders[0]
    assert result.executions == () and result.execution_quantity == 0
    assert result.issues == ()


@pytest.mark.parametrize("field", list(order_row()))
def test_all_required_fields_must_be_present(field):
    row = order_row()
    del row[field]
    with pytest.raises(EquityHistoryError, match=r"^equity_history_invalid$"):
        parse(encoded(row))


@pytest.mark.parametrize("field", ["fees", "id", "price", "quantity", "timestamp"])
def test_execution_fields_cannot_be_omitted_or_null(field):
    for missing in (True, False):
        row = order_row()
        fill = row["executions"][0]
        if missing:
            del fill[field]
        else:
            fill[field] = None
        with pytest.raises(EquityHistoryError):
            parse(encoded(row))


@pytest.mark.parametrize(
    "value",
    [
        None,
        0,
        True,
        0.001,
        "1e-3",
        " 0.003",
        "0.003 ",
        "NaN",
        "Infinity",
        "-0",
        "+0.003",
        "00.003",
        ".003",
        "1.",
        "1" * 21,
        "0." + "1" * 19,
    ],
)
def test_required_fees_reject_coercion_unbounded_values_and_missing_zero(value):
    row = order_row()
    row["fees"] = value
    with pytest.raises(EquityHistoryError):
        parse(encoded(row))


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-10-02",
        "2026-10-02T14:00:00",
        "2026-10-02T10:00:00-04:00",
        "2026-10-02T14:00:00-00:00",
        "2026-10-02T14:00:00.1234567890Z",
        "2026-10-02T14:02:00Z",
        "2026-10-02T13:59:59Z",
    ],
)
def test_fill_timestamps_are_lossless_utc_causal_and_not_after_receipt(stamp):
    row = order_row()
    row["executions"][0]["timestamp"] = stamp
    with pytest.raises(EquityHistoryError):
        parse(encoded(row))


def test_execution_redelivery_is_deduplicated_but_conflicts_are_denied():
    row = order_row()
    row["executions"].append(copy.deepcopy(row["executions"][0]))
    order = parse(encoded(row)).orders[0]
    assert len(order.executions) == 2 and order.duplicate_executions == 1
    assert order.execution_fees == Decimal("0.003") and order.issues == ()
    row["executions"][-1]["fees"] = "0.009"
    with pytest.raises(EquityHistoryError):
        parse(encoded(row))


def test_distinct_execution_ids_do_not_collapse_equal_economics():
    row = order_row()
    row["executions"][1].update(price="100.00", quantity="0.25", fees="0.001")
    row.update(cumulative_quantity="0.50", quantity="0.50", fees="0.002", average_price="100")
    order = parse(encoded(row)).orders[0]
    assert len(order.executions) == 2 and order.execution_quantity == Decimal("0.50")
    assert order.execution_fees == Decimal("0.002") and not order.issues


@pytest.mark.parametrize(
    "changes, issue",
    [
        ({"cumulative_quantity": "0.9"}, "execution_quantity_mismatch"),
        ({"fees": "0.009"}, "execution_fees_mismatch"),
        ({"quantity": "0.5"}, "requested_quantity_exceeded"),
        ({"quantity": "2"}, "filled_quantity_mismatch"),
        ({"average_price": None}, "average_price_missing"),
        ({"price": None}, "limit_price_missing"),
        ({"stop_price": "99"}, "stop_price_unexpected"),
        ({"state": "confirmed"}, "state_unknown"),
    ],
)
def test_contradictions_are_preserved_as_ineligible_evidence_not_guessed(changes, issue):
    row = order_row()
    row.update(changes)
    result = parse(encoded(row)).orders[0]
    assert issue in result.issues and not result.internally_consistent


def test_rounded_average_is_not_rejected_as_exact_vwap_and_unknown_agent_is_retained():
    row = order_row()
    row.update(average_price="100.01", placed_agent="future_internal")
    order = parse(encoded(row)).orders[0]
    assert not order.issues and order.placed_agent == "future_internal"


def test_explicit_fee_on_zero_fill_is_not_a_genuine_execution_sample():
    row = order_row()
    row.update(
        cumulative_quantity="0", fees="0.01", executions=[], average_price=None, state="rejected"
    )
    order = parse(encoded(row)).orders[0]
    assert order.fees == Decimal("0.01") and not order.executions
    assert "execution_fees_mismatch" in order.issues


@pytest.mark.parametrize("name", ["ref_id", "reject_reason"])
def test_optional_fields_preserve_omission_and_empty_without_accepting_null(name):
    row = order_row()
    assert getattr(parse(encoded(row)).orders[0], name) is None
    row[name] = ""
    assert getattr(parse(encoded(row)).orders[0], name) == ""
    row[name] = None
    with pytest.raises(EquityHistoryError):
        parse(encoded(row))


def test_exact_sums_do_not_depend_on_host_decimal_precision():
    row = order_row()
    row["executions"][0].update(quantity="0.123456789123456789", fees="0.000000000000000001")
    row["executions"][1].update(quantity="0.876543210876543211", fees="0.000000000000000002")
    row.update(fees="0.000000000000000003")
    with localcontext() as context:
        context.prec = 2
        order = parse(encoded(row)).orders[0]
    assert order.execution_quantity == Decimal("1.000000000000000000")
    assert order.execution_fees == Decimal("0.000000000000000003") and not order.issues


@pytest.mark.parametrize(
    "body",
    [
        b'{"data":{"orders":[]},"data":{"orders":[]},"guide":"x"}',
        b'{"data":{"orders":null},"guide":"x"}',
        b'{"data":{"orders":[null]},"guide":"x"}',
        b'{"data":{"orders":[],"next":null},"guide":"x"}',
        b'{"data":{"orders":[],"secret":"DO_NOT_ECHO"},"guide":"x"}',
        b'{"data":{"orders":[]},"guide":1}',
        b"\xff",
        b"{" * 50,
        b" " * 1048577,
    ],
)
def test_malformed_unbounded_or_null_history_is_not_a_verified_empty_page(body):
    with pytest.raises(EquityHistoryError) as error:
        parse(body)
    assert str(error.value) == "equity_history_invalid" and error.value.__cause__ is None


def test_repr_does_not_disclose_broker_identity_or_free_text():
    row = order_row()
    row.update(ref_id="PRIVATE_REF", reject_reason="PRIVATE_REASON")
    page = parse(encoded(row), requested_cursor="PRIVATE_CURSOR")
    assert "PRIVATE" not in repr(page) + repr(page.orders[0]) + repr(page.orders[0].executions[0])


@pytest.mark.parametrize(
    "filters",
    [
        (("symbol", "SPY"), ("symbol", "SPY")),
        (("account_number", "PRIVATE"),),
        (("symbol", "SPY"), ("state", "filled")),
        (("created_at_gte", "naive"),),
    ],
)
def test_request_identity_rejects_unknown_duplicate_unsorted_and_invalid_filter_inputs(filters):
    with pytest.raises(EquityHistoryError):
        EquityHistoryRequest(ACCOUNT, filters)


def test_terminal_cursor_omission_is_distinct_from_explicit_empty():
    absent, empty = parse(encoded(rows=[])), parse(encoded(rows=[], next=""))
    assert absent.next_cursor is None and not absent.next_present
    assert empty.next_cursor == "" and empty.next_present
    assert absent.body_sha256 != empty.body_sha256


def test_request_invalid_calendar_date_is_sanitized_without_echoing_values():
    with pytest.raises(EquityHistoryError, match=r"^equity_history_invalid$"):
        EquityHistoryRequest(ACCOUNT, (("created_at_gte", "2026-02-30"),))


def test_duplicate_execution_spelling_drift_is_not_an_exact_redelivery():
    row = order_row()
    duplicate = copy.deepcopy(row["executions"][0])
    duplicate["fees"] = "0.0010"
    row["executions"].append(duplicate)
    with pytest.raises(EquityHistoryError):
        parse(encoded(row))
