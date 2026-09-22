from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from trading_bot.brokers.robinhood_crypto_api import RobinhoodCryptoReadAdapter
from trading_bot.domain import AccountId, AssetClass

FIXTURES = Path(__file__).parents[2] / "fixtures/robinhood_crypto"
NOW = datetime(2026, 7, 17, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


class Transport:
    async def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        fixture = "accounts.json" if path.endswith("accounts/") else "holdings.json"
        return httpx.Response(
            200,
            content=(FIXTURES / fixture).read_bytes(),
            request=httpx.Request(method, f"https://trading.robinhood.com{path}"),
        )


@pytest.mark.asyncio
async def test_crypto_buying_power_is_not_equity_margin() -> None:
    adapter = RobinhoodCryptoReadAdapter(
        Transport(),
        Clock(),
        reconciled_equity={AccountId("RHC0001"): Decimal("100")},
        mark_prices={"BTC-USD": Decimal("50000")},
    )
    account = await adapter.get_account_state(AccountId("RHC0001"))
    assert account.buying_power_for(AssetClass.CRYPTO) == Decimal("100.00")
    assert account.equity == Decimal("100")


@pytest.mark.asyncio
async def test_holdings_use_explicit_mark_price() -> None:
    adapter = RobinhoodCryptoReadAdapter(
        Transport(),
        Clock(),
        reconciled_equity={AccountId("RHC0001"): Decimal("100")},
        mark_prices={"BTC-USD": Decimal("50000")},
    )
    positions = await adapter.get_positions(AccountId("RHC0001"))
    assert positions[0].market_value == Decimal("500")
