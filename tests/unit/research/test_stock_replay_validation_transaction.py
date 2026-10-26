"""Fictional parity, mutation and work bounds for one owned replay advance."""

import builtins
from dataclasses import replace
from datetime import timedelta, timezone
from decimal import Decimal

import pytest

from tests.unit.research.test_stock_dividend_book import accrue, book, calendar, event
from tests.unit.research.test_stock_retrospective_replay import advance, begin, spec
from tests.unit.research.test_stock_retrospective_replay_inputs import prepared
from trading_bot.hybrid.models import Account
from trading_bot.research import stock_dividend_book as ledger
from trading_bot.research import stock_economic_replay as kernel
from trading_bot.research import stock_operating_costs as costs
from trading_bot.research import stock_retrospective_replay as owner
from trading_bot.research.stock_operating_costs import (
    ModeledOperatingCharge,
    ModeledOperatingCostPlan,
)

D = Decimal


def test_owned_advance_scans_full_histories_only_at_entry_and_exit(monkeypatch):
    state = begin()
    counts = {"book": 0, "cost": 0, "made": 0}
    for module, name, label in (
        (ledger, "_validate_book", "book"),
        (kernel, "_validate_cost_history", "cost"),
        (ledger, "_make_book", "made"),
    ):
        original = getattr(module, name)

        def counted(*args, _original=original, _label=label, **kwargs):
            counts[_label] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(module, name, counted)
    before = len(state.cases[0].core.book.trace)
    result = advance(state)
    retained = len(result.cases[0].core.book.trace) - before
    assert counts["book"] <= 2, counts
    assert counts["cost"] <= 2, counts
    assert counts["made"] == retained, counts
    assert len(result.cases[0].core.cost_marks) == 2
    assert result.cases[0].core.book.account.paused is True


def test_owned_adoption_reuses_the_checked_dividend_tax_total(monkeypatch):
    state = begin()
    original = ledger.DividendBook.dividend_tax_reserved.fget
    visits = []

    def counted(value):
        visits.append(len(value.trace))
        return original(value)

    monkeypatch.setattr(ledger.DividendBook, "dividend_tax_reserved", property(counted))
    result = advance(state)
    assert len(visits) <= 2, visits
    assert result.cases[0].core.book.account.tax_reserve >= 0


@pytest.mark.parametrize("amount", [D(0), D(12), None, D(1001)])
@pytest.mark.parametrize("method", ["principal", "partial", "trailing"])
def test_owned_and_fresh_shared_core_have_identical_complete_outputs(amount, method):
    data = prepared()
    case = spec(owner, method=method)
    case = replace(
        case,
        operating_cost_plan=ModeledOperatingCostPlan(
            "fictional-explicit",
            (ModeledOperatingCharge("first", data._panel.calendar[200].opens_at, "other", amount),),
        ),
    )
    state = owner.begin_retrospective_economic_replay(data, cases=(case,))
    fresh = state.cases[0].core
    for index in (200, 201):
        frame = owner._frame(state.panel, case, index, state.annual)
        fresh = kernel._advance_economic_core(fresh, session_index=index, policy_frame=frame)
        state = advance(state)
        actual = state.cases[0].core
        assert actual == fresh
        assert actual.evidence_hash == fresh.evidence_hash
        assert actual.book.evidence_hash == fresh.book.evidence_hash


def transaction(value):
    factory = getattr(ledger, "_begin_book_transaction", None)
    assert factory is not None, "owned synchronous book transaction missing"
    return factory(value)


def test_transaction_rejects_foreign_same_clock_predecessor_and_account_rewind():
    original = book()
    tx = transaction(original)
    foreign = book()
    with pytest.raises(ValueError):
        tx.adopt(foreign, foreign.account, at=foreign.through_at)
    changed = Account.model_validate(original.account.model_dump() | {"cash": D(200)})
    with pytest.raises(ValueError):
        tx.adopt(original, changed, at=original.through_at)
    valid = tx.adopt(original, original.account, at=original.through_at)
    assert len(valid.trace) == len(original.trace) + 1
    assert tx.finish() is valid
    with pytest.raises(ValueError):
        tx.adopt(valid, valid.account, at=valid.through_at)


def test_transaction_still_rejects_new_cash_without_owned_cause():
    original = book()
    tx = transaction(original)
    invalid = Account.model_validate(original.account.model_dump() | {"tax_reserve": D(0)})
    with pytest.raises(ValueError):
        tx.adopt(original, invalid, at=original.through_at)


def test_transaction_full_exit_check_rejects_in_place_history_mutation():
    original = book()
    tx = transaction(original)
    current = tx.adopt(original, original.account, at=original.through_at)
    object.__setattr__(current.trace[0], "account_after_hash", "0" * 64)
    with pytest.raises(ValueError):
        tx.finish()


def cost_transaction():
    original = book()
    tx = transaction(original)
    plan = ModeledOperatingCostPlan(
        "fictional",
        (ModeledOperatingCharge("unknown", original.through_at, "other", None),),
    )
    return tx, costs._CostTransaction(tx, plan, {})


def test_owned_cost_summary_cannot_claim_unknown_liability_is_zero():
    tx, owner = cost_transaction()
    value = owner.apply(tx.current, at=tx.current.through_at)
    forged = replace(value, unpaid_unknown_ids=(), investable_cash=D(50))
    with pytest.raises(ValueError):
        owner._accept(forged)


def test_owned_cost_summary_rejects_changed_exact_plan_before_phase_binding():
    tx, owner = cost_transaction()
    value = owner.apply(tx.current, at=tx.current.through_at)
    object.__setattr__(owner.plan.charges[0], "amount_usd", D(0))
    with pytest.raises(ValueError):
        owner.phase_hash(value)


def test_owned_cost_summary_requires_exact_current_book_and_update():
    tx, owner = cost_transaction()
    value = owner.apply(tx.current, at=tx.current.through_at)
    assert owner.net(D(1000), value) is None
    with pytest.raises(ValueError):
        owner.net(D(1000), replace(value))
    current = tx.adopt(tx.current, tx.current.account, at=tx.current.through_at)
    with pytest.raises(ValueError):
        owner.net(D(1000), value)
    fresh = owner.apply(current, at=current.through_at)
    assert fresh.unpaid_unknown_ids == ("unknown",)
    assert owner.net(D(2), fresh) is None
    assert tx.finish() is current


@pytest.mark.parametrize("clock", ["future", "naive", "other_zone"])
def test_derived_summary_must_match_its_exact_owned_book_clock(clock):
    tx = transaction(book())
    owner = costs._CostTransaction(tx, ModeledOperatingCostPlan("fictional-zero", ()), {})
    value = owner.apply(tx.current, at=tx.current.through_at)
    at = value.at + timedelta(days=1)
    if clock == "naive":
        at = value.at.replace(tzinfo=None)
    elif clock == "other_zone":
        at = value.at.astimezone(timezone(timedelta(hours=1)))
    with pytest.raises(ValueError):
        owner._accept(replace(value, at=at))
    assert owner.phase_hash(value) == costs.stock_operating_phase_hash(value)
    assert tx.finish() is value.book


@pytest.mark.parametrize(
    "amounts,accepted",
    [
        ((D(0),), False),
        ((D(12),), False),
        ((None, D(12)), True),
        ((D(51), D(1)), True),
    ],
)
def test_derived_summary_cannot_skip_affordable_oldest_charge(amounts, accepted):
    tx = transaction(book())
    plan = ModeledOperatingCostPlan(
        "fictional-ordered",
        tuple(
            ModeledOperatingCharge(f"c{i}", tx.current.through_at, "other", amount)
            for i, amount in enumerate(amounts)
        ),
    )
    owner = costs._CostTransaction(tx, plan, {})
    unknown = tuple(f"c{i}" for i, value in enumerate(amounts) if value is None)
    unpaid = sum((value for value in amounts if value is not None), D(0))
    proposed = costs.OperatingCostUpdate(
        tx.current,
        plan,
        tx.current.through_at,
        D(0),
        unpaid,
        unknown,
        D(0) if unknown else max(D(0), tx.current.account.buying_power - unpaid),
    )
    if accepted:
        owner._accept(proposed)
        assert owner.phase_hash(proposed) == costs.stock_operating_phase_hash(proposed)
        assert tx.finish() is proposed.book
    else:
        with pytest.raises(ValueError):
            owner._accept(proposed)


def test_transaction_does_not_accept_a_caller_prepared_replacement_trace():
    original = book()
    tx = transaction(original)
    row = ledger._step(original, "advance", original.through_at, original.account, original.account)
    with pytest.raises(ValueError):
        ledger._make_book(
            original.account,
            original.entitlements,
            original.credited_events,
            original.tax_rate,
            original.account_at,
            original.through_at,
            original.sessions,
            original.calendar_source_hash,
            (*original.trace, row),
            _transaction=tx,
        )


def test_owned_append_does_not_compare_every_previously_checked_trace_row(monkeypatch):
    original = book()
    for _ in range(8):
        original = ledger.adopt_dividend_account(original, original.account, at=original.through_at)
    tx = transaction(original)
    comparisons = []

    def watched_zip(*values, strict=False):
        historical_trace = values and values[0] and values[0][0] is original.trace[0]
        for row in builtins.zip(*values, strict=strict):
            if historical_trace:
                comparisons.append(1)
            yield row

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "zip", watched_zip, raising=False)
        result = tx.adopt(original, original.account, at=original.through_at)
    assert comparisons == []
    assert len(result.trace) == 10
    assert tx.finish() is result


def test_owned_dividend_accrual_credit_and_tax_match_the_fresh_route():
    original = book()
    tx = transaction(original)
    earned = tx.accrue(
        original,
        event(),
        snapshot_at=calendar()[1].closes_at,
        ex_opens_at=calendar()[2].opens_at,
        modeled_pay_available_at=calendar()[4].opens_at,
    )
    assert tx.receivable(earned, at=calendar()[2].opens_at) == D("2.5")
    paid = tx.credit(earned, at=calendar()[4].opens_at)
    expected = ledger.credit_due_dividends(accrue(original), at=calendar()[4].opens_at)
    assert tx.finish().evidence_hash == expected.evidence_hash
    assert paid.account.cash == D("102.5")
    assert paid.account.tax_reserve == D("10.625")
    assert paid.account.lots == original.account.lots


def test_current_receivable_uses_checked_credit_ids_but_past_query_stays_historical(monkeypatch):
    paid = ledger.credit_due_dividends(accrue(), at=calendar()[4].opens_at)
    tx = transaction(paid)
    descriptor = ledger.DividendBookStep.action
    reads = []

    def counted(row):
        reads.append(1)
        return descriptor.__get__(row, ledger.DividendBookStep)

    with monkeypatch.context() as patch:
        patch.setattr(ledger.DividendBookStep, "action", property(counted))
        assert tx.receivable(paid, at=paid.through_at) == 0
        assert reads == []
        assert tx.receivable(paid, at=calendar()[2].opens_at) == D("2.5")
        assert reads
    assert tx.finish() is paid


@pytest.mark.parametrize("method", ["principal", "partial", "trailing"])
def test_sales_settlement_risk_and_receivables_match_fresh_complete_output(method):
    from trading_bot.research.stock_retrospective_replay_inputs import SYMBOLS

    stock = ("100",) * 150 + ("101",) * 51 + ("117",) * 2 + ("90",) * 503
    data = prepared(
        prices={s: ("100",) * 706 if s == "SPY" else stock for s in SYMBOLS},
        dividend=True,
    )
    case = spec(owner, method=method)
    case = replace(
        case,
        operating_cost_plan=ModeledOperatingCostPlan(
            "fictional-deferred-unknown",
            (ModeledOperatingCharge("late", data._panel.calendar[203].opens_at, "other", None),),
        ),
    )
    state = owner.begin_retrospective_economic_replay(data, cases=(case,))
    fresh = state.cases[0].core
    for index in range(200, 207):
        fresh = kernel._advance_economic_core(
            fresh,
            session_index=index,
            policy_frame=owner._frame(state.panel, case, index, state.annual),
        )
        state = advance(state)
        assert state.cases[0].core == fresh
        assert state.cases[0].core.evidence_hash == fresh.evidence_hash
    assert any(row.side == "sell" and row.outcome == "filled" for row in fresh.records)
    assert fresh.book.gross_earned > 0
    assert fresh.book.gross_paid == 0
    assert fresh.cost_marks[-1].net_equity is None
    assert fresh.book.account.tactical_suspended is True


@pytest.mark.parametrize("tamper", ["cash", "mark", "anchor", "plan", "pending"])
def test_every_new_advance_rechecks_prior_owner_state(tamper):
    state = advance(begin())
    core = state.cases[0].core
    if tamper == "cash":
        object.__setattr__(
            core.book,
            "account",
            Account.model_validate(
                core.book.account.model_dump() | {"cash": core.book.account.cash + 1},
            ),
        )
    elif tamper == "mark":
        object.__setattr__(core.cost_marks[-1], "paid_total", D(999))
    elif tamper == "anchor":
        object.__setattr__(core.book.trace[-1], "event_fingerprint", "0" * 64)
    elif tamper == "plan":
        object.__setattr__(core.operating_cost_plan, "label", "substituted")
    else:
        object.__setattr__(core, "pending", ())
        object.__setattr__(core, "previous_signals", ())
    with pytest.raises(ValueError):
        advance(state)
