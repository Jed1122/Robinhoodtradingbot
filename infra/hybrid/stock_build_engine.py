"""One owned legacy quiet build on the fixed root Engine; no retry or fallback."""

from __future__ import annotations

import errno
import json
import socket
from typing import NoReturn
from urllib.parse import urlencode

from infra.hybrid.stock_build_http import WIRE_LIMIT, StockBuildHTTPResponse
from infra.hybrid.stock_build_inputs import SourceArchive, build_image_id
from infra.hybrid.stock_container import ImageProfile, _object, verify_engine_version, verify_image
from infra.hybrid.stock_engine import StockEngineReader, _connection
from infra.hybrid.stock_producer_diagnostics import phase
from infra.hybrid.stock_release_producer import _current_source, _Lease

_LIMIT = WIRE_LIMIT
_ERRORS = (OSError, ValueError, TypeError, KeyError, OverflowError, AttributeError, RecursionError)


def _deny() -> NoReturn:
    raise ValueError("stock_build_engine_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


def _budget(lease: _Lease, cap: int) -> float:
    with phase("lease_check"):
        now = lease.check(not_after_ns=cap)
    return min(1.0, (cap - int(now["monotonic_ns"])) / 1_000_000_000)


def _request(lease: _Lease) -> bytes:
    return _source_request(lease.source)


def _source_request(source: SourceArchive) -> bytes:
    """Pure fixed request bytes; supplying these does not authorize an exchange."""
    query = urlencode(
        {
            "version": "1",
            "q": "true",
            "dockerfile": "Dockerfile",
            "pull": "false",
            "rm": "true",
            "forcerm": "false",
            "networkmode": "bridge",
            "platform": "linux/amd64",
            "memory": "536870912",
            "memswap": "536870912",
            "cpuperiod": "100000",
            "cpuquota": "50000",
            "buildargs": json.dumps({"PYTHON_BASE_IMAGE": source.base_ref}, separators=(",", ":")),
        }
    )
    return (
        "POST /v1.52/build?" + query + " HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n"
        "Content-Type: application/x-tar\r\nContent-Length: " + str(len(source.raw)) + "\r\n\r\n"
    ).encode("ascii") + source.raw


def _exchange(lease: _Lease, request: bytes, cap: int) -> bytes:
    with phase("claim"):
        lease.claim(request, cap)
    peer: socket.socket | None = None
    received = bytearray()
    response = StockBuildHTTPResponse()
    try:
        with phase("connect"):
            peer = _connection(cap / 1_000_000_000)
        with phase("lease_check"):
            upload_cap = min(
                cap, int(lease.check(not_after_ns=cap)["monotonic_ns"]) + 30_000_000_000
            )
        offset = 0
        while offset < len(request):
            with phase("send"):
                peer.settimeout(_budget(lease, upload_cap))
                try:
                    sent = peer.send(request[offset : offset + 65536])
                except TimeoutError:
                    continue  # Same socket and original cap; never another request.
                _require(type(sent) is int and 0 < sent <= len(request) - offset)
            offset += sent
            with phase("lease_check"):
                lease.check(not_after_ns=upload_cap)
        while True:
            with phase("receive"):
                peer.settimeout(_budget(lease, cap))
                try:
                    chunk = peer.recv(min(65536, _LIMIT + 1 - len(received)))
                except TimeoutError:
                    continue
            with phase("receive" if chunk else "eof"):
                room = _LIMIT - len(received)
                received.extend(chunk[:room])  # Retain bounded prefix even at overflow.
                _require(len(chunk) <= room)
                with phase("lease_check"):
                    lease.check(not_after_ns=cap)
                _require(bool(chunk))
            with phase("parse"):
                complete = response.feed(chunk)
            with phase("lease_check"):
                lease.check(not_after_ns=cap)
            if complete:
                # A proven frame does not require socket EOF. Check only bytes
                # already queued, without Python's positive-timeout readiness wait.
                with phase("receive"):
                    peer.settimeout(0.0)
                    try:
                        trailing = peer.recv(1, socket.MSG_PEEK)
                    except OSError as error:
                        if error.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.ECONNRESET):
                            raise
                        trailing = b""
                    received.extend(trailing[: _LIMIT - len(received)])
                    _require(not trailing)
                with phase("lease_check"):
                    lease.check(not_after_ns=cap)
                return bytes(received)
    finally:
        try:
            if peer is not None:
                with phase("close"):
                    peer.close()
        finally:
            with phase("response_retain"):
                lease.retain("build-response.http", bytes(received))


def _body(raw: bytes) -> bytes:
    response = StockBuildHTTPResponse()
    _require(response.feed(raw))
    return response.body()


def _build(lease: _Lease) -> ImageProfile:
    """Private actual-context operation; supplied data or old receipts cannot dispatch."""
    try:
        _require(type(lease) is _Lease)
        with phase("source"):
            _current_source(lease)
        with phase("begin_build"):
            deadline = lease.begin_build()
        with phase("version_get"):
            version = StockEngineReader._get("/version", not_after_ns=deadline)
        with phase("version_retain"):
            lease.retain("engine.bin", version)
        with phase("lease_check"):
            lease.check(not_after_ns=deadline)
        with phase("version_verify"):
            profile = verify_engine_version(version)
            record = _object(version)
            _require(record.get("Version") == "29.1.3" and profile.architecture == "amd64")
        raw = _exchange(lease, _request(lease), deadline)
        with phase("lease_check"):
            lease.check(not_after_ns=deadline)
        with phase("parse"):
            image_id = build_image_id(_body(raw))
        with phase("image_get"):
            metadata = StockEngineReader._get(
                "/v1.52/images/" + image_id + "/json", not_after_ns=deadline
            )
        with phase("image_retain"):
            lease.retain("image.bin", metadata)
        with phase("lease_check"):
            lease.check(not_after_ns=deadline)
        with phase("image_verify"):
            image = verify_image(metadata, image_id, profile)
        with phase("build_complete"):
            lease.record(
                "build-complete.json",
                {
                    "schema_version": 1,
                    "kind": "stock_build_complete",
                    "image_digest": image.image_digest,
                    "namespace_id": lease.namespace["namespace_id"],
                    "source_sha256": lease.source.digest,
                    "dispatch_sha256": lease.hashes["dispatch.json"],
                    "response_sha256": lease.hashes["build-response.http"],
                    "image_sha256": lease.hashes["image.bin"],
                    "build_deadline_ns": deadline,
                    "completed_clock": lease.check(not_after_ns=deadline),
                },
            )
        with phase("lease_check"):
            lease.check(not_after_ns=deadline)
        lease.built_image = image
        return image
    except _ERRORS:
        _deny()
