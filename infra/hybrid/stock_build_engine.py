"""One owned legacy quiet build on the fixed root Engine; no retry or fallback."""

from __future__ import annotations

import json
import re
import socket
from typing import NoReturn
from urllib.parse import urlencode

from infra.hybrid.stock_build_inputs import build_image_id
from infra.hybrid.stock_container import ImageProfile, _object, verify_engine_version, verify_image
from infra.hybrid.stock_engine import StockEngineReader, _connection
from infra.hybrid.stock_release_producer import _Lease

_LIMIT = 1048576 + 8192
_ERRORS = (OSError, ValueError, TypeError, KeyError, OverflowError, AttributeError, RecursionError)


def _deny() -> NoReturn:
    raise ValueError("stock_build_engine_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


def _budget(lease: _Lease, cap: int) -> float:
    now = lease.check(not_after_ns=cap)
    return min(1.0, (cap - int(now["monotonic_ns"])) / 1_000_000_000)


def _request(lease: _Lease) -> bytes:
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
            "buildargs": json.dumps(
                {"PYTHON_BASE_IMAGE": lease.source.base_ref}, separators=(",", ":")
            ),
        }
    )
    return (
        "POST /v1.52/build?" + query + " HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n"
        "Content-Type: application/x-tar\r\nContent-Length: "
        + str(len(lease.source.raw))
        + "\r\n\r\n"
    ).encode("ascii") + lease.source.raw


def _exchange(lease: _Lease, request: bytes, cap: int) -> bytes:
    lease.claim(request, cap)
    peer: socket.socket | None = None
    received = bytearray()
    try:
        peer = _connection(cap / 1_000_000_000)
        upload_cap = min(cap, int(lease.check(not_after_ns=cap)["monotonic_ns"]) + 30_000_000_000)
        offset = 0
        while offset < len(request):
            peer.settimeout(_budget(lease, upload_cap))
            try:
                sent = peer.send(request[offset : offset + 65536])
            except TimeoutError:
                continue  # Same socket and original cap; never another request.
            _require(type(sent) is int and 0 < sent <= len(request) - offset)
            offset += sent
            lease.check(not_after_ns=upload_cap)
        while True:
            peer.settimeout(_budget(lease, cap))
            try:
                chunk = peer.recv(min(65536, _LIMIT + 1 - len(received)))
            except TimeoutError:
                continue
            room = _LIMIT - len(received)
            received.extend(chunk[:room])  # Retain bounded original prefix even at overflow.
            _require(len(chunk) <= room)
            lease.check(not_after_ns=cap)
            if not chunk:
                return bytes(received)
            if b"\r\n\r\n" not in received:
                _require(len(received) < 8192)
    finally:
        try:
            if peer is not None:
                peer.close()
        finally:
            lease.retain("build-response.http", bytes(received))


def _body(raw: bytes) -> bytes:
    head, separator, body = raw.partition(b"\r\n\r\n")
    _require(separator == b"\r\n\r\n" and len(head) + 4 <= 8192 and 0 < len(body) <= 1048576)
    lines = head.split(b"\r\n")
    _require(re.fullmatch(rb"HTTP/1\.[01] 200(?: [\x20-\x7e]*)?", lines[0]) is not None)
    headers: dict[bytes, bytes] = {}
    for line in lines[1:]:
        name, colon, value = line.partition(b":")
        _require(colon == b":" and re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) is not None)
        _require(all(character == 9 or 32 <= character <= 126 for character in value))
        key = name.lower()
        _require(key not in headers)
        headers[key] = value.strip(b" \t")
    _require(
        headers.get(b"content-type") == b"application/json" and b"transfer-encoding" not in headers
    )
    _require(headers.get(b"content-encoding", b"identity") == b"identity")
    if b"content-length" in headers:
        length = headers[b"content-length"]
        _require(re.fullmatch(rb"[1-9][0-9]{0,6}", length) is not None and int(length) == len(body))
    return body


def _build(lease: _Lease) -> ImageProfile:
    """Private actual-context operation; supplied data or old receipts cannot dispatch."""
    try:
        _require(type(lease) is _Lease)
        deadline = lease.begin_build()
        version = StockEngineReader._get("/version", not_after_ns=deadline)
        lease.retain("engine.bin", version)
        lease.check(not_after_ns=deadline)
        profile = verify_engine_version(version)
        record = _object(version)
        _require(record.get("Version") == "29.1.3" and profile.architecture == "amd64")
        raw = _exchange(lease, _request(lease), deadline)
        lease.check(not_after_ns=deadline)
        image_id = build_image_id(_body(raw))
        metadata = StockEngineReader._get(
            "/v1.52/images/" + image_id + "/json", not_after_ns=deadline
        )
        lease.retain("image.bin", metadata)
        lease.check(not_after_ns=deadline)
        image = verify_image(metadata, image_id, profile)
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
        lease.check(not_after_ns=deadline)
        return image
    except _ERRORS:
        _deny()
