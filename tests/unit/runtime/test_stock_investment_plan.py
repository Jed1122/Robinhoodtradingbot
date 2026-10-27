"""Research-to-allocation planning, using exclusively fictional owned snapshots."""

import importlib
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.portfolio.test_stock_allocation import context, exposure
from tests.unit.runtime.test_stock_investment_evidence import NOW, PROFILE, inputs
from trading_bot.market_data.recording import canonical_json
from trading_bot.research.stock_investment_decisions import CurrentInvestmentPolicy


def api():
    try:
        return importlib.import_module("trading_bot.runtime.stock_investment_plan")
    except ModuleNotFoundError:
        pytest.fail("current research-to-proposal planner missing")


def controls(**changes):
    values = dict(
        research_enabled=True,
        kill_switch_active=False,
        tactical_entries_suspended=False,
        as_of=NOW,
        expires_at=NOW + timedelta(minutes=5),
        source_hash="4" * 64,
    )
    values.update(changes)
    return api().StockPlanningControls(**values)


def issuer(**changes):
    values = dict(
        symbol="ALFA",
        instrument_id="instrument-ALFA",
        issuer_id="issuer-ALFA",
        as_of=NOW,
        expires_at=NOW + timedelta(days=1),
        source_hash="5" * 64,
    )
    values.update(changes)
    return api().StockIssuerIdentity(**values)


def plan(source=None, **changes):
    values = dict(
        worker_profile_id=PROFILE,
        policy=CurrentInvestmentPolicy(
            financial_profile="current_provider_v1",
            policy_id="current-stock-investment-provider-v1",
        ),
        analysis_code_hash="6" * 64,
        controls=controls(),
        allocation_context=context(),
        issuers=(issuer(),),
    )
    values.update(changes)
    return api().compile_current_stock_plan(inputs() if source is None else source, **values)


def test_verified_current_research_reaches_a_cash_ceiling_without_creating_an_order():
    result = plan()
    assert len(result.rankings.long_term) == len(result.rankings.tactical) == 1
    assert result.allocation.total_proposed == Decimal(100)
    assert result.allocation.proposals[0].sleeve == "long_term"
    assert (
        result.allocation.proposals[0].decision_hash == result.rankings.long_term[0].decision_hash
    )
    assert result.execution_authorized is result.live_authorized is result.orders_created is False
    assert result.performance_evidence == "unproven_not_a_gate"
    assert len(result.evidence_hash) == 64
    assert "fresh_broker_quote_and_tradability" in result.remaining_execution_checks


def test_research_without_an_account_still_ranks_but_cannot_invent_cash():
    result = plan(allocation_context=None)
    assert len(result.rankings.long_term) == 1
    assert result.allocation is None
    assert "account_context_missing" in result.needs


def test_kill_switch_and_missing_or_expired_controls_block_all_new_proposals():
    for guarded in (
        None,
        controls(kill_switch_active=True),
        controls(expires_at=NOW - timedelta(seconds=1), as_of=NOW - timedelta(minutes=1)),
    ):
        result = plan(controls=guarded)
        assert result.allocation is None and result.needs
        assert result.rankings.long_term


def test_disabled_research_does_not_emit_new_decisions():
    result = plan(controls=controls(research_enabled=False))
    assert result.rankings is result.allocation is None
    assert result.needs == ("research_disabled",)


def test_unknown_or_rebound_issuer_cannot_circumvent_concentration_checks():
    for identities in ((), (issuer(instrument_id="other"),)):
        result = plan(issuers=identities)
        assert result.allocation.total_proposed == 0
        assert any(x.reason == "candidate_metadata_unknown" for x in result.allocation.denials)


@pytest.mark.parametrize("case", ("controls", "issuer"))
def test_allocation_authority_is_current_at_actual_review_not_old_source_time(case):
    changes = {"reviewed_at": NOW + timedelta(minutes=2)}
    if case == "controls":
        changes["controls"] = controls(expires_at=NOW + timedelta(minutes=1))
    else:
        changes["issuers"] = (issuer(expires_at=NOW + timedelta(minutes=1)),)
    result = plan(**changes)
    assert result.as_of == NOW
    assert result.allocation is None or result.allocation.total_proposed == 0


def test_issuer_metadata_must_be_current_and_unique():
    with pytest.raises(ValueError, match="current_stock_plan_invalid"):
        plan(issuers=(issuer(), issuer()))
    result = plan(
        issuers=(issuer(as_of=NOW - timedelta(days=2), expires_at=NOW - timedelta(days=1)),)
    )
    assert result.allocation.total_proposed == 0


def test_missing_held_monitoring_blocks_new_spending_without_erasing_rankings():
    source = replace(inputs(), needs=("held_evidence_missing:BETA",), status="needs_research")
    result = plan(source)
    assert result.rankings.long_term and result.allocation is None
    assert "held_evidence_missing:BETA" in result.needs


def test_nonpositive_research_can_choose_no_investment_despite_available_cash():
    result = plan(inputs(columns={"Annual EPS growth": "-0.1"}))
    assert result.rankings.long_term == result.rankings.tactical == ()
    assert result.allocation.total_proposed == 0


def test_report_hash_rejects_mutation_of_fixed_execution_authority():
    result = plan()
    object.__setattr__(result, "live_authorized", True)
    with pytest.raises(ValueError, match="current_stock_plan_invalid"):
        _ = result.evidence_hash


def test_owned_positions_cannot_be_omitted_from_current_research_inventory():
    actual = context(cash="900", equity="1000", exposures=(exposure("BETA"),))
    result = plan(allocation_context=actual)
    assert result.allocation is None
    assert "owned_research_inventory_mismatch" in result.needs


def test_owned_research_sleeve_must_match_the_reconciled_position():
    source = inputs(held=("ALFA",))
    actual = context(cash="900", equity="1000", exposures=(exposure("ALFA"),))
    result = plan(source, allocation_context=actual, held_sleeves=(("ALFA", "tactical"),))
    assert result.allocation is None
    assert "owned_research_inventory_mismatch" in result.needs


def test_correct_owned_research_inventory_is_not_blocked_or_reentered():
    from tests.unit.runtime.test_stock_portfolio_proposals import joined

    source = inputs(held=("ALFA",))
    _, _, actual, owner = joined(sleeve="long_term")
    result = plan(
        source,
        allocation_context=actual,
        held_sleeves=(("ALFA", "long_term"),),
        owned_holding_contexts=(owner,),
    )
    assert result.allocation is not None and result.allocation.total_proposed == 0
    assert "owned_research_inventory_mismatch" not in result.needs


def test_plan_includes_source_bound_portfolio_proposals_without_cash_credit():
    result = plan()
    assert result.portfolio_proposals is not None
    assert result.portfolio_proposals.cash_credited is False
    assert result.portfolio_proposals.orders_created is False


def test_owned_holding_and_profit_trims_are_composed_without_spending_estimated_sale_proceeds():
    from tests.unit.runtime.test_stock_portfolio_proposals import REVIEWED, joined, request

    _, _, portfolio, owner = joined()
    result = plan(
        inputs(held=("ALFA",)),
        allocation_context=portfolio,
        held_sleeves=(("ALFA", "tactical"),),
        owned_holding_contexts=(owner,),
        profit_requests=(request(owner),),
        reviewed_at=REVIEWED,
    )
    proposals = result.portfolio_proposals
    assert proposals.holding_reviews.reviews[0].extension_approved
    (profit,) = proposals.profit_reductions
    assert profit.status == "proposed" and profit.quantity == Decimal("1.666666")
    assert abs(profit.estimated_realized_gain - Decimal("33.33333")) < Decimal(".0001")
    assert result.allocation.total_proposed == 0
    assert result.allocation.cash_cap == Decimal(780)  # actual1000cash minus10%reserve220
    assert not proposals.cash_credited and not result.live_authorized


def test_owned_lot_quantity_mismatch_reaches_the_top_level_entry_blocker():
    from tests.unit.runtime.test_stock_portfolio_proposals import REVIEWED, joined

    _, _, portfolio, owner = joined()
    position = replace(portfolio.portfolio.positions[0], quantity=Decimal(11))
    portfolio = replace(portfolio, portfolio=replace(portfolio.portfolio, positions=(position,)))
    result = plan(
        inputs(held=("ALFA",)),
        allocation_context=portfolio,
        held_sleeves=(("ALFA", "tactical"),),
        owned_holding_contexts=(owner,),
        reviewed_at=REVIEWED,
    )
    assert result.allocation is None
    assert any("quantity" in reason for reason in result.needs)


def test_unresearched_new_candidate_is_review_without_blocking_a_fully_researched_candidate():
    source = inputs()
    discovery = json.loads(source.discovery_json)
    discovery["screen"]["opportunities"].append({"symbol": "BETA"})
    beta = replace(inputs(symbol="BETA").scanner_rows[0], record_index=1)
    source = replace(
        source,
        discovery_json=canonical_json(discovery),
        scanner_rows=(*source.scanner_rows, beta),
        status="needs_research",
        needs=("discovery_dossier_missing:BETA",),
    )
    result = plan(source)
    assert result.allocation is not None
    assert result.allocation.total_proposed == Decimal(100)
    assert {x.symbol for x in result.allocation.proposals} == {"ALFA"}
    beta_decisions = tuple(x for x in result.rankings.assessments if x.symbol == "BETA")
    assert beta_decisions and all(x.action == "review" for x in beta_decisions)
    assert "discovery_dossier_missing:BETA" in result.needs
