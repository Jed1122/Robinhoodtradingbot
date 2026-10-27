"""Fictional source-bound portfolio composition, without broker/account I/O."""

import importlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction

import pytest

from tests.unit.portfolio.test_stock_allocation import candidate, context, exposure
from tests.unit.runtime.test_stock_investment_holdings import NOW, current, owned
from trading_bot.portfolio.stock_allocation import plan_stock_allocations
from trading_bot.portfolio.stock_holding import StockProtectiveEvidence
from trading_bot.portfolio.stock_profit_taking import (
    StockProfitExitState,
    StockProfitMethodProgress,
    StockProfitOrigin,
    StockProfitPolicy,
)

D = Decimal
REVIEWED = NOW + timedelta(minutes=1)


def api():
    try:
        return importlib.import_module("trading_bot.runtime.stock_portfolio_proposals")
    except ModuleNotFoundError:
        pytest.fail("source-bound portfolio proposal composition missing")


def joined(*, first=None, sleeve="tactical", columns=None):
    batch, rankings = current(sleeve=sleeve, columns=columns)
    owner = owned(first=first, sleeve=sleeve)
    portfolio = context(
        cash="1000",
        equity="2200",
        exposures=(exposure("ALFA", sleeve=sleeve, notional="1200"),),
    )
    position = replace(portfolio.portfolio.positions[0], quantity=D(10))
    portfolio = replace(portfolio, portfolio=replace(portfolio.portfolio, positions=(position,)))
    owner = replace(owner, reconciliation_hash=portfolio.reconciliation_hash)
    return batch, rankings, portfolio, owner


def request(owner, **changes):
    mandate = owner.mandate
    origin = StockProfitOrigin(
        episode_id=mandate.episode_id,
        instrument_id=mandate.instrument_id,
        symbol=mandate.symbol,
        designated_cash=D(1000),
        original_quantity=D(10),
        information_at=mandate.first_fill_at,
        source_hash="4" * 64,
    )
    state = StockProfitExitState(
        episode_id=mandate.episode_id,
        instrument_id=mandate.instrument_id,
        symbol=mandate.symbol,
        origin_hash=origin.evidence_hash,
        information_at=NOW - timedelta(minutes=1),
        received_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        source_hash="5" * 64,
        pending_exit_quantity=D(0),
        progress=(),
    )
    values = dict(
        episode_id=mandate.episode_id,
        method="principal",
        origin=origin,
        state=state,
        fractional_eligible=True,
        peak_price=None,
        tax_rate=D(".25"),
        disposal_method="fifo_estimate",
        policy=StockProfitPolicy(),
    )
    values.update(changes)
    return api().StockProfitProposalRequest(**values)


def compile_case(case=None, *, requests=(), **changes):
    batch, rankings, portfolio, owner = joined() if case is None else case
    args = dict(
        rankings=rankings,
        allocation_context=portfolio,
        owned=(owner,),
        profit_requests=requests,
        reviewed_at=REVIEWED,
    )
    args.update(changes)
    return api().compile_stock_portfolio_proposals(batch, **args)


def test_matching_actual_quantity_sources_and_reconciliation_extend_month_one():
    result = compile_case()
    assert result.entry_block_reasons == () and result.needs == ()
    review = result.holding_reviews.reviews[0]
    assert review.action == "HOLD" and review.extension_approved
    assert review.price_pnl.price_pnl == D(200)
    assert len(result.evidence_hash) == 64
    assert (
        result.execution_authorized
        is result.live_authorized
        is result.orders_created
        is result.reservations_created
        is result.cash_credited
        is result.global_concurrency_authority
        is False
    )


def test_two_month_full_exit_precedes_optional_profit_trim():
    case = joined(first=datetime(2026, 8, 25, 14, tzinfo=UTC))
    result = compile_case(case, requests=(request(case[3]),))
    assert result.holding_reviews.reviews[0].reason == "two_calendar_month_terminal_review"
    assert result.holding_reviews.reviews[0].action == "EXIT"
    assert result.profit_reductions == ()
    assert "profit_trim_suppressed_by_full_exit:ALFA" in result.needs


def test_early_entry_weakness_does_not_become_an_automatic_full_exit():
    case = joined(first=datetime(2026, 10, 1, 14, tzinfo=UTC), columns={"Provider SMA 50": "130"})
    result = compile_case(case)
    assert result.holding_reviews.reviews[0].action == "HOLD"
    assert not result.holding_reviews.reviews[0].extension_approved


def test_long_term_has_no_monthly_deadline_or_automatic_profit_cut():
    case = joined(first=datetime(2026, 8, 25, 14, tzinfo=UTC), sleeve="long_term")
    result = compile_case(case, requests=(request(case[3]),))
    assert result.holding_reviews.reviews[0].action == "HOLD"
    assert result.profit_reductions[0].reason_codes == ("long_term_no_automatic_profit_cut",)


def test_missing_portfolio_context_does_not_invent_flat_lots_or_buying_power():
    case = joined()
    result = compile_case(case, allocation_context=None, requests=(request(case[3]),))
    assert "portfolio_context_missing" in result.entry_block_reasons
    assert result.holding_reviews is None and result.profit_reductions == ()


@pytest.mark.parametrize("kind", ("quantity", "reconciliation", "sleeve", "symbol", "instrument"))
def test_position_metadata_and_owned_mandate_must_join_exactly(kind):
    batch, rankings, portfolio, owner = joined()
    if kind == "quantity":
        position = replace(portfolio.portfolio.positions[0], quantity=D(9))
        portfolio = replace(
            portfolio, portfolio=replace(portfolio.portfolio, positions=(position,))
        )
    elif kind == "reconciliation":
        owner = replace(owner, reconciliation_hash="6" * 64)
    else:
        row = portfolio.exposures[0]
        row = replace(
            row,
            **{
                "sleeve": {"sleeve": "long_term"},
                "symbol": {"symbol": "BETA"},
                "instrument": {"instrument_id": "foreign-id"},
            }[kind],
        )
        portfolio = replace(portfolio, exposures=(row,))
    result = compile_case((batch, rankings, portfolio, owner))
    assert result.entry_block_reasons
    assert result.holding_reviews is None or result.holding_reviews.reviews == ()
    assert result.profit_reductions == ()


def test_actual_position_without_owner_is_an_explicit_entry_blocker():
    result = compile_case(owned=())
    assert "owned_holding_context_missing:ALFA" in result.entry_block_reasons
    assert result.holding_reviews.reviews == ()


def test_missing_lots_keeps_unknown_instead_of_flat_and_profit_unavailable():
    case = joined()
    owner = replace(case[3], remaining_lots=None)
    result = compile_case((*case[:3], owner), requests=(request(owner),))
    assert "owned_lots_unknown:ALFA" in result.entry_block_reasons
    assert result.holding_reviews.reviews[0].action == "REVIEW"
    assert result.holding_reviews.reviews[0].price_pnl.status == "unavailable"
    assert result.profit_reductions[0].status == "unavailable"
    assert "remaining_lots_unknown" in result.profit_reductions[0].reason_codes


def test_missing_lot_quantity_cannot_publish_a_full_terminal_disposal():
    case = joined(first=datetime(2026, 8, 25, 14, tzinfo=UTC))
    owner = replace(case[3], remaining_lots=None)
    result = compile_case((*case[:3], owner))
    assert result.holding_reviews.reviews[0].action == "REVIEW"
    assert result.holding_reviews.reviews[0].price_pnl.status == "unavailable"
    assert "owned_lots_unknown:ALFA" in result.entry_block_reasons


@pytest.mark.parametrize("kind", ("future", "expired", "unknown_source", "unknown_currency"))
def test_portfolio_context_clocks_and_sources_block_entries(kind):
    case = joined()
    changes = {
        "future": dict(as_of=REVIEWED + timedelta(seconds=1)),
        "expired": dict(expires_at=REVIEWED),
        "unknown_source": dict(source_hash=None),
        "unknown_currency": dict(currency=None),
    }[kind]
    result = compile_case(case, allocation_context=replace(case[2], **changes))
    assert result.entry_block_reasons


@pytest.mark.parametrize("kind", ("future", "expired", "unknown_currency"))
def test_owned_context_clocks_and_currency_cannot_be_promoted(kind):
    case = joined()
    changes = {
        "future": dict(as_of=REVIEWED),
        "expired": dict(expires_at=REVIEWED),
        "unknown_currency": dict(currency=None),
    }[kind]
    owner = replace(case[3], **changes)
    result = compile_case((*case[:3], owner))
    assert result.entry_block_reasons
    assert result.holding_reviews is None or result.holding_reviews.reviews == ()


def test_future_nested_position_is_revalidated_before_composition():
    case = joined()
    position = replace(case[2].portfolio.positions[0], observed_at=NOW + timedelta(seconds=1))
    portfolio = replace(case[2], portfolio=replace(case[2].portfolio, positions=(position,)))
    result = compile_case(case, allocation_context=portfolio)
    assert "portfolio_context_invalid" in result.entry_block_reasons
    assert result.holding_reviews is None


def test_no_researched_position_can_be_added_or_dropped_from_actual_inventory():
    case = joined()
    batch = replace(case[0], stocks=())
    result = api().compile_stock_portfolio_proposals(
        batch,
        rankings=replace(case[1], assessments=(), long_term=(), tactical=()),
        allocation_context=case[2],
        owned=(case[3],),
        reviewed_at=REVIEWED,
    )
    assert "portfolio_research_inventory_mismatch" in result.entry_block_reasons
    assert result.profit_reductions == ()


def test_one_profit_method_per_episode_rejects_even_distinct_simultaneous_methods():
    case = joined()
    with pytest.raises(ValueError, match=r"^stock_portfolio_proposals_invalid$"):
        compile_case(case, requests=(request(case[3]), request(case[3], method="partial_first")))


def test_unknown_profit_request_owner_is_not_guessed_from_symbol():
    case = joined()
    req = request(case[3], episode_id="unknown-episode")
    result = compile_case(case, requests=(req,))
    assert "profit_request_owner_missing:unknown-episode" in result.entry_block_reasons
    assert result.profit_reductions == ()


def test_principal_gain_and_tax_are_not_gross_proceeds_or_current_cash():
    case = joined()
    result = compile_case(case, requests=(request(case[3]),))
    reduction = result.profit_reductions[0]
    qty = Fraction(1666666, 1000000)
    assert reduction.status == "proposed" and Fraction(reduction.quantity) == qty
    assert Fraction(reduction.estimated_gross_proceeds) == qty * 120
    assert Fraction(reduction.disposed_basis) == qty * 100
    assert Fraction(reduction.estimated_realized_gain) == qty * 20
    assert Fraction(reduction.estimated_tax_reserve) == qty * 20 / 4
    assert case[2].account.cash == case[2].portfolio.cash == 1000
    assert not result.cash_credited and not reduction.cash_credited


@pytest.mark.parametrize(
    "kind,status", (("pending", "hold"), ("completed", "hold"), ("unknown", "unavailable"))
)
def test_actual_pending_completed_or_unknown_exit_state_is_preserved(kind, status):
    case = joined()
    req = request(case[3])
    if kind == "pending":
        req = replace(req, state=replace(req.state, pending_exit_quantity=D(1)))
    elif kind == "unknown":
        req = replace(req, state=replace(req.state, pending_exit_quantity=None))
    else:
        owner = case[3]
        owner = replace(
            owner, remaining_lots=(replace(owner.remaining_lots[0], quantity=D(9), basis=D(900)),)
        )
        position = replace(case[2].portfolio.positions[0], quantity=D(9))
        portfolio = replace(case[2], portfolio=replace(case[2].portfolio, positions=(position,)))
        case = (*case[:2], portfolio, owner)
        req = replace(
            req,
            state=replace(
                req.state,
                progress=(
                    StockProfitMethodProgress(
                        method="principal",
                        target_quantity=D(1),
                        filled_quantity=D(1),
                        fill_ids=("actual-fill",),
                    ),
                ),
            ),
        )
    result = compile_case(case, requests=(req,))
    assert result.profit_reductions[0].status == status
    assert not result.profit_reductions[0].completed_threshold_created


@pytest.mark.parametrize("unknown", ("origin", "state", "fractional_eligible"))
def test_unknown_profit_facts_return_unavailable_without_defaults(unknown):
    case = joined()
    result = compile_case(case, requests=(request(case[3], **{unknown: None}),))
    assert result.profit_reductions[0].status == "unavailable"
    assert unknown + "_unknown" in result.profit_reductions[0].reason_codes


def test_unknown_disposal_and_tax_stay_unknown_and_policy_must_be_explicit():
    case = joined()
    result = compile_case(
        case, requests=(request(case[3], disposal_method="unknown", tax_rate=None),)
    )
    assert result.profit_reductions[0].status == "unavailable"
    assert result.profit_reductions[0].estimated_tax_reserve is None
    with pytest.raises(ValueError, match=r"^stock_portfolio_proposals_invalid$"):
        compile_case(case, requests=(request(case[3], policy=None),))


def test_protective_full_exit_precedes_profit_even_when_current_mark_missing():
    case = joined(first=datetime(2026, 10, 1, 14, tzinfo=UTC), columns={"Quotation currency": None})
    owner = case[3]
    owner = replace(
        owner,
        protective_evidence=StockProtectiveEvidence(
            owner.mandate.episode_id,
            owner.mandate.instrument_id,
            "ALFA",
            NOW,
            "protective_stop",
            "7" * 64,
        ),
    )
    result = compile_case((*case[:3], owner), requests=(request(owner),))
    assert result.holding_reviews.reviews[0].action == "EXIT"
    assert result.profit_reductions == ()
    assert "profit_trim_suppressed_by_full_exit:ALFA" in result.needs


def test_missing_mark_without_full_exit_yields_unavailable_profit():
    case = joined(columns={"Quotation currency": None})
    result = compile_case(case, requests=(request(case[3]),))
    assert result.profit_reductions[0].status == "unavailable"
    assert "price_unknown" in result.profit_reductions[0].reason_codes


def test_source_policy_and_method_requests_bind_hash_without_mutating_cash_or_research():
    case = joined()
    batch_hash, ranking_hash, context_hash = (
        case[0].evidence_hash,
        case[1].report_hash,
        case[2].evidence_hash,
    )
    before = plan_stock_allocations(case[2], (candidate("BETA"),), now=REVIEWED)
    req = request(case[3])
    first = compile_case(case, requests=(req,))
    second = compile_case(case, requests=(replace(req, tax_rate=None),))
    assert first.evidence_hash != second.evidence_hash
    assert case[0].evidence_hash == batch_hash and case[1].report_hash == ranking_hash
    assert case[2].evidence_hash == context_hash
    assert plan_stock_allocations(case[2], (candidate("BETA"),), now=REVIEWED) == before
    assert before.cash_cap == 780


def test_scope_flags_cannot_be_mutated_into_execution_or_cash_authority():
    result = compile_case()
    object.__setattr__(result, "cash_credited", True)
    with pytest.raises(ValueError, match=r"^stock_portfolio_proposals_invalid$"):
        _ = result.evidence_hash


def test_future_analytical_time_is_never_backdated():
    case = joined()
    with pytest.raises(ValueError, match=r"^stock_portfolio_proposals_invalid$"):
        compile_case(case, reviewed_at=NOW - timedelta(seconds=1))


def test_context_and_owned_expiries_fence_active_proposals_without_renewal():
    case = joined()
    owner = replace(case[3], expires_at=NOW + timedelta(minutes=3))
    result = compile_case((*case[:3], owner))
    assert result.expires_at == owner.expires_at
    assert result.reviewed_at == REVIEWED


def test_actual_profit_state_expiry_fences_proposal_set():
    case = joined()
    req = request(case[3])
    req = replace(req, state=replace(req.state, expires_at=NOW + timedelta(minutes=2)))
    result = compile_case(case, requests=(req,))
    assert result.profit_reductions[0].status == "proposed"
    assert result.expires_at == req.state.expires_at


def test_profit_state_information_age_horizon_cannot_outlive_policy():
    case = joined()
    req = request(case[3], policy=StockProfitPolicy(state_max_age_minutes=3))
    result = compile_case(case, requests=(req,))
    assert result.expires_at == NOW + timedelta(minutes=2)


def test_only_missing_context_diagnostics_have_no_active_validity_claim():
    result = compile_case(allocation_context=None)
    assert result.expires_at is None


def test_valid_mark_fences_negative_pnl_exit_even_when_company_decision_has_no_expiry():
    from trading_bot.research.stock_investment_decisions import (
        CurrentInvestmentPolicy,
        rank_current_stocks,
    )

    batch, _, portfolio, owner = joined(columns={"Last": "80"})
    stock = batch.stocks[0]
    stock = replace(
        stock,
        metrics=tuple(
            replace(m, value=None) if m.name == "net_income" else m for m in stock.metrics
        ),
    )
    batch = replace(batch, stocks=(stock,))
    rankings = rank_current_stocks(
        batch.stocks,
        as_of=NOW,
        policy=CurrentInvestmentPolicy(
            financial_profile="current_provider_v1",
            policy_id="current-stock-investment-provider-v1",
        ),
    )
    assert rankings.assessments[0].expires_at is None
    far = NOW + timedelta(hours=3)
    result = compile_case(
        (batch, rankings, replace(portfolio, expires_at=far), replace(owner, expires_at=far))
    )
    assert result.holding_reviews.reviews[0].action == "EXIT"
    assert result.holding_reviews.reviews[0].price_pnl.price_pnl == -200
    price_ref = next(m for m in stock.metrics if m.name == "scanner_price").refs[0]
    assert result.expires_at == min(
        price_ref.expires_at, price_ref.received_at + timedelta(minutes=120)
    )


@pytest.mark.parametrize("kind", ("duplicate", "foreign_evidence", "future_decision"))
def test_rankings_must_bind_the_complete_current_evidence_inventory(kind):
    case = joined()
    decision = case[1].assessments[0]
    if kind == "duplicate":
        assessments = (decision, decision)
    elif kind == "foreign_evidence":
        assessments = (replace(decision, evidence_hash="9" * 64),)
    else:
        assessments = (replace(decision, as_of=NOW + timedelta(seconds=1)),)
    with pytest.raises(ValueError, match=r"^stock_portfolio_proposals_invalid$"):
        compile_case(case, rankings=replace(case[1], assessments=assessments))


@pytest.mark.parametrize("kind", ("origin", "state"))
def test_foreign_profit_source_owner_is_rejected_without_symbol_guessing(kind):
    case = joined()
    req = request(case[3])
    req = replace(req, **{kind: replace(getattr(req, kind), instrument_id="foreign-id")})
    with pytest.raises(ValueError, match=r"^stock_portfolio_proposals_invalid$"):
        compile_case(case, requests=(req,))


def test_owned_fee_and_slippage_are_applied_once_before_gain_tax():
    case = joined()
    owner = replace(
        case[3], costs=replace(case[3].costs, fee=D(".075"), adverse_slippage_bps=D(37))
    )
    result = compile_case((*case[:3], owner), requests=(request(owner),))
    reduction = result.profit_reductions[0]
    qty = Fraction(1666666, 1000000)
    net = qty * 120 * Fraction(9963, 10000) - Fraction(3, 40)
    assert Fraction(reduction.estimated_net_proceeds) == net
    assert Fraction(reduction.estimated_realized_gain) == net - qty * 100
    assert Fraction(reduction.estimated_tax_reserve) == (net - qty * 100) / 4
