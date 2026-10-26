"""Fictional annual-source work and compact private policy context."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from tests.unit.research import test_stock_annual_policy as fixtures
from trading_bot.research import hybrid_policies as policies
from trading_bot.research import stock_annual_quality as annual_module


def functions():
    assert hasattr(policies, "_compile_annual_policy_inventory"), "owned annual context missing"
    return policies._compile_annual_policy_inventory, policies._evaluate_owned_policies


def test_public_policy_remains_fresh_but_owned_context_avoids_reparsing(monkeypatch):
    bundle = fixtures.annual()
    data = replace(fixtures.inputs(), annual_quality=(bundle,))
    old = annual_module._assess
    calls = []

    def counted(request):
        calls.append(request)
        return old(request)

    monkeypatch.setattr(annual_module, "_assess", counted)
    expected = policies.evaluate_policies(data)
    first = len(calls)
    assert first > 0
    assert policies.evaluate_policies(data) == expected
    assert len(calls) > first
    compile_context, evaluate_owned = functions()
    context = compile_context((bundle,))
    calls.clear()
    for _ in range(5):
        assert evaluate_owned(replace(data, annual_quality=()), context) == expected
    assert calls == []


def test_annual_empty_public_evidence_and_owned_context_are_exactly_compatible():
    compile_context, evaluate_owned = functions()
    data = fixtures.inputs()
    assert evaluate_owned(data, compile_context(())) == policies.evaluate_policies(data)


def test_owned_context_preserves_latest_unavailable_and_dedup_permutation():
    compile_context, evaluate_owned = functions()
    older = fixtures.annual(year=2023)
    latest = fixtures.annual(year=2024, omit=("short_debt",))
    data = fixtures.inputs()
    expected = policies.evaluate_policies(replace(data, annual_quality=(older, latest)))
    assert evaluate_owned(data, compile_context((latest, older, older))) == expected
    assert any(
        x.family == "quality_momentum" and isinstance(x, policies.UnavailablePolicy)
        for x in expected
    )


def test_owned_context_filters_future_inventory_without_backdating_receipts():
    compile_context, evaluate_owned = functions()
    old = fixtures.annual(year=2023)
    future = fixtures.annual(year=2025)
    data = fixtures.inputs()
    assert future.availability_proxy_at > data.information_at
    context = compile_context((old, future))
    assert evaluate_owned(data, context) == policies.evaluate_policies(
        replace(data, annual_quality=(old,))
    )
    assert future.request.filing.receipt.received_at == fixtures.RECEIVED


def test_compact_annual_numeric_and_clock_tampering_rejects():
    compile_context, evaluate_owned = functions()
    bundle = fixtures.annual()
    context = compile_context((bundle,))
    object.__setattr__(bundle, "roe", Decimal(999))
    with pytest.raises(ValueError):
        evaluate_owned(fixtures.inputs(), context)


def test_owned_context_rejects_same_day_original_ambiguity():
    compile_context, _ = functions()
    a = fixtures.annual(filing_id="a", filed=date(2024, 2, 9))
    b = fixtures.annual(filing_id="b", filed=date(2024, 2, 9))
    with pytest.raises(ValueError):
        compile_context((a, b))


def test_owned_context_rejects_mixed_public_annual_or_legacy_overlap():
    compile_context, evaluate_owned = functions()
    bundle = fixtures.annual()
    context = compile_context((bundle,))
    with pytest.raises(ValueError):
        evaluate_owned(replace(fixtures.inputs(), annual_quality=(bundle,)), context)
    with pytest.raises(ValueError):
        evaluate_owned(replace(fixtures.inputs(), facts=fixtures.legacy_quality()), context)


def test_owned_annual_leaf_does_not_rehash_complete_fact_batches_per_step(monkeypatch):
    from trading_bot.market_data.stock_filing_facts import StockFilingFacts

    compile_context, evaluate_owned = functions()
    bundle = fixtures.annual()
    context = compile_context((bundle,))
    previous = StockFilingFacts.facts_hash.fget
    calls = []

    def counted(value):
        calls.append(value)
        return previous(value)

    monkeypatch.setattr(StockFilingFacts, "facts_hash", property(counted))
    evaluate_owned(fixtures.inputs(), context)
    assert calls == []


def test_private_annual_decimal_leaf_is_independent_of_capitals_context():
    from decimal import localcontext

    compile_context, evaluate_owned = functions()
    bundle = fixtures.annual(changes={"income": {"value": "1e-100"}})
    with localcontext() as context:
        context.capitals = 0
        first = compile_context((bundle,))
    with localcontext() as context:
        context.capitals = 1
        second = compile_context((bundle,))
        assert evaluate_owned(fixtures.inputs(), first) == evaluate_owned(fixtures.inputs(), second)
    assert first.root == second.root
