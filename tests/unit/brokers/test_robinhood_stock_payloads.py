"""Fictional offline argument tests; no broker SDK, transport or order calls."""

import importlib
import importlib.util
from dataclasses import FrozenInstanceError
from decimal import ROUND_UP, Decimal, localcontext
from uuid import UUID

import pytest

D = Decimal
MODULE = "trading_bot.brokers.robinhood_stock_payloads"
REF = "16e04ab0-7483-4e16-8234-a46d1a81d955"


def api():
    assert importlib.util.find_spec(MODULE) is not None, "pure stock payload serializer is missing"
    return importlib.import_module(MODULE)


def terms(**changes):
    values = dict(
        account_number="fictional-account",
        symbol="FIC",
        side="buy",
        order_type="market",
        quantity=D("2"),
    )
    values.update(changes)
    return api().StockOrderTerms(**values)


@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize("order_type", ["market", "limit"])
def test_exact_supported_review_and_place_arguments_share_all_terms(side, order_type):
    selected = terms(
        side=side,
        order_type=order_type,
        limit_price=D("103.125") if order_type == "limit" else None,
    )
    prepared = api().prepare_stock_order_payloads(selected, ref_id=REF)
    expected = {
        "account_number": "fictional-account",
        "symbol": "FIC",
        "side": side,
        "type": order_type,
        "quantity": "2",
        "market_hours": "regular_hours",
        "time_in_force": "gfd",
    }
    if order_type == "limit":
        expected["limit_price"] = "103.125"
    assert prepared.review_arguments == expected
    assert prepared.place_arguments == expected | {"ref_id": REF}
    assert "tax_lots" not in prepared.review_arguments
    assert "agent_initiated" not in prepared.place_arguments


def test_six_decimal_market_fraction_is_serialized_without_rounding_or_exponent():
    selected = terms(quantity=D("0.000001"))
    prepared = api().prepare_stock_order_payloads(selected, ref_id=REF)
    assert prepared.review_arguments["quantity"] == "0.000001"
    assert prepared.place_arguments["quantity"] == "0.000001"


def test_value_preserving_canonical_text_does_not_depend_on_decimal_spelling():
    a = api().prepare_stock_order_payloads(terms(quantity=D("2.0000000")), ref_id=REF)
    b = api().prepare_stock_order_payloads(terms(quantity=D("2E+0")), ref_id=REF)
    assert a.review_arguments == b.review_arguments
    assert a.terms_hash == b.terms_hash
    assert a.order_binding_hash == b.order_binding_hash


@pytest.mark.parametrize(
    "quantity",
    [
        D("0"),
        D("-1"),
        1.5,
        "1",
        True,
        D("NaN"),
        D("sNaN"),
        D("Infinity"),
        D("0.0000001"),
        D("1E-600"),
        D("1E+600"),
    ],
)
def test_quantity_rejects_unsupported_precision_nonpositive_or_inexact_inputs(quantity):
    with pytest.raises(ValueError, match="stock_quantity_invalid"):
        terms(quantity=quantity)


def test_fractional_limit_shares_reject_without_rounding_to_a_whole_share():
    with pytest.raises(ValueError, match="stock_limit_quantity_must_be_whole"):
        terms(order_type="limit", quantity=D("1.000001"), limit_price=D("10"))


@pytest.mark.parametrize("limit_price", [None, D(0), D("-1"), 1.25, "1.25", D("NaN")])
def test_limit_requires_an_exact_positive_applicable_price(limit_price):
    with pytest.raises(ValueError, match="stock_limit_price_invalid"):
        terms(order_type="limit", limit_price=limit_price)


def test_market_price_field_is_rejected_instead_of_silently_dropped():
    with pytest.raises(ValueError, match="stock_market_limit_price_forbidden"):
        terms(limit_price=D("10"))


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("side", "short", "stock_side_unsupported"),
        ("side", True, "stock_side_unsupported"),
        ("order_type", "stop_market", "stock_order_type_unsupported"),
        ("order_type", "stop_limit", "stock_order_type_unsupported"),
        ("market_hours", "extended_hours", "stock_market_hours_unsupported"),
        ("market_hours", "all_day_hours", "stock_market_hours_unsupported"),
        ("time_in_force", "gtc", "stock_time_in_force_unsupported"),
        ("symbol", "fic", "stock_symbol_invalid"),
        ("symbol", "FIC\n", "stock_symbol_invalid"),
        ("account_number", "", "stock_account_invalid"),
        ("account_number", "secret-account\n", "stock_account_invalid"),
    ],
)
def test_unsupported_terms_are_explicitly_rejected_without_coercion(field, value, reason):
    with pytest.raises(ValueError, match=reason) as failure:
        terms(**{field: value})
    assert "secret-account" not in str(failure.value)


@pytest.mark.parametrize("extra", ["dollar_amount", "stop_price", "tax_lots", "agent_initiated"])
def test_extra_unsupported_fields_are_rejected_instead_of_forwarded(extra):
    with pytest.raises(TypeError):
        terms(**{extra: "unsupported"})


@pytest.mark.parametrize(
    "ref_id",
    [
        REF.upper(),
        REF.replace("-", ""),
        "not-a-uuid",
        "",
        None,
        UUID(REF),
        "00000000-0000-0000-0000-000000000000",
    ],
)
def test_caller_must_supply_one_canonical_uuid_without_generated_fallback(ref_id):
    with pytest.raises(ValueError, match="stock_ref_id_invalid"):
        api().prepare_stock_order_payloads(terms(), ref_id=ref_id)


def test_preparation_requires_exact_typed_terms():
    with pytest.raises(ValueError, match="typed_stock_order_terms_required"):
        api().prepare_stock_order_payloads({"account_number": "secret-account"}, ref_id=REF)


def test_prepared_terms_and_reference_are_immutable_and_returned_dicts_are_defensive():
    selected = terms()
    prepared = api().prepare_stock_order_payloads(selected, ref_id=REF)
    with pytest.raises(FrozenInstanceError):
        selected.quantity = D("3")
    with pytest.raises(FrozenInstanceError):
        prepared.ref_id = "ec6d1c33-3d1b-41a9-ae2f-7c77471a33bb"
    review = prepared.review_arguments
    review["quantity"] = "999"
    placement = prepared.place_arguments
    placement["account_number"] = "foreign"
    assert prepared.review_arguments["quantity"] == "2"
    assert prepared.place_arguments["account_number"] == "fictional-account"
    assert prepared.place_arguments == prepared.review_arguments | {"ref_id": REF}


@pytest.mark.parametrize("tamper", ["terms", "ref"])
def test_valid_value_mutation_cannot_rebind_an_already_prepared_order(tamper):
    selected = terms()
    prepared = api().prepare_stock_order_payloads(selected, ref_id=REF)
    if tamper == "terms":
        object.__setattr__(selected, "quantity", D("3"))
    else:
        object.__setattr__(prepared, "ref_id", "ec6d1c33-3d1b-41a9-ae2f-7c77471a33bb")
    with pytest.raises(ValueError, match="stock_order_binding_changed"):
        _ = prepared.place_arguments
    with pytest.raises(ValueError, match="stock_order_binding_changed"):
        _ = prepared.review_arguments


def test_retry_binding_is_stable_and_distinguishes_terms_from_the_callers_reference():
    prepare = api().prepare_stock_order_payloads
    a, retry = prepare(terms(), ref_id=REF), prepare(terms(), ref_id=REF)
    new_ref = prepare(terms(), ref_id="ec6d1c33-3d1b-41a9-ae2f-7c77471a33bb")
    changed = prepare(terms(quantity=D("3")), ref_id=REF)
    assert (
        a.review_arguments == retry.review_arguments and a.place_arguments == retry.place_arguments
    )
    assert a.terms_hash == retry.terms_hash == new_ref.terms_hash
    assert a.order_binding_hash == retry.order_binding_hash != new_ref.order_binding_hash
    assert a.terms_hash != changed.terms_hash and a.order_binding_hash != changed.order_binding_hash


def test_serialized_terms_and_hashes_ignore_ambient_decimal_precision_and_rounding():
    selected = terms(order_type="limit", quantity=D("25"), limit_price=D("123.456789123"))
    expected = api().prepare_stock_order_payloads(selected, ref_id=REF)
    with localcontext() as context:
        context.prec, context.rounding, context.Emax, context.Emin = 2, ROUND_UP, 9, -9
        actual = api().prepare_stock_order_payloads(selected, ref_id=REF)
        assert actual.review_arguments == expected.review_arguments
        assert actual.terms_hash == expected.terms_hash
        assert actual.order_binding_hash == expected.order_binding_hash


def test_sensitive_terms_and_payloads_are_absent_from_object_reprs():
    selected = terms(account_number="fictional-secret-account")
    prepared = api().prepare_stock_order_payloads(selected, ref_id=REF)
    for value in (selected, prepared):
        assert "fictional-secret-account" not in repr(value)
        assert REF not in repr(value)


def test_emitted_shapes_match_the_saved_official_declared_input_field_types():
    # Projection of the exact 2026-10-26 tool descriptions' TypeScript args;
    # this is not a claim that a background server inputSchema was qualified.
    required = {"account_number", "side", "symbol", "type"}
    declared_strings = required | {
        "quantity",
        "dollar_amount",
        "limit_price",
        "stop_price",
        "market_hours",
        "time_in_force",
    }
    for order_type in ("market", "limit"):
        prepared = api().prepare_stock_order_payloads(
            terms(order_type=order_type, limit_price=D("101") if order_type == "limit" else None),
            ref_id=REF,
        )
        review, placement = prepared.review_arguments, prepared.place_arguments
        assert required <= review.keys() <= declared_strings
        assert required <= placement.keys() <= declared_strings | {"ref_id"}
        assert all(type(value) is str for value in placement.values())
        assert placement == review | {"ref_id": REF}
