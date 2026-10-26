"""Fictional scheduled budgets and paused accounts; no observed spending or broker."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from trading_bot.hybrid.models import Account, PaperOrder, Settlement
from trading_bot.research.hybrid_policies import CalendarSession
from trading_bot.research.stock_dividend_book import (
    adopt_dividend_account,
    create_dividend_book,
)
from trading_bot.research.stock_operating_costs import (
    ModeledOperatingCharge,
    ModeledOperatingCostPlan,
    apply_stock_operating_costs,
    net_equity_after_operating_costs,
)

D = Decimal
START = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
DEFAULT_COST = D(12)


def book(**changes):
    sessions = tuple(
        CalendarSession(i, START + timedelta(days=i), START + timedelta(days=i, hours=6))
        for i in range(4)
    )
    return create_dividend_book(
        Account.model_validate({"cash": D(1000)} | changes),
        account_at=START,
        sessions=sessions,
        calendar_source_hash="b" * 64,
        tax_rate=D(".25"),
    )


def charge(identity="hosting-jan", amount=DEFAULT_COST, due_at=START, category="hosting"):
    return ModeledOperatingCharge(identity, due_at, category, amount)


def plan(*charges):
    return ModeledOperatingCostPlan("fictional-monthly-budget", charges or (charge(),))


def test_due_cost_debits_owned_cash_without_inventing_a_trade_or_tax():
    original = book(tax_reserve=D(5), fees=D(2), kill_switch=True)
    result = apply_stock_operating_costs(original, plan(), at=START)
    assert result.book.account.cash == 988 and result.paid_total == 12
    assert result.book.account.tax_reserve == 5 and result.book.account.fees == 2
    assert result.book.account.kill_switch is True and result.book.account.paused is True
    assert result.book.account.lots == original.account.lots
    assert result.book.account.fills == result.book.account.orders == ()
    assert result.book.account.realized_gain == 0
    assert result.unpaid_known == 0 and result.unpaid_unknown_ids == ()
    assert result.investable_cash == 983
    assert result.book.gross_paid == result.book.dividend_tax_reserved == 0
    step = result.book.trace[-1]
    assert step.action == "operating_expense" and step.event_id == "hosting-jan"
    assert step.gross_amount == 12 and step.tax_reserve_added == 0
    assert net_equity_after_operating_costs(D(988), result) == 988


def test_future_cost_is_not_debited_or_already_incurred():
    original = book()
    result = apply_stock_operating_costs(
        original, plan(charge(due_at=START + timedelta(days=1))), at=START
    )
    assert result.book == original and result.paid_total == result.unpaid_known == 0
    assert result.investable_cash == 1000


def test_same_instant_retry_and_restart_are_idempotent():
    schedule = plan()
    first = apply_stock_operating_costs(book(), schedule, at=START)
    second = apply_stock_operating_costs(first.book, schedule, at=START)
    assert first == second
    later = apply_stock_operating_costs(first.book, schedule, at=START + timedelta(days=1))
    assert later.book.account.cash == 988 and later.paid_total == 12
    assert len([s for s in later.book.trace if s.action == "operating_expense"]) == 1


def test_reserved_cash_and_tax_cannot_pay_cost_and_liability_is_not_zero():
    reserved = PaperOrder(
        id="owned-buy",
        symbol="AXP",
        side="buy",
        sleeve="tactical",
        quantity=D(1),
        reserved_cash=D(10),
    )
    original = book(cash=D(20), tax_reserve=D(5), orders=(reserved,))
    result = apply_stock_operating_costs(original, plan(), at=START)
    assert result.book.account.cash == 20 and result.paid_total == 0
    assert result.book.account.reserved_cash == 10 and result.unpaid_known == 12
    assert result.investable_cash == 0
    assert net_equity_after_operating_costs(D(20), result) == 8


def test_unsettled_sales_cannot_fund_cost_until_owned_settlement():
    from trading_bot.hybrid.execution import settle

    due = START + timedelta(days=1)
    original = book(cash=D(0), settlements=(Settlement(id="prior-sale", amount=D(50), due_at=due),))
    first = apply_stock_operating_costs(original, plan(), at=START)
    assert first.unpaid_known == 12 and first.book.account.cash == 0
    funded = adopt_dividend_account(first.book, settle(first.book.account, due), at=due)
    later = apply_stock_operating_costs(funded, plan(), at=due)
    assert later.book.account.cash == 38 and later.unpaid_known == 0


def test_unknown_due_cost_makes_net_equity_unavailable_and_blocks_later_payments():
    schedule = plan(charge("a", None), charge("b", D(5)))
    result = apply_stock_operating_costs(book(), schedule, at=START)
    assert result.book.account.cash == 1000 and result.paid_total == 0
    assert result.unpaid_unknown_ids == ("a",) and result.unpaid_known == 5
    assert result.investable_cash == 0
    assert net_equity_after_operating_costs(D(1000), result) is None


def test_unaffordable_cost_preserves_fifo_and_can_report_negative_net_equity():
    result = apply_stock_operating_costs(
        book(cash=D(2)), plan(charge("a", D(12)), charge("b", D(1))), at=START
    )
    assert result.book.account.cash == 2 and result.unpaid_known == 13
    assert result.paid_total == result.investable_cash == 0
    assert net_equity_after_operating_costs(D(2), result) == -11


@pytest.mark.parametrize("change", ("amount", "due", "label", "remove", "extend"))
def test_paid_schedule_cannot_be_rewritten_after_restart(change):
    original_plan = plan()
    paid = apply_stock_operating_costs(book(), original_plan, at=START).book
    changed = {
        "amount": plan(charge(amount=D(13))),
        "due": plan(charge(due_at=START - timedelta(seconds=1))),
        "label": replace(original_plan, label="changed-model"),
        "remove": ModeledOperatingCostPlan("fictional-monthly-budget", ()),
        "extend": plan(charge(), charge("hosting-feb", due_at=START + timedelta(days=31))),
    }[change]
    with pytest.raises(ValueError, match="operating"):
        apply_stock_operating_costs(paid, changed, at=START)


def test_expense_does_not_allow_an_unexplained_cash_adoption():
    result = apply_stock_operating_costs(book(), plan(), at=START)
    with pytest.raises(ValueError, match="unattributed_cash"):
        adopt_dividend_account(
            result.book, result.book.account.model_copy(update={"cash": D(980)}), at=START
        )


@pytest.mark.parametrize("amount", (D(-1), D("NaN"), D("Infinity"), True, 12, "12"))
def test_invalid_known_amount_cannot_be_a_cost_or_credit(amount):
    with pytest.raises(ValueError):
        charge(amount=amount)


@pytest.mark.parametrize("value", ("", "\n", "a" * 129))
def test_invalid_identity_is_rejected(value):
    with pytest.raises(ValueError):
        charge(value)


def test_schedule_requires_unique_ordered_immutable_utc_charges():
    with pytest.raises(ValueError):
        plan(charge(), charge())
    with pytest.raises(ValueError):
        plan(charge("b"), charge("a"))
    with pytest.raises(ValueError):
        ModeledOperatingCostPlan("fictional", [charge()])
    with pytest.raises(ValueError):
        charge(due_at=START.replace(tzinfo=None))
    with pytest.raises(ValueError):
        charge(category="secret-provider")


def test_zero_cost_is_an_explicit_scenario_and_flags_cannot_promote():
    schedule = ModeledOperatingCostPlan("modeled-zero-cost-sensitivity", (charge(amount=D(0)),))
    result = apply_stock_operating_costs(book(), schedule, at=START)
    assert result.paid_total == 0 and result.unpaid_known == 0
    assert result.book.trace[-1].action == "operating_expense"
    assert result.qualified is result.live_authorized is result.investment_eligible is False
    with pytest.raises(FrozenInstanceError):
        result.qualified = True
    with pytest.raises(ValueError):
        apply_stock_operating_costs(result.book, schedule, at=START - timedelta(seconds=1))


def test_tampered_schedule_or_result_is_revalidated():
    schedule = plan()
    object.__setattr__(schedule.charges[0], "amount_usd", D(-10))
    with pytest.raises(ValueError):
        apply_stock_operating_costs(book(), schedule, at=START)


@pytest.mark.parametrize(
    "changes",
    (
        {"paid_total": D(0)},
        {"unpaid_known": D(5)},
        {"unpaid_unknown_ids": ("fabricated",)},
        {"investable_cash": D(1000)},
    ),
)
def test_forged_derived_costs_cannot_enter_net_equity(changes):
    result = apply_stock_operating_costs(book(), plan(), at=START)
    with pytest.raises(ValueError):
        net_equity_after_operating_costs(D(988), replace(result, **changes))


def test_cost_cannot_erase_an_earned_dividend_or_reserve():
    from datetime import date

    from trading_bot.hybrid.models import Lot
    from trading_bot.market_data.stock_economic_evidence import StockCashDividendEvent
    from trading_bot.research.stock_dividend_book import (
        credit_due_dividends,
        receivable_value,
        record_dividend_entitlement,
    )

    original = book(
        lots=(
            Lot(
                id="owned",
                symbol="AXP",
                sleeve="long_term",
                quantity=D(4),
                basis=D(400),
                acquired_at=START,
            ),
        )
    )
    ex_open, pay_open = original.sessions[1].opens_at, original.sessions[3].opens_at
    event = StockCashDividendEvent(
        id="native-income",
        ticker="AXP",
        cash_amount=D(1),
        currency="USD",
        ex_dividend_date=date(2025, 1, 3),
        pay_date=date(2025, 1, 4),
        record_date=date(2025, 1, 3),
        declaration_date=date(2025, 1, 1),
        distribution_type="recurring",
        frequency=4,
        received_at=datetime(2026, 10, 26, tzinfo=UTC),
        source_csv_sha256="a" * 64,
    )
    original = adopt_dividend_account(original, original.account, at=original.sessions[0].closes_at)
    earned = record_dividend_entitlement(
        original,
        event,
        snapshot_at=original.sessions[0].closes_at,
        ex_opens_at=ex_open,
        modeled_pay_available_at=pay_open,
    )
    charged = apply_stock_operating_costs(earned, plan(), at=ex_open)
    assert charged.book.account.cash == 988
    assert receivable_value(charged.book, at=ex_open) == 4
    paid = credit_due_dividends(charged.book, at=pay_open)
    assert paid.account.cash == 992 and paid.account.tax_reserve == 1
    costs = apply_stock_operating_costs(paid, plan(), at=pay_open)
    assert costs.paid_total == 12 and costs.book.gross_paid == 4
    assert costs.investable_cash == 991 and costs.book.account.lots == original.account.lots


def test_unknown_plan_flags_cannot_claim_observed_spending_or_qualified_results():
    schedule = plan()
    object.__setattr__(schedule, "observed_spending", True)
    with pytest.raises(ValueError):
        apply_stock_operating_costs(book(), schedule, at=START)
    result = apply_stock_operating_costs(book(), plan(), at=START)
    object.__setattr__(result, "qualified", True)
    with pytest.raises(ValueError):
        net_equity_after_operating_costs(D(988), result)


def test_ambient_decimal_precision_cannot_change_cash_or_liability():
    schedule = plan(charge(amount=D("12.123456789123456789")))
    expected = apply_stock_operating_costs(book(), schedule, at=START)
    original = book()
    with localcontext() as ctx:
        ctx.prec = 5
        ctx.rounding = ROUND_DOWN
        actual = apply_stock_operating_costs(original, schedule, at=START)
        assert ctx.prec == 5 and ctx.rounding == ROUND_DOWN
    assert actual == expected
    assert actual.book.account.cash == D("987.876543210876543211")


def test_schedule_hash_and_update_hash_bind_unknowns_and_complete_schedule():
    known, unknown = plan(), plan(charge(amount=None))
    assert known.evidence_hash != unknown.evidence_hash
    assert apply_stock_operating_costs(book(), known, at=START).evidence_hash != (
        apply_stock_operating_costs(book(), unknown, at=START).evidence_hash
    )


def test_direct_book_transition_cannot_bypass_a_prior_unknown_cost():
    from trading_bot.market_data.recording import content_hash
    from trading_bot.research.stock_dividend_book import pay_modeled_operating_expense

    unknown, later = charge("a", None), charge("b", D(5))
    schedule = plan(unknown, later)
    skipped = pay_modeled_operating_expense(
        book(),
        charge_id="b",
        amount_usd=D(5),
        at=START,
        charge_fingerprint=str(
            content_hash(
                (
                    "stock-operating-charge-v1",
                    schedule.evidence_hash,
                    later,
                )
            )
        ),
    )
    with pytest.raises(ValueError, match="operating"):
        apply_stock_operating_costs(skipped, schedule, at=START)


@pytest.mark.parametrize(
    "amount", (D("1e-48"), D("12.000000000000000000000000000000000000000000000001"))
)
def test_rounding_cannot_record_a_payment_without_its_exact_cash_debit(amount):
    with pytest.raises(ValueError, match="operating"):
        apply_stock_operating_costs(book(), plan(charge(amount=amount)), at=START)
