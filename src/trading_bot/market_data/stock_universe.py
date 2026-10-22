"""Bounded public current-listing observations; no historical or investment authority."""

import hashlib
import json
import math
import os
import re
import stat
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx

SOURCE_URLS = (
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
)
_HEADERS = (
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|"
    "ETF|NextShares",
    "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol",
)
_MAX_BYTES = 2_000_000
_MAX_ROWS = 30_000
SecurityKind = Literal[
    "common_stock", "adr", "preferred", "warrant", "right", "unit", "fund", "ambiguous"
]
_LIMITATIONS = (
    "current_listing_snapshot_not_historical_universe",
    "listing_names_are_not_permanent_security_identifiers",
    "classification_uses_listing_name_heuristics",
    "us_listing_does_not_establish_issuer_domicile",
    "source_footer_timezone_unspecified",
    "provider_omissions_and_completeness_unverified",
    "no_prices_liquidity_broker_eligibility_or_investment_selection",
    "source_terms_and_historical_availability_unqualified",
)


def _check(condition: bool) -> None:
    if not condition:
        raise ValueError("stock_universe_invalid")


def _utc(value: datetime) -> None:
    _check(type(value) is datetime and value.tzinfo is UTC)


def _hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _kind(name: str) -> SecurityKind:
    # Non-ETF funds can issue instruments literally called "Common Stock".
    if re.search(r"\bfund\b", name, re.IGNORECASE):
        return "fund"
    description = name.partition(" - ")[2] or name
    # Derivative descriptions can mention common/ordinary shares they represent.
    for pattern, kind in (
        (r"\b(preferred|preference|depositary preference)\b", "preferred"),
        (r"\bwarrants?\b", "warrant"),
        (r"\brights?\b", "right"),
        (r"\bunits?\b", "unit"),
        (r"\bamerican depos(?:it[ao]ry|itory) (?:shares|receipts)\b|\bAD[RS]s?\b", "adr"),
        (r"\b(?:common|ordinary) (?:stock|shares?)\b", "common_stock"),
    ):
        if re.search(pattern, description, re.IGNORECASE):
            # Literal branches retain a finite type rather than trusting source labels.
            if kind == "preferred":
                return "preferred"
            if kind == "warrant":
                return "warrant"
            if kind == "right":
                return "right"
            if kind == "unit":
                return "unit"
            if kind == "adr":
                return "adr"
            return "common_stock"
    return "ambiguous"


@dataclass(frozen=True, slots=True)
class StockListing:
    symbol: str
    security_name: str
    listing_exchange: str
    source_url: str
    security_kind: SecurityKind
    classification_uncertain: bool
    research_eligible: bool
    ineligible_reasons: tuple[str, ...]
    classification_method: Literal["listing_name_heuristic_v1"] = field(
        default="listing_name_heuristic_v1", init=False
    )
    permanent_security_id: None = field(default=None, init=False)
    issuer_domicile: None = field(default=None, init=False)
    us_listed: Literal[True] = field(default=True, init=False)

    def __post_init__(self) -> None:
        _check(type(self.symbol) is str and type(self.security_name) is str)
        _check(type(self.listing_exchange) is str and type(self.source_url) is str)
        _check(type(self.security_kind) is str and self.security_kind == _kind(self.security_name))
        _check(type(self.classification_uncertain) is bool and type(self.research_eligible) is bool)
        _check(
            type(self.ineligible_reasons) is tuple
            and all(type(item) is str for item in self.ineligible_reasons)
        )
        _check(
            self.permanent_security_id is None
            and self.issuer_domicile is None
            and self.us_listed is True
        )
        _check(self.classification_method == "listing_name_heuristic_v1")


@dataclass(frozen=True, slots=True, repr=False)
class ListingSource:
    url: str
    body: bytes
    body_sha256: str
    received_at: datetime
    creation_footer: str
    declared_timestamp: datetime
    record_count: int
    declared_timezone: None = field(default=None, init=False)


def _parse(
    body: bytes, index: int, received_at: datetime
) -> tuple[ListingSource, tuple[StockListing, ...]]:
    _utc(received_at)
    _check(type(body) is bytes and 0 < len(body) <= _MAX_BYTES and body.endswith(b"\n"))
    try:
        text = body.decode("utf-8")
    except UnicodeError:
        raise ValueError("stock_universe_invalid") from None
    _check(all(ord(char) >= 32 or char in "\r\n" for char in text))
    lines = text.splitlines()
    _check(3 <= len(lines) <= _MAX_ROWS + 2 and lines[0] == _HEADERS[index])
    # Nasdaq's otherlisted footer has seven fields although its header has eight.
    suffix = "|" * (7 if index == 0 else 6)
    match = re.fullmatch(r"File Creation Time: ([0-9]{10}:[0-9]{2})" + re.escape(suffix), lines[-1])
    _check(match is not None)
    if match is None:
        raise ValueError("stock_universe_invalid")
    try:
        declared = datetime.strptime(match[1], "%m%d%Y%H:%M")
    except ValueError:
        raise ValueError("stock_universe_invalid") from None
    records: list[StockListing] = []
    seen: set[str] = set()
    for line in lines[1:-1]:
        row = line.split("|")
        _check(len(row) == 8)
        symbol, name = row[0], row[1].strip()
        _check(re.fullmatch(r"[A-Z0-9][A-Z0-9.$+^=/@_-]{0,31}", symbol) is not None)
        _check(symbol not in seen and 0 < len(name) <= 1024)
        seen.add(symbol)
        if index == 0:
            exchange, test, financial, lot, etf, nextshares = row[2:]
            _check(
                exchange in ("Q", "G", "S")
                and financial in ("N", "D", "E", "Q", "G", "H", "J", "K")
            )
        else:
            exchange, cqs, etf, lot, test, nasdaq = row[2:]
            _check(bool(cqs) and bool(nasdaq) and re.fullmatch(r"[A-Z]", exchange) is not None)
            financial, nextshares = "N", "N"
        _check(test in ("Y", "N") and etf in ("Y", "N") and nextshares in ("Y", "N"))
        _check(re.fullmatch(r"[0-9]{1,6}", lot) is not None and int(lot) > 0)
        kind = _kind(name)
        reasons = []
        for excluded, reason in (
            (test == "Y", "test_issue"),
            (etf == "Y", "etf"),
            (nextshares == "Y", "nextshares"),
            (financial != "N", "financial_status_not_normal"),
            (index == 1 and exchange not in ("A", "N", "P", "Z", "V"), "unknown_listing_exchange"),
            (kind not in ("common_stock", "adr"), "security_type_" + kind),
        ):
            if excluded:
                reasons.append(reason)
        records.append(
            StockListing(
                symbol,
                name,
                exchange,
                SOURCE_URLS[index],
                kind,
                kind == "ambiguous",
                not reasons,
                tuple(reasons),
            )
        )
    source = ListingSource(
        SOURCE_URLS[index], body, _hash(body), received_at, lines[-1], declared, len(records)
    )
    return source, tuple(records)


@dataclass(frozen=True, slots=True, repr=False)
class StockUniverseSnapshot:
    captured_at: datetime
    sources: tuple[ListingSource, ListingSource]
    records: tuple[StockListing, ...]
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)

    def __post_init__(self) -> None:
        _utc(self.captured_at)
        _check(type(self.sources) is tuple and len(self.sources) == 2)
        expected: list[StockListing] = []
        for index, source in enumerate(self.sources):
            _check(type(source) is ListingSource)
            _check(type(source.record_count) is int)
            parsed, rows = _parse(source.body, index, source.received_at)
            _check(source == parsed and source.received_at <= self.captured_at)
            expected.extend(rows)
        _check(len({row.symbol for row in expected}) == len(expected))
        _check(type(self.records) is tuple)
        for row in self.records:
            _check(type(row) is StockListing)
            row.__post_init__()
        _check(
            type(self.records) is tuple
            and self.records == tuple(sorted(expected, key=lambda row: row.symbol))
        )
        _check(
            self.source_qualified is False
            and self.strategy_qualified is False
            and self.live_authorized is False
        )
        _check(self.limitations == _LIMITATIONS)

    @property
    def available_at(self) -> datetime:
        return self.captured_at

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def snapshot_hash(self) -> str:
        self.__post_init__()
        return _hash(_json(_identity(self)))


def _identity(snapshot: StockUniverseSnapshot) -> dict[str, object]:
    return {
        "schema": "current-stock-universe-v1",
        "classification_method": "listing_name_heuristic_v1",
        "captured_at": snapshot.captured_at.isoformat(),
        "available_at": snapshot.available_at.isoformat(),
        "record_count": snapshot.record_count,
        "sources": [
            {
                "url": source.url,
                "body_sha256": source.body_sha256,
                "received_at": source.received_at.isoformat(),
                "creation_footer": source.creation_footer,
                "declared_timestamp": source.declared_timestamp.isoformat(),
                "declared_timezone": None,
                "record_count": source.record_count,
            }
            for source in snapshot.sources
        ],
        "limitations": snapshot.limitations,
        "source_qualified": False,
        "strategy_qualified": False,
        "live_authorized": False,
    }


def _assemble(sources: tuple[ListingSource, ListingSource]) -> StockUniverseSnapshot:
    rows = tuple(
        row
        for index, source in enumerate(sources)
        for row in _parse(source.body, index, source.received_at)[1]
    )
    return StockUniverseSnapshot(
        max(source.received_at for source in sources),
        sources,
        tuple(sorted(rows, key=lambda row: row.symbol)),
    )


def parse_stock_universe(
    nasdaq_body: bytes, other_body: bytes, *, captured_at: datetime
) -> StockUniverseSnapshot:
    """Parse caller-supplied originals at a declared receipt clock; performs no I/O."""
    return _assemble(
        (_parse(nasdaq_body, 0, captured_at)[0], _parse(other_body, 1, captured_at)[0])
    )


class NasdaqStockUniverseFetcher:
    """Injected transport only; fixed HTTPS sources, one request/second, no retries.

    Callers sharing several instances/processes must impose an aggregate limiter.
    No environment proxy, default network transport or credential input is used.
    """

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport,
        user_agent: str,
        max_bytes: int = _MAX_BYTES,
        timeout_seconds: float = 10.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        _check(isinstance(transport, httpx.BaseTransport))
        _check(
            type(user_agent) is str
            and re.fullmatch(
                r"[A-Za-z][A-Za-z0-9._-]{1,63}/[A-Za-z0-9._-]{1,32}(?: \([\x20-\x7e]{1,120}\))?",
                user_agent,
            )
            is not None
        )
        _check(type(max_bytes) is int and 1 <= max_bytes <= _MAX_BYTES)
        _check(
            type(timeout_seconds) in (int, float)
            and math.isfinite(timeout_seconds)
            and 0 < timeout_seconds <= 30
        )
        self._client = httpx.Client(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=timeout_seconds,
            headers={"User-Agent": user_agent, "Accept-Encoding": "identity"},
        )
        self._clock, self._monotonic, self._sleep = clock, monotonic, sleep
        self._max_bytes, self._last_request = max_bytes, float("-inf")
        self._timeout_seconds = timeout_seconds
        self._lock = threading.Lock()

    def __enter__(self) -> "NasdaqStockUniverseFetcher":
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def capture(self) -> StockUniverseSnapshot:
        try:
            with self._lock:
                sources: list[ListingSource] = []
                for index, url in enumerate(SOURCE_URLS):
                    now = self._monotonic()
                    _check(math.isfinite(now))
                    delay = max(0.0, 1.0 - (now - self._last_request))
                    _check(delay <= 1.0)
                    if delay:
                        self._sleep(delay)
                    now = self._monotonic()
                    _check(math.isfinite(now) and now - self._last_request >= 1.0)
                    self._last_request = now
                    with self._client.stream("GET", url) as response:
                        _check(self._monotonic() - now <= self._timeout_seconds)
                        _check(response.status_code == 200)
                        _check(
                            response.headers.get("content-encoding", "identity").lower()
                            == "identity"
                        )
                        _check(
                            response.headers.get("content-type", "").split(";")[0].lower()
                            == "text/plain"
                        )
                        length = response.headers.get("content-length")
                        if length is not None:
                            _check(length.isdecimal() and int(length) <= self._max_bytes)
                        body = bytearray()
                        for chunk in response.iter_bytes(chunk_size=65536):
                            _check(self._monotonic() - now <= self._timeout_seconds)
                            _check(len(body) + len(chunk) <= self._max_bytes)
                            body.extend(chunk)
                        _check(length is None or len(body) == int(length))
                        _check(self._monotonic() - now <= self._timeout_seconds)
                    received = self._clock()
                    source = _parse(bytes(body), index, received)[0]
                    _check(not sources or received >= sources[-1].received_at)
                    sources.append(source)
                return _assemble((sources[0], sources[1]))
        except (httpx.HTTPError, OSError, ValueError, TypeError, OverflowError):
            raise ValueError("stock_universe_invalid") from None


@dataclass(frozen=True, slots=True)
class StockUniverseArchiveReceipt:
    receipt_path: Path
    receipt_sha256: str
    body_paths: tuple[Path, ...]


def _publish(directory: int, name: str, body: bytes) -> None:
    temporary = ".pending-" + uuid.uuid4().hex
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        # link publishes complete bytes atomically and fails if the target exists.
        os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory)


def archive_stock_universe(
    snapshot: StockUniverseSnapshot, root: Path
) -> StockUniverseArchiveReceipt:
    """Commit original bytes plus a final SHA-bound receipt in a private directory.

    The receipt is the commit marker: readers must ignore bodies without one.
    Publication never replaces an existing body/receipt; failures remove only
    files this invocation successfully published. A crash can leave orphan bodies.
    """
    directory = -1
    published: list[str] = []
    try:
        _check(type(snapshot) is StockUniverseSnapshot)
        snapshot.__post_init__()
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(directory)
        _check(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700)
        identity = snapshot.snapshot_hash
        names = tuple(
            identity + f".{index}." + source.body_sha256 + ".listing.txt"
            for index, source in enumerate(snapshot.sources)
        )
        for name, source in zip(names, snapshot.sources, strict=True):
            _publish(directory, name, source.body)
            published.append(name)
        os.fsync(directory)
        receipt = _identity(snapshot)
        receipt["snapshot_hash"] = identity
        receipt["body_files"] = names
        receipt["classification_counts"] = {
            kind: sum(row.security_kind == kind for row in snapshot.records)
            for kind in sorted({row.security_kind for row in snapshot.records})
        }
        receipt["research_eligible_count"] = sum(row.research_eligible for row in snapshot.records)
        raw = _json(receipt)
        digest = _hash(raw)
        name = digest + ".stock-universe-receipt.json"
        _publish(directory, name, raw)
        published.append(name)
        os.fsync(directory)
        return StockUniverseArchiveReceipt(
            root / name, digest, tuple(root / item for item in names)
        )
    except (OSError, ValueError, TypeError, AttributeError):
        if directory >= 0:
            for name in reversed(published):
                os.unlink(name, dir_fd=directory)
        raise ValueError("stock_universe_invalid") from None
    finally:
        if directory >= 0:
            os.close(directory)
