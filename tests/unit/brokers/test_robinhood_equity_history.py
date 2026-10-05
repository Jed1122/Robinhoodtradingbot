"""Synthetic declarations, never authenticated customer orders or calibration."""

import copy
import hashlib
import json
from dataclasses import FrozenInstanceError, replace
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


def assemble(*pages):  # type: ignore[no-untyped-def]
    from trading_bot.brokers.robinhood_equity_history import assemble_equity_order_history

    return assemble_equity_order_history(pages)


def test_chain_preserves_source_order_and_opaque_cursor_without_transport():
    cursor = "https://NOT-A-REQUEST.invalid/?cursor=untouched"
    first = parse(encoded(next=cursor))
    second = parse(encoded(rows=[], next=""), requested_cursor=cursor, received_at_ns=RECEIPT + 1)
    result = assemble(first, second)
    assert result.orders[0].id == ORDER and len(result.orders) == 1
    assert result.page_hashes == (first.page_hash, second.page_hash)
    assert result.supplied_chain_complete and result.history_complete is None
    assert result.fees_final is None and not result.authenticated
    assert not result.execution_eligible and not result.promotable
    assert result.request.request_hash == first.request.request_hash
    assert result.history_hash == assemble(first, second).history_hash
    later = replace(second, received_at_ns=RECEIPT + 2)
    assert result.history_hash != assemble(first, later).history_hash


def test_chain_counts_order_redelivery_without_double_counting_partial_fills():
    first = parse(encoded(next="opaque"))
    second = parse(encoded(), requested_cursor="opaque")
    result = assemble(first, second)
    assert len(result.orders) == 1 and result.duplicate_orders == 1
    assert result.unique_executions == 2
    assert result.orders[0].execution_fees == Decimal("0.003")


@pytest.mark.parametrize(
    "changed", [{"fees": "0.004"}, {"fees": "0.0030"}, {"state": "pending_cancelled"}]
)
def test_chain_rejects_changed_snapshots_under_the_same_order_uuid(changed):
    first = parse(encoded(next="opaque"))
    row = order_row()
    row.update(changed)
    second = parse(encoded(row), requested_cursor="opaque")
    with pytest.raises(EquityHistoryError):
        assemble(first, second)


def test_chain_rejects_execution_uuid_reused_by_another_order():
    row = order_row()
    row["id"] = "55555555-5555-4555-8555-555555555555"
    page = parse(encoded(rows=[order_row(), row]))
    with pytest.raises(EquityHistoryError):
        assemble(page)


@pytest.mark.parametrize(
    "tamper", ["orders", "body_sha256", "next_cursor", "next_present", "declaration_sha256"]
)
def test_assembler_reparses_raw_bytes_and_denies_tampered_summaries(tamper):
    page = parse(encoded())
    replacements = {
        "orders": (),
        "body_sha256": "f" * 64,
        "next_cursor": "invented",
        "next_present": True,
        "declaration_sha256": "f" * 64,
    }
    with pytest.raises(EquityHistoryError):
        assemble(replace(page, **{tamper: replacements[tamper]}))


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "wrong_cursor",
        "first_cursor",
        "loop",
        "extra_terminal",
        "earlier_receipt",
        "filter_drift",
        "account_drift",
    ],
)
def test_incomplete_or_changed_chain_never_becomes_supplied_complete(case):
    first = parse(encoded(rows=[], next="opaque"))
    second = parse(encoded(rows=[]), requested_cursor="opaque")
    pages = (first, second)
    if case == "missing":
        pages = (first,)
    elif case == "wrong_cursor":
        pages = (first, replace(second, requested_cursor="other"))
    elif case == "first_cursor":
        pages = (replace(first, requested_cursor="opaque"), second)
    elif case == "loop":
        second = parse(encoded(rows=[], next="opaque"), requested_cursor="opaque")
        pages = (first, second, parse(encoded(rows=[]), requested_cursor="opaque"))
    elif case == "extra_terminal":
        pages = (parse(encoded(rows=[])), second)
    elif case == "earlier_receipt":
        pages = (first, replace(second, received_at_ns=RECEIPT - 1))
    elif case == "filter_drift":
        pages = (
            first,
            replace(second, request=EquityHistoryRequest(ACCOUNT, (("symbol", "SPY"),))),
        )
    else:
        pages = (first, replace(second, request=EquityHistoryRequest("b" * 64)))
    with pytest.raises(EquityHistoryError):
        assemble(*pages)


def test_creation_filter_and_terminal_pages_do_not_attest_execution_window_coverage():
    request = EquityHistoryRequest(
        ACCOUNT, (("created_at_gte", "2026-10-02"), ("placed_agent", "agentic"))
    )
    result = assemble(parse(encoded(rows=[]), request=request))
    assert result.supplied_chain_complete and result.orders == ()
    assert result.history_complete is None and result.fees_final is None
    assert not result.promotable and result.unique_executions == 0


def test_page_chain_resource_limits_fail_without_partial_history():
    with pytest.raises(EquityHistoryError):
        assemble()
    with pytest.raises(EquityHistoryError):
        assemble(*([parse(encoded(rows=[]))] * 129))
    pages = []
    for i in range(17):
        body = encoded(rows=[], **({"next": str(i + 1)} if i < 16 else {}))
        pages.append(
            parse(body + b" " * (1048576 - len(body)), requested_cursor=str(i) if i else None)
        )
    with pytest.raises(EquityHistoryError):
        assemble(*pages)


@pytest.mark.parametrize("target", ["orders", "executions"])
def test_per_page_and_per_order_row_limits_reject_before_interpreting_rows(target):
    if target == "orders":
        body = encoded(rows=[{}] * 2001)
    else:
        row = order_row()
        row["executions"] = [{}] * 2001
        body = encoded(row)
    with pytest.raises(EquityHistoryError):
        parse(body)


def test_chain_unique_order_limit_is_enforced_across_small_pages():
    row = order_row()
    row.update(
        executions=[],
        cumulative_quantity="0",
        fees="0",
        average_price=None,
        last_transaction_at=None,
        state="queued",
    )
    pages = []
    for page in range(21):
        rows = []
        for index in range(1000):
            item = dict(row)
            item["id"] = f"00000000-0000-4000-8000-{page * 1000 + index:012d}"
            rows.append(item)
        pages.append(
            parse(
                encoded(rows=rows, **({"next": str(page + 1)} if page < 20 else {})),
                requested_cursor=str(page) if page else None,
            )
        )
    with pytest.raises(EquityHistoryError):
        assemble(*pages)


def test_nonempty_parsed_history_does_not_unlock_authenticated_mapping():
    from trading_bot.brokers.robinhood_equity_mapping import (
        UnverifiedNonemptyShape,
        ensure_authenticated_empty_collection,
    )

    page = parse(encoded())
    assert assemble(page).unique_executions == 2
    with pytest.raises(UnverifiedNonemptyShape):
        ensure_authenticated_empty_collection(
            [order_row()], collection_name="orders", next_page=None
        )


@pytest.mark.parametrize(
    "filters",
    [
        (("symbol", "QQQ"),),
        (("order_id", FILL_1),),
        (("placed_agent", "user"),),
        (("state", "queued"),),
        (("created_at_gte", "2026-10-03"),),
    ],
)
def test_rows_contradicting_explicit_request_filters_are_not_bound_as_matching(filters):
    with pytest.raises(EquityHistoryError):
        parse(encoded(), request=EquityHistoryRequest(ACCOUNT, filters))


def test_single_order_mode_does_not_accept_two_order_deliveries():
    row = order_row()
    row["id"] = "55555555-5555-4555-8555-555555555555"
    with pytest.raises(EquityHistoryError):
        parse(
            encoded(rows=[order_row(), row]),
            request=EquityHistoryRequest(ACCOUNT, (("order_id", ORDER),)),
        )


def test_matching_declared_filters_bind_rows_without_upgrading_authentication():
    request = EquityHistoryRequest(
        ACCOUNT,
        (
            ("created_at_gte", "2026-10-02T14:00:00Z"),
            ("order_id", ORDER),
            ("placed_agent", "agentic"),
            ("state", "filled"),
            ("symbol", "SPY"),
        ),
    )
    page = parse(encoded(), request=request)
    assert len(page.orders) == 1 and not page.authenticated


@pytest.mark.parametrize("zero", [False, True])
def test_partial_state_with_zero_or_complete_shares_denies_internal_consistency(zero):
    row = order_row()
    row["state"] = "partially_filled"
    if zero:
        row.update(cumulative_quantity="0", fees="0", average_price=None, executions=[])
    order = parse(encoded(row)).orders[0]
    assert "partial_quantity_mismatch" in order.issues
    assert not order.internally_consistent
    assert not assemble(parse(encoded(row))).internally_consistent


@pytest.mark.parametrize("dollar_based", [False, True])
def test_legitimate_fractional_partial_fill_preserves_nullable_requested_quantity(dollar_based):
    row = order_row()
    row.update(state="partially_filled", quantity="2.00")
    if dollar_based:
        row.update(
            quantity=None,
            dollar_based_amount={"amount": "200.00", "currency_code": "USD"},
            type="market",
            price=None,
        )
    order = parse(encoded(row)).orders[0]
    assert order.internally_consistent
    assert order.cumulative_quantity == Decimal("1.00")
    assert order.quantity == (None if dollar_based else Decimal("2.00"))
