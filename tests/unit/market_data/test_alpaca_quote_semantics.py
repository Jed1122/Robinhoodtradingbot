"""Literal native-shaped inputs test interpretation, never source qualification."""

import importlib
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, Inexact, Overflow, Rounded, localcontext

import pytest

from trading_bot.market_data.alpaca_native import AlpacaQuoteRecord


def api():
    try:
        return importlib.import_module("trading_bot.market_data.alpaca_quote_semantics")
    except ModuleNotFoundError:
        pytest.fail("native quote semantics decoder is not implemented")


def record(**changes):
    return AlpacaQuoteRecord(
        **(
            {
                "body_sha256": "a" * 64,
                "page_index": 7,
                "row_index": 12,
                "timestamp_ns": 1762232400000000001,
                "bid": Decimal("500.01"),
                "ask": Decimal("500.02"),
                "bid_size": 40,
                "ask_size": 80,
                "bid_exchange": "P",
                "ask_exchange": "N",
                "conditions": ("R",),
                "tape": "B",
            }
            | changes
        )
    )


@pytest.mark.parametrize(
    "conditions,bid,ask",
    [
        (("R",), "R", "R"),
        (("A", "B"), "A", "B"),
        ((" ", "R"), " ", "R"),
        ((), None, None),
        (("R", "A", "B"), None, None),
    ],
)
def test_conditions_decode_both_sides_or_ordered_sides_without_inventing_missing_flags(
    conditions, bid, ask
):
    result = api().interpret_alpaca_quote(record(conditions=conditions))
    assert result.bid_condition == bid
    assert result.ask_condition == ask
    assert "condition_eligibility_unverified" in result.reasons
    assert ("condition_interpretation_unverified" in result.reasons) is (bid is None)


def test_result_binds_same_native_record_and_protocol_without_changing_legacy_identity():
    original = record(conditions=("B", "A"))
    original_hash = original.record_hash
    original_reasons = original.observation_reasons
    result = api().interpret_alpaca_quote(original)
    assert result.record is original
    assert result.record_hash == original_hash
    assert result.protocol_reference_sha256 == (
        "82feb537497fb2f1518dd921987831780239e6e798ae225b15ccaaacb697a9a8"
    )
    assert result.record.body_sha256 == "a" * 64
    assert (result.record.page_index, result.record.row_index) == (7, 12)
    assert result.record.timestamp_ns == 1762232400000000001
    assert (result.record.bid_exchange, result.record.ask_exchange, result.record.tape) == (
        "P",
        "N",
        "B",
    )
    assert result.record.conditions == ("B", "A")
    assert result.record.publication_at_ns is None
    assert original.record_hash == original_hash
    assert original.observation_reasons == original_reasons
    assert result.source_qualified is False
    assert result.execution_enabled is False
    assert result.evidence_promotable is False
    assert {
        "condition_eligibility_unverified",
        "control_coverage_unverified",
        "fractional_terms_unverified",
    } <= set(result.reasons)


@pytest.mark.parametrize(
    "timestamp,shares,reason",
    [
        (1451917800000000001, None, "round_lot_conversion_unverified"),
        (1762127999999999999, None, "round_lot_conversion_unverified"),
        (1762128000000000000, None, "size_transition_unverified"),
        (1762232399999999999, None, "size_transition_unverified"),
        (1762232400000000000, Decimal("40"), None),
    ],
)
def test_only_share_era_is_normalized_and_transition_boundaries_remain_unresolved(
    timestamp, shares, reason
):
    original = record(timestamp_ns=timestamp)
    result = api().interpret_alpaca_quote(original)
    assert result.bid_size_shares == shares
    assert result.ask_size_shares == (Decimal("80") if shares is not None else None)
    assert original.bid_size == 40 and original.ask_size == 80
    if reason is not None:
        assert reason in result.reasons
    assert result.execution_enabled is False


@pytest.mark.parametrize(
    "bid,ask,reasons",
    [
        ("0", "500", {"inactive_bid"}),
        ("500", "0", {"inactive_ask"}),
        ("0", "0", {"inactive_bid", "inactive_ask"}),
        ("501", "500", {"crossed_quote"}),
        ("500", "500", {"locked_quote"}),
    ],
)
def test_inactive_crossed_and_locked_quotes_are_described_not_admitted(bid, ask, reasons):
    result = api().interpret_alpaca_quote(record(bid=Decimal(bid), ask=Decimal(ask)))
    assert reasons <= set(result.reasons)
    assert "condition_eligibility_unverified" in result.reasons
    assert result.source_qualified is False and result.execution_enabled is False


def test_exact_uint32_share_sizes_ignore_hostile_decimal_context():
    original = record(bid_size=4294967295, ask_size=0)
    with localcontext() as context:
        context.prec = 1
        context.Emax = 1
        context.Emin = -1
        for signal in (Inexact, Rounded, Overflow):
            context.traps[signal] = True
        result = api().interpret_alpaca_quote(original)
    assert result.bid_size_shares == Decimal("4294967295")
    assert result.ask_size_shares == Decimal("0")
    assert type(result.bid_size_shares) is Decimal


@pytest.mark.parametrize("value", [None, True, {}, "private-token", 1, object()])
def test_wrong_top_level_types_return_only_sanitized_errors(value):
    module = api()
    with pytest.raises(module.AlpacaQuoteSemanticsError, match=r"^alpaca_quote_semantics_invalid$"):
        module.interpret_alpaca_quote(value)


@pytest.mark.parametrize(
    "name,value",
    [
        ("body_sha256", "private-token"),
        ("page_index", True),
        ("page_index", 128),
        ("row_index", -1),
        ("row_index", 10000),
        ("timestamp_ns", True),
        ("timestamp_ns", -1),
        ("timestamp_ns", 2**63),
        ("bid", 500.01),
        ("bid", Decimal("NaN")),
        ("bid", Decimal("Infinity")),
        ("bid", Decimal("-1")),
        ("bid", Decimal("1e600")),
        ("ask", 1),
        ("bid_size", True),
        ("bid_size", -1),
        ("bid_size", 2**32),
        ("ask_size", Decimal("1")),
        ("conditions", ["R"]),
        ("conditions", ("R",) * 33),
        ("conditions", ("\nprivate-token",)),
        ("conditions", ("\u00e9",)),
        ("conditions", ("R" * 17,)),
        ("bid_exchange", ""),
        ("ask_exchange", "\u00e9"),
        ("tape", "X"),
        ("publication_at_ns", 1),
        ("executable", True),
        ("executable", 0),
    ],
)
def test_decoder_revalidates_mutated_native_fields_and_flags(name, value):
    module = api()
    original = record()
    object.__setattr__(original, name, value)
    with pytest.raises(module.AlpacaQuoteSemanticsError, match=r"^alpaca_quote_semantics_invalid$"):
        module.interpret_alpaca_quote(original)


def test_native_subclass_cannot_override_unit_or_validation():
    class ForgedQuote(AlpacaQuoteRecord):
        @property
        def size_unit(self):
            return "shares"

    original = record(timestamp_ns=1451917800000000001)
    forged = object.__new__(ForgedQuote)
    for name in original.__dataclass_fields__:
        object.__setattr__(forged, name, getattr(original, name))
    module = api()
    with pytest.raises(module.AlpacaQuoteSemanticsError, match=r"^alpaca_quote_semantics_invalid$"):
        module.interpret_alpaca_quote(forged)


def test_incomplete_exact_native_instance_is_sanitized():
    module = api()
    with pytest.raises(module.AlpacaQuoteSemanticsError, match=r"^alpaca_quote_semantics_invalid$"):
        module.interpret_alpaca_quote(object.__new__(AlpacaQuoteRecord))


def test_result_and_safety_flags_are_frozen_without_caller_switches():
    module = api()
    result = module.interpret_alpaca_quote(record())
    with pytest.raises(FrozenInstanceError):
        result.execution_enabled = True
    for name in ("source_qualified", "execution_enabled", "evidence_promotable"):
        assert result.__dataclass_fields__[name].init is False
        with pytest.raises(FrozenInstanceError):
            setattr(result, name, True)
        # CPython versions reject init=False replacement through different paths.
        with pytest.raises((TypeError, ValueError), match=name):
            replace(result, **{name: True})
        assert getattr(result, name) is False
    with pytest.raises(TypeError):
        module.interpret_alpaca_quote(record(), verified=True)


@pytest.mark.parametrize("name", ["source_qualified", "execution_enabled", "evidence_promotable"])
def test_result_revalidation_rejects_unsafe_flag_mutation(name):
    module = api()
    result = module.interpret_alpaca_quote(record())
    object.__setattr__(result, name, True)
    with pytest.raises(module.AlpacaQuoteSemanticsError, match=r"^alpaca_quote_semantics_invalid$"):
        result.__post_init__()
