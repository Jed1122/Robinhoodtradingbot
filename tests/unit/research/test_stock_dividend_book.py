"""Fictional experimental-account facts; no brokerage or capital orders are sent."""

import importlib
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, DefaultContext, Inexact, localcontext

import pytest

from trading_bot.hybrid.models import (
    Account,
    AllocationEpisode,
    ExitProgress,
    FillFact,
    Lot,
    PaperOrder,
    Settlement,
)
from trading_bot.market_data.stock_economic_evidence import StockCashDividendEvent
from trading_bot.research.hybrid_policies import CalendarSession

D = Decimal
SOURCE = "a" * 64
CALENDAR_SOURCE = "b" * 64
RECEIVED = datetime(2026, 10, 26, 12, tzinfo=UTC)
DEFAULT_TAX = D(".25")


def calendar():
    days = (
        date(2025, 1, 2),
        date(2025, 1, 3),
        date(2025, 1, 6),
        date(2025, 1, 7),
        date(2025, 1, 8),
        date(2025, 1, 9),
    )
    return tuple(
        CalendarSession(
            i,
            datetime(day.year, day.month, day.day, 14, 30, tzinfo=UTC),
            datetime(day.year, day.month, day.day, 21, tzinfo=UTC),
        )
        for i, day in enumerate(days)
    )


def account(**changes):
    sessions = calendar()
    lots = (
        Lot(
            id="long",
            symbol="AXP",
            sleeve="long_term",
            quantity=D(4),
            basis=D(360),
            acquired_at=sessions[0].opens_at,
            episode_id="long-episode",
        ),
        Lot(
            id="tactical",
            symbol="AXP",
            sleeve="tactical",
            quantity=D(6),
            basis=D(540),
            acquired_at=sessions[0].opens_at,
            episode_id="tactical-episode",
        ),
    )
    # Retained pending experimental facts test reservation preservation only.
    orders = (
        PaperOrder(
            id="pending",
            symbol="BAC",
            side="buy",
            sleeve="long_term",
            quantity=D(1),
            reserved_cash=D(40),
        ),
        PaperOrder(id="sell", symbol="AXP", side="sell", sleeve="long_term", quantity=D(4)),
    )
    values = {"cash": D(100), "tax_reserve": D(10), "lots": lots, "orders": orders}
    return Account.model_validate(values | changes)


def event(**changes):
    values = {
        "id": "native-event",
        "ticker": "AXP",
        "cash_amount": D(".25"),
        "currency": "USD",
        "ex_dividend_date": date(2025, 1, 6),
        "pay_date": date(2025, 1, 7),
        "record_date": date(2025, 1, 7),
        "declaration_date": date(2025, 1, 1),
        "distribution_type": "recurring",
        "frequency": 4,
        "received_at": RECEIVED,
        "source_csv_sha256": SOURCE,
    }
    return StockCashDividendEvent(**(values | changes))


def book(*, tax_rate=DEFAULT_TAX, state=None):
    from trading_bot.research.stock_dividend_book import create_dividend_book

    return create_dividend_book(
        account() if state is None else state,
        account_at=calendar()[1].closes_at,
        sessions=calendar(),
        calendar_source_hash=CALENDAR_SOURCE,
        tax_rate=tax_rate,
    )


def accrue(value=None, native=None, **changes):
    from trading_bot.research.stock_dividend_book import record_dividend_entitlement

    values = {
        "snapshot_at": calendar()[1].closes_at,
        "ex_opens_at": calendar()[2].opens_at,
        "modeled_pay_available_at": calendar()[4].opens_at,
    }
    return record_dividend_entitlement(
        book() if value is None else value,
        event() if native is None else native,
        **(values | changes),
    )


def test_entitlement_accrues_owned_cross_sleeve_shares_without_crediting_cash():
    from trading_bot.research.stock_dividend_book import receivable_value

    original = book()
    result = accrue(original)
    entitlement = result.entitlements[0]
    assert entitlement.accrual.shares_before_ex == D(10)
    assert entitlement.accrual.accrued_amount == result.gross_earned == D("2.5")
    assert entitlement.event.received_at == RECEIVED
    assert entitlement.event.source_csv_sha256 == SOURCE
    assert result.account == original.account
    assert result.gross_paid == result.dividend_tax_reserved == 0
    assert receivable_value(result, at=calendar()[1].closes_at) == 0
    assert receivable_value(result, at=calendar()[2].opens_at) == D("2.5")
    assert len(entitlement.snapshot_owned_lots_hash) == len(entitlement.event_fingerprint) == 64
    assert result.account.buying_power == D(50)


def test_date_only_pay_day_does_not_supply_cash_before_bound_next_session():
    from trading_bot.research.stock_dividend_book import credit_due_dividends, receivable_value

    original = accrue()
    pay_day = credit_due_dividends(original, at=calendar()[3].closes_at)
    assert pay_day.account.cash == D(100)
    assert pay_day.gross_paid == 0
    assert receivable_value(pay_day, at=calendar()[3].closes_at) == D("2.5")
    paid = credit_due_dividends(pay_day, at=calendar()[4].opens_at)
    assert paid.account.cash == D("102.5")
    assert paid.account.tax_reserve == D("10.625")
    assert paid.gross_paid == D("2.5")
    assert paid.dividend_tax_reserved == D(".625")
    assert paid.credited_events == ("native-event",)
    assert receivable_value(paid, at=calendar()[4].opens_at) == 0
    assert receivable_value(paid, at=calendar()[2].opens_at) == D("2.5")
    assert paid.account.lots == original.account.lots
    assert paid.account.orders == original.account.orders
    assert paid.account.fills == original.account.fills
    assert paid.account.settlements == original.account.settlements
    assert paid.account.realized_gain == original.account.realized_gain
    assert paid.account.fees == original.account.fees
    assert paid.account.buying_power == D("51.875")


@pytest.mark.parametrize("rate,added", [(None, "2.5"), (D(0), "0"), (D(1), "2.5")])
def test_explicit_tax_scenario_and_unknown_rate_reserve_paid_cash(rate, added):
    from trading_bot.research.stock_dividend_book import credit_due_dividends

    paid = credit_due_dividends(accrue(book(tax_rate=rate)), at=calendar()[4].opens_at)
    assert paid.dividend_tax_reserved == D(added)
    assert paid.account.tax_reserve == D(10) + D(added)
    assert paid.account.cash == D("102.5")


def test_earned_right_survives_later_modeled_sale_and_current_lot_change():
    from trading_bot.research.stock_dividend_book import (
        adopt_dividend_account,
        credit_due_dividends,
        receivable_value,
    )

    accrued = accrue()
    old = accrued.account
    external_sale = Account.model_validate(
        old.model_dump()
        | {
            "lots": old.lots[1:],
            "orders": (
                old.orders[0],
                old.orders[1].model_copy(update={"filled": D(4), "status": "filled"}),
            ),
            "fills": (
                FillFact(
                    id="external-modeled-sale",
                    order_id="sell",
                    quantity=D(4),
                    price=D(90),
                    fee=D(0),
                    at=calendar()[3].opens_at,
                ),
            ),
            "settlements": (
                Settlement(
                    id="external-modeled-sale", amount=D(360), due_at=calendar()[4].opens_at
                ),
            ),
        }
    )
    adopted = adopt_dividend_account(accrued, external_sale, at=calendar()[3].closes_at)
    assert adopted.account.lots == old.lots[1:]
    assert adopted.entitlements == accrued.entitlements
    assert receivable_value(adopted, at=calendar()[3].closes_at) == D("2.5")
    paid = credit_due_dividends(adopted, at=calendar()[4].opens_at)
    assert paid.account.cash == D("102.5")
    assert paid.account.settlements == external_sale.settlements
    assert paid.gross_paid == D("2.5")
    assert paid.trace[-2].action == "adopt_account"
    assert paid.trace[-2].account_before_hash != paid.trace[-2].account_after_hash


def test_zero_owned_shares_are_an_explicit_zero_entitlement():
    from trading_bot.research.stock_dividend_book import credit_due_dividends

    result = accrue(native=event(ticker="KO"))
    assert len(result.entitlements) == 1
    assert result.entitlements[0].accrual.shares_before_ex == 0
    assert result.gross_earned == 0
    paid = credit_due_dividends(result, at=calendar()[4].opens_at)
    assert paid.account == result.account
    assert paid.credited_events == ("native-event",)


def test_unknown_pay_date_and_missing_available_calendar_stay_receivable():
    from trading_bot.research.stock_dividend_book import credit_due_dividends, receivable_value

    for native in (event(pay_date=None), event()):
        result = accrue(native=native, modeled_pay_available_at=None)
        later = credit_due_dividends(result, at=calendar()[5].closes_at)
        assert later.account.cash == D(100)
        assert later.gross_paid == 0
        assert receivable_value(later, at=calendar()[5].closes_at) == D("2.5")


def test_same_native_event_and_snapshot_are_idempotent_even_after_credit():
    from trading_bot.research.stock_dividend_book import credit_due_dividends

    accrued = accrue()
    assert accrue(accrued) is accrued
    paid = credit_due_dividends(accrued, at=calendar()[4].opens_at)
    assert credit_due_dividends(paid, at=calendar()[4].opens_at) is paid
    assert accrue(paid) is paid


@pytest.mark.parametrize(
    "change",
    [
        {"cash_amount": D(".5")},
        {"source_csv_sha256": "c" * 64},
        {"received_at": RECEIVED + timedelta(seconds=1)},
        {"pay_date": date(2025, 1, 8)},
    ],
)
def test_conflicting_native_id_or_original_binding_cannot_overwrite_entitlement(change):
    with pytest.raises(ValueError):
        accrue(accrue(), native=event(**change))


def test_another_native_id_cannot_duplicate_the_same_economic_event():
    with pytest.raises(ValueError):
        accrue(accrue(), native=event(id="replacement-id"))
    with pytest.raises(ValueError):
        accrue(accrue(), native=event(id="replacement-id", cash_amount=D(".5")))


@pytest.mark.parametrize("distribution", [None, "special", "supplemental", "irregular", "unknown"])
def test_unsupported_distribution_requires_due_bill_rules(distribution):
    with pytest.raises(ValueError):
        accrue(native=event(distribution_type=distribution))


@pytest.mark.parametrize(
    "change",
    [
        {"snapshot_at": calendar()[2].opens_at},
        {"snapshot_at": calendar()[1].opens_at},
        {"snapshot_at": calendar()[0].closes_at},
        {"snapshot_at": calendar()[1].closes_at.replace(tzinfo=None)},
        {"ex_opens_at": calendar()[3].opens_at},
        {"ex_opens_at": calendar()[2].opens_at + timedelta(seconds=1)},
        {"modeled_pay_available_at": calendar()[3].opens_at},
        {"modeled_pay_available_at": calendar()[4].closes_at},
        {"modeled_pay_available_at": calendar()[5].opens_at},
    ],
)
def test_snapshot_ex_open_and_modeled_payment_must_match_bound_calendar(change):
    with pytest.raises(ValueError):
        accrue(**change)


def test_unknown_native_payment_cannot_receive_fabricated_availability():
    with pytest.raises(ValueError):
        accrue(native=event(pay_date=None))


def test_native_accrual_pay_date_flag_never_credits_same_day_book_cash():
    from trading_bot.research.stock_dividend_book import credit_due_dividends, receivable_value

    same_day = accrue(
        native=event(pay_date=date(2025, 1, 6)),
        modeled_pay_available_at=calendar()[3].opens_at,
    )
    # The existing helper has date-only semantics; the book deliberately waits.
    assert same_day.entitlements[0].accrual.cash_available == D("2.5")
    assert same_day.account.cash == D(100)
    assert receivable_value(same_day, at=calendar()[2].opens_at) == D("2.5")
    waiting = credit_due_dividends(same_day, at=calendar()[2].closes_at)
    assert waiting.account.cash == D(100)
    paid = credit_due_dividends(waiting, at=calendar()[3].opens_at)
    assert paid.account.cash == D("102.5")


@pytest.mark.parametrize(
    "change",
    [
        {"sessions": ()},
        {"sessions": list(calendar())},
        {"sessions": calendar()[::-1]},
        {"calendar_source_hash": "unbound"},
        {"account_at": calendar()[1].closes_at.replace(tzinfo=None)},
    ],
)
def test_factory_requires_immutable_known_calendar_source_and_utc_snapshot(change):
    from trading_bot.research.stock_dividend_book import create_dividend_book

    values = {
        "account_at": calendar()[1].closes_at,
        "sessions": calendar(),
        "calendar_source_hash": CALENDAR_SOURCE,
    }
    with pytest.raises(ValueError):
        create_dividend_book(account(), **(values | change))


def test_same_day_or_post_snapshot_acquisition_cannot_be_backdated():
    for acquired in (calendar()[2].opens_at, calendar()[1].closes_at + timedelta(seconds=1)):
        state = account(lots=(account().lots[0].model_copy(update={"acquired_at": acquired}),))
        with pytest.raises(ValueError):
            accrue(book(state=state))


def test_credit_and_new_accrual_cannot_rewind_state_clock():
    from trading_bot.research.stock_dividend_book import credit_due_dividends

    accrued = accrue()
    with pytest.raises(ValueError):
        credit_due_dividends(accrued, at=calendar()[1].closes_at)
    advanced = credit_due_dividends(accrued, at=calendar()[3].closes_at)
    with pytest.raises(ValueError):
        accrue(advanced, native=event(id="other-symbol-event", ticker="KO"))


def test_adoption_retains_credited_income_history_and_rejects_unexplained_cash_rewind():
    from trading_bot.research.stock_dividend_book import (
        adopt_dividend_account,
        credit_due_dividends,
    )

    paid = credit_due_dividends(accrue(), at=calendar()[4].opens_at)
    adopted = adopt_dividend_account(paid, paid.account, at=calendar()[4].closes_at)
    assert adopted.entitlements == paid.entitlements
    assert adopted.credited_events == paid.credited_events
    assert adopted.gross_paid == D("2.5")
    assert credit_due_dividends(adopted, at=calendar()[4].closes_at) is adopted
    with pytest.raises(ValueError):
        adopt_dividend_account(paid, account(), at=calendar()[4].closes_at)


@pytest.mark.parametrize(
    "change",
    [
        {"starting_capital": D(999)},
        {"orders": ()},
        {"paused": False},
        {"tax_reserve": D(0)},
    ],
)
def test_adoption_rejects_obvious_history_or_dividend_reserve_loss(change):
    from trading_bot.research.stock_dividend_book import (
        adopt_dividend_account,
        credit_due_dividends,
    )

    paid = credit_due_dividends(accrue(), at=calendar()[4].opens_at)
    modified = Account.model_validate(paid.account.model_dump() | change)
    with pytest.raises(ValueError):
        adopt_dividend_account(paid, modified, at=calendar()[4].closes_at)


@pytest.mark.parametrize("flag", ["kill_switch", "tactical_suspended", "weekly_review_required"])
def test_adoption_cannot_clear_sticky_safety_flags(flag):
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = book(state=account(**{flag: True}))
    cleared = Account.model_validate(original.account.model_dump() | {flag: False})
    with pytest.raises(ValueError):
        adopt_dividend_account(original, cleared, at=calendar()[2].opens_at)


def test_adoption_cannot_drop_or_modify_prior_fills_or_reduce_filled_quantity():
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    existing_fill = FillFact(
        id="old-fill",
        order_id="sell",
        quantity=D(1),
        price=D(90),
        fee=D(0),
        at=calendar()[0].closes_at,
    )
    initial = account()
    existing_order = initial.orders[1].model_copy(update={"status": "partial", "filled": D(1)})
    original = book(
        state=account(orders=(initial.orders[0], existing_order), fills=(existing_fill,))
    )
    variants = (
        {"fills": ()},
        {"fills": (existing_fill.model_copy(update={"price": D(91)}),)},
        {
            "orders": (
                initial.orders[0],
                existing_order.model_copy(update={"status": "open", "filled": D(0)}),
            )
        },
    )
    for changes in variants:
        with pytest.raises(ValueError):
            adopt_dividend_account(
                original,
                Account.model_validate(original.account.model_dump() | changes),
                at=calendar()[2].opens_at,
            )


def test_settlement_only_adoption_preserves_previously_credited_cash():
    from trading_bot.research.stock_dividend_book import (
        adopt_dividend_account,
        credit_due_dividends,
    )

    pending = Settlement(id="prior-sale", amount=D(20), due_at=calendar()[4].opens_at)
    paid = credit_due_dividends(
        accrue(book(state=account(settlements=(pending,)))), at=calendar()[4].opens_at
    )
    settled = Account.model_validate(
        paid.account.model_dump() | {"settlements": (), "cash": D("122.5")}
    )
    adopted = adopt_dividend_account(paid, settled, at=calendar()[4].opens_at)
    assert adopted.account.cash == D("122.5")
    assert adopted.gross_paid == D("2.5")
    with pytest.raises(ValueError):
        adopt_dividend_account(
            paid,
            Account.model_validate(settled.model_dump() | {"cash": D(120)}),
            at=calendar()[4].opens_at,
        )


def modeled_sale(original):
    from trading_bot.config.hybrid import HybridSettings
    from trading_bot.hybrid.execution import fill_order

    fill = FillFact(
        id="new-modeled-sale",
        order_id="sell",
        quantity=D(4),
        price=D(90),
        fee=D(".01"),
        at=calendar()[3].opens_at,
    )
    return fill_order(
        original.account, fill, HybridSettings(), settlement_at=calendar()[4].opens_at
    )


def test_new_settlement_without_appended_fill_cannot_create_future_cash():
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = book(state=Account())
    unsupported_claim = Settlement(
        id="unearned-claim", amount=D(1000), due_at=calendar()[3].opens_at
    )
    proposed = Account.model_validate(
        original.account.model_dump() | {"settlements": (unsupported_claim,)}
    )
    with pytest.raises(ValueError):
        adopt_dividend_account(original, proposed, at=calendar()[2].opens_at)


@pytest.mark.parametrize(
    "corruption",
    ["amount", "zero_amount", "wrong_side", "foreign_id", "due_before_fill", "due_at_fill"],
)
def test_new_settlement_requires_exact_causal_appended_sell_fill(corruption):
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = book()
    proposed = modeled_sale(original)
    claim = proposed.settlements[0]
    updates = {}
    if corruption == "amount":
        claim = claim.model_copy(update={"amount": D(360)})
    elif corruption == "zero_amount":
        claim = claim.model_copy(update={"amount": D(0)})
    elif corruption == "wrong_side":
        updates["fills"] = (proposed.fills[0].model_copy(update={"order_id": "pending"}),)
    elif corruption == "foreign_id":
        claim = claim.model_copy(update={"id": "unrelated-claim"})
    elif corruption == "due_before_fill":
        claim = claim.model_copy(update={"due_at": proposed.fills[0].at - timedelta(seconds=1)})
    else:
        claim = claim.model_copy(update={"due_at": proposed.fills[0].at})
    proposed = Account.model_validate(proposed.model_dump() | updates | {"settlements": (claim,)})
    with pytest.raises(ValueError):
        adopt_dividend_account(original, proposed, at=calendar()[3].closes_at)


def test_old_fill_cannot_be_reused_to_introduce_another_settlement_claim():
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    old_fill = FillFact(
        id="already-recorded",
        order_id="sell",
        quantity=D(1),
        price=D(90),
        fee=D(0),
        at=calendar()[0].closes_at,
    )
    original = book(state=account(fills=(old_fill,)))
    recycled_claim = Settlement(id=old_fill.id, amount=D(90), due_at=calendar()[3].opens_at)
    proposed = Account.model_validate(
        original.account.model_dump() | {"settlements": (recycled_claim,)}
    )
    with pytest.raises(ValueError):
        adopt_dividend_account(original, proposed, at=calendar()[2].opens_at)


def test_fill_order_sale_claim_and_later_settlement_cash_are_accepted():
    from trading_bot.hybrid.execution import settle
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = book()
    proposed = modeled_sale(original)
    adopted = adopt_dividend_account(original, proposed, at=calendar()[3].closes_at)
    assert adopted.account.cash == D(100)
    assert adopted.account.settlements[0].id == adopted.account.fills[0].id
    assert adopted.account.settlements[0].amount == D("359.99")
    cleared = settle(adopted.account, calendar()[4].opens_at)
    final = adopt_dividend_account(adopted, cleared, at=calendar()[4].opens_at)
    assert final.account.cash == D("459.99")
    assert final.account.settlements == ()
    assert final.account.lots == original.account.lots[1:]
    assert final.entitlements == original.entitlements


def test_evidence_and_snapshots_are_stable_and_orders_are_traced():
    original, repeated = accrue(), accrue()
    assert original.evidence_hash == repeated.evidence_hash
    assert len(original.evidence_hash) == 64
    assert original.trace[-1].orders_before_hash == original.trace[-1].orders_after_hash
    assert (
        original.trace[-1].snapshot_owned_lots_hash
        == original.entitlements[0].snapshot_owned_lots_hash
    )
    changed = accrue(book(state=account(lots=(account().lots[0],))))
    assert changed.evidence_hash != original.evidence_hash
    assert (
        changed.entitlements[0].snapshot_owned_lots_hash
        != original.entitlements[0].snapshot_owned_lots_hash
    )


@pytest.mark.parametrize("rate", [True, 0.25, D("-.01"), D("1.01"), D("NaN"), D("Infinity")])
def test_invalid_tax_assumptions_fail_closed(rate):
    with pytest.raises(ValueError):
        book(tax_rate=rate)


def test_factory_revalidates_experimental_account_and_rejects_unpaused_state():
    with pytest.raises(ValueError):
        book(state=account(paused=False))
    invalid = account().model_copy(update={"cash": D(-1)})
    with pytest.raises(ValueError):
        book(state=invalid)


@pytest.mark.parametrize(
    "flag",
    ["qualified", "source_qualified", "investment_eligible", "trading_enabled", "live_authorized"],
)
def test_factory_only_book_and_frozen_false_flags_cannot_authorize_investments(flag):
    from trading_bot.research.stock_dividend_book import DividendBook

    value = accrue()
    assert getattr(value, flag) is False
    with pytest.raises((TypeError, ValueError)):
        replace(value, **{flag: True})
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        setattr(value, flag, True)
    with pytest.raises(TypeError):
        DividendBook()


def test_explicit_context_ignores_ambient_and_global_default_context():
    from trading_bot.research import stock_dividend_book as module

    old_default = DefaultContext.copy()
    try:
        ordinary = module.credit_due_dividends(
            accrue(native=event(cash_amount=D(".123456789123456789"))), at=calendar()[4].opens_at
        )
        DefaultContext.prec = 3
        DefaultContext.rounding = ROUND_DOWN
        DefaultContext.Emin, DefaultContext.Emax = -2, 2
        DefaultContext.clamp, DefaultContext.capitals = 1, 0
        DefaultContext.traps[Inexact] = True
        importlib.reload(module)
        with localcontext() as ctx:
            ctx.prec = 3
            ctx.rounding = ROUND_DOWN
            ctx.traps[Inexact] = True
            hostile = module.credit_due_dividends(
                accrue(native=event(cash_amount=D(".123456789123456789"))),
                at=calendar()[4].opens_at,
            )
        assert hostile.account == ordinary.account
        assert hostile.evidence_hash == ordinary.evidence_hash
        assert hostile.arithmetic_precision == 50
    finally:
        for name in ("prec", "rounding", "Emin", "Emax", "capitals", "clamp"):
            setattr(DefaultContext, name, getattr(old_default, name))
        DefaultContext.flags = old_default.flags.copy()
        DefaultContext.traps = old_default.traps.copy()
        importlib.reload(module)


@pytest.mark.parametrize("paid", [False, True])
def test_adoption_cannot_release_existing_tax_capital_even_above_dividend_floor(paid):
    from trading_bot.research.stock_dividend_book import (
        adopt_dividend_account,
        credit_due_dividends,
    )

    original = book()
    if paid:
        original = credit_due_dividends(accrue(original), at=calendar()[4].opens_at)
    proposed = Account.model_validate(
        original.account.model_dump() | {"tax_reserve": original.account.tax_reserve - D(1)}
    )
    assert proposed.tax_reserve >= original.dividend_tax_reserved
    with pytest.raises(ValueError):
        adopt_dividend_account(original, proposed, at=calendar()[5].closes_at)


def test_a_modeled_sell_fill_does_not_authorize_release_of_prior_tax_capital():
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = book()
    proposed = Account.model_validate(modeled_sale(original).model_dump() | {"tax_reserve": D(9)})
    with pytest.raises(ValueError):
        adopt_dividend_account(original, proposed, at=calendar()[3].closes_at)


@pytest.mark.parametrize("unrelated_sale", [False, True])
def test_active_buy_reservation_cannot_disappear_without_its_own_fill_or_cancellation(
    unrelated_sale,
):
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = book()
    state = modeled_sale(original) if unrelated_sale else original.account
    proposed = Account.model_validate(
        state.model_dump()
        | {
            "orders": (
                state.orders[0].model_copy(update={"reserved_cash": D(0)}),
                *state.orders[1:],
            )
        }
    )
    assert proposed.orders[0].status == "open"
    assert proposed.orders[0].filled == original.account.orders[0].filled == 0
    with pytest.raises(ValueError):
        adopt_dividend_account(original, proposed, at=calendar()[3].closes_at)


def test_unrelated_fill_cannot_supply_another_orders_filled_quantity_delta():
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = book()
    state = modeled_sale(original)
    forged_order = state.orders[0].model_copy(
        update={"filled": D(1), "status": "filled", "reserved_cash": D(0)}
    )
    proposed = Account.model_validate(
        state.model_dump() | {"orders": (forged_order, *state.orders[1:])}
    )
    with pytest.raises(ValueError):
        adopt_dividend_account(original, proposed, at=calendar()[3].closes_at)


@pytest.mark.parametrize("terminal", ["cancelled", "rejected"])
def test_terminal_no_fill_release_and_unchanged_tax_reserve_remain_supported(terminal):
    from trading_bot.hybrid.execution import cancel_order
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = book()
    changed = cancel_order(original.account, "pending")
    if terminal == "rejected":
        changed = Account.model_validate(
            changed.model_dump()
            | {
                "orders": (
                    changed.orders[0].model_copy(update={"status": terminal}),
                    *changed.orders[1:],
                )
            }
        )
    result = adopt_dividend_account(original, changed, at=calendar()[2].opens_at)
    assert result.account.orders[0].reserved_cash == 0
    assert result.account.tax_reserve == original.account.tax_reserve
    assert result.account.buying_power == original.account.buying_power + D(40)


def partial_exit_book():
    from trading_bot.config.hybrid import HybridSettings
    from trading_bot.hybrid.execution import fill_order

    episode = AllocationEpisode(
        id="owned-episode",
        symbol="AXP",
        sleeve="tactical",
        original_cash=D(1000),
        original_quantity=D(10),
    )
    threshold = "owned-episode:partial_first"
    state = Account(
        cash=D(100),
        lots=(
            Lot(
                id="owned-lot",
                symbol="AXP",
                sleeve="tactical",
                quantity=D(10),
                basis=D(1000),
                acquired_at=calendar()[0].opens_at,
                episode_id=episode.id,
            ),
        ),
        orders=(
            PaperOrder(
                id="rung-order",
                symbol="AXP",
                side="sell",
                sleeve="tactical",
                quantity=D("2.5"),
                threshold=threshold,
                episode_id=episode.id,
            ),
            PaperOrder(
                id="other-buy",
                symbol="BAC",
                side="buy",
                sleeve="long_term",
                quantity=D(1),
                reserved_cash=D(20),
            ),
        ),
        episodes=(episode,),
        exit_progress=(
            ExitProgress(threshold=threshold, symbol="AXP", sleeve="tactical", target=D("2.5")),
        ),
    )
    filled = fill_order(
        state,
        FillFact(
            id="first-rung-fill",
            order_id="rung-order",
            quantity=D(1),
            price=D(125),
            fee=D(0),
            at=calendar()[0].closes_at,
        ),
        HybridSettings(),
        settlement_at=calendar()[3].opens_at,
    )
    return book(state=filled)


@pytest.mark.parametrize(
    "change",
    [
        None,
        {"threshold": "replacement"},
        {"symbol": "BAC"},
        {"sleeve": "long_term"},
        {"target": D(3)},
        {"target": D(2)},
        {"filled": D(".5")},
        {"filled": D("1.5")},
    ],
)
def test_partial_exit_history_cannot_be_forgotten_rewritten_or_advanced_without_fill(change):
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = partial_exit_book()
    progress = original.account.exit_progress[0]
    proposed = Account.model_validate(
        original.account.model_dump()
        | {"exit_progress": () if change is None else (progress.model_copy(update=change),)}
    )
    with pytest.raises(ValueError):
        adopt_dividend_account(original, proposed, at=calendar()[2].opens_at)


def test_an_unrelated_buy_fill_cannot_erase_prior_exit_history():
    from trading_bot.config.hybrid import HybridSettings
    from trading_bot.hybrid.execution import fill_order
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = partial_exit_book()
    purchased = fill_order(
        original.account,
        FillFact(
            id="unrelated-buy",
            order_id="other-buy",
            quantity=D(1),
            price=D(20),
            fee=D(0),
            at=calendar()[3].opens_at,
        ),
        HybridSettings(),
    )
    proposed = Account.model_validate(purchased.model_dump() | {"exit_progress": ()})
    with pytest.raises(ValueError):
        adopt_dividend_account(original, proposed, at=calendar()[3].closes_at)


@pytest.mark.parametrize("quantity", [D(".5"), D("1.5")])
def test_owned_partial_and_full_exit_fills_advance_the_same_target(quantity):
    from trading_bot.config.hybrid import HybridSettings
    from trading_bot.hybrid.execution import fill_order
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = partial_exit_book()
    filled = fill_order(
        original.account,
        FillFact(
            id="next-rung-fill",
            order_id="rung-order",
            quantity=quantity,
            price=D(126),
            fee=D(".01"),
            at=calendar()[3].opens_at,
        ),
        HybridSettings(),
        settlement_at=calendar()[4].opens_at,
    )
    result = adopt_dividend_account(original, filled, at=calendar()[3].closes_at)
    assert result.account.exit_progress[0].target == D("2.5")
    assert result.account.exit_progress[0].filled == D(1) + quantity


def test_cancelled_partial_exit_retains_the_original_rung_remainder():
    from trading_bot.config.hybrid import HybridSettings
    from trading_bot.hybrid.execution import cancel_order
    from trading_bot.hybrid.exits import propose_exit
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = partial_exit_book()
    cancelled = cancel_order(original.account, "rung-order")
    result = adopt_dividend_account(original, cancelled, at=calendar()[2].opens_at)
    proposal = propose_exit(
        result.account, "owned-episode", "partial_first", D(125), D(125), HybridSettings()
    )
    assert proposal is not None and proposal.quantity == D("1.5")
    assert result.account.exit_progress == original.account.exit_progress


@pytest.mark.parametrize(
    "change",
    [
        None,
        {"id": "replacement"},
        {"symbol": "BAC"},
        {"sleeve": "long_term"},
        {"original_cash": D(999)},
        {"original_cash": D(2000)},
        {"original_quantity": D(9)},
        {"original_quantity": D(20)},
    ],
)
def test_original_allocation_episode_cannot_be_forgotten_or_rewritten_without_buy_fill(change):
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = partial_exit_book()
    episode = original.account.episodes[0]
    proposed = Account.model_validate(
        original.account.model_dump()
        | {"episodes": () if change is None else (episode.model_copy(update=change),)}
    )
    with pytest.raises(ValueError):
        adopt_dividend_account(original, proposed, at=calendar()[2].opens_at)


def test_no_fill_adoption_cannot_invent_an_allocation_episode():
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = book()
    extra = AllocationEpisode(
        id="invented", symbol="BAC", sleeve="long_term", original_cash=D(10), original_quantity=D(1)
    )
    proposed = Account.model_validate(original.account.model_dump() | {"episodes": (extra,)})
    with pytest.raises(ValueError):
        adopt_dividend_account(original, proposed, at=calendar()[2].opens_at)


def buy_episode_transition(count=2):
    from trading_bot.config.hybrid import HybridSettings
    from trading_bot.hybrid.execution import fill_order

    episode = AllocationEpisode(
        id="buy-episode",
        symbol="BAC",
        sleeve="long_term",
        original_cash=D(40),
        original_quantity=D(2),
    )
    state = Account(
        cash=D(100),
        lots=(
            Lot(
                id="prior-buy",
                symbol="BAC",
                sleeve="long_term",
                quantity=D(2),
                basis=D(40),
                acquired_at=calendar()[0].opens_at,
                episode_id=episode.id,
            ),
        ),
        orders=(
            PaperOrder(
                id="add-capital",
                symbol="BAC",
                side="buy",
                sleeve="long_term",
                quantity=D(2),
                reserved_cash=D(50),
                episode_id=episode.id,
            ),
        ),
        episodes=(episode,),
    )
    original = book(state=state)
    result = state
    fills = (("buy-one", D(20), D(".01")), ("buy-two", D(19), D(".02")))
    for identity, price, fee in fills[:count]:
        result = fill_order(
            result,
            FillFact(
                id=identity,
                order_id="add-capital",
                quantity=D(1),
                price=price,
                fee=fee,
                at=calendar()[3].opens_at,
            ),
            HybridSettings(),
        )
    return original, result


@pytest.mark.parametrize(
    "count,capital,quantity,reservation",
    [(1, D("60.01"), D(3), D("29.99")), (2, D("79.03"), D(4), D(0))],
)
def test_attributable_buy_fills_extend_original_capital_and_quantity_with_fees(
    count, capital, quantity, reservation
):
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original, purchased = buy_episode_transition(count)
    result = adopt_dividend_account(original, purchased, at=calendar()[3].closes_at)
    assert result.account.episodes[0].original_cash == capital
    assert result.account.episodes[0].original_quantity == quantity
    assert result.account.orders[0].reserved_cash == reservation
    assert result.account.tax_reserve == original.account.tax_reserve


@pytest.mark.parametrize("field,value", [("original_cash", D("79")), ("original_quantity", D(5))])
def test_buy_episode_additions_must_match_owned_fill_contributions_exactly(field, value):
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original, purchased = buy_episode_transition()
    proposed = Account.model_validate(
        purchased.model_dump()
        | {"episodes": (purchased.episodes[0].model_copy(update={field: value}),)}
    )
    with pytest.raises(ValueError):
        adopt_dividend_account(original, proposed, at=calendar()[3].closes_at)


def test_new_owned_buy_episode_preserves_other_original_contributions_and_rungs():
    from trading_bot.config.hybrid import HybridSettings
    from trading_bot.hybrid.execution import fill_order
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    original = partial_exit_book()
    purchased = fill_order(
        original.account,
        FillFact(
            id="separate-buy",
            order_id="other-buy",
            quantity=D(1),
            price=D(20),
            fee=D(0),
            at=calendar()[3].opens_at,
        ),
        HybridSettings(),
    )
    result = adopt_dividend_account(original, purchased, at=calendar()[3].closes_at)
    assert result.account.exit_progress == original.account.exit_progress
    assert result.account.episodes[0] == original.account.episodes[0]
    assert result.account.episodes[1].id == "other-buy"
    assert result.account.episodes[1].original_cash == D(20)
    assert result.account.episodes[1].original_quantity == D(1)


def test_buy_contribution_rounding_matches_owned_fill_cost_before_original_capital_addition():
    from trading_bot.config.hybrid import HybridSettings
    from trading_bot.hybrid.execution import fill_order
    from trading_bot.research.stock_dividend_book import adopt_dividend_account

    # An arithmetic boundary fixture, not an observed or eligible security price.
    episode = AllocationEpisode(
        id="rounding", symbol="BAC", sleeve="long_term", original_cash=D(1), original_quantity=D(1)
    )
    state = Account(
        cash=D(1),
        episodes=(episode,),
        orders=(
            PaperOrder(
                id="tiny-buy",
                symbol="BAC",
                side="buy",
                sleeve="long_term",
                quantity=D(".000001"),
                reserved_cash=D(1),
                episode_id=episode.id,
            ),
        ),
    )
    original = book(state=state)
    with localcontext() as context:
        context.prec = 50
        filled = fill_order(
            state,
            FillFact(
                id="tiny-fill",
                order_id="tiny-buy",
                quantity=D(".000001"),
                price=D("3e-44"),
                fee=D("3e-50"),
                at=calendar()[3].opens_at,
            ),
            HybridSettings(),
        )
    result = adopt_dividend_account(original, filled, at=calendar()[3].closes_at)
    assert result.account.episodes == filled.episodes
    assert result.account.episodes[0].original_cash > D(1)
