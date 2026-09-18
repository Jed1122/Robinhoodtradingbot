"""Exact independent terminal-payoff expectations; no package execution claims."""

from dataclasses import replace
from decimal import Decimal

import pytest

from tests.unit.domain.test_options import contract, intent
from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.domain.enums import Side
from trading_bot.domain.options import (
    OptionKind,
    OptionLeg,
    OptionStructure,
    PositionEffect,
    StructureKind,
)
from trading_bot.research.options_payoffs import payoff_bounds, terminal_pnl

D = Decimal


def leg(strike: str, kind: OptionKind, side: Side) -> OptionLeg:
    c = contract(contract_id=f"synthetic-{kind}-{strike}", strike=D(strike), kind=kind)
    return OptionLeg(c, side, PositionEffect.OPEN, 1)


def structure(kind: StructureKind, option_kind: OptionKind = OptionKind.CALL) -> OptionStructure:
    if kind is StructureKind.IRON_CONDOR:
        return OptionStructure(
            kind,
            (
                leg("90", OptionKind.PUT, Side.BUY),
                leg("95", OptionKind.PUT, Side.SELL),
                leg("105", OptionKind.CALL, Side.SELL),
                leg("115", OptionKind.CALL, Side.BUY),
            ),
        )
    debit = kind is StructureKind.DEBIT_VERTICAL
    low_long = debit == (option_kind is OptionKind.CALL)
    return OptionStructure(
        kind,
        (
            leg("100", option_kind, Side.BUY if low_long else Side.SELL),
            leg("105", option_kind, Side.SELL if low_long else Side.BUY),
        ),
    )


def test_long_call_and_put_multiplier_fees_and_complete_units() -> None:
    call = replace(intent(), limit_price=D("2"), quantity=2)
    assert terminal_pnl(call, spot=D("110"), total_fees=D("4")) == D("1596")
    assert terminal_pnl(call, spot=D("90"), total_fees=D("4")) == D("-404")
    bounds = payoff_bounds(call, total_fees=D("4"))
    assert bounds.max_loss == D("404")
    assert bounds.max_profit is None
    put = replace(
        call,
        structure=OptionStructure(StructureKind.LONG_PUT, (leg("100", OptionKind.PUT, Side.BUY),)),
    )
    assert terminal_pnl(put, spot=D("0"), total_fees=D("4")) == D("19596")
    assert payoff_bounds(put, total_fees=D("4")).max_profit == D("19596")


@pytest.mark.parametrize("option_kind", list(OptionKind))
@pytest.mark.parametrize("kind", [StructureKind.DEBIT_VERTICAL, StructureKind.CREDIT_VERTICAL])
def test_vertical_bounds_are_exact_for_both_directions(
    kind: StructureKind, option_kind: OptionKind
) -> None:
    debit = kind is StructureKind.DEBIT_VERTICAL
    order = replace(
        intent(),
        structure=structure(kind, option_kind),
        limit_price=D("2"),
        net_effect="debit" if debit else "credit",
    )
    result = payoff_bounds(order, total_fees=D("2"))
    assert result.max_loss == (D("202") if debit else D("302"))
    assert result.max_profit == (D("298") if debit else D("198"))
    for spot in (D("0"), D("100"), D("102"), D("105"), D("1000000")):
        pnl = terminal_pnl(order, spot=spot, total_fees=D("2"))
        assert -result.max_loss <= pnl <= result.max_profit


def test_unequal_condor_wings_use_larger_tail_and_charge_costs_once() -> None:
    order = replace(
        intent(),
        structure=structure(StructureKind.IRON_CONDOR),
        limit_price=D("2"),
        net_effect="credit",
    )
    result = payoff_bounds(order, total_fees=D("4"))
    assert result.max_loss == D("804")
    assert result.max_profit == D("196")
    assert terminal_pnl(order, spot=D("0"), total_fees=D("4")) == D("-304")
    assert terminal_pnl(order, spot=D("100"), total_fees=D("4")) == D("196")
    assert terminal_pnl(order, spot=D("115"), total_fees=D("4")) == D("-804")


def test_closing_intents_and_invalid_costs_are_not_new_episodes() -> None:
    closing = replace(
        intent(),
        structure=OptionStructure(
            StructureKind.LONG_CALL, (OptionLeg(contract(), Side.SELL, PositionEffect.CLOSE, 1),)
        ),
        net_effect="credit",
    )
    with pytest.raises(DomainValidationError, match="opening"):
        payoff_bounds(closing, total_fees=D("0"))
    for invalid in (D("NaN"), D("-1"), 0.0):
        with pytest.raises(DomainValidationError):
            payoff_bounds(intent(), total_fees=invalid)
    with pytest.raises(DomainValidationError):
        terminal_pnl(intent(), spot=D("-1"), total_fees=D("0"))
