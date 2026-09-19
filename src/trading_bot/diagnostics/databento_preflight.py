"""Private credentials and a free, cost-estimate-only Databento diagnostic.

No time-series, batch, live-data, account-management or broker API is exposed.
This standalone diagnostic is not wired into any trading runtime or scheduler.
"""

import asyncio
import base64
import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import httpx

from trading_bot.clock import Clock, require_utc
from trading_bot.diagnostics.alpaca_probe import _quiet_http_logging
from trading_bot.logging import SecretRegistry
from trading_bot.market_data.bundle_models import BundleError
from trading_bot.market_data.bundle_store import (
    _directory_flags,
    _open_root,
    _publish,
    _read_descriptor,
)

_COST_URL = "https://hist.databento.com/v0/metadata.get_cost"
_KEY_FILE = "databento.key"
_KEY_PATTERN = re.compile(r"db-[A-Za-z0-9]{29}")
_ERRORS = frozenset(
    {
        "credential_invalid",
        "credential_storage_failed",
        "scope_invalid",
        "metadata_network_not_authorized",
        "access_denied",
        "rate_limited",
        "http_failed",
        "response_invalid",
        "timeout",
        "terminal_required",
        "credential_confirmation_mismatch",
        "command_invalid",
    }
)


class DatabentoPreflightError(ValueError):
    """Only fixed reason codes cross the credential/HTTP boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code if type(code) is str and code in _ERRORS else "command_invalid")


@dataclass(frozen=True, slots=True)
class DatabentoCredential:
    api_key: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.api_key) is not str or _KEY_PATTERN.fullmatch(self.api_key) is None:
            raise DatabentoPreflightError("credential_invalid")
        registry = SecretRegistry()
        registry.register(self.api_key)
        registry.register(base64.b64encode((self.api_key + ":").encode()).decode())


def _credential_directory(directory: Path, repository_root: Path) -> int:
    """Reuse private traversal, then reject all Git-marked descriptor ancestors.

    A linked worktree's ROOT alone does not cover its main or sibling checkouts.
    Check directory identities up to filesystem root without following symlinks.
    """
    root = _open_root(directory, repository_root)
    try:
        cursor = os.dup(root)
        try:
            while True:
                try:
                    os.stat(".git", dir_fd=cursor, follow_symlinks=False)
                except FileNotFoundError:
                    parent = os.open("..", _directory_flags(), dir_fd=cursor)
                else:
                    raise DatabentoPreflightError("credential_invalid")
                old, new = os.fstat(cursor), os.fstat(parent)
                os.close(cursor)
                cursor = parent
                if (old.st_dev, old.st_ino) == (new.st_dev, new.st_ino):
                    break
        finally:
            os.close(cursor)
    except BaseException:
        os.close(root)
        raise
    return root


def _key_bytes(parent: int) -> bytes:
    descriptor = os.open(_KEY_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        if os.fstat(descriptor).st_nlink != 1:
            raise DatabentoPreflightError("credential_invalid")
        return _read_descriptor(descriptor, 32)
    finally:
        os.close(descriptor)


def save_credential(
    directory: Path, credential: DatabentoCredential, *, repository_root: Path
) -> None:
    """Publish in an existing private directory outside the project; never overwrite."""
    if type(credential) is not DatabentoCredential:
        raise DatabentoPreflightError("credential_invalid")
    try:
        descriptor = _credential_directory(directory, repository_root)
        try:
            _publish(descriptor, _KEY_FILE, credential.api_key.encode("ascii"))
            if _key_bytes(descriptor) != credential.api_key.encode("ascii"):
                raise DatabentoPreflightError("credential_storage_failed")
        finally:
            os.close(descriptor)
        return
    except (BundleError, OSError, ValueError):
        pass
    raise DatabentoPreflightError("credential_storage_failed")


def load_credential(directory: Path, *, repository_root: Path) -> DatabentoCredential:
    """Open only the explicitly selected file, without following links or scanning stores."""
    try:
        parent = _credential_directory(directory, repository_root)
        try:
            body = _key_bytes(parent)
        finally:
            os.close(parent)
        return DatabentoCredential(body.decode("ascii"))
    except (BundleError, OSError, ValueError, UnicodeError):
        pass
    raise DatabentoPreflightError("credential_invalid")


@dataclass(frozen=True, slots=True)
class CostRequest:
    symbols: tuple[str, ...]
    schema: Literal["definition", "cbbo-1m"]
    start: date
    end: date

    def __post_init__(self) -> None:
        if (
            type(self.symbols) is not tuple
            or not 1 <= len(self.symbols) <= 4
            or any(
                type(s) is not str or re.fullmatch(r"[A-Z]{1,6}", s) is None for s in self.symbols
            )
            or len(set(self.symbols)) != len(self.symbols)
            or type(self.schema) is not str
            or self.schema not in ("definition", "cbbo-1m")
            or type(self.start) is not date
            or type(self.end) is not date
            or self.end <= self.start
        ):
            raise DatabentoPreflightError("scope_invalid")

    def query(self) -> dict[str, str]:
        return {
            "dataset": "OPRA.PILLAR",
            "symbols": ",".join(symbol + ".OPT" for symbol in self.symbols),
            "stype_in": "parent",
            "schema": self.schema,
            # UTC day boundaries give whole 24-hour ranges for definition estimates.
            "start": datetime.combine(self.start, datetime.min.time(), UTC).isoformat(),
            "end": datetime.combine(self.end, datetime.min.time(), UTC).isoformat(),
        }


@dataclass(frozen=True, slots=True)
class CostEstimate:
    request: CostRequest
    cost_usd: Decimal
    quoted_at: datetime
    download_authorized: Literal[False] = field(default=False, init=False)
    economic_evidence: Literal[False] = field(default=False, init=False)


def _parse_cost(body: bytes) -> Decimal:
    if len(body) > 512:
        raise DatabentoPreflightError("response_invalid")
    try:
        value = json.loads(body, parse_float=Decimal, parse_int=Decimal)
        if type(value) is Decimal and value.is_finite() and 0 <= value <= Decimal("1e12"):
            return value
    except (ValueError, UnicodeError, ArithmeticError, RecursionError):
        pass
    raise DatabentoPreflightError("response_invalid")


async def _fetch_cost(request: CostRequest, credential: DatabentoCredential) -> Decimal:
    transport = httpx.AsyncHTTPTransport(verify=True, trust_env=False, retries=0)
    async with (
        httpx.AsyncClient(
            transport=transport,
            verify=True,
            trust_env=False,
            follow_redirects=False,
            timeout=10.0,
            auth=httpx.BasicAuth(credential.api_key, ""),
        ) as client,
        client.stream(
            "GET",
            _COST_URL,
            params=request.query(),
            headers={"Accept": "application/json", "Accept-Encoding": "identity"},
        ) as response,
    ):
        if response.status_code in (401, 403):
            raise DatabentoPreflightError("access_denied")
        if response.status_code == 429:
            raise DatabentoPreflightError("rate_limited")
        if response.status_code != 200:
            raise DatabentoPreflightError("http_failed")
        if (
            response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
            or response.headers.get("content-encoding", "identity").lower() != "identity"
        ):
            raise DatabentoPreflightError("response_invalid")
        body = bytearray()
        async for piece in response.aiter_bytes(chunk_size=513):
            body.extend(piece)
            if len(body) > 512:
                raise DatabentoPreflightError("response_invalid")
        return _parse_cost(bytes(body))


async def estimate_cost(
    request: CostRequest,
    credential: DatabentoCredential,
    *,
    clock: Clock,
    allow_metadata_network: bool = False,
) -> CostEstimate:
    """One free GET, no retries/redirects/proxies; success is not download entitlement."""
    if allow_metadata_network is not True:
        raise DatabentoPreflightError("metadata_network_not_authorized")
    if type(request) is not CostRequest or type(credential) is not DatabentoCredential:
        raise DatabentoPreflightError("scope_invalid")
    reason = "http_failed"
    try:
        started = require_utc(clock.now())
        if request.end > started.date():
            raise DatabentoPreflightError("scope_invalid")
        with _quiet_http_logging():
            async with asyncio.timeout(30):
                cost = await _fetch_cost(request, credential)
        completed = require_utc(clock.now())
        if completed < started:
            raise DatabentoPreflightError("scope_invalid")
        return CostEstimate(request, cost, completed)
    except DatabentoPreflightError as error:
        reason = str(error)
    except (TimeoutError, httpx.TimeoutException):
        reason = "timeout"
    except Exception:
        reason = "http_failed"
    # Deliberately outside handlers: provider exception chains never escape.
    raise DatabentoPreflightError(reason)
