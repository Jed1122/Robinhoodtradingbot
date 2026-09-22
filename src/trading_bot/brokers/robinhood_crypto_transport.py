"""Exact-byte official Crypto v2 HTTP transport with read-only retries."""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from urllib.parse import urlencode

import httpx

from trading_bot.brokers.errors import BrokerSubmissionAmbiguous
from trading_bot.brokers.robinhood_crypto_auth import (
    CryptoCredentialProvider,
    sign_crypto_request,
)
from trading_bot.clock import Clock, require_utc
from trading_bot.domain import canonical_decimal_text

BASE_URL = "https://trading.robinhood.com"


class RetryClass(StrEnum):
    READ_SAFE = "read_safe"
    WRITE_NEVER = "write_never"


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    raise TypeError("request payload is not canonical JSON")


def _timestamp_seconds(value: datetime) -> int:
    delta = require_utc(value) - datetime(1970, 1, 1, tzinfo=UTC)
    return delta.days * 86400 + delta.seconds


class RobinhoodCryptoTransport:
    def __init__(
        self,
        client: httpx.AsyncClient,
        credentials: CryptoCredentialProvider,
        clock: Clock,
        *,
        read_attempts: int = 3,
        initial_backoff_seconds: Decimal = Decimal("0.25"),
        maximum_backoff_seconds: Decimal = Decimal("2"),
    ) -> None:
        if read_attempts < 1:
            raise ValueError("read attempts must be positive")
        self._client = client
        self._credentials = credentials
        self._clock = clock
        self._attempts = read_attempts
        self._initial_backoff = initial_backoff_seconds
        self._maximum_backoff = maximum_backoff_seconds

    async def request(
        self,
        method: str,
        path: str,
        *,
        query: tuple[tuple[str, str], ...] = (),
        json_body: dict[str, object] | None = None,
        retry_class: RetryClass,
    ) -> httpx.Response:
        normalized_method = method.upper()
        if normalized_method not in {"GET", "POST"}:
            raise ValueError("Crypto transport supports only GET and POST")
        if retry_class is RetryClass.WRITE_NEVER and normalized_method != "POST":
            raise ValueError("WRITE_NEVER is reserved for POST")
        if retry_class is RetryClass.READ_SAFE and normalized_method != "GET":
            raise ValueError("POST cannot use read retries")
        encoded_query = urlencode(sorted(query), doseq=True)
        path_with_query = path if not encoded_query else f"{path}?{encoded_query}"
        body = None
        if json_body is not None:
            body = json.dumps(
                json_body,
                default=_json_default,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        attempts = self._attempts if retry_class is RetryClass.READ_SAFE else 1
        credentials = self._credentials.load()
        for attempt in range(attempts):
            headers = sign_crypto_request(
                credentials=credentials,
                timestamp_seconds=_timestamp_seconds(self._clock.now()),
                method=normalized_method,  # type: ignore[arg-type]
                path_with_query=path_with_query,
                body=body,
            ).as_httpx()
            if body is not None:
                headers["content-type"] = "application/json"
            try:
                response = await self._client.request(
                    normalized_method,
                    f"{BASE_URL}{path_with_query}",
                    headers=headers,
                    content=body,
                )
            except (httpx.ConnectError, httpx.TimeoutException):
                if retry_class is RetryClass.WRITE_NEVER:
                    raise BrokerSubmissionAmbiguous() from None
                if attempt + 1 == attempts:
                    raise
            else:
                if response.status_code != 429 and response.status_code < 500:
                    return response
                if attempt + 1 == attempts:
                    return response
            delay = min(
                self._initial_backoff * (Decimal("2") ** attempt),
                self._maximum_backoff,
            )
            await asyncio.sleep(float(delay))
        raise AssertionError("Crypto retry loop exhausted without result")


__all__ = ["BASE_URL", "RetryClass", "RobinhoodCryptoTransport"]
