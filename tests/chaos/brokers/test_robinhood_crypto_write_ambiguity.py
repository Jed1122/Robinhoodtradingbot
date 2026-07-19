import pytest

from trading_bot.brokers.errors import BrokerCancellationAmbiguous
from trading_bot.brokers.robinhood_crypto_api import RobinhoodCryptoCancelAdapter
from trading_bot.domain import AccountId, BrokerOrderId


class FailingTransport:
    calls = 0

    async def request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise TimeoutError


@pytest.mark.asyncio
async def test_cancel_timeout_is_ambiguous_not_retried() -> None:
    transport = FailingTransport()
    adapter = RobinhoodCryptoCancelAdapter(transport, None)  # type: ignore[arg-type]
    with pytest.raises(BrokerCancellationAmbiguous):
        await adapter.cancel_known_order(AccountId("account"), BrokerOrderId("order"))
    assert transport.calls == 1
