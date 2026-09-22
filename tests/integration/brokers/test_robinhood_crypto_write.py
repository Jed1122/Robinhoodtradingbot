import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from tests.unit.execution._fixtures import make_intent, make_review
from trading_bot.brokers.robinhood_crypto_api import (
    RobinhoodCryptoPlaceAdapter,
)
from trading_bot.brokers.robinhood_crypto_transport import RetryClass
from trading_bot.domain import ExecutionMode, LeaseId, OrderType, PersistedReviewedOrder


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class Transport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, object] | None, RetryClass]] = []

    async def request(self, method, path, *, query=(), json_body=None, retry_class):  # type: ignore[no-untyped-def]
        del query
        self.requests.append((method, path, json_body, retry_class))
        if path.endswith("cancel/"):
            return httpx.Response(200)
        payload = json.loads(Path("tests/fixtures/robinhood_crypto/orders.json").read_text())
        return httpx.Response(
            200,
            json=payload["results"][0],
            request=httpx.Request(method, f"https://example.invalid{path}"),
        )


def submission() -> PersistedReviewedOrder:
    intent = make_intent()
    review = make_review(intent)
    return PersistedReviewedOrder(
        "review",
        "attempt",
        review,
        "d" * 64,
        1,
        ExecutionMode.MICRO_LIVE,
        LeaseId("lease"),
        "e" * 64,
        intent.account_id,
        intent.config_hash,
    )


@pytest.mark.asyncio
async def test_limit_order_payload_uses_client_order_id() -> None:
    persisted = submission()
    transport = Transport()
    await RobinhoodCryptoPlaceAdapter(transport, Clock(persisted.review.reviewed_at)).place_order(
        persisted
    )
    method, _, payload, retry = transport.requests[0]
    assert method == "POST" and retry is RetryClass.WRITE_NEVER
    assert payload is not None
    assert payload["client_order_id"] == str(persisted.review.client_order_id)
    assert payload["type"] == "limit"
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_market_order_has_no_placement_path() -> None:
    persisted = submission()
    intent = replace(
        persisted.review.normalized_order,
        order_type=OrderType.MARKET,
        limit_price=None,
    )
    market = replace(persisted, review=make_review(intent))
    with pytest.raises(ValueError, match="market-order"):
        adapter = RobinhoodCryptoPlaceAdapter(Transport(), Clock(persisted.review.reviewed_at))
        await adapter.place_order(market)
