"""Current research through the real fictional ledger; never a live broker test."""

import asyncio
import importlib
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.hybrid.test_journal import journal as journal
from tests.unit.portfolio.test_stock_allocation import context as allocation_context
from tests.unit.runtime.test_stock_investment_evidence import NOW, inputs
from tests.unit.runtime.test_stock_investment_plan import controls, issuer, plan
from trading_bot.brokers import FakeBroker
from trading_bot.config.hybrid import HybridSettings
from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrderId,
    CancelReceipt,
    DataHash,
    ExecutionMode,
    Fill,
    FillId,
    Instrument,
    InstrumentId,
    MarketClock,
    OrderState,
    quantize_down,
)
from trading_bot.hybrid.models import Account, Quote
from trading_bot.research.stock_investment_decisions import CurrentInvestmentPolicy
from trading_bot.runtime.stock_investment_reports import current_stock_plan_document

D = Decimal
SIMULATION_ID = "sim-task5-offline"


class Clock:
    def __init__(self):
        self.current = NOW

    def now(self):
        return self.current


def api():
    try:
        return importlib.import_module("trading_bot.execution.stock_simulation_journal")
    except ModuleNotFoundError:
        pytest.fail("current research has no durable simulation execution bridge")


def current_case(*, paper=None, source_inputs=None):
    from trading_bot.execution.stock_intents import (
        StockExecutionContext,
        StockExecutionMarketEvidence,
        StockExecutionSelection,
        StockSimulationGrant,
        stock_simulation_account_hash,
    )
    from trading_bot.market_data.recording import content_hash

    paper = Account(paused=False) if paper is None else paper
    source = inputs() if source_inputs is None else source_inputs
    source_row = next(row for row in source.scanner_rows if row.symbol == "ALFA")
    instrument_id = source_row.instrument_id
    price = D(json.loads(source_row.native_row_json)["columns"]["Last"])
    account = allocation_context()
    account = replace(
        account,
        account=replace(account.account, account_id=AccountId(SIMULATION_ID)),
        portfolio=replace(account.portfolio, account_id=AccountId(SIMULATION_ID)),
        reconciliation_hash=stock_simulation_account_hash(paper),
    )
    planning = controls()
    identity = issuer(instrument_id=instrument_id)
    result = plan(source, allocation_context=account, controls=planning, issuers=(identity,))
    document = current_stock_plan_document(result)
    # Use the actual report encoding and artifact identity, not a display hash.
    import hashlib

    body_hash = hashlib.sha256(
        json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    ).hexdigest()
    policy = HybridSettings()
    execution_hash = str(content_hash(policy.model_dump(mode="json")))
    instrument = Instrument(
        InstrumentId(instrument_id),
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
        "issuer-ALFA",
        NOW,
        DataHash("8" * 64),
    )
    quote = Quote(
        symbol="ALFA",
        bid=price,
        ask=price,
        as_of=NOW,
        tradable=True,
        fractional=True,
        regular_session=True,
        halted=False,
        average_dollar_volume=D(30000000),
        sector="technology",
        earnings_clear=True,
    )
    market = StockExecutionMarketEvidence(
        instrument=instrument,
        quote=quote,
        market_clock=MarketClock(
            AssetClass.EQUITY,
            "fictional-regular-session",
            NOW,
            True,
            False,
            False,
            False,
            None,
            NOW + timedelta(hours=1),
        ),
        currency="USD",
        received_at=NOW,
        expires_at=NOW + timedelta(seconds=5),
        source_hash="9" * 64,
        sector_source_hash="a" * 64,
        earnings_source_hash="b" * 64,
        liquidity_source_hash="c" * 64,
    )
    execution = StockExecutionContext(
        plan=result,
        inputs=source,
        policy=CurrentInvestmentPolicy(
            financial_profile="current_provider_v1",
            policy_id="current-stock-investment-provider-v1",
        ),
        controls=planning,
        allocation_context=account,
        issuers=(identity,),
        held_sleeves=(),
        owned_holding_contexts=(),
        profit_requests=(),
        limits=None,
        execution_policy=policy,
        execution_config_hash=execution_hash,
        source_report_body_sha256=body_hash,
        market=(market,),
    )
    selection = StockExecutionSelection(
        kind="entry",
        symbol="ALFA",
        sleeve="long_term",
        source_evidence_hash=result.allocation.proposals[0].decision_hash,
        episode_id=None,
        method=None,
        order_type="market",
        limit_price=None,
        risk_stop=None,
    )
    grant = StockSimulationGrant(
        approval_id="manual-fictional-task5",
        mode=ExecutionMode.SIMULATION,
        simulation_account_id=SIMULATION_ID,
        sleeve="long_term",
        approved_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
        plan_hash=result.evidence_hash,
        policy_hash=result.policy_hash,
        source_config_hash=result.source_config_hash,
        analysis_code_hash=result.analysis_code_hash,
        execution_config_hash=execution_hash,
        source_report_body_sha256=body_hash,
        context_hash=execution.evidence_hash,
        selection_hash=selection.evidence_hash,
        before_account_hash=stock_simulation_account_hash(paper),
    )
    return execution, grant, selection, paper


class QuotedFakeBroker(FakeBroker):
    """A documented fictional price replaces FakeBroker's $1 market placeholder."""

    def __init__(self, account, clock, *, price):
        super().__init__(account, clock)
        self.price = price
        self.place_calls = 0

    async def review_order(self, intent):
        result = await super().review_order(intent)
        return replace(
            result, estimated_notional=intent.quantity * self.price, estimated_fees=D(".01")
        )

    async def place_order(self, submission):
        self.place_calls += 1
        return await super().place_order(submission)


async def owner_case(journal, **changes):
    _, factory = journal
    context, grant, selection, paper = current_case(**changes)
    clock = Clock()
    owner = api().StockSimulationJournal(
        factory,
        context.execution_config_hash,
        simulation_account_id=SIMULATION_ID,
        policy=context.execution_policy,
        clock=clock,
    )
    await owner.initialize(paper, event_id="task5-fictional-genesis")
    return owner, context, grant, selection, clock, factory


async def submitted_case(journal):
    owner, context, grant, selection, clock, factory = await owner_case(journal)
    reserved = await owner.reserve(context, grant=grant, selection=selection)
    broker = QuotedFakeBroker(context.allocation_context.account, clock, price=D(120))
    review = await broker.review_order(reserved.prepared.intent)
    ticket = await owner.claim_submission(reserved.prepared.intent.id, review)
    assert ticket is not None
    response = await broker.place_order(ticket.submission)
    await owner.record_order(reserved.prepared.intent.id, response)
    return owner, context, grant, selection, clock, factory, reserved, broker, response


def simulated_fill(reserved, response, *, quantity=None, fill_id="fictional-fill-1", at=NOW):
    intent = reserved.prepared.intent
    return Fill(
        FillId(fill_id),
        response.broker_order_id,
        intent.account_id,
        intent.instrument_id,
        intent.side,
        intent.quantity if quantity is None else quantity,
        D(120),
        D(".005"),
        at,
        DataHash("d" * 64),
    )


@pytest.mark.asyncio
async def test_current_research_reaches_real_atomic_risk_and_one_simulated_handoff(journal):
    owner, context, grant, selection, clock, _ = await owner_case(journal)
    attempt = await owner.reserve(context, grant=grant, selection=selection)
    prepared = attempt.prepared
    state = await owner.read_state()
    assert state.cash == 1000 and 0 < state.reserved_cash <= 100
    assert prepared.intent.quantity == prepared.paper_order.quantity
    assert prepared.paper_order.risk_stop is None
    assert prepared.intent.id == prepared.paper_order.id == prepared.payloads.ref_id
    assert prepared.live_authorized is prepared.broker_transport_allowed is False
    broker = QuotedFakeBroker(context.allocation_context.account, clock, price=D(120))
    review = await broker.review_order(prepared.intent)
    ticket = await owner.claim_submission(prepared.intent.id, review)
    assert ticket is not None
    assert ticket.submission.execution_mode is ExecutionMode.SIMULATION
    assert ticket.submission.live_lease_id is None
    assert (await owner.read_state()).attempts[0].phase == "submitting"
    assert await owner.claim_submission(prepared.intent.id, review) is None
    result = await broker.place_order(ticket.submission)
    await owner.record_order(prepared.intent.id, result)
    assert broker.place_calls == 1
    assert (await owner.read_state()).cash == 1000  # acknowledgement is not a fill


@pytest.mark.asyncio
async def test_restart_after_reservation_cannot_issue_a_new_handoff(journal):
    owner, context, grant, selection, clock, factory = await owner_case(journal)
    attempt = await owner.reserve(context, grant=grant, selection=selection)
    restarted = api().StockSimulationJournal(
        factory,
        context.execution_config_hash,
        simulation_account_id=SIMULATION_ID,
        policy=context.execution_policy,
        clock=clock,
    )
    broker = QuotedFakeBroker(context.allocation_context.account, clock, price=D(120))
    review = await broker.review_order(attempt.prepared.intent)
    assert await restarted.claim_submission(attempt.prepared.intent.id, review) is None
    assert (await restarted.read_state()).reserved_cash > 0 and broker.place_calls == 0


@pytest.mark.asyncio
async def test_concurrent_research_replays_reserve_capital_once(journal):
    owner, context, grant, selection, clock, factory = await owner_case(journal)
    other = api().StockSimulationJournal(
        factory,
        context.execution_config_hash,
        simulation_account_id=SIMULATION_ID,
        policy=context.execution_policy,
        clock=clock,
    )
    receipts = await asyncio.gather(
        owner.reserve(context, grant=grant, selection=selection),
        other.reserve(context, grant=grant, selection=selection),
    )
    assert sum(item.created for item in receipts) == 1
    assert receipts[0].prepared == receipts[1].prepared
    state = await owner.read_state()
    assert len(state.orders) == 1 and 0 < state.reserved_cash <= 100


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ("kill", "stale_quote"))
async def test_actual_reservation_risk_gates_cannot_be_overridden_by_research(journal, cause):
    paper = Account(paused=False, kill_switch=cause == "kill")
    owner, context, grant, selection, clock, _ = await owner_case(journal, paper=paper)
    if cause == "stale_quote":
        clock.current += timedelta(seconds=6)
    with pytest.raises(ValueError):
        await owner.reserve(context, grant=grant, selection=selection)
    state = await owner.read_state()
    assert state.orders == () and state.reserved_cash == 0 and state.cash == 1000


@pytest.mark.asyncio
async def test_live_mode_cannot_be_requested_through_the_offline_policy_grant(journal):
    owner, context, grant, selection, _, _ = await owner_case(journal)
    with pytest.raises(ValueError):
        await owner.reserve(
            context, grant=replace(grant, mode=ExecutionMode.NORMAL_LIVE), selection=selection
        )
    assert (await owner.read_state()).orders == ()


@pytest.mark.asyncio
async def test_ambiguous_handoff_retains_hold_and_reconnect_does_not_resend(journal):
    owner, context, grant, selection, clock, factory = await owner_case(journal)
    reserved = await owner.reserve(context, grant=grant, selection=selection)
    broker = QuotedFakeBroker(context.allocation_context.account, clock, price=D(120))
    review = await broker.review_order(reserved.prepared.intent)
    ticket = await owner.claim_submission(reserved.prepared.intent.id, review)
    assert ticket is not None
    response = await broker.place_order(ticket.submission)
    # The fictional provider accepted; its response was lost before recording.
    await owner.record_ambiguous(reserved.prepared.intent.id, reason="transport_ambiguous")
    restarted = api().StockSimulationJournal(
        factory,
        context.execution_config_hash,
        simulation_account_id=SIMULATION_ID,
        policy=context.execution_policy,
        clock=clock,
    )
    state = await restarted.read_state()
    assert state.paused and state.reserved_cash > 0 and state.cash == 1000
    assert await restarted.claim_submission(reserved.prepared.intent.id, review) is None
    assert broker.place_calls == 1
    # Reconnect supplies the exact owned order. Acknowledgement still credits no fill.
    await restarted.record_order(reserved.prepared.intent.id, response)
    assert (await restarted.read_state()).cash == 1000


@pytest.mark.asyncio
async def test_actual_simulated_partial_fill_and_terminal_cancel_preserve_basis(journal):
    owner, _, _, _, clock, _, reserved, broker, response = await submitted_case(journal)
    part = quantize_down(reserved.prepared.intent.quantity / 2, D(".000001"))
    fill = simulated_fill(reserved, response, quantity=part)
    await owner.record_fill(reserved.prepared.intent.id, fill)
    partial = await owner.read_state()
    assert partial.cash == D(1000) - part * 120 - fill.fee
    assert sum(lot.quantity for lot in partial.lots) == part
    assert sum(lot.basis for lot in partial.lots) == part * 120 + fill.fee
    assert partial.reserved_cash > 0 and partial.realized_gain == 0
    await owner.record_fill(reserved.prepared.intent.id, fill)
    assert await owner.read_state() == partial
    ack = CancelReceipt(response.broker_order_id, True, False, clock.now(), "fake_ack_only")
    await owner.record_cancel_ack(reserved.prepared.intent.id, ack)
    assert (await owner.read_state()).reserved_cash == partial.reserved_cash
    final = replace(
        response, state=OrderState.CANCELED, filled_quantity=part, updated_at=clock.now()
    )
    await owner.confirm_terminal(reserved.prepared.intent.id, final)
    closed = await owner.read_state()
    assert closed.reserved_cash == 0 and closed.cash == partial.cash
    assert closed.lots == partial.lots and closed.realized_gain == 0
    assert broker.place_calls == 1


@pytest.mark.asyncio
async def test_rejected_order_releases_only_its_confirmed_unfilled_hold(journal):
    owner, _, _, _, clock, _, reserved, _, response = await submitted_case(journal)
    rejection = replace(response, state=OrderState.REJECTED, updated_at=clock.now())
    await owner.confirm_terminal(reserved.prepared.intent.id, rejection)
    state = await owner.read_state()
    assert state.cash == 1000 and state.reserved_cash == 0
    assert state.orders[0].status == "rejected" and state.lots == () and state.realized_gain == 0


@pytest.mark.asyncio
async def test_fill_clock_and_owned_identity_are_verified_before_accounting(journal):
    owner, _, _, _, _, _, reserved, _, response = await submitted_case(journal)
    before = await owner.read_state()
    fill = simulated_fill(reserved, response)
    invalid = (
        replace(fill, broker_order_id=BrokerOrderId("unrelated-fake-order")),
        replace(fill, occurred_at=NOW - timedelta(seconds=1)),
        replace(fill, occurred_at=NOW + timedelta(seconds=1)),
    )
    for candidate in invalid:
        with pytest.raises(ValueError):
            await owner.record_fill(reserved.prepared.intent.id, candidate)
        assert await owner.read_state() == before


@pytest.mark.asyncio
async def test_filled_order_summary_alone_never_creates_owned_lots_or_cash(journal):
    owner, _, _, _, clock, _, reserved, _, response = await submitted_case(journal)
    before = await owner.read_state()
    filled = replace(
        response,
        state=OrderState.FILLED,
        filled_quantity=reserved.prepared.intent.quantity,
        updated_at=clock.now(),
    )
    with pytest.raises(ValueError):
        await owner.confirm_terminal(reserved.prepared.intent.id, filled)
    assert await owner.read_state() == before


@pytest.mark.asyncio
async def test_owned_fill_after_original_grant_expiry_still_reconciles(journal):
    owner, _, _, _, clock, _, reserved, _, response = await submitted_case(journal)
    clock.current += timedelta(minutes=2)
    fill = simulated_fill(reserved, response, at=clock.now())
    await owner.record_fill(reserved.prepared.intent.id, fill)
    state = await owner.read_state()
    assert state.orders[0].status == "filled" and state.reserved_cash == 0
    assert sum(lot.quantity for lot in state.lots) == fill.quantity
    await owner.record_fill(reserved.prepared.intent.id, fill)
    assert await owner.read_state() == state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,quantity", (("profit_reduction", D("1.666666")), ("holding_exit", D(10)))
)
async def test_sourced_owned_exit_accounts_actual_gain_and_settles_only_when_due(
    journal, kind, quantity
):
    from tests.unit.execution.test_stock_intents import owned_case, regrant
    from trading_bot.market_data.recording import content_hash

    context, paper, grant, selection = owned_case(kind)
    policy = HybridSettings(tax_rate=D(".25"))
    context = replace(
        context,
        execution_policy=policy,
        execution_config_hash=str(content_hash(policy.model_dump(mode="json"))),
    )
    context, paper, grant, selection = regrant((context, paper, grant, selection))
    clock = Clock()
    clock.current = grant.approved_at
    owner = api().StockSimulationJournal(
        journal[1],
        context.execution_config_hash,
        simulation_account_id=grant.simulation_account_id,
        policy=policy,
        clock=clock,
    )
    await owner.initialize(paper, event_id="owned-exit-fictional-genesis")
    reservation = await owner.reserve(context, grant=grant, selection=selection)
    prepared = reservation.prepared
    assert prepared.intent.quantity == quantity and prepared.paper_order.side == "sell"
    before_fill = await owner.read_state()
    assert before_fill.cash == 1000  # proposed reductions credit no cash
    broker = QuotedFakeBroker(context.allocation_context.account, clock, price=D(120))
    ticket = await owner.claim_submission(
        prepared.intent.id, await broker.review_order(prepared.intent)
    )
    assert ticket is not None
    response = await broker.place_order(ticket.submission)
    await owner.record_order(prepared.intent.id, response)
    fill = Fill(
        FillId("fictional-owned-sale"),
        response.broker_order_id,
        prepared.intent.account_id,
        prepared.intent.instrument_id,
        prepared.intent.side,
        quantity,
        D(120),
        D(".01"),
        clock.now(),
        DataHash("e" * 64),
    )
    due = NOW + timedelta(days=1)  # explicitly supplied fictional settlement fact
    await owner.record_fill(prepared.intent.id, fill, settlement_at=due)
    sold = await owner.read_state()
    gross = quantity * 120
    basis = quantity * 100
    actual_gain = gross - fill.fee - basis
    assert sold.cash == 1000
    assert sum(item.amount for item in sold.settlements) == gross - fill.fee
    assert sold.realized_gain == actual_gain
    assert sold.tax_reserve == actual_gain * D(".25")
    assert sum(lot.quantity for lot in sold.lots) == D(10) - quantity
    assert sum(lot.basis for lot in sold.lots) == D(1000) - basis
    if kind == "profit_reduction":
        assert actual_gain == D("33.32332") and gross == D("199.999920")
    await owner.settle_due()
    assert (await owner.read_state()).cash == 1000
    clock.current = due
    await owner.settle_due()
    settled = await owner.read_state()
    assert settled.cash == D(1000) + gross - fill.fee and settled.settlements == ()
    assert settled.realized_gain == actual_gain and settled.tax_reserve == sold.tax_reserve
    await owner.settle_due()
    assert await owner.read_state() == settled


@pytest.mark.asyncio
async def test_current_marks_update_loss_references_and_never_auto_resume_tactical_entries(journal):
    from tests.unit.execution.test_stock_intents import owned_case

    context, paper, grant, selection = owned_case()
    clock = Clock()
    clock.current = grant.approved_at
    owner = api().StockSimulationJournal(
        journal[1],
        context.execution_config_hash,
        simulation_account_id=grant.simulation_account_id,
        policy=context.execution_policy,
        clock=clock,
    )
    await owner.initialize(paper, event_id="loss-reference-fictional-genesis")
    original_lots = paper.lots
    await owner.mark_market((context.market[0].quote,))
    first = await owner.read_state()
    assert first.last_equity == 2200 and first.high_watermark == 2200
    assert first.valuation_at == clock.now() and first.lots == original_lots
    await owner.mark_market((context.market[0].quote,))
    assert await owner.read_state() == first
    # Valuation changes the approved before-state; an old grant cannot spend it.
    with pytest.raises(ValueError):
        await owner.reserve(context, grant=grant, selection=selection)
    clock.current += timedelta(days=1)
    up = context.market[0].quote.model_copy(
        update={"bid": D(132), "ask": D("132.01"), "as_of": clock.now()}
    )
    await owner.mark_market((up,))
    high = await owner.read_state()
    assert high.high_watermark == 2320 and high.daily_reference == 2200
    clock.current += timedelta(seconds=1)
    down = up.model_copy(update={"bid": D(80), "ask": D("80.01"), "as_of": clock.now()})
    await owner.mark_market((down,))
    low = await owner.read_state()
    assert low.last_equity == 1800 and low.tactical_suspended and low.weekly_review_required
    assert low.realized_gain == 0 and low.tax_reserve == 0 and low.lots == original_lots
    clock.current += timedelta(seconds=1)
    await owner.mark_market((up.model_copy(update={"as_of": clock.now()}),))
    assert (await owner.read_state()).tactical_suspended
