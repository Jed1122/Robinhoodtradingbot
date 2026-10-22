
import pytest

from trading_bot.brokers.errors import UnsupportedCapabilityError
from trading_bot.brokers.robinhood_prediction import (
    RobinhoodPredictionAdapter,
)


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
