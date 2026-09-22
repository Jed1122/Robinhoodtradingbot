"""Synthetic account observations; no provider data or credentials."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.domain.test_options import NOW, contract
from trading_bot.domain import AccountId, OrderState, Side
from trading_bot.domain.options import OptionLeg, OptionStructure, PositionEffect, StructureKind
from trading_bot.domain.options_account import (
    ObservedOptionFill,
    ObservedOptionLeg,
    ObservedOptionOrder,
    ObservedOptionPosition,
    OptionsAccountSnapshot,
    OptionsCash,
    OptionsSnapshotSection,
    OwnedOptionPosition,
)

D = Decimal
ACCOUNT = AccountId("synthetic-research")


@pytest.fixture(autouse=True)
def offline_observation_boundary(monkeypatch):
    import socket

    def deny(*args, **kwargs):
        raise AssertionError("network is forbidden in offline options observation tests")

    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)


def order(**changes: object) -> ObservedOptionOrder:
    return replace(
        ObservedOptionOrder(
            "order-1",
            (ObservedOptionLeg(contract().contract_id, Side.BUY, PositionEffect.OPEN, 1),),
            1,
            1,
            D("0.25"),
            "debit",
            OrderState.FILLED,
            NOW - timedelta(seconds=2),
            NOW,
        ),
        **changes,
    )


def fill(**changes: object) -> ObservedOptionFill:
    return replace(
        ObservedOptionFill(
            "fill-1",
            "order-1",
            contract().contract_id,
            Side.BUY,
            PositionEffect.OPEN,
            1,
            D("0.25"),
            D("0.10"),
            NOW,
        ),
        **changes,
    )


def owned(**changes: object) -> OwnedOptionPosition:
    return replace(
        OwnedOptionPosition(
            "strategy-1",
            OptionStructure(
                StructureKind.LONG_CALL, (OptionLeg(contract(), Side.BUY, PositionEffect.OPEN, 1),)
            ),
            1,
        ),
        **changes,
    )


def snapshot(**changes: object) -> OptionsAccountSnapshot:
    return replace(
        OptionsAccountSnapshot(
            ACCOUNT,
            NOW - timedelta(days=1),
            NOW,
            "a" * 64,
            tuple(OptionsSnapshotSection),
            OptionsCash(D("99.90"), D("74.90"), D("74.90"), D("0"), D("0"), D("0"), D("0")),
            (contract(),),
            (ObservedOptionPosition(contract().contract_id, 1, D("25"), D("0.25"), 0, 0, 0),),
            (order(),),
            (fill(),),
            (),
            (),
            (),
        ),
        **changes,
    )
