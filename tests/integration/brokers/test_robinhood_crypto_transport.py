from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from tests.unit.brokers.test_robinhood_crypto_auth import credentials
from trading_bot.brokers import BrokerSubmissionAmbiguous
from trading_bot.brokers.robinhood_crypto_transport import RetryClass, RobinhoodCryptoTransport


class Credentials:
    def load(self):
        return credentials()


class Clock:
    def now(self) -> datetime:
        return datetime(2027, 1, 15, 8, tzinfo=UTC)


@pytest.mark.asyncio
async def test_transport_signs_and_sends_the_same_query_and_body_bytes() -> None:
    captured = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = RobinhoodCryptoTransport(client, Credentials(), Clock(), read_attempts=1)
        response = await transport.request(
            "POST",
            "/api/v2/crypto/trading/orders/",
            query=(("symbol", "BTC-USD"), ("account_number", "RHC1")),
            json_body={"quantity": Decimal("0.01")},
            retry_class=RetryClass.WRITE_NEVER,
        )
    assert response.status_code == 200
    assert captured[0].url.query == b"account_number=RHC1&symbol=BTC-USD"
    assert captured[0].content == b'{"quantity":"0.01"}'


@pytest.mark.asyncio
async def test_post_timeout_is_ambiguous_and_never_retried() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = RobinhoodCryptoTransport(client, Credentials(), Clock(), read_attempts=3)
        with pytest.raises(BrokerSubmissionAmbiguous):
            await transport.request(
                "POST", "/api/v2/crypto/trading/orders/", retry_class=RetryClass.WRITE_NEVER
            )
    assert calls == 1
