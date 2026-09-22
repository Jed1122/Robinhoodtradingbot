from decimal import Decimal

import pytest

from trading_bot.brokers.errors import UnsupportedCapabilityError
from trading_bot.brokers.robinhood_prediction import (
    PREDICTION_LIVE_ENABLED,
    RobinhoodPredictionAdapter,
)


def test_prediction_fixture_normalization_is_available() -> None:
    adapter = RobinhoodPredictionAdapter()
    quote = adapter.normalize_quote(
        {"contract_id": "rain", "yes_price": "0.31", "no_price": "0.69"}
    )
    assert quote.yes_price == Decimal("0.31")
    assert not PREDICTION_LIVE_ENABLED


@pytest.mark.asyncio
async def test_prediction_live_place_always_fails() -> None:
    adapter = RobinhoodPredictionAdapter()
    with pytest.raises(UnsupportedCapabilityError, match="not verified"):
        await adapter.place_order(object())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["review", "cancel"])
async def test_every_prediction_live_operation_fails(operation: str) -> None:
    adapter = RobinhoodPredictionAdapter()
    with pytest.raises(UnsupportedCapabilityError):
        if operation == "review":
            await adapter.review_order(object())
        else:
            await adapter.cancel_known_order(object(), object())
