"""Current-policy intent preparation uses fictional offline evidence only."""

import hashlib
import importlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from tests.unit.portfolio.test_stock_allocation import context as allocation
from tests.unit.portfolio.test_stock_allocation import exposure
from tests.unit.runtime.test_stock_investment_evidence import NOW, PROFILE, inputs
from tests.unit.runtime.test_stock_investment_plan import controls, issuer
from trading_bot.config.hybrid import HybridSettings
from trading_bot.domain import AssetClass, ExecutionMode, Instrument, MarketClock
from trading_bot.hybrid.models import Account, AllocationEpisode, FillFact, Lot, PaperOrder, Quote
from trading_bot.market_data.recording import canonical_json
from trading_bot.research.stock_investment_decisions import CurrentInvestmentPolicy
from trading_bot.runtime.stock_investment_plan import compile_current_stock_plan
from trading_bot.runtime.stock_investment_reports import current_stock_plan_document


def api():
    try:
        return importlib.import_module("trading_bot.execution.stock_intents")
    except ModuleNotFoundError:
        pytest.fail("pure current-stock simulation preparation missing")


def test_simulation_contract_has_explicit_typed_names_and_no_default_live_path():
    module = api()
    for name in (
        "StockExecutionMarketEvidence",
        "StockExecutionRiskStop",
        "StockExecutionSelection",
        "StockExecutionContext",
        "StockSimulationGrant",
        "PreparedStockExecution",
        "stock_simulation_account_hash",
        "prepare_stock_execution",
    ):
        assert hasattr(module, name)


def prepared_case(*, sleeve="long_term", instrument_changes=None, policy=None):
    module = api()
    account = Account(paused=False)
    before = module.stock_simulation_account_hash(account)
    source = inputs()
    ctx = allocation()
    ctx = replace(
        ctx,
        account=replace(ctx.account, account_id="sim-fictional"),
        portfolio=replace(ctx.portfolio, account_id="sim-fictional"),
        reconciliation_hash=before,
    )
    policy = policy or HybridSettings()
    selected_policy = CurrentInvestmentPolicy(
        financial_profile="current_provider_v1", policy_id="current-stock-investment-provider-v1"
    )
    limits = None
    if sleeve == "tactical":
        from trading_bot.portfolio.stock_allocation import StockAllocationLimits

        limits = StockAllocationLimits(long_term_target=D(0))
    plan = compile_current_stock_plan(
        source,
        worker_profile_id=PROFILE,
        policy=selected_policy,
        analysis_code_hash="6" * 64,
        controls=controls(),
        allocation_context=ctx,
        issuers=(issuer(),),
        limits=limits,
    )
    proposal = next(x for x in plan.allocation.proposals if x.sleeve == sleeve)
    instrument = Instrument(
        "instrument-ALFA",
        "ALFA",
        AssetClass.EQUITY,
        "active",
        True,
        True,
        D(".01"),
        D(".000001"),
        D(".000001"),
        D(1),
        None,
        "technology",
        NOW,
        "7" * 64,
    )
    if instrument_changes:
        instrument = replace(instrument, **instrument_changes)
    mark = Quote(
        symbol="ALFA",
        bid=D(120),
        ask=D("120.01"),
        as_of=NOW,
        tradable=True,
        fractional=True,
        regular_session=True,
        halted=False,
        average_dollar_volume=D(30000000),
        sector="technology",
        earnings_clear=True,
    )
    market = module.StockExecutionMarketEvidence(
        instrument=instrument,
        quote=mark,
        market_clock=MarketClock(
            AssetClass.EQUITY, "XNYS", NOW, True, False, False, False, None, None
        ),
        currency="USD",
        received_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
        source_hash="7" * 64,
        sector_source_hash="8" * 64,
        earnings_source_hash="9" * 64,
        liquidity_source_hash="a" * 64,
    )
    document = current_stock_plan_document(plan)
    report_hash = hashlib.sha256(canonical_json(document).encode()).hexdigest()
    context = module.StockExecutionContext(
        plan=plan,
        inputs=source,
        policy=selected_policy,
        controls=controls(),
        allocation_context=ctx,
        issuers=(issuer(),),
        held_sleeves=(),
        owned_holding_contexts=(),
        profit_requests=(),
        limits=limits,
        execution_policy=policy,
        execution_config_hash="b" * 64,
        source_report_body_sha256=report_hash,
        market=(market,),
    )
    stop = (
        None
        if sleeve == "long_term"
        else module.StockExecutionRiskStop(
            instrument_id=instrument.id,
            symbol=instrument.symbol,
            price=D(114),
            as_of=NOW,
            expires_at=NOW + timedelta(minutes=1),
            source_hash="c" * 64,
        )
    )
    selection = module.StockExecutionSelection(
        kind="entry",
        symbol="ALFA",
        sleeve=sleeve,
        source_evidence_hash=proposal.decision_hash,
        episode_id=None,
        method=None,
        order_type="market",
        limit_price=None,
        risk_stop=stop,
    )
    grant = module.StockSimulationGrant(
        approval_id="manual-fictional-1",
        mode=ExecutionMode.SIMULATION,
        simulation_account_id="sim-fictional",
        sleeve=sleeve,
        approved_at=NOW + timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
        plan_hash=plan.evidence_hash,
        policy_hash=plan.policy_hash,
        source_config_hash=plan.source_config_hash,
        analysis_code_hash=plan.analysis_code_hash,
        execution_config_hash=context.execution_config_hash,
        source_report_body_sha256=report_hash,
        context_hash=context.evidence_hash,
        selection_hash=selection.evidence_hash,
        before_account_hash=before,
    )
    return context, account, grant, selection


def prepare(case=None, *, now=None, **changes):
    ctx, account, grant, selection = prepared_case() if case is None else case
    values = dict(
        account=account,
        simulation_account_id="sim-fictional",
        grant=grant,
        selection=selection,
        now=NOW + timedelta(seconds=1) if now is None else now,
    )
    values.update(changes)
    return api().prepare_stock_execution(ctx, **values)


def test_current_long_term_cash_ceiling_maps_to_fractional_market_without_fake_stop():
    ctx, account, grant, selection = prepared_case()
    before = account.model_dump_json()
    result = prepare((ctx, account, grant, selection))
    assert result.paper_order.sleeve == "long_term" and result.paper_order.risk_stop is None
    assert result.intent.quantity == result.paper_order.quantity > 0
    assert result.intent.stop_price is None
    assert result.intent.id == result.paper_order.id == result.payloads.ref_id
    assert result.payloads.review_arguments["account_number"] == "sim-fictional"
    assert result.payloads.review_arguments["type"] == "market"
    assert result.intent.quantity * (D("120.01") * (1 + D(5) / 10000)) + D(".01") <= D(100)
    assert result.source_report_body_sha256 == ctx.source_report_body_sha256
    assert not result.live_authorized and not result.broker_transport_allowed
    assert not result.reservations_created and account.model_dump_json() == before


def test_retry_clock_keeps_identical_uuid_and_all_original_semantic_bytes():
    case = prepared_case()
    first = prepare(case)
    second = prepare(case, now=NOW + timedelta(seconds=2))
    assert first == second
    assert first.to_record() == second.to_record()
    assert first.created_at == case[2].approved_at
    assert first.expires_at == NOW + timedelta(seconds=5)


def test_tactical_stop_and_both_known_leg_costs_fit_half_percent_budget():
    case = prepared_case(sleeve="tactical", policy=HybridSettings(simulation_fee_usd=D("2.45")))
    result = prepare(case)
    quantity = result.paper_order.quantity
    entry = D("120.01") * (1 + D(5) / 10000)
    sale = D(114) * (1 - D(5) / 10000)
    assert quantity * (entry - sale) + D("4.90") <= D(5)
    assert quantity * entry + D("2.45") <= D(40)
    assert result.paper_order.risk_stop == D(114)


def regrant(case, *, context=None, account=None, selection=None, **grant_changes):
    old_context, old_account, old_grant, old_selection = case
    context = old_context if context is None else context
    account = old_account if account is None else account
    selection = old_selection if selection is None else selection
    grant = replace(
        old_grant,
        context_hash=context.evidence_hash,
        selection_hash=selection.evidence_hash,
        plan_hash=context.plan.evidence_hash,
        policy_hash=context.plan.policy_hash,
        source_config_hash=context.plan.source_config_hash,
        analysis_code_hash=context.plan.analysis_code_hash,
        execution_config_hash=context.execution_config_hash,
        source_report_body_sha256=context.source_report_body_sha256,
        before_account_hash=api().stock_simulation_account_hash(account),
        **grant_changes,
    )
    return context, account, grant, selection


def test_manual_approval_cannot_precede_the_executable_quote_receipt():
    case = prepared_case()
    market = replace(case[0].market[0], received_at=NOW + timedelta(seconds=2))
    context = replace(case[0], market=(market,))
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare(regrant(case, context=context), now=NOW + timedelta(seconds=3))


@pytest.mark.parametrize(
    "field", ["intent_quantity", "paper_quantity", "payload_terms", "created_at", "request_hash"]
)
def test_prepared_record_rejects_cross_binding_tampering(field):
    result = prepare()
    if field == "intent_quantity":
        changed = replace(
            result, intent=replace(result.intent, quantity=result.intent.quantity + D(1))
        )
    elif field == "paper_quantity":
        changed = replace(
            result, paper_order=result.paper_order.model_copy(update={"quantity": D(1)})
        )
    elif field == "payload_terms":
        from trading_bot.brokers.robinhood_stock_payloads import prepare_stock_order_payloads

        payloads = prepare_stock_order_payloads(
            replace(result.payloads.terms, symbol="FOREIGN"), ref_id=result.payloads.ref_id
        )
        changed = replace(result, payloads=payloads)
    elif field == "created_at":
        changed = replace(result, created_at=result.created_at + timedelta(seconds=1))
    else:
        changed = replace(result, request_hash="f" * 64)
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        _ = changed.evidence_hash


@pytest.mark.parametrize(
    "mode", [ExecutionMode.PAPER, ExecutionMode.NORMAL_LIVE, ExecutionMode.BACKTEST, "simulation"]
)
def test_only_explicit_exact_simulation_mode_is_admissible(mode):
    case = prepared_case()
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare((*case[:2], replace(case[2], mode=mode), case[3]))


@pytest.mark.parametrize(
    "field",
    [
        "plan_hash",
        "policy_hash",
        "source_config_hash",
        "analysis_code_hash",
        "execution_config_hash",
        "source_report_body_sha256",
        "before_account_hash",
        "context_hash",
        "selection_hash",
    ],
)
def test_approval_binds_every_source_execution_and_before_state_hash(field):
    case = prepared_case()
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare((*case[:2], replace(case[2], **{field: "f" * 64}), case[3]))


@pytest.mark.parametrize(
    "kind",
    ["closed", "halt", "not_tradable", "earnings", "liquidity", "sector", "future", "expired"],
)
def test_current_execution_evidence_is_not_inferred_from_research(kind):
    case = prepared_case()
    market = case[0].market[0]
    if kind == "closed":
        market = replace(market, market_clock=replace(market.market_clock, is_open=False))
    elif kind == "halt":
        market = replace(market, quote=market.quote.model_copy(update={"halted": True}))
    elif kind == "not_tradable":
        market = replace(market, instrument=replace(market.instrument, tradable=False))
    elif kind == "earnings":
        market = replace(market, earnings_source_hash=None)
    elif kind == "liquidity":
        market = replace(
            market, quote=market.quote.model_copy(update={"average_dollar_volume": None})
        )
    elif kind == "sector":
        market = replace(market, sector_source_hash=None)
    elif kind == "future":
        market = replace(
            market,
            quote=market.quote.model_copy(update={"as_of": NOW + timedelta(seconds=2)}),
            received_at=NOW + timedelta(seconds=2),
        )
    else:
        market = replace(market, expires_at=NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare(regrant(case, context=replace(case[0], market=(market,))))


def test_expiry_is_exclusive_and_retry_never_renews_quote_deadline():
    case = prepared_case()
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare(case, now=NOW + timedelta(seconds=5))


def test_changed_actual_cash_cannot_use_approved_before_state():
    case = prepared_case()
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare(case, account=case[1].model_copy(update={"cash": D(1001)}))


def test_tactical_entry_rejects_absent_stop_and_costs_alone_above_budget():
    case = prepared_case(sleeve="tactical")
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare(regrant(case, selection=replace(case[3], risk_stop=None)))
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare(
            prepared_case(sleeve="tactical", policy=HybridSettings(simulation_fee_usd=D("2.50")))
        )


def rebuild_source(context, **changes):
    context = replace(context, **changes)
    source_plan = compile_current_stock_plan(
        context.inputs,
        worker_profile_id=PROFILE,
        policy=context.policy,
        analysis_code_hash=context.plan.analysis_code_hash,
        controls=context.controls,
        allocation_context=context.allocation_context,
        issuers=context.issuers,
        held_sleeves=context.held_sleeves,
        owned_holding_contexts=context.owned_holding_contexts,
        profit_requests=context.profit_requests,
        limits=context.limits,
        reviewed_at=context.plan.portfolio_proposals.reviewed_at,
    )
    return replace(
        context,
        plan=source_plan,
        source_report_body_sha256=hashlib.sha256(
            canonical_json(current_stock_plan_document(source_plan)).encode()
        ).hexdigest(),
    )


def owned_case(kind="holding_exit", *, bid=D(120)):
    from tests.unit.runtime.test_stock_investment_holdings import owned
    from tests.unit.runtime.test_stock_portfolio_proposals import request

    base_context, _, grant, _ = prepared_case()
    first = datetime(2026, 8 if kind == "holding_exit" else 9, 25, 14, tzinfo=UTC)
    owner = owned(first=first)
    episode_id = owner.mandate.episode_id
    origin = PaperOrder(
        id="origin-buy",
        symbol="ALFA",
        side="buy",
        sleeve="tactical",
        quantity=D(10),
        filled=D(10),
        status="filled",
        episode_id=episode_id,
    )
    account = Account(
        starting_capital=D(2000),
        cash=D(1000),
        paused=False,
        high_watermark=D(2200),
        daily_reference=D(2200),
        weekly_reference=D(2200),
        lots=(
            Lot(
                id="lot-ALFA",
                symbol="ALFA",
                sleeve="tactical",
                quantity=D(10),
                basis=D(1000),
                acquired_at=first,
                episode_id=episode_id,
            ),
        ),
        episodes=(
            AllocationEpisode(
                id=episode_id,
                symbol="ALFA",
                sleeve="tactical",
                original_cash=D(1000),
                original_quantity=D(10),
            ),
        ),
        orders=(origin,),
        fills=(
            FillFact(
                id="buy-fill", order_id=origin.id, quantity=D(10), price=D(100), fee=D(0), at=first
            ),
        ),
    )
    before = api().stock_simulation_account_hash(account)
    owner = replace(owner, reconciliation_hash=before)
    ctx = allocation(
        cash="1000",
        equity=str(D(1000) + 10 * bid),
        exposures=(exposure("ALFA", sleeve="tactical", notional=str(10 * bid)),),
    )
    ctx = replace(
        ctx,
        account=replace(ctx.account, account_id="sim-fictional"),
        portfolio=replace(
            ctx.portfolio,
            account_id="sim-fictional",
            positions=(
                replace(ctx.portfolio.positions[0], account_id="sim-fictional", quantity=D(10)),
            ),
        ),
        reconciliation_hash=before,
    )
    requests = ()
    if kind == "profit_reduction":
        req = request(owner)
        req = replace(req, state=replace(req.state, source_hash=before))
        requests = (req,)
    market = replace(
        base_context.market[0],
        quote=base_context.market[0].quote.model_copy(update={"bid": bid, "ask": bid + D(".01")}),
    )
    context = rebuild_source(
        base_context,
        inputs=inputs(held=("ALFA",)),
        allocation_context=ctx,
        held_sleeves=(("ALFA", "tactical"),),
        owned_holding_contexts=(owner,),
        profit_requests=requests,
        market=(market,),
    )
    proposals = context.plan.portfolio_proposals
    source = (
        proposals.holding_reviews.reviews[0]
        if kind == "holding_exit"
        else proposals.profit_reductions[0]
    )
    selection = api().StockExecutionSelection(
        kind=kind,
        symbol="ALFA",
        sleeve="tactical",
        source_evidence_hash=source.evidence_hash,
        episode_id=episode_id,
        method=None if kind == "holding_exit" else "principal",
        order_type="market",
        limit_price=None,
        risk_stop=None,
    )
    return regrant((context, account, replace(grant, sleeve="tactical"), selection))


def test_owned_terminal_exit_maps_exact_episode_quantity_without_projected_cash():
    case = owned_case()
    before = case[1].model_dump_json()
    result = prepare(case)
    assert result.paper_order.quantity == D(10) and result.paper_order.side == "sell"
    assert result.paper_order.episode_id == case[3].episode_id
    assert result.paper_order.threshold is None
    assert result.payloads.review_arguments["quantity"] == "10"
    assert case[1].model_dump_json() == before and not result.reservations_created


def test_owned_profit_reduction_caps_to_source_and_keeps_threshold_identity():
    case = owned_case("profit_reduction")
    result = prepare(case)
    assert result.paper_order.quantity == D("1.666666")
    assert result.paper_order.threshold is not None
    assert result.intent.id == result.payloads.ref_id
    assert case[1].cash == 1000 and not case[1].settlements


def test_known_current_principal_surplus_caps_old_indicative_reduction_quantity():
    case = owned_case("profit_reduction", bid=D(110))
    result = prepare(case)
    assert result.paper_order.quantity == D(".909090")
    assert (D(10) - result.paper_order.quantity) * D(110) >= D(1000)


def test_sourced_lot_basis_cannot_be_rebound_while_actual_episode_is_unchanged():
    case = owned_case()
    owner = case[0].owned_holding_contexts[0]
    owner = replace(owner, remaining_lots=(replace(owner.remaining_lots[0], basis=D(999)),))
    context = rebuild_source(case[0], owned_holding_contexts=(owner,))
    selection = replace(
        case[3],
        source_evidence_hash=context.plan.portfolio_proposals.holding_reviews.reviews[
            0
        ].evidence_hash,
    )
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare(regrant(case, context=context, selection=selection))


def partial_case(*, foreign_fill=False, future_fill_relative_to_state=False):
    from trading_bot.hybrid.models import ExitProgress, Settlement
    from trading_bot.portfolio.stock_holding import StockRealizedPriceGain
    from trading_bot.portfolio.stock_profit_taking import StockProfitMethodProgress

    original = owned_case("profit_reduction")
    req = replace(original[0].profit_requests[0], method="partial_first")
    context = rebuild_source(original[0], profit_requests=(req,))
    reduction = context.plan.portfolio_proposals.profit_reductions[0]
    selection = replace(
        original[3], method="partial_first", source_evidence_hash=reduction.evidence_hash
    )
    first = prepare(regrant(original, context=context, selection=selection))
    threshold = first.paper_order.threshold
    assert threshold is not None
    sold_at = NOW - timedelta(minutes=1)
    sell = PaperOrder(
        id="actual-sell",
        symbol="ALFA",
        side="sell",
        sleeve="tactical",
        quantity=D(1),
        filled=D(1),
        status="filled",
        threshold=threshold,
        episode_id=selection.episode_id,
    )
    account = original[1].model_copy(
        update={
            "lots": (original[1].lots[0].model_copy(update={"quantity": D(9), "basis": D(900)}),),
            "orders": (*original[1].orders, sell),
            "fills": (
                *original[1].fills,
                FillFact(
                    id="sell-fill",
                    order_id=sell.id,
                    quantity=D(1),
                    price=D(120),
                    fee=D(0),
                    at=sold_at,
                ),
            ),
            "settlements": (
                Settlement(id="sell-fill", amount=D(120), due_at=NOW + timedelta(days=1)),
            ),
            "realized_gain": D(20),
            "tax_reserve": D(20),
            "exit_progress": (
                ExitProgress(
                    threshold=threshold,
                    symbol="ALFA",
                    sleeve="tactical",
                    target=D("2.5"),
                    filled=D(1),
                ),
            ),
        }
    )
    before = api().stock_simulation_account_hash(account)
    source_context = context.allocation_context
    source_context = replace(
        source_context,
        account=replace(source_context.account, equity=D(2080)),
        portfolio=replace(
            source_context.portfolio,
            equity=D(2080),
            gross_exposure=D(1080),
            net_exposure=D(1080),
            positions=(
                replace(source_context.portfolio.positions[0], quantity=D(9), market_value=D(1080)),
            ),
        ),
        exposures=(replace(source_context.exposures[0], remaining_notional=D(1080)),),
        reconciliation_hash=before,
        tax_reserve=D(20),
    )
    owner = context.owned_holding_contexts[0]
    owner = replace(
        owner,
        reconciliation_hash=before,
        remaining_lots=(replace(owner.remaining_lots[0], quantity=D(9), basis=D(900)),),
        realized_gains=(
            StockRealizedPriceGain(
                "sell-fill",
                owner.mandate.episode_id,
                owner.mandate.instrument_id,
                "ALFA",
                D(20),
                sold_at,
                before,
            ),
        ),
    )
    progress = StockProfitMethodProgress(
        method="partial_first",
        target_quantity=D("2.5"),
        filled_quantity=D(1),
        fill_ids=("foreign-fill" if foreign_fill else "sell-fill",),
    )
    state = replace(
        req.state,
        source_hash=before,
        information_at=NOW - timedelta(minutes=2) if future_fill_relative_to_state else NOW,
        progress=(progress,),
    )
    context = rebuild_source(
        context,
        allocation_context=source_context,
        owned_holding_contexts=(owner,),
        profit_requests=(replace(req, state=state),),
    )
    selection = replace(
        selection,
        source_evidence_hash=context.plan.portfolio_proposals.profit_reductions[0].evidence_hash,
    )
    return regrant((context, account, original[2], selection))


def test_partial_rung_uses_actual_target_fills_and_stable_episode_method_key():
    case = partial_case()
    result = prepare(case)
    assert result.paper_order.quantity == D("1.5")
    assert result.paper_order.threshold == case[1].exit_progress[0].threshold
    assert case[1].cash == 1000 and case[1].settlements[0].amount == 120


def test_claimed_profit_fill_ids_cannot_replace_actual_progress():
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare(partial_case(foreign_fill=True))


def test_profit_progress_information_cannot_precede_its_actual_fill():
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare(partial_case(future_fill_relative_to_state=True))


def test_whole_limit_uses_supplied_tick_while_fractional_market_respects_increment():
    case = prepared_case()
    market = case[0].market[0]
    market = replace(
        market, quote=market.quote.model_copy(update={"bid": D("19.99"), "ask": D(20)})
    )
    context = replace(case[0], market=(market,))
    selection = replace(case[3], order_type="limit", limit_price=D("20.01"))
    result = prepare(regrant(case, context=context, selection=selection))
    assert (
        result.paper_order.quantity == D(4)
        and result.payloads.review_arguments["limit_price"] == "20.01"
    )
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare(
            regrant(case, context=context, selection=replace(selection, limit_price=D("20.005")))
        )
    result = prepare(prepared_case(instrument_changes={"quantity_increment": D(".2")}))
    assert result.paper_order.quantity == D(".8")


@pytest.mark.parametrize(
    "changes",
    [{"minimum_notional": D(100)}, {"minimum_quantity": D(1)}, {"fractional_eligible": False}],
)
def test_small_cash_ceiling_never_invents_minimum_or_fractional_eligibility(changes):
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare(prepared_case(instrument_changes=changes))


def pending_issuer_case(status):
    context, base, grant, selection = prepared_case()
    pending = PaperOrder(
        id="pending-BETA",
        symbol="BETA",
        side="buy",
        sleeve="long_term",
        quantity=D(".75"),
        reserved_cash=D(90),
        episode_id="beta-episode",
    )
    account = base.model_copy(update={"orders": (pending,)})
    before = api().stock_simulation_account_hash(account)
    row = exposure(
        "BETA",
        origin="broker_pending",
        sleeve="long_term",
        issuer="issuer-BETA",
        notional="90",
        reference=pending.id,
    )
    source = allocation(bp="910", exposures=(row,))
    source = replace(
        source,
        account=replace(source.account, account_id="sim-fictional"),
        portfolio=replace(source.portfolio, account_id="sim-fictional"),
        reconciliation_hash=before,
    )
    market = context.market[0]
    beta = replace(
        market,
        instrument=replace(market.instrument, id="instrument-BETA", symbol="BETA"),
        quote=market.quote.model_copy(update={"symbol": "BETA"}),
    )
    identity = issuer(symbol="BETA", instrument_id="instrument-BETA", issuer_id="issuer-BETA")
    if status == "contradictory":
        identity = replace(identity, issuer_id="issuer-ALFA")
    elif status == "instrument":
        identity = replace(identity, instrument_id="instrument-FOREIGN")
    elif status == "expired":
        identity = replace(identity, expires_at=NOW + timedelta(microseconds=500000))
    identities = (issuer(),) if status == "missing" else (issuer(), identity)
    context = rebuild_source(
        context, allocation_context=source, issuers=identities, market=(market, beta)
    )
    return regrant((context, account, grant, selection))


@pytest.mark.parametrize("status", ["contradictory", "instrument", "missing", "expired"])
def test_pending_exposure_issuer_must_match_current_source_before_new_entry(status):
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare(pending_issuer_case(status))


def test_matching_pending_issuer_control_keeps_distinct_company_cash_ceiling():
    case = pending_issuer_case("matching")
    result = prepare(case)
    assert result.paper_order.symbol == "ALFA"
    assert result.paper_order.quantity == prepare().paper_order.quantity
    assert case[1].reserved_cash == 90 and case[1].cash == 1000


@pytest.mark.parametrize("issuer_status", ["missing", "expired"])
def test_unneeded_issuer_gap_does_not_suppress_quantity_known_terminal_exit(issuer_status):
    case = owned_case()
    identities = (
        ()
        if issuer_status == "missing"
        else (replace(issuer(), expires_at=NOW + timedelta(microseconds=500000)),)
    )
    context = rebuild_source(case[0], issuers=identities)
    result = prepare(regrant(case, context=context))
    assert result.paper_order.side == "sell" and result.paper_order.quantity == D(10)


def test_terminal_quantity_review_preserves_unknown_realized_gains():
    case = owned_case()
    owner = replace(case[0].owned_holding_contexts[0], realized_gains=None)
    context = rebuild_source(case[0], owned_holding_contexts=(owner,))
    review = context.plan.portfolio_proposals.holding_reviews.reviews[0]
    assert review.price_pnl.status == "unavailable" and review.action == "EXIT"
    selection = replace(case[3], source_evidence_hash=review.evidence_hash)
    result = prepare(regrant(case, context=context, selection=selection))
    assert result.paper_order.side == "sell" and result.paper_order.quantity == 10
    assert context.owned_holding_contexts[0].realized_gains is None


def test_source_instrument_maximum_quantity_limits_the_cash_ceiling_draft():
    result = prepare(prepared_case(instrument_changes={"maximum_quantity": D(".1")}))
    assert result.intent.quantity == result.paper_order.quantity == D(".1")
    assert result.payloads.review_arguments["quantity"] == "0.1"


def test_supplied_earlier_regular_session_close_fences_original_draft_and_retry():
    case = prepared_case()
    market = case[0].market[0]
    close = NOW + timedelta(seconds=3)
    market = replace(market, market_clock=replace(market.market_clock, next_close_at=close))
    context = replace(case[0], market=(market,))
    bound = regrant(case, context=context)
    first = prepare(bound)
    assert first.expires_at == first.intent.expires_at == close
    assert prepare(bound, now=NOW + timedelta(seconds=2)) == first
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare(bound, now=close)


def test_disabled_research_plan_cannot_be_promoted_by_a_manual_simulation_grant():
    case = prepared_case()
    context = rebuild_source(case[0], controls=controls(research_enabled=False))
    assert context.plan.rankings is context.plan.portfolio_proposals is None
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare((context, *case[1:]))


def test_actual_paper_quantity_does_not_replace_unknown_source_lot_ownership():
    case = owned_case()
    owner = replace(case[0].owned_holding_contexts[0], remaining_lots=None)
    context = rebuild_source(case[0], owned_holding_contexts=(owner,))
    review = context.plan.portfolio_proposals.holding_reviews.reviews[0]
    assert review.action == "REVIEW" and case[1].lots[0].quantity == 10
    selection = replace(case[3], source_evidence_hash=review.evidence_hash)
    with pytest.raises(ValueError, match="stock_simulation_intent_unavailable"):
        prepare(regrant(case, context=context, selection=selection))
