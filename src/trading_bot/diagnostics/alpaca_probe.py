"""Bounded first-response diagnostics, not a market-data provider or trading adapter."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal, cast

import httpx

from trading_bot.clock import Clock, require_utc
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.config.loader import LoadedConfig
from trading_bot.domain import BarInterval

MAX_MANIFEST_BYTES = 16_384
MAX_RESPONSE_BYTES = 1_048_576
TOTAL_TIMEOUT_SECONDS = 60
_SCHEMA = "alpaca-first-response-v1"
_BARS: Final = "/v2/stocks/bars"
_ACTIONS: Final = "/v1/corporate-actions"
_ERRORS = frozenset(
    {
        "probe_manifest_invalid",
        "probe_scope_mismatch",
        "probe_expired",
        "probe_path_invalid",
        "probe_credential_invalid",
        "probe_storage_failed",
        "probe_access_denied",
        "probe_rate_limited",
        "probe_http_failed",
        "probe_timeout",
        "probe_response_invalid",
        "probe_response_too_large",
        "probe_secret_echo",
    }
)


class ProbeError(ValueError):
    """A fixed reason code only; caller/provider strings are never retained."""

    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code in _ERRORS else "probe_manifest_invalid"
        super().__init__(self.code)


def _check(condition: bool, code: str = "probe_manifest_invalid") -> None:
    if not condition:
        raise ProbeError(code)


def _digest(value: object, length: int = 64) -> bool:
    return type(value) is str and re.fullmatch(r"[a-f0-9]{" + str(length) + "}", value) is not None


def _utc(value: datetime, code: str = "probe_manifest_invalid") -> datetime:
    try:
        return require_utc(value)
    except (TypeError, ValueError, OverflowError):
        pass
    raise ProbeError(code)


def _parse_time(value: object) -> datetime:
    if type(value) is str:
        try:
            result = _utc(datetime.fromisoformat(value))
            if result.isoformat() == value:
                return result
        except (ValueError, TypeError, OverflowError):
            pass
    raise ProbeError("probe_manifest_invalid")


def _path(value: object) -> bool:
    return (
        isinstance(value, Path)
        and value.is_absolute()
        and len(value.parts) > 1
        and ".." not in value.parts
        and "\x00" not in str(value)
    )


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(value: str) -> object:
    raise ValueError("nonfinite JSON number")


def _json_object(body: bytes, *, max_bytes: int, code: str) -> dict[str, object]:
    """Strict bounded JSON syntax only; this does not validate provider semantics."""
    _check(type(body) is bytes and 0 < len(body) <= max_bytes, code)
    try:
        result: object = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=Decimal,
            parse_constant=_nonfinite,
        )
        if type(result) is dict:
            # Bound traversal depth as well as input size; do not recurse over untrusted objects.
            pending: list[tuple[object, int]] = [(result, 0)]
            while pending:
                value, depth = pending.pop()
                if depth > 64:
                    raise ValueError("JSON nesting exceeds diagnostic bound")
                if type(value) is dict:
                    pending.extend((v, depth + 1) for v in value.values())
                elif type(value) is list:
                    pending.extend((v, depth + 1) for v in value)
                elif isinstance(value, Decimal) and not value.is_finite():
                    raise ValueError("nonfinite JSON number")
            return cast(dict[str, object], result)
    except (ValueError, TypeError, RecursionError, ArithmeticError):
        pass
    raise ProbeError(code)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class ProbeRequest:
    path: Literal["/v2/stocks/bars", "/v1/corporate-actions"]
    query: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _check(type(self.path) is str and self.path in (_BARS, _ACTIONS))
        _check(type(self.query) is tuple)
        _check(
            all(
                type(p) is tuple and len(p) == 2 and all(type(v) is str for v in p)
                for p in self.query
            )
        )
        _check(len({k for k, _ in self.query}) == len(self.query))


def _requests(symbols: str, start: datetime, end: datetime) -> tuple[ProbeRequest, ...]:
    return (
        ProbeRequest(
            _BARS,
            (
                ("symbols", symbols),
                ("timeframe", "1Day"),
                ("start", start.isoformat()),
                ("end", end.isoformat()),
                ("adjustment", "raw"),
                ("asof", "-"),
                ("feed", "sip"),
                ("currency", "USD"),
                ("sort", "asc"),
                ("limit", "1"),
            ),
        ),
        ProbeRequest(
            _ACTIONS,
            (
                ("symbols", symbols),
                ("start", start.date().isoformat()),
                ("end", end.date().isoformat()),
                ("region", "us"),
                ("data_quality", "all"),
                ("sort", "asc"),
                ("limit", "1"),
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class ProbeManifest:
    code_revision: str
    config_hash: str
    prepared_at: datetime
    expires_at: datetime
    requests: tuple[ProbeRequest, ...]
    credential_file: Path
    quarantine_root: Path
    repository_root: Path
    max_response_bytes: int
    total_timeout_seconds: int

    def __post_init__(self) -> None:
        _check(_digest(self.code_revision, 40) and _digest(self.config_hash))
        prepared, expires = _utc(self.prepared_at), _utc(self.expires_at)
        _check(expires - prepared == timedelta(minutes=30))
        _check(
            type(self.max_response_bytes) is int and self.max_response_bytes == MAX_RESPONSE_BYTES
        )
        _check(
            type(self.total_timeout_seconds) is int
            and self.total_timeout_seconds == TOTAL_TIMEOUT_SECONDS
        )
        _check(
            all(
                _path(p) for p in (self.credential_file, self.quarantine_root, self.repository_root)
            )
        )
        _check(not self.credential_file.is_relative_to(self.repository_root))
        _check(not self.quarantine_root.is_relative_to(self.repository_root))
        _check(
            type(self.requests) is tuple
            and len(self.requests) == 2
            and all(type(r) is ProbeRequest for r in self.requests)
        )
        query = dict(self.requests[0].query)
        _check({"symbols", "start", "end"}.issubset(query))
        symbols = query["symbols"]
        tokens = symbols.split(",")
        _check(
            all(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", s) for s in tokens)
            and len(set(tokens)) == len(tokens)
        )
        start, end = _parse_time(query["start"]), _parse_time(query["end"])
        _check(start < end and prepared - end >= timedelta(hours=24))
        _check(self.requests == _requests(symbols, start, end))


@dataclass(frozen=True, slots=True)
class ProbeCredential:
    key_id: str = field(repr=False)
    secret_key: str = field(repr=False)

    def __post_init__(self) -> None:
        _check(
            all(
                type(v) is str and 16 <= len(v) <= 256 and all(33 <= ord(c) <= 126 for c in v)
                for v in (self.key_id, self.secret_key)
            ),
            "probe_credential_invalid",
        )


@dataclass(frozen=True, slots=True)
class ProbeReceipt:
    manifest_sha256: str
    request_index: int
    started_at: datetime
    completed_at: datetime
    status_code: int | None
    body_sha256: str | None
    body_bytes: int
    reason_code: str

    def __post_init__(self) -> None:
        _check(_digest(self.manifest_sha256))
        _check(type(self.request_index) is int and self.request_index in (0, 1))
        _check(_utc(self.completed_at) >= _utc(self.started_at))
        _check(
            self.status_code is None
            or (type(self.status_code) is int and 100 <= self.status_code <= 599)
        )
        _check(type(self.body_bytes) is int)
        _check(type(self.reason_code) is str)
        if self.reason_code == "probe_sample_retained":
            _check(
                self.status_code == 200
                and _digest(self.body_sha256)
                and 0 < self.body_bytes <= MAX_RESPONSE_BYTES
            )
        else:
            _check(
                self.reason_code in _ERRORS and self.body_sha256 is None and self.body_bytes == 0
            )


def _loaded_identity(loaded: LoadedConfig) -> None:
    _check(type(loaded) is LoadedConfig, "probe_scope_mismatch")
    encoded, digest = hash_loaded_config(loaded.config, loaded.safety_envelope)
    _check(
        encoded == loaded.canonical_json and digest == loaded.config_hash, "probe_scope_mismatch"
    )
    _check(
        loaded.config.equity_strategies.bar_interval is BarInterval.ONE_DAY, "probe_scope_mismatch"
    )


def prepare_probe(
    loaded: LoadedConfig,
    *,
    clock: Clock,
    code_revision: str,
    requested_end: datetime,
    credential_file: Path,
    quarantine_root: Path,
    repository_root: Path,
) -> ProbeManifest:
    """Prepare only; paths are lexical and no file or network is opened."""
    _loaded_identity(loaded)
    now, end = _utc(clock.now()), _utc(requested_end)
    try:
        start = end - timedelta(days=loaded.config.research.history_calendar_days)
        expiry = now + timedelta(minutes=30)
    except OverflowError:
        pass
    else:
        return ProbeManifest(
            code_revision,
            str(loaded.config_hash),
            now,
            expiry,
            _requests(
                ",".join(loaded.config.equity_strategies.research_universe_symbols), start, end
            ),
            credential_file,
            quarantine_root,
            repository_root,
            MAX_RESPONSE_BYTES,
            TOTAL_TIMEOUT_SECONDS,
        )
    raise ProbeError("probe_manifest_invalid")


def encode_manifest(manifest: ProbeManifest) -> bytes:
    _check(type(manifest) is ProbeManifest)
    manifest.__post_init__()
    payload: dict[str, object] = {"schema_version": _SCHEMA}
    for item in fields(manifest):
        value = getattr(manifest, item.name)
        if isinstance(value, datetime):
            value = _utc(value).isoformat()
        elif isinstance(value, Path):
            value = str(value)
        elif item.name == "requests":
            value = [{"path": r.path, "query": r.query} for r in manifest.requests]
        payload[item.name] = value
    try:
        encoded = _canonical(payload)
    except (UnicodeError, ValueError, TypeError):
        pass
    else:
        _check(len(encoded) <= MAX_MANIFEST_BYTES)
        return encoded
    raise ProbeError("probe_manifest_invalid")


def decode_manifest(body: bytes) -> ProbeManifest:
    wire = _json_object(body, max_bytes=MAX_MANIFEST_BYTES, code="probe_manifest_invalid")
    _check(set(wire) == {f.name for f in fields(ProbeManifest)} | {"schema_version"})
    _check(wire["schema_version"] == _SCHEMA)
    try:
        requests: list[ProbeRequest] = []
        raw_requests = wire["requests"]
        _check(type(raw_requests) is list)
        for raw in cast(list[object], raw_requests):
            _check(type(raw) is dict and set(raw) == {"path", "query"})
            mapping = cast(dict[str, object], raw)
            query = mapping["query"]
            _check(type(query) is list)
            pairs: list[tuple[str, str]] = []
            for p in cast(list[object], query):
                _check(type(p) is list and len(p) == 2 and all(type(v) is str for v in p))
                pair = cast(list[str], p)
                pairs.append((pair[0], pair[1]))
            requests.append(
                ProbeRequest(
                    cast(Literal["/v2/stocks/bars", "/v1/corporate-actions"], mapping["path"]),
                    tuple(pairs),
                )
            )
        paths: list[Path] = []
        for key in ("credential_file", "quarantine_root", "repository_root"):
            _check(type(wire[key]) is str)
            path = Path(cast(str, wire[key]))
            _check(str(path) == wire[key])
            paths.append(path)
        return ProbeManifest(
            cast(str, wire["code_revision"]),
            cast(str, wire["config_hash"]),
            _parse_time(wire["prepared_at"]),
            _parse_time(wire["expires_at"]),
            tuple(requests),
            paths[0],
            paths[1],
            paths[2],
            cast(int, wire["max_response_bytes"]),
            cast(int, wire["total_timeout_seconds"]),
        )
    except ProbeError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError):
        pass
    raise ProbeError("probe_manifest_invalid")


def manifest_sha256(manifest: ProbeManifest) -> str:
    return hashlib.sha256(encode_manifest(manifest)).hexdigest()


def _capture_time(manifest: ProbeManifest, clock: Clock, *, minimum: datetime) -> datetime:
    value = _utc(clock.now(), "probe_expired")
    _check(minimum <= value < manifest.expires_at, "probe_expired")
    return value


@contextmanager
def _quiet_http_logging() -> Iterator[None]:
    # Standalone diagnostics only: suppress library diagnostics while credentials are in scope.
    names = {
        "httpx",
        "httpcore",
        "httpcore.connection",
        "httpcore.http11",
        "httpcore.http2",
        "httpcore.proxy",
        "httpcore.socks",
    }
    names.update(
        name
        for name in logging.Logger.manager.loggerDict
        if name.startswith(("httpx.", "httpcore."))
    )
    loggers = [(logging.getLogger(name), logging.getLogger(name).disabled) for name in names]
    try:
        for logger, _ in loggers:
            logger.disabled = True
        yield
    finally:
        for logger, disabled in loggers:
            logger.disabled = disabled


def _screen_response(body: bytes, credential: ProbeCredential) -> None:
    values = _json_object(body, max_bytes=MAX_RESPONSE_BYTES, code="probe_response_invalid")
    forbidden = (credential.key_id, credential.secret_key, "APCA-API-KEY-ID", "APCA-API-SECRET-KEY")
    _check(not any(s.encode() in body for s in forbidden), "probe_secret_echo")
    pending: list[object] = [values]
    while pending:
        value = pending.pop()
        if type(value) is str:
            _check(
                not any(s.casefold() in value.casefold() for s in forbidden), "probe_secret_echo"
            )
        elif type(value) is dict:
            pending.extend(value.keys())
            pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)


async def _sample(
    client: httpx.AsyncClient,
    manifest: ProbeManifest,
    credential: ProbeCredential,
    index: int,
    digest: str,
    clock: Clock,
    minimum: datetime,
) -> ProbeReceipt:
    from trading_bot.diagnostics.alpaca_probe_io import publish_probe_blob, publish_probe_receipt

    started = _capture_time(manifest, clock, minimum=minimum)
    status: int | None = None
    failure: str | None = None
    completed: datetime | None = None
    body = b""
    request = manifest.requests[index]
    try:
        async with client.stream(
            "GET",
            "https://data.alpaca.markets" + request.path,
            params=request.query,
            headers={
                "APCA-API-KEY-ID": credential.key_id,
                "APCA-API-SECRET-KEY": credential.secret_key,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
        ) as response:
            status = response.status_code
            if status in (401, 403):
                raise ProbeError("probe_access_denied")
            if status == 429:
                raise ProbeError("probe_rate_limited")
            _check(status == 200, "probe_http_failed")
            _check(
                response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                == "application/json",
                "probe_response_invalid",
            )
            _check(
                response.headers.get("content-encoding", "identity").strip().lower() == "identity",
                "probe_response_invalid",
            )
            declared = response.headers.get("content-length")
            if declared is not None:
                _check(
                    declared.isascii() and declared.isdecimal() and len(declared) <= 10,
                    "probe_response_invalid",
                )
                _check(int(declared) <= manifest.max_response_bytes, "probe_response_too_large")
            pieces: list[bytes] = []
            count = 0
            async for piece in response.aiter_raw(chunk_size=65_536):
                count += len(piece)
                _check(count <= manifest.max_response_bytes, "probe_response_too_large")
                pieces.append(piece)
            _check(declared is None or int(declared) == count, "probe_response_invalid")
            body = b"".join(pieces)
        completed = _capture_time(manifest, clock, minimum=started)
        _screen_response(body, credential)
    except ProbeError as error:
        failure = error.code
    except (httpx.TimeoutException, TimeoutError):
        failure = "probe_timeout"
    except Exception:
        failure = "probe_http_failed"
    if failure is not None:
        # Do not fabricate a completion instant if the injected clock is invalid or regresses.
        failed_at = _utc(clock.now(), "probe_expired")
        _check(failed_at >= started, "probe_expired")
        receipt = ProbeReceipt(digest, index, started, failed_at, status, None, 0, failure)
        publish_probe_receipt(
            manifest.quarantine_root, receipt, repository_root=manifest.repository_root
        )
        raise ProbeError(failure)
    _check(completed is not None, "probe_response_invalid")
    _capture_time(manifest, clock, minimum=cast(datetime, completed))
    blob_hash = publish_probe_blob(
        manifest.quarantine_root, body, repository_root=manifest.repository_root
    )
    receipt = ProbeReceipt(
        digest,
        index,
        started,
        cast(datetime, completed),
        status,
        blob_hash,
        len(body),
        "probe_sample_retained",
    )
    publish_probe_receipt(
        manifest.quarantine_root, receipt, repository_root=manifest.repository_root
    )
    return receipt


async def capture_probe(
    manifest: ProbeManifest,
    *,
    approved_manifest_sha256: str,
    loaded: LoadedConfig,
    active_code_revision: str,
    clock: Clock,
) -> tuple[ProbeReceipt, ...]:
    """One approved diagnostic only; the caller must separately resolve entitlement/rights.

    A supplied digest is confirmation of reviewed scope, not a security capability or legal
    clearance. This function is never wired to a runtime, scheduler or broker.
    """
    from trading_bot.diagnostics.alpaca_probe_io import _claim_probe_attempt, read_probe_credential
    from trading_bot.market_data.bundle_models import BundleError
    from trading_bot.market_data.bundle_store import _open_root

    digest = manifest_sha256(manifest)
    _loaded_identity(loaded)
    _check(
        type(approved_manifest_sha256) is str and approved_manifest_sha256 == digest,
        "probe_scope_mismatch",
    )
    _check(
        active_code_revision == manifest.code_revision
        and loaded.config_hash == manifest.config_hash,
        "probe_scope_mismatch",
    )
    bars_query = dict(manifest.requests[0].query)
    end = _parse_time(bars_query["end"])
    try:
        start = end - timedelta(days=loaded.config.research.history_calendar_days)
    except OverflowError:
        pass
    else:
        expected = _requests(
            ",".join(loaded.config.equity_strategies.research_universe_symbols), start, end
        )
        _check(manifest.requests == expected, "probe_scope_mismatch")
        _capture_time(manifest, clock, minimum=manifest.prepared_at)
        code = "probe_path_invalid"
        try:
            for path in (manifest.quarantine_root, manifest.credential_file.parent):
                descriptor = _open_root(path, manifest.repository_root)
                os.close(descriptor)
            _claim_probe_attempt(
                manifest.quarantine_root, digest, repository_root=manifest.repository_root
            )
            with _quiet_http_logging():
                async with asyncio.timeout(manifest.total_timeout_seconds):
                    credential = read_probe_credential(
                        manifest.credential_file, repository_root=manifest.repository_root
                    )
                    transport = httpx.AsyncHTTPTransport(verify=True, trust_env=False, retries=0)
                    async with httpx.AsyncClient(
                        verify=True,
                        trust_env=False,
                        follow_redirects=False,
                        timeout=10.0,
                        transport=transport,
                    ) as client:
                        receipts: list[ProbeReceipt] = []
                        minimum = manifest.prepared_at
                        for index in range(2):
                            receipt = await _sample(
                                client, manifest, credential, index, digest, clock, minimum
                            )
                            receipts.append(receipt)
                            minimum = receipt.completed_at
                        return tuple(receipts)
        except ProbeError as error:
            code = error.code
        except (httpx.TimeoutException, TimeoutError):
            code = "probe_timeout"
        except (BundleError, OSError):
            code = "probe_path_invalid"
        except Exception:
            code = "probe_http_failed"
        raise ProbeError(code)
    raise ProbeError("probe_scope_mismatch")
