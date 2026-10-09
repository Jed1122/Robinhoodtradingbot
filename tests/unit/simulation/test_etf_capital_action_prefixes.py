"""Original action prefixes; only fabricated accounting inputs."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D
from decimal import localcontext

import pytest

from .test_etf_capital_account import script
from .test_etf_capital_action_account import action


def prefixes(events):
    from trading_bot.simulation.etf_capital_account import replay_capital_action_account_prefixes

    return replay_capital_action_account_prefixes(initial_cash=D("100"), events=events)


def test_split_prefix_preserves_literal_cash_basis_and_equity():
    values = prefixes((*script()[:5], action("split")))
    assert isinstance(values, tuple) and len(values) == 7
    assert (values[0].cash, values[0].quantity, values[0].marked_equity) == (
        D("100"), D("0"), D("100")
    )
    assert (values[-1].cash, values[-1].quantity, values[-1].average_price,
            values[-1].marked_equity) == (D("90.06"), D(".2"), D("49.5"), D("99.96"))
    assert values[-2].marked_equity is None
    assert all(not p.execution_enabled and not p.evidence_promotable and not p.source_qualified
               for p in values)
    with pytest.raises(FrozenInstanceError):
        values[-1].cash = D("999")


def test_entitlement_payment_preserves_nav_without_spendable_receivable():
    values = prefixes((*script()[:5], action(), action("payment", n=6)))
    assert (values[-2].cash, values[-2].distribution_receivable,
            values[-2].available_cash, values[-2].marked_equity) == (
        D("90.06"), D(".10"), D("90.00"), D("99.96")
    )
    assert (values[-1].cash, values[-1].distribution_receivable,
            values[-1].available_cash, values[-1].marked_equity) == (
        D("90.16"), D("0"), D("90.10"), D("99.96")
    )


def test_duplicates_align_with_raw_deliveries_and_preserve_final_identity():
    from trading_bot.simulation.etf_capital_account import replay_capital_action_account

    split = action("split")
    events = (*script()[:5], split, script()[2], split)
    values = prefixes(events)
    assert len(values) == len(events) + 1
    assert values[-3] == values[-2] == values[-1]
    assert values[-1] == replay_capital_action_account(initial_cash=D("100"), events=events)


def test_invalid_late_mark_cannot_return_valid_prefix_tuple():
    events = (*script()[:5], action("split", ratio=D("1e255"),
                                   post_action_mark=D("1e300")))
    with pytest.raises(ValueError, match="capital_account_invalid"):
        prefixes(events)


def test_conflicting_late_duplicate_denies_whole_call():
    split = action("split")
    with pytest.raises(ValueError, match="capital_account_invalid"):
        prefixes((*script()[:5], split, replace(split, ratio=D("4"))))


def test_action_prefixes_are_decimal_context_independent():
    events = (*script()[:5], action(), action("payment", n=6))
    expected = prefixes(events)
    with localcontext() as context:
        context.prec = 3
        assert prefixes(events) == expected
