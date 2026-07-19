import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from trading_bot.domain import InstrumentId, TimestampSource
from trading_bot.market_data.robinhood_crypto_api import RobinhoodCryptoMarketData

NOW = datetime(2026, 7, 17, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


class Transport:
    def __init__(self) -> None:
        self.estimated_price_sides: list[str] = []

    async def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        query = dict(kwargs.get("query", ()))
        if path.endswith("best_bid_ask/"):
            payload = {
                "next": None,
                "previous": None,
                "results": [
                    {
                        "symbol": "BTC-USD",
                        "bid_inclusive_of_sell_spread": "49999",
                        "ask_inclusive_of_buy_spread": "50001",
                    }
                ],
            }
        else:
            side = query["side"]
            self.estimated_price_sides.append(side)
            payload = {
                "next": None,
                "previous": None,
                "results": [
                    {
                        "symbol": "BTC-USD",
                        "side": side,
                        "quantity": query["quantity"],
                        "estimated_price": "49999" if side == "sell" else "50001",
                        "timestamp": "2026-07-17T00:00:00Z",
                    }
                ],
            }
        return httpx.Response(
            200,
            content=json.dumps(payload).encode(),
            request=httpx.Request(method, f"https://trading.robinhood.com{path}"),
        )


@pytest.mark.asyncio
async def test_best_bid_ask_cannot_satisfy_executable_freshness() -> None:
    quote = await RobinhoodCryptoMarketData(Transport(), Clock()).get_quote(InstrumentId("BTC-USD"))
    assert not quote.freshness_verified


@pytest.mark.asyncio
async def test_executable_quote_uses_two_timestamped_estimates() -> None:
    transport = Transport()
    provider = RobinhoodCryptoMarketData(transport, Clock())
    quote = await provider.get_executable_quote(InstrumentId("BTC-USD"), Decimal("0.001"))
    assert quote.source == "robinhood_crypto_estimated_price_pair"
    assert quote.freshness_verified and quote.timestamp_source is TimestampSource.PROVIDER
    assert transport.estimated_price_sides == ["sell", "buy"]
