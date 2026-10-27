"""Once-only durable simulation ownership with explicitly fictional outcome facts."""

import asyncio
import importlib
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from tests.integration.execution.test_current_stock_simulation import (
    SIMULATION_ID,
    Clock,
    QuotedFakeBroker,
    current_case,
)
from tests.unit.hybrid.test_journal import journal as journal
from trading_bot.config.hybrid import HybridSettings
from trading_bot.domain import (
    AccountId,
    CancelReceipt,
    DataHash,
    ExecutionMode,
    Fill,
    FillId,
    OrderState,
)
from trading_bot.hybrid.models import Account, Lot
from trading_bot.persistence.hybrid_journal import HybridJournal

D = Decimal


def api():
    try:
        return importlib.import_module("trading_bot.execution.stock_simulation_journal")
    except ModuleNotFoundError:
        pytest.fail("durable current-stock simulation owner missing")


@pytest.fixture
async def case(journal, monkeypatch):
    _, factory = journal
    context, grant, selection, paper = current_case()
    module = api()
    calls = []

    real_prepare = module.prepare_stock_execution

    def prepare(context, *, account, simulation_account_id, grant, selection, now):
        assert type(account) is Account
        calls.append(account)
        return real_prepare(
            context,
            account=account,
            simulation_account_id=simulation_account_id,
            grant=grant,
            selection=selection,
            now=now,
        )

    monkeypatch.setattr(module, "prepare_stock_execution", prepare)
    clock = Clock()
    owner = module.StockSimulationJournal(
        factory,
        context.execution_config_hash,
        simulation_account_id=SIMULATION_ID,
        policy=context.execution_policy,
        clock=clock,
    )
    await owner.initialize(paper, event_id="fictional-owner-genesis")
    broker = QuotedFakeBroker(context.allocation_context.account, clock, price=D(120))
    return owner, context, grant, selection, clock, factory, broker, calls


async def reserved(case):
    owner, context, grant, selection, *_ = case
    result = await owner.reserve(context, grant=grant, selection=selection)
    return result


async def submitted(case):
    result = await reserved(case)
    owner, _, _, _, _, _, broker, _ = case
    review = await broker.review_order(result.prepared.intent)
    ticket = await owner.claim_submission(result.prepared.intent.id, review)
    assert ticket is not None
    order = await broker.place_order(ticket.submission)
    await owner.record_order(result.prepared.intent.id, order)
    return result, ticket, order


def fill(result, order, clock, *, identity="owned-fill", quantity=".2", at=None):
    return Fill(
        FillId(identity),
        order.broker_order_id,
        result.prepared.intent.account_id,
        result.prepared.intent.instrument_id,
        result.prepared.intent.side,
        D(quantity),
        D(120),
        D(".01"),
        clock.now() if at is None else at,
        DataHash("f" * 64),
    )


async def test_required_simulation_state_cannot_be_read_as_legacy_account(case):
    owner, context, _, _, _, factory, _, _ = case
    state = await owner.read_state()
    assert state.simulation_account_id == SIMULATION_ID
    assert state.attempts == ()
    assert state.live_authorized is state.broker_transport_allowed is False
    with pytest.raises(ValueError):
        await HybridJournal(factory, context.execution_config_hash).read()


async def test_reserve_is_atomic_exact_base_and_duplicate_does_not_prepare_again(case):
    owner, context, grant, selection, _, _, _, calls = case
    first = await reserved(case)
    second = await owner.reserve(context, grant=grant, selection=selection)
    assert first.created and not second.created
    assert first.prepared == second.prepared and len(calls) == 1
    state = await owner.read_state()
    assert 0 < state.reserved_cash <= 100 and state.cash == 1000
    assert len(state.attempts) == len(state.orders) == 1
    assert state.attempts[0].phase == "reserved"


async def test_two_concurrent_matching_reservations_have_one_committed_owner(case):
    owner, context, grant, selection, _, _, _, calls = case
    results = await asyncio.gather(
        owner.reserve(context, grant=grant, selection=selection),
        owner.reserve(context, grant=grant, selection=selection),
    )
    assert sorted(x.created for x in results) == [False, True] and len(calls) == 1
    assert len((await owner.read_state()).orders) == 1


async def test_stale_before_state_cannot_be_rebound_under_another_grant(case):
    owner, context, grant, selection, *_ = case
    await reserved(case)
    before = (await owner.read_state()).model_dump_json()
    with pytest.raises(ValueError):
        await owner.reserve(
            context, grant=replace(grant, approval_id="another-manual-grant"), selection=selection
        )
    assert (await owner.read_state()).model_dump_json() == before


async def test_claim_is_durable_before_return_and_only_once(case):
    owner, *_ = case
    result, ticket, _ = await submitted(case)
    assert ticket.submission.execution_mode is ExecutionMode.SIMULATION
    assert ticket.submission.fencing_token == 0 and ticket.submission.live_lease_id is None
    assert (await owner.read_state()).attempts[0].phase == "submitted"
    assert await owner.claim_submission(result.prepared.intent.id, ticket.submission.review) is None


async def test_restart_after_reserved_or_submitting_never_returns_handoff(case):
    owner, context, _, _, clock, factory, broker, _ = case
    result = await reserved(case)
    restarted = api().StockSimulationJournal(
        factory,
        context.execution_config_hash,
        simulation_account_id=SIMULATION_ID,
        policy=context.execution_policy,
        clock=clock,
    )
    review = await broker.review_order(result.prepared.intent)
    assert await restarted.claim_submission(result.prepared.intent.id, review) is None
    ticket = await owner.claim_submission(result.prepared.intent.id, review)
    assert ticket is not None
    final = api().StockSimulationJournal(
        factory,
        context.execution_config_hash,
        simulation_account_id=SIMULATION_ID,
        policy=context.execution_policy,
        clock=clock,
    )
    assert await final.claim_submission(result.prepared.intent.id, review) is None
    assert (await final.read_state()).attempts[0].phase == "submitting"


async def test_wrong_review_or_expired_claim_never_hands_out_transport(case):
    owner, _, _, _, clock, _, broker, _ = case
    result = await reserved(case)
    review = await broker.review_order(result.prepared.intent)
    clock.current = result.prepared.expires_at
    with pytest.raises(ValueError):
        await owner.claim_submission(result.prepared.intent.id, review)
    assert (await owner.read_state()).reserved_cash > 0 and broker.place_calls == 0


async def test_exact_zero_fill_rejection_is_distinct_and_releases_only_the_hold(case):
    owner, _, _, _, _, _, broker, _ = case
    result = await reserved(case)
    ticket = await owner.claim_submission(
        result.prepared.intent.id, await broker.review_order(result.prepared.intent)
    )
    order = await broker.place_order(ticket.submission)
    await owner.record_order(result.prepared.intent.id, replace(order, state=OrderState.REJECTED))
    state = await owner.read_state()
    assert state.orders[0].status == "rejected" and state.reserved_cash == 0
    assert state.cash == 1000 and state.fills == () and state.realized_gain == 0
    assert state.attempts[0].phase == "terminal"


async def test_ambiguous_keeps_funds_and_requires_explicit_resolution(case):
    owner, _, _, _, _, _, broker, _ = case
    result = await reserved(case)
    ticket = await owner.claim_submission(
        result.prepared.intent.id, await broker.review_order(result.prepared.intent)
    )
    assert ticket is not None
    before = (await owner.read_state()).reserved_cash
    await owner.record_ambiguous(result.prepared.intent.id)
    state = await owner.read_state()
    assert state.attempts[0].phase == "ambiguous" and state.reserved_cash == before
    assert state.paused and state.cash == 1000 and state.fills == ()


async def test_foreign_response_cannot_clear_reservation_or_bind_broker_identity(case):
    owner, _, _, _, _, _, broker, _ = case
    result = await reserved(case)
    ticket = await owner.claim_submission(
        result.prepared.intent.id, await broker.review_order(result.prepared.intent)
    )
    response = await broker.place_order(ticket.submission)
    with pytest.raises(ValueError):
        await owner.record_order(
            result.prepared.intent.id, replace(response, account_id=AccountId("sim-foreign"))
        )
    state = await owner.read_state()
    assert state.reserved_cash > 0 and state.cash == 1000


async def test_partial_fill_changes_only_actual_quantity_and_survives_restart(case):
    owner, context, _, _, clock, factory, _, _ = case
    result, _, order = await submitted(case)
    fact = fill(result, order, clock)
    await owner.record_fill(result.prepared.intent.id, fact)
    state = await owner.read_state()
    assert state.orders[0].filled == D(".2") and state.lots[0].quantity == D(".2")
    assert state.lots[0].basis == D("24.01") and state.cash == D("975.99")
    assert state.reserved_cash > 0 and state.attempts[0].phase == "partial"
    duplicate = await owner.record_fill(result.prepared.intent.id, fact)
    assert duplicate.phase == "partial" and (await owner.read_state()) == state
    restarted = api().StockSimulationJournal(
        factory,
        context.execution_config_hash,
        simulation_account_id=SIMULATION_ID,
        policy=context.execution_policy,
        clock=clock,
    )
    assert await restarted.read_state() == state
    with pytest.raises(ValueError):
        await restarted.record_fill(result.prepared.intent.id, replace(fact, fee=D(".02")))


async def test_late_owned_fill_outlives_grant_without_renewing_authority(case):
    owner, _, grant, _, clock, *_ = case
    result, _, order = await submitted(case)
    clock.current = grant.expires_at + timedelta(hours=1)
    await owner.record_fill(result.prepared.intent.id, fill(result, order, clock))
    state = await owner.read_state()
    assert state.orders[0].filled == D(".2") and state.cash == D("975.99")
    assert state.attempts[0].grant.expires_at == grant.expires_at


@pytest.mark.parametrize(
    "kind", ("unknown_broker", "foreign_broker", "backdated", "future", "overfill")
)
async def test_fill_identity_and_clock_gaps_do_not_change_financial_state(case, kind):
    owner, _, _, _, clock, _, broker, _ = case
    if kind == "unknown_broker":
        result = await reserved(case)
        ticket = await owner.claim_submission(
            result.prepared.intent.id, await broker.review_order(result.prepared.intent)
        )
        order = await broker.place_order(ticket.submission)
    else:
        result, ticket, order = await submitted(case)
    fact = fill(result, order, clock)
    if kind == "foreign_broker":
        fact = replace(fact, broker_order_id=type(order.broker_order_id)("unrelated"))
    elif kind == "backdated":
        fact = replace(fact, occurred_at=ticket.attempted_at - timedelta(microseconds=1))
    elif kind == "future":
        fact = replace(fact, occurred_at=clock.now() + timedelta(microseconds=1))
    else:
        fact = replace(fact, quantity=D(1))
    before = (await owner.read_state()).model_dump_json()
    with pytest.raises(ValueError):
        await owner.record_fill(result.prepared.intent.id, fact)
    assert (await owner.read_state()).model_dump_json() == before


async def test_cancel_ack_never_releases_until_confirmed_terminal_after_actual_fills(case):
    owner, _, _, _, clock, _, broker, _ = case
    result, _, order = await submitted(case)
    await owner.record_fill(result.prepared.intent.id, fill(result, order, clock))
    before = (await owner.read_state()).reserved_cash
    receipt = await broker.cancel_known_order(order.account_id, order.broker_order_id)
    await owner.record_cancel_ack(result.prepared.intent.id, receipt)
    state = await owner.read_state()
    assert state.reserved_cash == before and state.attempts[0].phase == "cancel_pending"
    terminal = replace(order, state=OrderState.CANCELED, filled_quantity=D(".2"))
    await owner.confirm_terminal(result.prepared.intent.id, terminal)
    state = await owner.read_state()
    assert state.reserved_cash == 0 and state.cash == D("975.99")
    assert state.orders[0].filled == D(".2") and state.lots[0].quantity == D(".2")


async def test_terminal_cannot_infer_missing_fills_or_reject_actual_partial_execution(case):
    owner, _, _, _, clock, *_ = case
    result, _, order = await submitted(case)
    await owner.record_fill(result.prepared.intent.id, fill(result, order, clock))
    before = (await owner.read_state()).model_dump_json()
    for bad in (
        replace(order, state=OrderState.CANCELED, filled_quantity=D(".3")),
        replace(order, state=OrderState.REJECTED, filled_quantity=D(".2")),
    ):
        with pytest.raises(ValueError):
            await owner.confirm_terminal(result.prepared.intent.id, bad)
    assert (await owner.read_state()).model_dump_json() == before


async def test_completed_prepared_and_review_bindings_survive_typed_json_roundtrip(case):
    owner, *_ = case
    result, ticket, _ = await submitted(case)
    state = await owner.read_state()
    attempt = state.attempts[0]
    assert attempt.prepared == result.prepared and attempt.submission == ticket.submission
    assert attempt.prepared.payloads.place_arguments["ref_id"] == result.prepared.intent.id
    restored = api().StockSimulationAccount.model_validate_json(state.model_dump_json())
    assert restored == state


async def test_fill_after_cancel_ack_preserves_the_pending_cancel_intent(case):
    owner, _, _, _, clock, _, broker, _ = case
    result, _, order = await submitted(case)
    receipt = await broker.cancel_known_order(order.account_id, order.broker_order_id)
    await owner.record_cancel_ack(result.prepared.intent.id, receipt)
    await owner.record_fill(result.prepared.intent.id, fill(result, order, clock))
    state = await owner.read_state()
    assert state.attempts[0].phase == "cancel_pending"
    assert state.reserved_cash > 0 and state.orders[0].filled == D(".2")


async def test_reported_partial_quantity_does_not_resolve_until_actual_fill_facts_arrive(case):
    owner, _, _, _, clock, _, broker, _ = case
    result = await reserved(case)
    ticket = await owner.claim_submission(
        result.prepared.intent.id, await broker.review_order(result.prepared.intent)
    )
    order = await broker.place_order(ticket.submission)
    partial = replace(order, state=OrderState.PARTIALLY_FILLED, filled_quantity=D(".3"))
    await owner.record_order(result.prepared.intent.id, partial)
    assert (await owner.read_state()).attempts[0].phase == "ambiguous"
    await owner.record_fill(result.prepared.intent.id, fill(result, order, clock))
    state = await owner.read_state()
    assert state.orders[0].filled == D(".2") and state.attempts[0].phase == "ambiguous"
    await owner.record_fill(
        result.prepared.intent.id,
        replace(fill(result, order, clock, identity="second", quantity=".1"), fee=D(0)),
    )
    state = await owner.read_state()
    assert state.orders[0].filled == D(".3") and state.attempts[0].phase == "partial"
    assert state.paused  # Resolving source facts never silently unpauses the account.


@pytest.mark.parametrize("kind", ("scope", "payload_hash", "authority"))
async def test_persisted_flat_prepared_codec_rejects_ignored_or_rebound_fields(case, kind):
    import json

    owner, *_ = case
    await reserved(case)
    raw = json.loads((await owner.read_state()).model_dump_json())
    p = raw["attempts"][0]["prepared"]
    if kind == "scope":
        p["mode"] = "normal_live"
    elif kind == "payload_hash":
        p["payloads"]["terms_hash"] = "0" * 64
    else:
        p["broker_transport_allowed"] = True
    with pytest.raises(ValueError):
        api().StockSimulationAccount.model_validate_json(json.dumps(raw))


async def test_claim_rechecks_kill_switch_after_reservation_before_any_ticket(case):
    owner, _, _, _, _, _, broker, _ = case
    result = await reserved(case)
    await owner.change(
        "manual-kill",
        "control",
        {"kill": True},
        lambda a: a.model_copy(update={"kill_switch": True}),
    )
    review = await broker.review_order(result.prepared.intent)
    with pytest.raises(ValueError):
        await owner.claim_submission(result.prepared.intent.id, review)
    assert (await owner.read_state()).reserved_cash > 0 and broker.place_calls == 0


async def test_claim_rejects_a_market_review_notional_unbound_from_supplied_quote(case):
    owner, _, _, _, _, _, broker, _ = case
    result = await reserved(case)
    review = await broker.review_order(result.prepared.intent)
    with pytest.raises(ValueError):
        await owner.claim_submission(
            result.prepared.intent.id, replace(review, estimated_notional=D(1))
        )
    assert (await owner.read_state()).reserved_cash > 0 and broker.place_calls == 0


async def test_simulation_root_authority_flags_do_not_normalize_numeric_zero(case):
    import json

    owner, *_ = case
    raw = json.loads((await owner.read_state()).model_dump_json())
    raw["broker_transport_allowed"] = 0
    with pytest.raises(ValueError):
        api().StockSimulationAccount.model_validate_json(json.dumps(raw))


async def test_settle_due_credits_only_retained_due_proceeds_once_without_changing_metadata(
    journal,
):
    from tests.unit.execution.test_stock_intents import owned_case

    _, factory = journal
    context, paper, grant, selection = owned_case()
    clock = Clock()
    clock.current = grant.approved_at
    owner = api().StockSimulationJournal(
        factory,
        context.execution_config_hash,
        simulation_account_id=grant.simulation_account_id,
        policy=context.execution_policy,
        clock=clock,
    )
    await owner.initialize(paper, event_id="owned-fictional-genesis")
    result = await owner.reserve(context, grant=grant, selection=selection)
    broker = QuotedFakeBroker(context.allocation_context.account, clock, price=D(120))
    ticket = await owner.claim_submission(
        result.prepared.intent.id, await broker.review_order(result.prepared.intent)
    )
    order = await broker.place_order(ticket.submission)
    await owner.record_order(result.prepared.intent.id, order)
    due = clock.now() + timedelta(days=1)
    fact = fill(result, order, clock, quantity=str(result.prepared.intent.quantity))
    await owner.record_fill(result.prepared.intent.id, fact, settlement_at=due)
    before = await owner.read_state()
    assert before.cash == paper.cash and len(before.settlements) == 1
    proceeds = before.settlements[0].amount
    metadata = before.attempts
    clock.current = due - timedelta(microseconds=1)
    unchanged = await owner.settle_due()
    assert unchanged.cash == before.cash and unchanged.settlements == before.settlements
    clock.current = due
    settled = await owner.settle_due()
    assert settled.cash == before.cash + proceeds and settled.settlements == ()
    assert settled.attempts == metadata and settled.tax_reserve == before.tax_reserve
    assert await owner.settle_due() == settled
    restarted = api().StockSimulationJournal(
        factory,
        context.execution_config_hash,
        simulation_account_id=grant.simulation_account_id,
        policy=context.execution_policy,
        clock=clock,
    )
    assert await restarted.read_state() == settled
    assert await restarted.settle_due() == settled


@pytest.mark.parametrize("prior", ("reported", "actual"))
@pytest.mark.parametrize("terminal", (False, True))
async def test_reported_cumulative_fill_cannot_regress_or_release_an_unreconciled_hold(
    case, prior, terminal
):
    owner, _, _, _, clock, *_ = case
    result, _, order = await submitted(case)
    if prior == "reported":
        await owner.record_order(
            result.prepared.intent.id,
            replace(order, state=OrderState.PARTIALLY_FILLED, filled_quantity=D(".2")),
        )
    else:
        await owner.record_fill(result.prepared.intent.id, fill(result, order, clock))
    before = await owner.read_state()
    clock.current += timedelta(seconds=1)
    response = replace(
        order,
        state=OrderState.CANCELED if terminal else OrderState.SUBMITTED,
        updated_at=clock.now(),
    )
    with pytest.raises(ValueError):
        await owner.record_order(result.prepared.intent.id, response)
    with pytest.raises(ValueError):
        await owner.confirm_terminal(
            result.prepared.intent.id, replace(response, state=OrderState.CANCELED)
        )
    assert await owner.read_state() == before
    assert before.reserved_cash > 0


def test_simulation_namespace_hash_owns_decimal_rendering_context(journal):
    _, factory = journal
    policy = HybridSettings(simulation_fee_usd=D("1e-8"))
    hashes = []
    for capitals, precision in ((0, 2), (1, 50)):
        with localcontext() as arithmetic:
            arithmetic.capitals, arithmetic.prec = capitals, precision
            owner = api().StockSimulationJournal(
                factory,
                "b" * 64,
                simulation_account_id=SIMULATION_ID,
                policy=policy,
                clock=Clock(),
            )
            hashes.append(owner.config_hash)
    assert hashes[0] == hashes[1]


async def test_simulation_policy_and_state_codec_survive_cross_context_restart(journal):
    _, factory = journal
    policy = HybridSettings(simulation_fee_usd=D("1e-8"))
    owner = api().StockSimulationJournal(
        factory, "b" * 64, simulation_account_id=SIMULATION_ID, policy=policy, clock=Clock()
    )
    with localcontext() as arithmetic:
        arithmetic.capitals, arithmetic.prec = 0, 2
        state = await owner.initialize(Account(cash=D("1000.00000001")), event_id="codec-genesis")
        raw = state.model_dump_json()
    with localcontext() as arithmetic:
        arithmetic.capitals, arithmetic.prec = 1, 50
        restored = await owner.read_state()
        assert restored == state and restored.model_dump_json() == raw
        restarted = api().StockSimulationJournal(
            factory,
            "b" * 64,
            simulation_account_id=SIMULATION_ID,
            policy=policy,
            clock=Clock(),
        )
        assert await restarted.read_state() == restored
        assert api().StockSimulationAccount.model_validate_json(raw) == restored


@pytest.fixture
async def mark_case(journal):
    from tests.unit.execution.test_stock_intents import owned_case

    _, factory = journal
    context, paper, grant, _ = owned_case()
    clock = Clock()
    clock.current = grant.approved_at
    owner = api().StockSimulationJournal(
        factory,
        context.execution_config_hash,
        simulation_account_id=grant.simulation_account_id,
        policy=context.execution_policy,
        clock=clock,
    )
    await owner.initialize(paper, event_id="mark-genesis")
    return owner, context.market[0].quote, clock, factory, context, grant


async def test_market_mark_tracks_drawdown_references_and_replays_without_unpausing(mark_case):
    owner, quote, clock, factory, context, grant = mark_case
    quote = quote.model_copy(update={"bid": D(130), "ask": D("130.01")})
    before = await owner.read_state()
    first = await owner.mark_market((quote,))
    assert first.last_equity == first.high_watermark == D(2300)
    assert first.daily_reference == first.weekly_reference == D(2000)
    assert first.valuation_at == clock.now() and first.attempts == before.attempts
    assert await owner.mark_market((quote,)) == first
    clock.current += timedelta(seconds=1)
    fallen = quote.model_copy(update={"bid": D(90), "ask": D("90.01"), "as_of": clock.now()})
    second = await owner.mark_market((fallen,))
    assert second.last_equity == D(1900) and second.high_watermark == D(2300)
    assert second.tactical_suspended and second.weekly_review_required
    clock.current += timedelta(days=1)
    recovered = quote.model_copy(update={"as_of": clock.now()})
    third = await owner.mark_market((recovered,))
    assert third.daily_reference == D(1900) and third.tactical_suspended
    restarted = api().StockSimulationJournal(
        factory,
        context.execution_config_hash,
        simulation_account_id=grant.simulation_account_id,
        policy=context.execution_policy,
        clock=clock,
    )
    assert await restarted.mark_market((recovered,)) == third


@pytest.mark.parametrize("kind", ("missing", "duplicate", "future", "stale", "crossed", "conflict"))
async def test_market_mark_rejects_incomplete_or_invalid_observations_without_mutation(
    mark_case, kind
):
    owner, quote, clock, *_ = mark_case
    if kind == "conflict":
        await owner.mark_market((quote,))
        quotes = (quote.model_copy(update={"bid": D(119)}),)
    elif kind == "missing":
        quotes = ()
    elif kind == "duplicate":
        quotes = (quote, quote)
    elif kind == "future":
        quotes = (quote.model_copy(update={"as_of": clock.now() + timedelta(microseconds=1)}),)
    elif kind == "stale":
        quotes = (
            quote.model_copy(update={"as_of": clock.now() - timedelta(seconds=5, microseconds=1)}),
        )
    else:
        quotes = (quote.model_copy(update={"bid": D(121)}),)
    before = await owner.read_state()
    with pytest.raises(ValueError):
        await owner.mark_market(quotes)
    assert await owner.read_state() == before


@pytest.mark.parametrize("suspended", (False, True))
async def test_claim_rechecks_tactical_buy_suspension_before_handoff(journal, suspended):
    from tests.unit.execution.test_stock_intents import prepared_case

    _, factory = journal
    context, paper, grant, selection = prepared_case(sleeve="tactical")
    clock = Clock()
    clock.current = grant.approved_at
    owner = api().StockSimulationJournal(
        factory,
        context.execution_config_hash,
        simulation_account_id=grant.simulation_account_id,
        policy=context.execution_policy,
        clock=clock,
    )
    await owner.initialize(paper, event_id="tactical-claim-genesis")
    result = await owner.reserve(context, grant=grant, selection=selection)
    if suspended:
        await owner.change(
            "tactical-suspend",
            "control",
            {"suspended": True},
            lambda state: state.model_copy(update={"tactical_suspended": True}),
        )
    broker = QuotedFakeBroker(context.allocation_context.account, clock, price=D("120.01"))
    review = await broker.review_order(result.prepared.intent)
    if suspended:
        with pytest.raises(ValueError):
            await owner.claim_submission(result.prepared.intent.id, review)
        state = await owner.read_state()
        assert state.reserved_cash > 0 and state.attempts[0].phase == "reserved"
        assert broker.place_calls == 0
    else:
        assert await owner.claim_submission(result.prepared.intent.id, review) is not None


@pytest.mark.parametrize("kind", ("mark", "control", "exposure", "metadata"))
async def test_claim_requires_reserved_base_snapshot_but_allows_metadata_only_changes(case, kind):
    owner, context, _, _, clock, _, broker, _ = case
    result = await reserved(case)
    if kind == "mark":
        await owner.mark_market((context.market[0].quote,))
    elif kind == "control":
        await owner.change(
            "base-control",
            "control",
            {"suspended": True},
            lambda state: state.model_copy(update={"tactical_suspended": True}),
        )
    elif kind == "exposure":
        lot = Lot(
            id="new-owned-exposure",
            symbol="BETA",
            sleeve="long_term",
            quantity=D(1),
            basis=D(100),
            acquired_at=clock.now(),
            episode_id="other-owned-episode",
        )
        await owner.change(
            "base-exposure",
            "control",
            {"exposure": "BETA"},
            lambda state: state.model_copy(update={"lots": (lot,)}),
        )
    else:
        clock.current += timedelta(seconds=1)
        await owner.change(
            "metadata-clock",
            "control",
            {"observed_at": clock.now().isoformat()},
            lambda state: state.model_copy(
                update={
                    "attempts": tuple(
                        attempt.model_copy(update={"last_observed_at": clock.now()})
                        for attempt in state.attempts
                    ),
                }
            ),
        )
    review = await broker.review_order(result.prepared.intent)
    before = await owner.read_state()
    if kind == "metadata":
        assert await owner.claim_submission(result.prepared.intent.id, review) is not None
    else:
        with pytest.raises(ValueError):
            await owner.claim_submission(result.prepared.intent.id, review)
        assert await owner.read_state() == before and before.reserved_cash > 0
        assert broker.place_calls == 0


@pytest.mark.parametrize("terminal", (OrderState.CANCELED, OrderState.EXPIRED, OrderState.FILLED))
async def test_native_terminal_observation_releases_only_after_exact_actual_fill_facts(
    case, terminal
):
    owner, _, _, _, clock, *_ = case
    result, _, order = await submitted(case)
    quantity = result.prepared.intent.quantity if terminal is OrderState.FILLED else D(".2")
    await owner.record_fill(
        result.prepared.intent.id, fill(result, order, clock, quantity=str(quantity))
    )
    before = await owner.read_state()
    clock.current += timedelta(seconds=1)
    observed = replace(order, state=terminal, filled_quantity=quantity, updated_at=clock.now())
    await owner.record_order(result.prepared.intent.id, observed)
    after = await owner.read_state()
    assert after.reserved_cash == 0 and after.orders[0].filled == quantity
    assert after.cash == before.cash and after.fills == before.fills and after.lots == before.lots
    assert after.attempts[0].phase == "terminal"
    assert after.attempts[0].terminal_state is terminal
    assert await owner.record_order(result.prepared.intent.id, observed) == after.attempts[0]


async def test_native_filled_summary_keeps_hold_until_exact_fill_facts_arrive(case):
    owner, _, _, _, clock, *_ = case
    result, _, order = await submitted(case)
    before = await owner.read_state()
    summary = replace(
        order, state=OrderState.FILLED, filled_quantity=result.prepared.intent.quantity
    )
    await owner.record_order(result.prepared.intent.id, summary)
    unresolved = await owner.read_state()
    assert unresolved.cash == before.cash and unresolved.fills == unresolved.lots == ()
    assert unresolved.reserved_cash == before.reserved_cash and unresolved.paused
    assert unresolved.attempts[0].phase == "ambiguous"
    await owner.record_fill(
        result.prepared.intent.id,
        fill(result, order, clock, quantity=str(result.prepared.intent.quantity)),
    )
    after = await owner.read_state()
    assert after.reserved_cash == 0 and after.orders[0].filled == result.prepared.intent.quantity
    assert len(after.fills) == len(after.lots) == 1 and after.paused


@pytest.mark.parametrize("ambiguous", (False, True))
async def test_unaccepted_cancel_receipt_retains_hold_and_later_partial_fill_diagnostic(
    case, ambiguous
):
    owner, _, _, _, clock, *_ = case
    result, _, order = await submitted(case)
    before = await owner.read_state()
    receipt = CancelReceipt(
        order.broker_order_id, False, ambiguous, clock.now(), "fictional-cancel"
    )
    await owner.record_cancel_ack(result.prepared.intent.id, receipt)
    observed = await owner.read_state()
    assert observed.reserved_cash == before.reserved_cash and observed.cash == before.cash
    assert observed.attempts[0].phase == ("ambiguous" if ambiguous else "submitted")
    assert observed.paused is ambiguous
    await owner.record_fill(result.prepared.intent.id, fill(result, order, clock))
    after = await owner.read_state()
    assert after.orders[0].filled == D(".2") and after.reserved_cash > 0
    assert after.attempts[0].phase == ("ambiguous" if ambiguous else "partial")
    assert after.attempts[0].diagnostic == ("cancel_ambiguous" if ambiguous else "none")
