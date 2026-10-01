"""Standalone bounded SPY native capture; never a source or broker qualification.

The caller verifies operator authority, entitlement and a clean committed checkout.
The approved digest confirms this new scope, not the old two-response diagnostic.
No runtime imports this owner. It accepts no transport URL, retry or broker operation.
"""

import asyncio
import hashlib
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import httpx

from trading_bot.clock import Clock, require_utc
from trading_bot.config import LoadedConfig
from trading_bot.diagnostics.alpaca_probe import (
    ProbeCredential,
    ProbeError,
    _canonical,
    _digest,
    _json_object,
    _loaded_identity,
    _parse_time,
    _path,
    _quiet_http_logging,
    _screen_response,
)
from trading_bot.diagnostics.alpaca_probe_io import (
    _publish_private_file,
    publish_probe_blob,
    read_probe_credential,
)
from trading_bot.domain import ExecutionMode
from trading_bot.market_data.alpaca_native import (
    MAX_PAGE_BYTES,
    MAX_PAGES,
    AlpacaNativeError,
    AlpacaNativePage,
    AlpacaStockRequest,
    parse_alpaca_page,
    parse_timestamp_ns,
    validate_alpaca_pages,
)
from trading_bot.market_data.bundle_store import _open_root
from trading_bot.market_data.recording import content_hash

_ERRORS = frozenset(
    {
        "capture_manifest_invalid",
        "capture_scope_mismatch",
        "capture_expired",
        "capture_storage_failed",
        "capture_credential_invalid",
        "capture_access_denied",
        "capture_rate_limited",
        "capture_http_failed",
        "capture_timeout",
        "capture_response_invalid",
        "capture_response_too_large",
        "capture_secret_echo",
        "capture_native_invalid",
        "capture_page_limit",
    }
)


class CaptureError(ValueError):
    def __init__(self, code: str, *, status: int | None = None) -> None:
        self.code = code if code in _ERRORS else "capture_manifest_invalid"
        self.status = status if type(status) is int and 100 <= status <= 599 else None
        super().__init__(self.code)


def _check(condition: bool, code: str = "capture_manifest_invalid") -> None:
    if not condition:
        raise CaptureError(code)


@dataclass(frozen=True, slots=True, repr=False)
class CaptureManifest:
    code_revision: str
    config_hash: str
    prepared_at: datetime
    expires_at: datetime
    request: AlpacaStockRequest
    credential_file: Path
    quarantine_root: Path
    repository_root: Path
    max_pages: int

    def __post_init__(self) -> None:
        _check(_digest(self.code_revision, 40) and _digest(self.config_hash))
        _check(
            require_utc(self.expires_at) - require_utc(self.prepared_at) == timedelta(minutes=30)
        )
        _check(type(self.request) is AlpacaStockRequest)
        replace(self.request)
        # A profile ceiling, not silently interchangeable data outside the locked study.
        _check(parse_timestamp_ns("2016-01-01T00:00:00Z") <= self.request.start_ns)
        _check(self.request.end_ns <= parse_timestamp_ns("2026-01-01T00:00:00Z"))
        _check(self.request.limit <= 1000)
        if self.request.kind == "quotes":
            _check(self.request.end_ns - self.request.start_ns <= 86400 * 10**9)
        _check(self.request.end_ns <= parse_timestamp_ns(self.prepared_at.isoformat()))
        _check(type(self.max_pages) is int and 1 <= self.max_pages <= MAX_PAGES)
        _check(
            all(
                _path(p) for p in (self.credential_file, self.quarantine_root, self.repository_root)
            )
        )
        _check(not self.credential_file.is_relative_to(self.repository_root))
        _check(not self.quarantine_root.is_relative_to(self.repository_root))
        _check(not self.credential_file.is_relative_to(self.quarantine_root))


def prepare_capture(
    loaded: LoadedConfig,
    *,
    clock: Clock,
    code_revision: str,
    request: AlpacaStockRequest,
    credential_file: Path,
    quarantine_root: Path,
    repository_root: Path,
    max_pages: int = MAX_PAGES,
) -> CaptureManifest:
    """Pure preparation: neither paths nor credentials are opened."""
    _loaded_identity(loaded)
    _check(loaded.config.mode is ExecutionMode.BACKTEST and not loaded.config.live_trading_enabled)
    now = require_utc(clock.now())
    return CaptureManifest(
        code_revision,
        str(loaded.config_hash),
        now,
        now + timedelta(minutes=30),
        request,
        credential_file,
        quarantine_root,
        repository_root,
        max_pages,
    )


def encode_capture_manifest(manifest: CaptureManifest) -> bytes:
    _check(type(manifest) is CaptureManifest)
    replace(manifest)
    return _canonical(
        {
            "schema": "alpaca-native-capture-v1",
            "code_revision": manifest.code_revision,
            "config_hash": manifest.config_hash,
            "prepared_at": manifest.prepared_at.isoformat(),
            "expires_at": manifest.expires_at.isoformat(),
            "request": {
                "kind": manifest.request.kind,
                "start_ns": manifest.request.start_ns,
                "end_ns": manifest.request.end_ns,
                "limit": manifest.request.limit,
            },
            "credential_file": str(manifest.credential_file),
            "quarantine_root": str(manifest.quarantine_root),
            "repository_root": str(manifest.repository_root),
            "max_pages": manifest.max_pages,
        }
    )


def capture_manifest_sha256(manifest: CaptureManifest) -> str:
    return hashlib.sha256(encode_capture_manifest(manifest)).hexdigest()


def decode_capture_manifest(body: bytes) -> CaptureManifest:
    try:
        wire = _json_object(body, max_bytes=16384, code="probe_manifest_invalid")
        _check(
            set(wire)
            == {
                "schema",
                "code_revision",
                "config_hash",
                "prepared_at",
                "expires_at",
                "request",
                "credential_file",
                "quarantine_root",
                "repository_root",
                "max_pages",
            }
        )
        _check(wire["schema"] == "alpaca-native-capture-v1")
        request = wire["request"]
        _check(type(request) is dict and set(request) == {"kind", "start_ns", "end_ns", "limit"})
        record = cast(dict[str, object], request)
        paths = []
        for name in ("credential_file", "quarantine_root", "repository_root"):
            value = wire[name]
            _check(type(value) is str)
            path = Path(cast(str, value))
            _check(str(path) == value)
            paths.append(path)
        return CaptureManifest(
            cast(str, wire["code_revision"]),
            cast(str, wire["config_hash"]),
            _parse_time(wire["prepared_at"]),
            _parse_time(wire["expires_at"]),
            AlpacaStockRequest(
                cast(Literal["bars", "quotes"], record["kind"]),
                cast(int, record["start_ns"]),
                cast(int, record["end_ns"]),
                cast(int, record["limit"]),
            ),
            paths[0],
            paths[1],
            paths[2],
            cast(int, wire["max_pages"]),
        )
    except (ValueError, TypeError, KeyError, ArithmeticError):
        pass
    raise CaptureError("capture_manifest_invalid")


def _time(manifest: CaptureManifest, clock: Clock, minimum: datetime) -> datetime:
    try:
        now = require_utc(clock.now())
        _check(minimum <= now < manifest.expires_at, "capture_expired")
        return now
    except (ValueError, TypeError, ArithmeticError):
        pass
    raise CaptureError("capture_expired")


def _claim(manifest: CaptureManifest, digest: str) -> None:
    """New namespaced one-shot claim: uncertain/failed captures cannot replay."""
    failure = "capture_storage_failed"
    try:
        parent = _open_root(manifest.quarantine_root, manifest.repository_root)
        try:
            descriptor = os.open(
                digest + ".native.attempt",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            try:
                os.fchmod(descriptor, 0o600)
                os.fsync(descriptor)
                os.fsync(parent)
            finally:
                os.close(descriptor)
        finally:
            os.close(parent)
        return
    except FileExistsError:
        failure = "capture_scope_mismatch"
    except (OSError, ValueError):
        pass
    raise CaptureError(failure)


def _publish_receipt(manifest: CaptureManifest, payload: dict[str, object]) -> str:
    body = _canonical(payload)
    digest = hashlib.sha256(body).hexdigest()
    _publish_private_file(
        manifest.quarantine_root / (digest + ".capture-receipt.json"),
        body,
        repository_root=manifest.repository_root,
    )
    return digest


@dataclass(frozen=True, slots=True)
class CaptureResult:
    reason: str
    record_count: int
    pagination_complete: bool
    receipt_sha256s: tuple[str, ...]
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)


async def _read_response(
    client: httpx.AsyncClient,
    manifest: CaptureManifest,
    credential: ProbeCredential,
    token: str | None,
) -> tuple[int, bytes]:
    """Only fixed HTTPS GET; inspect no error bodies, accept no compressed expansion."""
    async with client.stream(
        "GET",
        "https://data.alpaca.markets" + manifest.request.path,
        params=manifest.request.query(token),
        headers={
            "APCA-API-KEY-ID": credential.key_id,
            "APCA-API-SECRET-KEY": credential.secret_key,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    ) as response:
        status = response.status_code
        if status in (401, 403):
            raise CaptureError("capture_access_denied", status=status)
        if status == 429:
            raise CaptureError("capture_rate_limited", status=status)
        if status != 200:
            raise CaptureError("capture_http_failed", status=status)
        _check(
            response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            == "application/json",
            "capture_response_invalid",
        )
        _check(
            response.headers.get("content-encoding", "identity").strip().lower() == "identity",
            "capture_response_invalid",
        )
        declared = response.headers.get("content-length")
        if declared is not None:
            _check(
                declared.isascii() and declared.isdecimal() and len(declared) <= 10,
                "capture_response_invalid",
            )
            _check(int(declared) <= MAX_PAGE_BYTES, "capture_response_too_large")
        pieces = []
        size = 0
        async for piece in response.aiter_raw(chunk_size=65536):
            size += len(piece)
            _check(size <= MAX_PAGE_BYTES, "capture_response_too_large")
            pieces.append(piece)
        _check(declared is None or int(declared) == size, "capture_response_invalid")
        raw = b"".join(pieces)
        _screen_response(raw, credential)
        return status, raw


async def _pages(
    client: httpx.AsyncClient,
    manifest: CaptureManifest,
    digest: str,
    credential: ProbeCredential,
    clock: Clock,
    minimum: datetime,
) -> CaptureResult:
    pages: list[AlpacaNativePage] = []
    receipts: list[str] = []
    token: str | None = None
    count = 0
    for index in range(manifest.max_pages):
        started = _time(manifest, clock, minimum)
        completed: datetime | None = None
        body_digest: str | None = None
        body_bytes = 0
        status: int | None = None
        reason = "page_retained"
        try:
            status, raw = await _read_response(client, manifest, credential, token)
            completed = _time(manifest, clock, started)
            body_digest = publish_probe_blob(
                manifest.quarantine_root, raw, repository_root=manifest.repository_root
            )
            body_bytes = len(raw)
            page = parse_alpaca_page(
                raw,
                request=manifest.request,
                expected_sha256=body_digest,
                page_index=index,
                requested_page_token=token,
            )
            assessment = validate_alpaca_pages(manifest.request, (*pages, page))
        except CaptureError as error:
            reason = error.code
            if error.status is not None:
                status = error.status
        except AlpacaNativeError:
            reason = "capture_native_invalid"
        except ProbeError as error:
            reason = (
                error.code.replace("probe_", "capture_", 1)
                if error.code in ("probe_secret_echo", "probe_response_invalid")
                else "capture_storage_failed"
            )
        except (httpx.TimeoutException, TimeoutError):
            reason = "capture_timeout"
        except Exception:
            reason = "capture_http_failed"
        receipt = {
            "schema": "alpaca-native-page-receipt-v1",
            "manifest_sha256": digest,
            "request_sha256": manifest.request.request_hash,
            "page_index": index,
            "query_sha256": str(content_hash(manifest.request.query(token))),
            "previous_receipt_sha256": receipts[-1] if receipts else None,
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat() if completed is not None else None,
            "status_code": status,
            "body_sha256": body_digest,
            "body_bytes": body_bytes,
            "reason": reason,
            "source_qualified": False,
            "evidence_promotable": False,
        }
        receipts.append(_publish_receipt(manifest, receipt))
        if reason != "page_retained":
            return CaptureResult(reason, count, False, tuple(receipts))
        pages.append(page)
        count = assessment.record_count
        token = page.next_page_token
        minimum = cast(datetime, completed)
        if assessment.pagination_complete:
            return CaptureResult("capture_transport_complete", count, True, tuple(receipts))
    return CaptureResult("capture_page_limit", count, False, tuple(receipts))


async def capture_native(
    manifest: CaptureManifest,
    *,
    approved_manifest_sha256: str,
    loaded: LoadedConfig,
    active_code_revision: str,
    clock: Clock,
) -> CaptureResult:
    """Authorized bounded acquisition only; successful transport is not source acceptance."""
    digest = capture_manifest_sha256(manifest)
    _loaded_identity(loaded)
    _check(
        loaded.config.mode is ExecutionMode.BACKTEST and not loaded.config.live_trading_enabled,
        "capture_scope_mismatch",
    )
    _check(
        digest == approved_manifest_sha256
        and manifest.code_revision == active_code_revision
        and manifest.config_hash == loaded.config_hash,
        "capture_scope_mismatch",
    )
    preflight_at = _time(manifest, clock, manifest.prepared_at)
    _claim(manifest, digest)
    failure = "capture_http_failed"
    try:
        _publish_private_file(
            manifest.quarantine_root / (digest + ".capture-manifest.json"),
            encode_capture_manifest(manifest),
            repository_root=manifest.repository_root,
        )
        with _quiet_http_logging():
            async with asyncio.timeout(60):
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
                    result = await _pages(client, manifest, digest, credential, clock, preflight_at)
        summary = _canonical(
            {
                "schema": "alpaca-native-capture-result-v1",
                "manifest_sha256": digest,
                "reason": result.reason,
                "record_count": result.record_count,
                "pagination_complete": result.pagination_complete,
                "receipt_sha256s": result.receipt_sha256s,
                "source_qualified": False,
                "evidence_promotable": False,
            }
        )
        _publish_private_file(
            manifest.quarantine_root / (digest + ".capture-result.json"),
            summary,
            repository_root=manifest.repository_root,
        )
        return result
    except CaptureError as error:
        failure = error.code
    except ProbeError as error:
        failure = (
            "capture_credential_invalid"
            if error.code == "probe_credential_invalid"
            else "capture_storage_failed"
        )
    except (OSError, ValueError):
        failure = "capture_storage_failed"
    except (httpx.TimeoutException, TimeoutError):
        failure = "capture_timeout"
    except Exception:
        failure = "capture_http_failed"
    raise CaptureError(failure)
