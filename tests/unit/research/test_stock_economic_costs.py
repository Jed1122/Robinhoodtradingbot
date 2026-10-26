"""Fictional explicit operating budgets; no actual financial outcomes or providers."""

import hashlib
from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, Inexact, localcontext

import pytest
from pydantic import BaseModel

from tests.unit.research import test_stock_economic_policies as policies
from tests.unit.research import test_stock_economic_replay as scripted
from trading_bot.hybrid.models import Account, PaperOrder
from trading_bot.market_data.recording import canonical_json
from trading_bot.market_data.stock_economic_evidence import StockCashDividendEvent
from trading_bot.research import stock_economic_replay as kernel
from trading_bot.research.stock_dividend_book import adopt_dividend_account
from trading_bot.research.stock_economic_policies import run_seven_family_fictional_replay
from trading_bot.research.stock_operating_costs import (
    ModeledOperatingCharge,
    ModeledOperatingCostPlan,
)

D = Decimal
ZERO = D(0)


def budget(data, amount=ZERO, *, index=200, phase="open", extra=()):
    at = data.calendar[index].opens_at if phase == "open" else data.calendar[index].closes_at
    return ModeledOperatingCostPlan(
        "fictional-explicit-budget",
        (ModeledOperatingCharge("first", at, "hosting", amount), *extra),
    )


def begin(data=None, plan=None, **protocol):
    data = scripted.fixture() if data is None else data
    return kernel.begin_stock_economic_replay(
        data,
        kernel.StockEconomicReplayProtocol(slippage_bps=D(0), fee_usd=D(0), **protocol),
        operating_cost_plan=plan,
    )


def advance(state):
    return kernel.advance_stock_economic_session(state, session_index=state.next_session)


def mark(state, phase="close"):
    return next(row for row in reversed(state.cost_marks) if row.phase == phase)


def plain(value):
    if isinstance(value, BaseModel):
        return plain(value.model_dump())
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(map(plain, value))
    return value


def test_none_mode_retains_literal_scripted_hashes_and_legacy_result_shape():
    initial = scripted.begin()
    assert (
        initial.evidence_hash == "b30f705e0f0a2cd339502261a562a4cac9273b62af06a087fc739ff85cb4d118"
    )
    assert (
        scripted.through(initial, 201).evidence_hash
        == "fea284fb626ef67e8caf05f03c48ce63ecbcc6d5984cee67c0608b5b3e5970f0"
    )
    final = scripted.through(initial, 224)
    assert final.evidence_hash == "d9aa9d437c769a8a4907f82495b7e68b275d763cb780bea8d3b3f04c6ffdade4"
    result = kernel.finish_stock_economic_replay(final)
    assert type(result) is kernel.StockEconomicReplayResult
    assert (
        hashlib.sha256(canonical_json(plain(result)).encode()).hexdigest()
        == "d265dd3c2d262825599cb39cbe4cc8a90eab4a5b71673bd99f9a0e47c8518349"
    )


def test_none_mode_retains_literal_policy_and_seven_family_hashes():
    data = policies.fixture()
    initial = policies.begin(data)
    assert (
        initial.evidence_hash == "a9d5280789dcac4fb1c62bc77187efdcfdb78e517d263bb668ef74a266279c38"
    )
    final = policies.through(initial, 206)
    assert final.evidence_hash == "4d00ddc983a6a8641b58f9598874522fa85ae6923b2f593475657243efea7036"
    result = kernel.finish_stock_economic_replay(final)
    assert (
        hashlib.sha256(canonical_json(plain(result)).encode()).hexdigest()
        == "5b14290d20e7bc58626b5c28ca5f6ce21955779a9b1387390d7f3505fac1d5e3"
    )
    short = policies.fixture(count=202)
    wrapped = run_seven_family_fictional_replay(
        short,
        tuple(policies.request(short, i) for i in range(199, 202)),
        kernel.StockEconomicReplayProtocol(),
    )
    assert (
        wrapped.evidence_hash == "6cb952e287aa35fa32158e7a1d6219b2429e049c972113961c28422a1295ddef"
    )
    assert (
        hashlib.sha256(canonical_json(plain(wrapped)).encode()).hexdigest()
        == "c91b53dd3cefdb7435cf427b1c40c6328316d20facee418eb1a4eb4f636acebf"
    )


def test_cost_binds_before_outcomes_but_never_debits_warmup():
    data = scripted.fixture()
    plan = budget(data, D(12))
    state = begin(data, plan)
    assert state.book.account.cash == 1000 and state.cost_marks == ()
    assert state.operating_cost_plan_hash == plan.evidence_hash
    assert not any(row.action == "operating_expense" for row in state.book.trace)
    assert state.snapshots[-1].session_index == 199
    assert state.evidence_hash != begin(data).evidence_hash


def test_due_cost_precedes_pending_orders_and_triggers_unchanged_daily_loss_rule():
    data = scripted.fixture()
    state = advance(begin(data, budget(data, D(12))))
    opened = mark(state, "open")
    assert opened.gross_before_payment == 1000 and opened.gross_equity == 988
    assert opened.paid_total == 12 and opened.net_equity == 988
    assert state.book.account.tactical_suspended is True
    assert not any(lot.sleeve == "tactical" for lot in state.book.account.lots)
    assert sum((lot.quantity * D(100) for lot in state.book.account.lots), D(0)) == 741
    assert state.book.account.cash == 247
    assert any(row.reason == "sticky_tactical_suspension" for row in state.records)
    assert next(
        i for i, row in enumerate(state.book.trace) if row.action == "operating_expense"
    ) < next(
        i
        for i, row in enumerate(state.book.trace)
        if row.orders_before_hash != row.orders_after_hash
    )
    assert state.book.account.high_watermark == 1000


def test_unknown_due_amount_blocks_all_buys_and_keeps_net_unavailable():
    data = scripted.fixture()
    state = advance(begin(data, budget(data, None)))
    assert state.book.account.cash == 1000 and not state.book.account.fills
    assert state.book.account.last_equity == 1000
    assert mark(state).net_equity is None and mark(state).investable_cash == 0
    assert mark(state).unpaid_unknown_ids == ("first",)
    assert not state.pending
    assert all(row.reason == "operating_cost_unknown_liability" for row in state.records)


def test_known_unpaid_liability_can_exceed_gross_without_negative_account_cash():
    data = scripted.fixture()
    state = advance(begin(data, budget(data, D(1500))))
    assert mark(state).gross_equity == 1000 and mark(state).net_equity == -500
    assert mark(state).unpaid_known == 1500 and mark(state).paid_total == 0
    assert state.book.account.cash == state.book.account.last_equity == 1000
    assert not state.book.account.fills and not state.pending


def test_full_cash_depletion_fails_explicitly_without_epsilon_or_mutating_original():
    data = scripted.fixture()
    initial = begin(data, budget(data, D(1000)))
    with pytest.raises(ValueError, match="operating_cost_gross_equity_depleted"):
        advance(initial)
    assert initial.book.account.cash == 1000 and not initial.book.account.fills


def test_unknown_future_cost_does_not_prevent_current_entries():
    data = scripted.fixture()
    state = advance(begin(data, budget(data, None, index=201)))
    assert any(lot.sleeve == "tactical" for lot in state.book.account.lots)
    assert mark(state).net_equity is not None and not mark(state).unpaid_unknown_ids


def test_close_due_charge_is_not_prepaid_at_open():
    data = scripted.fixture()
    state = advance(begin(data, budget(data, D(12), phase="close")))
    assert mark(state, "open").paid_total == 0
    assert mark(state).paid_total == 12 and mark(state).net_equity == 988
    assert mark(state).tactical_suspended is True
    assert any(lot.sleeve == "tactical" for lot in state.book.account.lots)
    assert state.book.account.tactical_suspended is True


@pytest.mark.parametrize(
    ("amount", "daily", "weekly"),
    (
        ("9.99", False, False),
        ("10", True, False),
        ("29.99", True, False),
        ("30", True, True),
        ("99.99", True, True),
        ("100", True, True),
    ),
)
def test_expense_risk_threshold_boundaries_are_never_relaxed(amount, daily, weekly):
    data = scripted.fixture()
    state = advance(begin(data, budget(data, D(amount))))
    assert mark(state, "open").gross_equity == D(1000) - D(amount)
    assert state.book.account.tactical_suspended is daily
    assert state.book.account.weekly_review_required is weekly
    assert state.book.account.high_watermark == 1000


def test_intraday_due_cost_is_processed_at_close_not_guessed_billing_time():
    data = scripted.fixture()
    plan = ModeledOperatingCostPlan(
        "fictional-intraday",
        (
            ModeledOperatingCharge(
                "intraday", data.calendar[200].opens_at + timedelta(hours=1), "model", D(12)
            ),
        ),
    )
    state = advance(begin(data, plan))
    assert mark(state, "open").paid_total == 0 and mark(state).paid_total == 12
    assert (
        next(row for row in state.book.trace if row.action == "operating_expense").at
        == data.calendar[200].closes_at
    )


def test_unrepresentable_cost_debit_cannot_be_hidden_by_session_integration():
    data = scripted.fixture()
    initial = begin(data, budget(data, D("1e-48")))
    with pytest.raises(ValueError, match="operating_expense_debit_not_exactly_representable"):
        advance(initial)
    assert initial.book.account.cash == 1000 and not initial.book.account.fills


def test_unknown_due_cost_keeps_owned_known_risk_exit_executable():
    data = scripted.fixture(stocks=1, signals={"S0": tuple(199 <= i <= 200 for i in range(225))})
    state = scripted.through(begin(data, budget(data, None, index=202)), 201)
    assert any(row.side == "sell" and row.reason == "family_signal_exit" for row in state.pending)
    state = advance(state)
    assert any(row.side == "sell" and row.outcome == "filled" for row in state.records)
    assert mark(state).net_equity is None
    assert state.book.account.settlements and state.book.account.cash >= 0


def test_due_liability_waits_for_true_settlement_and_is_never_deducted_twice():
    data = scripted.fixture(stocks=1, signals={"S0": tuple(199 <= i <= 200 for i in range(225))})
    data = replace(data, long_term_allocations=())
    state = scripted.through(begin(data, budget(data, D(980), index=202)), 202)
    assert state.book.account.cash == 960 and mark(state).unpaid_known == 980
    assert mark(state).net_equity == 20 and state.book.account.settlements[0].amount == 40
    due = state.book.account.settlements[0].due_at
    while state.inputs.calendar[state.next_session].opens_at < due:
        state = advance(state)
        assert mark(state).paid_total == 0
    state = advance(state)
    assert state.book.account.cash == 20 and not state.book.account.settlements
    assert mark(state).paid_total == 980 and mark(state).unpaid_known == 0
    assert mark(state).gross_equity == mark(state).net_equity == 20
    assert len([row for row in state.book.trace if row.action == "operating_expense"]) == 1


def test_owned_order_and_tax_reservations_cannot_fund_costs_or_reinvestment():
    data = scripted.fixture(stocks=1)
    initial = begin(data, budget(data, D(12)))
    account = Account.model_validate(
        initial.book.account.model_dump()
        | {
            "tax_reserve": D(5),
            "orders": (
                PaperOrder(
                    id="reserved",
                    symbol="S0",
                    side="buy",
                    sleeve="tactical",
                    quantity=D(1),
                    reserved_cash=D(990),
                ),
            ),
        }
    )
    initial = replace(
        initial, book=adopt_dividend_account(initial.book, account, at=initial.book.through_at)
    )
    state = advance(initial)
    assert state.book.account.cash == 1000 and state.book.account.tax_reserve == 5
    assert state.book.account.reserved_cash == 990 and mark(state).unpaid_known == 12
    assert mark(state).investable_cash == 0 and not state.book.account.fills


def test_earned_dividend_and_its_tax_reserve_do_not_become_free_expense_cash():
    data = scripted.fixture(stocks=1)
    event = StockCashDividendEvent(
        id="fixture-income",
        ticker="S0",
        cash_amount=D(1),
        currency="USD",
        ex_dividend_date=data.calendar[201].opens_at.date(),
        pay_date=data.calendar[202].opens_at.date(),
        record_date=None,
        declaration_date=data.calendar[200].opens_at.date(),
        distribution_type="recurring",
        frequency=4,
        received_at=datetime(2026, 10, 26, tzinfo=UTC),
        source_csv_sha256="a" * 64,
    )
    funding = tuple(
        kernel.DividendFundingDay(data.calendar[i].opens_at.date(), "supported", "a" * 64)
        for i in (202, 203)
    )
    data = replace(
        data, long_term_allocations=(), dividends=(event,), dividend_funding_days=funding
    )
    state = scripted.through(begin(data, budget(data, D("960.2"), index=201)), 201)
    assert state.snapshots[-1].receivable == D(".4")
    assert mark(state).unpaid_known == D("960.2")
    state = scripted.through(state, 203)
    assert state.book.account.cash == D("960.4") and state.book.account.tax_reserve == D(".4")
    assert mark(state).paid_total == 0 and mark(state).investable_cash == 0
    assert mark(state).net_equity == D("40.2")


def overnight_fixture(open_price, *, first_stock_signal=200):
    signals = {f"S{i}": tuple(i >= first_stock_signal for i in range(225)) for i in range(4)}
    data = scripted.fixture(signals=signals)
    spy = data.assets[0]
    bars = list(spy.bars)
    bars[201] = replace(bars[201], open=D(open_price))
    return replace(data, assets=(replace(spy, bars=tuple(bars)), *data.assets[1:]))


def test_all_explicit_plans_share_preopen_risk_timing_on_overnight_loss():
    data = overnight_fixture("90")
    legacy = scripted.through(begin(data), 201)
    zero = scripted.through(begin(data, budget(data)), 201)
    positive = scripted.through(begin(data, budget(data, D(".01"), index=201)), 201)
    assert any(lot.sleeve == "tactical" for lot in legacy.book.account.lots)
    assert legacy.book.account.tactical_suspended is False
    for state in (zero, positive):
        assert not any(lot.sleeve == "tactical" for lot in state.book.account.lots)
        assert state.book.account.tactical_suspended is True
        assert state.book.account.weekly_review_required is True
        assert mark(state).risk_phase == "explicit-cost-preopen-gross-risk-v1"


def test_preopen_spike_does_not_move_closed_high_watermark_or_false_suspend():
    data = overnight_fixture("140")
    state = scripted.through(begin(data, budget(data)), 201)
    assert state.book.account.high_watermark == 1000
    assert state.book.account.tactical_suspended is False


def test_new_week_open_uses_prior_close_not_old_week_baseline():
    data = scripted.fixture()
    day = next(
        i
        for i in range(201, 225)
        if data.calendar[i].opens_at.isocalendar()[:2]
        != data.calendar[i - 1].closes_at.isocalendar()[:2]
    )
    data = replace(
        data,
        long_term_allocations=(),
        assets=tuple(replace(a, signals=(False,) * 225) for a in data.assets),
    )
    state = scripted.through(begin(data, budget(data, D(31), index=day)), day - 1)
    old = state.book.account.model_copy(update={"weekly_reference": D(500)})
    state = replace(state, book=adopt_dividend_account(state.book, old, at=state.book.through_at))
    state = advance(state)
    assert mark(state, "open").weekly_reference == 1000
    assert state.book.account.weekly_review_required is True


def test_flat_zero_cost_preserves_numeric_paths_and_cutoff_carry():
    data = scripted.fixture(count=207)
    legacy = scripted.through(begin(data), 206)
    initial = begin(data, budget(data))
    cut = scripted.through(initial, 202)
    resumed = scripted.through(cut, 206)
    direct = scripted.through(initial, 206)
    assert resumed == direct
    assert resumed.snapshots == legacy.snapshots and resumed.records == legacy.records
    assert resumed.book.account == legacy.book.account
    assert len([step for step in resumed.book.trace if step.action == "operating_expense"]) == 1
    result = kernel.finish_stock_economic_replay(resumed)
    assert isinstance(result, kernel.StockCostedEconomicReplayResult)
    assert result.operating_costs.marks == resumed.cost_marks
    assert result.operating_costs.plan_hash == initial.operating_cost_plan_hash
    assert result.operating_costs.evidence_hash
    assert result.full_task5_complete is result.qualified is result.live_authorized is False


@pytest.mark.parametrize("change", ("remove", "replace", "hash", "history"))
def test_frozen_cost_configuration_or_history_cannot_be_silently_replaced(change):
    data = scripted.fixture()
    state = advance(begin(data, budget(data)))
    changes = {
        "remove": {"operating_cost_plan": None},
        "replace": {"operating_cost_plan": budget(data, D(1))},
        "hash": {"operating_cost_plan_hash": "0" * 64},
        "history": {"cost_marks": ()},
    }[change]
    with pytest.raises(ValueError, match="operating_cost"):
        advance(replace(state, **changes))


def test_warmup_charge_rejects_and_future_final_charge_is_not_incurred():
    data = scripted.fixture(count=202)
    with pytest.raises(ValueError, match="operating_cost_before_activation"):
        begin(data, budget(data, index=199))
    extra = ModeledOperatingCharge("after", data.calendar[202].opens_at, "model", None)
    state = scripted.through(begin(data, budget(data, extra=(extra,))), 201)
    assert not mark(state).unpaid_unknown_ids


def test_cost_sidecar_scope_is_immutable_and_cannot_authorize_orders():
    data = scripted.fixture()
    state = advance(begin(data, budget(data)))
    row = mark(state)
    assert (
        row.qualified
        is row.live_authorized
        is row.source_qualified
        is row.investment_eligible
        is False
    )
    assert row.strategy_qualified is row.trading_enabled is row.full_task5_complete is False
    with pytest.raises(FrozenInstanceError):
        row.net_equity = D(99999)
    with pytest.raises((ValueError, TypeError)):
        replace(row, qualified=True)


def test_context50_restores_hostile_ambient_context():
    data = scripted.fixture(count=202)
    schedule = budget(data, D(".123456789123456789"))
    original = begin(data, schedule)
    expected = advance(original)
    with localcontext() as ctx:
        ctx.prec = 5
        ctx.traps[Inexact] = True
        actual = advance(original)
        assert ctx.prec == 5 and ctx.traps[Inexact] is True
    assert actual == expected and actual.evidence_hash == expected.evidence_hash


def test_seven_independent_family_cases_expose_the_same_frozen_cost_plan():
    data = policies.fixture(count=202)
    schedule = budget(data, D(12))
    result = run_seven_family_fictional_replay(
        data,
        tuple(policies.request(data, i) for i in range(199, 202)),
        kernel.StockEconomicReplayProtocol(slippage_bps=D(0), fee_usd=D(0)),
        operating_cost_plan=schedule,
    )
    assert len(result.cases) == 7
    for case in result.cases:
        assert isinstance(case.replay, kernel.StockCostedEconomicReplayResult)
        assert case.replay.operating_costs.plan_hash == schedule.evidence_hash
        assert case.replay.operating_costs.marks[-1].paid_total == 12
        assert not any(lot.sleeve == "tactical" for lot in case.replay.book.account.lots)


@pytest.mark.parametrize("entry", ("advance", "finish", "report", "standalone_report"))
@pytest.mark.parametrize("tamper", ("unknown_hidden", "paid_total", "update_hash"))
def test_historical_summary_tampering_rejects_at_every_public_boundary(entry, tamper):
    data = scripted.fixture(count=203 if entry == "advance" else 202)
    state = scripted.through(
        begin(data, budget(data, None if tamper == "unknown_hidden" else D(12))), 201
    )
    changes = {
        "unknown_hidden": lambda row: replace(
            row,
            unpaid_unknown_ids=(),
            unpaid_known=D(0),
            net_equity=row.gross_equity,
            cost_update_hash="0" * 64,
        ),
        "paid_total": lambda row: replace(row, paid_total=D(0)),
        "update_hash": lambda row: replace(row, cost_update_hash="0" * 64),
    }[tamper]
    fake = tuple(changes(row) for row in state.cost_marks)
    with pytest.raises(ValueError, match="operating_cost"):
        if entry == "standalone_report":
            report = kernel.stock_economic_cost_report(state)
            _ = replace(report, marks=fake).evidence_hash
        else:
            state = replace(state, cost_marks=fake)
            if entry == "advance":
                advance(state)
            elif entry == "finish":
                kernel.finish_stock_economic_replay(state)
            else:
                _ = kernel.stock_economic_cost_report(state).evidence_hash


@pytest.mark.parametrize("change", ("sequence", "step_hash", "swapped"))
def test_cost_mark_anchors_must_identify_the_owned_phase(change):
    data = scripted.fixture(count=202)
    state = scripted.through(begin(data, budget(data)), 201)
    original = state.cost_marks[0]
    with pytest.raises(ValueError, match="operating_cost"):
        if change == "sequence":
            first = replace(original, ledger_sequence=0)
        elif change == "step_hash":
            first = replace(original, ledger_step_sha256="0" * 64)
        else:
            first = replace(
                original,
                ledger_sequence=state.cost_marks[1].ledger_sequence,
                ledger_step_sha256=state.cost_marks[1].ledger_step_sha256,
            )
        kernel.finish_stock_economic_replay(
            replace(state, cost_marks=(first, *state.cost_marks[1:]))
        )


@pytest.mark.parametrize("entry", ("advance", "finish"))
def test_unpaid_future_plan_cannot_disappear_after_owned_phase_proofs(entry):
    data = scripted.fixture(count=203 if entry == "advance" else 202)
    state = scripted.through(begin(data, budget(data, None, index=202)), 201)
    assert not any(row.action == "operating_expense" for row in state.book.trace)
    assert any(row.action == "operating_cost_phase" for row in state.book.trace)
    stripped = replace(
        state, operating_cost_plan=None, operating_cost_plan_hash=None, cost_marks=()
    )
    with pytest.raises(ValueError, match="operating_cost_mode_history_mismatch"):
        if entry == "advance":
            advance(stripped)
        else:
            kernel.finish_stock_economic_replay(stripped)
