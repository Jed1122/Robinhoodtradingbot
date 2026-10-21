"""Pure stock-minute capture declarations and independent original-byte reconstruction.

Integrity and clock consistency do not authenticate a calendar, provider, HTTP
response, elapsed time, entitlement or investment input. This module performs no I/O.
"""

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Literal, cast
from uuid import UUID

from trading_bot.market_data.alpaca_stock_minutes import (
    MAX_PAGE_BYTES,
    MAX_PAGES_PER_SESSION,
    MAX_PROOF_BYTES,
    MAX_PROOF_PAGES,
    MAX_SESSIONS,
    StockCoreSessionDeclaration,
    StockMinuteProofAssessment,
    StockMinuteRequest,
    _token,
    assess_stock_minute_proof,
    parse_stock_minute_page,
)

MAX_MANIFEST_BYTES = 3 * MAX_PAGE_BYTES
_MAX_CLOCK = 2**63 - 1
_WINDOW_NS = 60_000_000_000
_FLAGS = (
    "qualified",
    "source_qualified",
    "strategy_qualified",
    "investment_eligible",
    "trading_enabled",
    "live_authorized",
)
_MANIFEST_FIELDS = {
    "schema_version",
    "capture_id",
    "code_sha256",
    "config_sha256",
    "requests",
    "calendar_bodies",
    "capture_boot_id",
    "capture_started_monotonic_ns",
    "capture_started_at",
}
_REQUEST_FIELDS = {
    "symbol",
    "request_sha256",
    "session_date",
    "opens_at",
    "closes_at",
    "calendar_source_url",
    "calendar_sha256",
    "calendar_received_at",
}
_VALIDATION_ERRORS = (ValueError, TypeError, AttributeError, ArithmeticError, RecursionError)


class StockCaptureManifestError(ValueError):
    """A fixed public error without original bytes or caller context."""

    def __init__(self) -> None:
        super().__init__("stock_capture_manifest_invalid")


def _check(valid: bool) -> None:
    if not valid:
        raise StockCaptureManifestError()


def _hex(value: object, length: int) -> None:
    _check(
        type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(length) + r"}", value) is not None
    )


def _boot(value: str) -> None:
    _check(type(value) is str and str(UUID(value)) == value)


def _clock(value: int) -> None:
    _check(type(value) is int and 0 < value <= _MAX_CLOCK)


def _utc(value: datetime) -> None:
    _check(type(value) is datetime and value.tzinfo is not None)
    _check(value.utcoffset() == timedelta(0))


def _false_flags(value: object) -> None:
    _check(all(getattr(value, name) is False for name in _FLAGS))


@dataclass(frozen=True, slots=True, repr=False)
class _Unqualified:
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True, repr=False)
class StockMinuteCaptureManifest(_Unqualified):
    capture_id: str
    code_sha256: str
    config_sha256: str
    requests: tuple[StockMinuteRequest, ...]
    calendar_bodies: tuple[bytes, ...]
    capture_boot_id: str
    capture_started_monotonic_ns: int
    capture_started_at: datetime

    def __post_init__(self) -> None:
        try:
            _false_flags(self)
            _hex(self.capture_id, 32)
            _hex(self.code_sha256, 64)
            _hex(self.config_sha256, 64)
            _boot(self.capture_boot_id)
            _clock(self.capture_started_monotonic_ns)
            _utc(self.capture_started_at)
            _check(type(self.requests) is tuple and 0 < len(self.requests) <= MAX_SESSIONS)
            _check(type(self.calendar_bodies) is tuple and 0 < len(self.calendar_bodies) <= 2)
            hashes: list[str] = []
            for body in self.calendar_bodies:
                _check(type(body) is bytes and 0 < len(body) <= MAX_PAGE_BYTES)
                hashes.append(hashlib.sha256(body).hexdigest())
            _check(hashes == sorted(set(hashes)))
            referenced: set[str] = set()
            previous_close = None
            for request in self.requests:
                _check(type(request) is StockMinuteRequest)
                request.__post_init__()
                _false_flags(request)
                _false_flags(request.session)
                _check(request.request_is_caller_declared is True)
                _check(request.session.calendar_authenticity_verified is False)
                _check(replace(request) == request and replace(request.session) == request.session)
                _check(request.symbol == self.requests[0].symbol)
                session = request.session
                _check(previous_close is None or previous_close < session.opens_at)
                previous_close = session.closes_at
                _check(session.closes_at + timedelta(minutes=15) <= self.capture_started_at)
                _check(session.calendar_received_at <= self.capture_started_at)
                referenced.add(session.calendar_sha256)
            _check(referenced == set(hashes))
        except _VALIDATION_ERRORS:
            raise StockCaptureManifestError() from None


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("ascii")


def _request_wire(request: StockMinuteRequest) -> dict[str, object]:
    session = request.session
    return {
        "symbol": request.symbol,
        "request_sha256": request.request_sha256,
        "session_date": session.session_date.isoformat(),
        "opens_at": session.opens_at.isoformat(),
        "closes_at": session.closes_at.isoformat(),
        "calendar_source_url": session.calendar_source_url,
        "calendar_sha256": session.calendar_sha256,
        "calendar_received_at": session.calendar_received_at.isoformat(),
    }


def dump_stock_capture_manifest(manifest: StockMinuteCaptureManifest) -> bytes:
    """Encode closed canonical declarations without accepting derived data or flags."""
    try:
        _check(type(manifest) is StockMinuteCaptureManifest)
        manifest.__post_init__()
        raw = _canonical(
            {
                "schema_version": 1,
                "capture_id": manifest.capture_id,
                "code_sha256": manifest.code_sha256,
                "config_sha256": manifest.config_sha256,
                "requests": [_request_wire(request) for request in manifest.requests],
                "calendar_bodies": [
                    {
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "body_base64": base64.b64encode(body).decode("ascii"),
                    }
                    for body in manifest.calendar_bodies
                ],
                "capture_boot_id": manifest.capture_boot_id,
                "capture_started_monotonic_ns": manifest.capture_started_monotonic_ns,
                "capture_started_at": manifest.capture_started_at.isoformat(),
            }
        )
        _check(len(raw) <= MAX_MANIFEST_BYTES)
        return raw
    except _VALIDATION_ERRORS:
        raise StockCaptureManifestError() from None


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        _check(name not in result)
        result[name] = value
    return result


def _constant(value: str) -> object:
    raise StockCaptureManifestError()


def _closed(value: object, fields: set[str]) -> dict[str, object]:
    _check(type(value) is dict and set(cast(dict[str, object], value)) == fields)
    return cast(dict[str, object], value)


def _text(value: object) -> str:
    _check(type(value) is str)
    return cast(str, value)


def _datetime(value: object) -> datetime:
    text = _text(value)
    result = datetime.fromisoformat(text)
    _utc(result)
    _check(result.isoformat() == text)
    return result


def _parse_request(value: object) -> StockMinuteRequest:
    wire = _closed(value, _REQUEST_FIELDS)
    day_text = _text(wire["session_date"])
    day = date.fromisoformat(day_text)
    _check(day.isoformat() == day_text)
    request = StockMinuteRequest(
        _text(wire["symbol"]),
        StockCoreSessionDeclaration(
            day,
            _datetime(wire["opens_at"]),
            _datetime(wire["closes_at"]),
            _text(wire["calendar_source_url"]),
            _text(wire["calendar_sha256"]),
            _datetime(wire["calendar_received_at"]),
        ),
    )
    _check(request.request_sha256 == wire["request_sha256"])
    return request


def _parse_calendar(value: object) -> bytes:
    wire = _closed(value, {"sha256", "body_base64"})
    encoded = _text(wire["body_base64"])
    _check(0 < len(encoded) <= 4 * ((MAX_PAGE_BYTES + 2) // 3))
    body = base64.b64decode(encoded, validate=True)
    _check(0 < len(body) <= MAX_PAGE_BYTES)
    _check(base64.b64encode(body).decode("ascii") == encoded)
    _check(hashlib.sha256(body).hexdigest() == wire["sha256"])
    return body


def parse_stock_capture_manifest(raw: bytes) -> StockMinuteCaptureManifest:
    """Reconstruct existing request declarations and verify exact canonical bytes."""
    try:
        _check(type(raw) is bytes and 0 < len(raw) <= MAX_MANIFEST_BYTES)
        wire = _closed(
            json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant),
            _MANIFEST_FIELDS,
        )
        _check(type(wire["schema_version"]) is int and wire["schema_version"] == 1)
        requests, calendars = wire["requests"], wire["calendar_bodies"]
        _check(type(requests) is list and 0 < len(cast(list[object], requests)) <= MAX_SESSIONS)
        _check(type(calendars) is list and 0 < len(cast(list[object], calendars)) <= 2)
        manifest = StockMinuteCaptureManifest(
            _text(wire["capture_id"]),
            _text(wire["code_sha256"]),
            _text(wire["config_sha256"]),
            tuple(_parse_request(request) for request in cast(list[object], requests)),
            tuple(_parse_calendar(calendar) for calendar in cast(list[object], calendars)),
            _text(wire["capture_boot_id"]),
            cast(int, wire["capture_started_monotonic_ns"]),
            _datetime(wire["capture_started_at"]),
        )
        _check(dump_stock_capture_manifest(manifest) == raw)
        return manifest
    except _VALIDATION_ERRORS:
        raise StockCaptureManifestError() from None


@dataclass(frozen=True, slots=True, repr=False)
class StockMinuteCapturedResponse(_Unqualified):
    request_sha256: str
    body_sha256: str
    body: bytes
    page_index: int
    requested_page_token: str | None
    received_at: datetime
    received_monotonic_ns: int
    boot_id: str
    http_status: int

    def __post_init__(self) -> None:
        try:
            _false_flags(self)
            _hex(self.request_sha256, 64)
            _hex(self.body_sha256, 64)
            _check(type(self.body) is bytes and 0 < len(self.body) <= MAX_PAGE_BYTES)
            _check(hashlib.sha256(self.body).hexdigest() == self.body_sha256)
            _check(type(self.page_index) is int and 0 <= self.page_index < MAX_PAGES_PER_SESSION)
            _token(self.requested_page_token)
            _utc(self.received_at)
            _clock(self.received_monotonic_ns)
            _boot(self.boot_id)
            _check(type(self.http_status) is int and self.http_status == 200)
        except _VALIDATION_ERRORS:
            raise StockCaptureManifestError() from None


def reconstruct_stock_capture(
    manifest_raw: bytes,
    responses: tuple[StockMinuteCapturedResponse, ...],
    *,
    as_of: datetime,
) -> StockMinuteProofAssessment:
    """Reparse every original body, preserving incomplete captures without dropping rows."""
    try:
        manifest = parse_stock_capture_manifest(manifest_raw)
        _utc(as_of)
        _check(manifest.capture_started_at <= as_of)
        _check(type(responses) is tuple and len(responses) <= MAX_PROOF_PAGES)
        requests = {request.request_sha256: request for request in manifest.requests}
        seen: set[tuple[str, int]] = set()
        pages = []
        total_bytes = 0
        previous_utc = previous_monotonic = None
        for response in responses:
            _check(type(response) is StockMinuteCapturedResponse)
            response.__post_init__()
            _check(response.request_sha256 in requests)
            identity = (response.request_sha256, response.page_index)
            _check(identity not in seen)
            seen.add(identity)
            _check(response.boot_id == manifest.capture_boot_id)
            _check(manifest.capture_started_at <= response.received_at <= as_of)
            _check(response.received_at - manifest.capture_started_at <= timedelta(seconds=60))
            _check(
                0
                <= response.received_monotonic_ns - manifest.capture_started_monotonic_ns
                <= _WINDOW_NS
            )
            _check(previous_utc is None or previous_utc < response.received_at)
            _check(
                previous_monotonic is None or previous_monotonic < response.received_monotonic_ns
            )
            previous_utc, previous_monotonic = response.received_at, response.received_monotonic_ns
            total_bytes += len(response.body)
            _check(total_bytes <= MAX_PROOF_BYTES)
            pages.append(
                parse_stock_minute_page(
                    response.body,
                    request=requests[response.request_sha256],
                    expected_sha256=response.body_sha256,
                    capture_started_at=manifest.capture_started_at,
                    received_at=response.received_at,
                    page_index=response.page_index,
                    requested_page_token=response.requested_page_token,
                )
            )
        return assess_stock_minute_proof(
            requests=manifest.requests, pages=tuple(pages), as_of=as_of
        )
    except _VALIDATION_ERRORS:
        raise StockCaptureManifestError() from None
