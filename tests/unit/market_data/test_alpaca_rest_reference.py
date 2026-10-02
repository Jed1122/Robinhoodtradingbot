"""Schema facts never certify executions, controls, or share capacity."""

import importlib
from dataclasses import asdict, replace
from decimal import Decimal

import pytest

from tests.unit.market_data.test_alpaca_quote_semantics import record


def api():
    return importlib.import_module("trading_bot.market_data.alpaca_rest_reference")


@pytest.mark.parametrize(
    "stamp,unit",
    [
        (1451917800000000001, "round_lots"),
        (1762127999999999999, "round_lots"),
        (1762128000000000000, None),
        (1762232399999999999, None),
        (1762232400000000000, "shares"),
    ],
)
def test_dated_rest_units_are_facts_not_invented_share_capacity(stamp, unit):
    original = record(timestamp_ns=stamp)
    old_hash = original.record_hash
    result = api().assess_alpaca_rest_quote(original)
    assert result.documented_size_unit == unit
    assert result.raw_bid_size == 40 and result.raw_ask_size == 80
    assert result.record_hash == old_hash == original.record_hash
    assert result.round_lot_multiplier is None
    assert result.execution_qualified is False
    assert result.protocol_reference_sha256 == (
        "d408356bc3fc73d19fbab43a01501f05d1e888da60e21a03460cd3d2d7696cd9"
    )
    assert ("size_transition_timezone_unresolved" in result.reasons) is (unit is None)


@pytest.mark.parametrize(
    "conditions,bid,ask",
    [(("R",), "R", "R"), (("E", "F"), "E", "F"), ((), None, None)],
)
def test_ordered_side_flags_are_not_an_execution_allow_list(conditions, bid, ask):
    result = api().assess_alpaca_rest_quote(record(conditions=conditions))
    assert (result.bid_condition, result.ask_condition) == (bid, ask)
    assert result.condition_scope_documented is (bid is not None)
    assert "condition_eligibility_and_luld_unverified" in result.reasons
    assert result.execution_qualified is False


@pytest.mark.parametrize(
    "changes,quality",
    [
        ({}, "two_sided_uncrossed"),
        ({"bid": Decimal(0)}, "inactive_side"),
        ({"ask": Decimal(0)}, "inactive_side"),
        ({"ask": Decimal("500.01")}, "locked"),
        ({"bid": Decimal("501")}, "crossed"),
        ({"ask_size": 0}, "zero_size"),
    ],
)
def test_quote_quality_classification_preserves_all_observations(changes, quality):
    original = record(**changes)
    result = api().assess_alpaca_rest_quote(original)
    assert result.quality == quality
    assert original.record_hash == result.record_hash
    assert result.source_qualified is False and result.evidence_promotable is False
    assert result.report_hash == api().assess_alpaca_rest_quote(original).report_hash
    assert "bid" not in asdict(result) and "ask" not in asdict(result)


@pytest.mark.parametrize("field,value", [("executable", True), ("publication_at_ns", 1)])
def test_forged_native_flags_cannot_be_reset_into_a_valid_assessment(field, value):
    original = record()
    object.__setattr__(original, field, value)
    with pytest.raises(ValueError, match="alpaca_rest_reference_invalid"):
        api().assess_alpaca_rest_quote(original)


def test_reference_assessment_revalidates_prices_and_record_type():
    with pytest.raises(ValueError, match="alpaca_rest_reference_invalid"):
        api().assess_alpaca_rest_quote(object())
    original = record()
    object.__setattr__(original, "bid", Decimal("NaN"))
    with pytest.raises(ValueError, match="alpaca_rest_reference_invalid"):
        api().assess_alpaca_rest_quote(original)
    assert api().assess_alpaca_rest_quote(replace(record())).execution_qualified is False
