from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.config.hybrid import HybridSettings
from trading_bot.hybrid.models import Account
from trading_bot.hybrid.scenario import Scenario, replay

NOW = datetime(2026, 10, 21, 14, tzinfo=UTC)


async def test_scenario_flows_through_reservation_fill_and_recovery():
    scenario = Scenario.model_validate(
        {
            "steps": [
                {
                    "kind": "quote",
                    "at": NOW,
                    "quote": {
                        "symbol": "XYZ",
                        "bid": "10",
                        "ask": "10.01",
                        "as_of": NOW,
                        "tradable": True,
                        "fractional": True,
                        "regular_session": True,
                        "halted": False,
                        "average_dollar_volume": "50000000",
                        "sector": "Technology",
                        "earnings_clear": True,
                    },
                },
                {
                    "kind": "order",
                    "at": NOW,
                    "order": {
                        "id": "o",
                        "symbol": "XYZ",
                        "side": "buy",
                        "sleeve": "tactical",
                        "quantity": "3",
                        "risk_stop": "9",
                    },
                },
                {
                    "kind": "fill",
                    "at": NOW,
                    "fill": {
                        "id": "f",
                        "order_id": "o",
                        "quantity": "1",
                        "price": "10.01",
                        "fee": "0.01",
                        "at": NOW,
                    },
                },
                {"kind": "cancel", "at": NOW, "order_id": "o"},
            ]
        }
    )
    result = await replay(scenario, HybridSettings(), Account(paused=False))
    assert result.cash == Decimal("989.98")
    assert result.reserved_cash == 0
    assert result.orders[0].status == "cancelled"
    assert result.lots[0].quantity == 1


def test_scenario_rejects_time_travel():
    with pytest.raises(ValueError):
        Scenario.model_validate(
            {
                "steps": [
                    {"kind": "settle", "at": NOW},
                    {"kind": "settle", "at": NOW - timedelta(days=1)},
                ]
            }
        )


async def test_restored_multi_symbol_quotes_are_valued_as_one_complete_snapshot():
    from trading_bot.hybrid.models import Lot

    initial = Account(
        cash=Decimal("800"),
        lots=tuple(
            Lot(
                id=symbol,
                symbol=symbol,
                sleeve="long_term",
                quantity=Decimal(1),
                basis=Decimal(100),
                acquired_at=NOW - timedelta(days=1),
            )
            for symbol in ("AAA", "BBB")
        ),
    )
    scenario = Scenario.model_validate(
        {
            "steps": [
                {
                    "kind": "quote",
                    "at": NOW,
                    "quote": {
                        "symbol": symbol,
                        "bid": price,
                        "ask": price,
                        "as_of": NOW,
                    },
                }
                for symbol, price in (("AAA", "110"), ("BBB", "120"))
            ]
        }
    )
    result = await replay(scenario, HybridSettings(), initial)
    assert result.last_equity == Decimal("1030")
    assert {mark.symbol for mark in result.marks} == {"AAA", "BBB"}


async def test_conflicting_same_time_quote_batch_rejects_without_valuation():
    scenario = Scenario.model_validate(
        {
            "steps": [
                {
                    "kind": "quote",
                    "at": NOW,
                    "quote": {
                        "symbol": "AAA",
                        "bid": price,
                        "ask": price,
                        "as_of": NOW,
                    },
                }
                for price in ("110", "120")
            ]
        }
    )
    with pytest.raises(ValueError, match="conflicting simultaneous"):
        await replay(scenario, HybridSettings(), Account())
