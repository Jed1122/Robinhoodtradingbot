"""Bounded local Engine metadata reads, with no Docker mutation or retry API.

The fixed Linux root-owned Unix socket is the only endpoint. HTTP/1.0 close
framing avoids accepting chunked/streaming messages; native compatibility still
requires verification. Returned bytes must pass the separate policy verifiers.
"""

from __future__ import annotations

import os
import re
import socket
import stat
import struct
import sys
import time
from typing import NoReturn

from infra.hybrid.stock_container import API_VERSION

_IO_SECONDS = 5.0
_HEAD_LIMIT = 8192
_BODY_LIMIT = 1048576
_CID = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_HEADER = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_LENGTH = re.compile(r"(0|[1-9][0-9]{0,6})\Z")


def _deny() -> NoReturn:
    raise ValueError("stock_engine_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    _require(remaining > 0)
    return min(remaining, _IO_SECONDS)


def _connection(deadline: float) -> socket.socket:
    """Only a root daemon on the fixed root-controlled socket is supported."""
    _require(sys.platform == "linux" and os.geteuid() == 0)
    peer_option = getattr(socket, "SO_PEERCRED", None)
    if type(peer_option) is not int:
        _deny()
    info = os.lstat("/var/run/docker.sock")
    _require(stat.S_ISSOCK(info.st_mode) and info.st_uid == 0 and info.st_mode & 0o007 == 0)
    peer: socket.socket | None = None
    try:
        peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        peer.settimeout(_remaining(deadline))
        peer.connect("/var/run/docker.sock")
        pid, uid, _gid = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, peer_option, 12))
        _require(pid > 0 and uid == 0)
        _remaining(deadline)
        return peer
    except BaseException:
        if peer is not None:
            peer.close()
        raise


def _receive(peer: socket.socket, deadline: float, size: int) -> bytes:
    peer.settimeout(_remaining(deadline))
    result = peer.recv(size)
    _remaining(deadline)
    return result


def _headers(peer: socket.socket, deadline: float) -> tuple[dict[str, str], bytes]:
    buffered = b""
    while b"\r\n\r\n" not in buffered:
        _require(len(buffered) < _HEAD_LIMIT)
        chunk = _receive(peer, deadline, min(4096, _HEAD_LIMIT - len(buffered)))
        _require(bool(chunk))
        buffered += chunk
    head, body = buffered.split(b"\r\n\r\n", 1)
    lines = head.split(b"\r\n")
    _require(re.fullmatch(rb"HTTP/1\.[01] 200(?: [\x20-\x7e]*)?", lines[0]) is not None)
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, separator, value = line.partition(b":")
        _require(separator == b":" and _HEADER.fullmatch(name) is not None)
        _require(all(character == 9 or 32 <= character <= 126 for character in value))
        key = name.decode("ascii").lower()
        _require(key not in headers)
        headers[key] = value.decode("ascii").strip(" \t")
    _require("transfer-encoding" not in headers)
    return headers, body


def _body(peer: socket.socket, deadline: float, headers: dict[str, str], buffered: bytes) -> bytes:
    if "content-length" in headers:
        text = headers["content-length"]
        _require(_LENGTH.fullmatch(text) is not None)
        size = int(text)
        _require(0 < size <= _BODY_LIMIT and len(buffered) <= size)
        while len(buffered) < size:
            chunk = _receive(peer, deadline, min(65536, size - len(buffered)))
            _require(bool(chunk))
            buffered += chunk
    else:
        while True:
            _require(len(buffered) <= _BODY_LIMIT)
            chunk = _receive(peer, deadline, min(65536, _BODY_LIMIT + 1 - len(buffered)))
            if not chunk:
                break
            buffered += chunk
        _require(0 < len(buffered) <= _BODY_LIMIT)
    return buffered


def _route(path: str) -> None:
    _require(type(path) is str and len(path) <= 256)
    if path == "/version":
        return
    prefix = "/v" + API_VERSION + "/"
    _require(path.startswith(prefix))
    parts = path[len(prefix) :].split("/")
    _require(len(parts) == 3 and parts[2] == "json")
    kind, identifier, _ = parts
    if kind == "images":
        _require(_IMAGE.fullmatch(identifier) is not None)
    elif kind == "containers":
        name_prefix = "hybrid-stock-research-"
        _require(
            _CID.fullmatch(identifier) is not None
            or (
                identifier.startswith(name_prefix)
                and _ATTEMPT.fullmatch(identifier[len(name_prefix) :]) is not None
            )
        )
    else:
        _deny()


class StockEngineReader:
    """Fresh GET-only observations; no context/env/socket/path override is exposed."""

    @staticmethod
    def _get(path: str) -> bytes:
        try:
            _route(path)
            deadline = time.monotonic() + _IO_SECONDS
            with _connection(deadline) as peer:
                peer.settimeout(_remaining(deadline))
                request = (
                    "GET " + path + " HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n"
                ).encode("ascii")
                peer.sendall(request)
                headers, initial = _headers(peer, deadline)
                body = _body(peer, deadline, headers, initial)
                _remaining(deadline)
                return body
        except (OSError, ValueError, TypeError, OverflowError, struct.error):
            _deny()

    def version(self) -> bytes:
        return self._get("/version")

    def image(self, image_digest: str) -> bytes:
        _require(type(image_digest) is str and _IMAGE.fullmatch(image_digest) is not None)
        return self._get("/v" + API_VERSION + "/images/" + image_digest + "/json")

    def inspect(self, container_id: str) -> bytes:
        _require(type(container_id) is str and _CID.fullmatch(container_id) is not None)
        return self._get("/v" + API_VERSION + "/containers/" + container_id + "/json")

    def inspect_attempt(self, attempt_id: str) -> bytes:
        _require(type(attempt_id) is str and _ATTEMPT.fullmatch(attempt_id) is not None)
        return self._get(
            "/v" + API_VERSION + "/containers/hybrid-stock-research-" + attempt_id + "/json"
        )
