"""Scoped create/start transport, not a launcher or deployment composition.

Every exchange owns its store claim/fence sequence. There is no caller route,
body, container ID or start-fence override. Acknowledgement is neither actual
container-policy verification, observed termination nor successful research.
"""

from __future__ import annotations

import os
import re
import socket
import struct
import sys
import time
from typing import NoReturn, cast

from infra.hybrid.stock_attempts import OPERATIONS_ROOT, AttemptStore, StartFence
from infra.hybrid.stock_container import API_VERSION, ImageProfile
from infra.hybrid.stock_engine import (
    _BODY_LIMIT,
    _HEAD_LIMIT,
    _HEADER,
    _body,
    _connection,
    _receive,
    _remaining,
)
from infra.hybrid.stock_prestart import container_name, verify_creation, worker_request
from infra.hybrid.stock_release import StockRelease

_IO_SECONDS = 5.0
_ERRORS = (
    OSError,
    ValueError,
    TypeError,
    KeyError,
    OverflowError,
    RecursionError,
    AttributeError,
    struct.error,
)


def _deny() -> NoReturn:
    raise ValueError("stock_engine_mutation_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


def _production_store(store: AttemptStore) -> None:
    _require(type(store) is AttemptStore)
    _require(sys.platform == "linux" and os.geteuid() == 0)
    _require(store._root == OPERATIONS_ROOT and store._uid == 0)


def _response(peer: socket.socket, deadline: float, expected: int) -> bytes:
    buffered = b""
    while b"\r\n\r\n" not in buffered:
        _require(len(buffered) < _HEAD_LIMIT)
        chunk = _receive(peer, deadline, min(4096, _HEAD_LIMIT - len(buffered)))
        _require(bool(chunk))
        buffered += chunk
    head, initial = buffered.split(b"\r\n\r\n", 1)
    lines = head.split(b"\r\n")
    status = re.fullmatch(rb"HTTP/1\.[01] ([0-9]{3})(?: [\x20-\x7e]*)?", lines[0])
    if status is None:
        _deny()
    _require(int(status[1]) == expected)
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, separator, value = line.partition(b":")
        _require(separator == b":" and _HEADER.fullmatch(name) is not None)
        _require(all(character == 9 or 32 <= character <= 126 for character in value))
        key = name.decode("ascii").lower()
        _require(key not in headers)
        headers[key] = value.decode("ascii").strip(" \t")
    _require("transfer-encoding" not in headers)
    if expected == 204:
        _require(headers.get("content-length", "0") == "0" and not initial)
        body = b""
    else:
        body = _body(peer, deadline, headers, initial)
    # HTTP/1.0 + Connection:close: even a delayed extra body byte denies acknowledgement.
    _require(not _receive(peer, deadline, 1))
    return body


class StockEngineMutator:
    """Uncomposed root-only library with one create/start per owning store attempt."""

    @staticmethod
    def _exchange(
        operation: str,
        store: AttemptStore,
        release: StockRelease | None = None,
        image: ImageProfile | None = None,
    ) -> tuple[bytes, StartFence | None]:
        try:
            _production_store(store)
            _require(type(operation) is str and operation in {"create", "start"})
            deadline = time.monotonic() + _IO_SECONDS
            fence = None
            if operation == "create":
                _require(type(release) is StockRelease and type(image) is ImageProfile)
                scoped_release, scoped_image = (
                    cast(StockRelease, release),
                    cast(ImageProfile, image),
                )
                claim = store.claim_create(scoped_release)
                body = worker_request(scoped_release, scoped_image, claim.attempt_id)
                path = (
                    "/v"
                    + API_VERSION
                    + "/containers/create?name="
                    + container_name(claim.attempt_id)
                )
                expected = 201
            else:
                _require(release is None and image is None)
                fence = store.prepare_start()
                body = b""
                path = "/v" + API_VERSION + "/containers/" + fence.container_id + "/start"
                expected = 204
            _require(len(body) <= _BODY_LIMIT)
            request = (
                "POST " + path + " HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n"
                "Content-Type: application/json\r\nContent-Length: " + str(len(body)) + "\r\n\r\n"
            ).encode("ascii") + body
            _remaining(deadline)
            with _connection(deadline) as peer:
                if fence is None:
                    store.check_create_claim(claim)
                else:
                    store.check_start_fence(fence)
                peer.settimeout(_remaining(deadline))
                peer.sendall(request)
                response = _response(peer, deadline, expected)
                _remaining(deadline)
                return response, fence
        except _ERRORS:
            _deny()

    def create_worker(self, store: AttemptStore, release: StockRelease, image: ImageProfile) -> str:
        try:
            body, _ = self._exchange("create", store, release, image)
            return verify_creation(body)
        except _ERRORS:
            _deny()

    def start_worker(self, store: AttemptStore) -> StartFence:
        body, fence = self._exchange("start", store)
        _require(not body and fence is not None)
        return cast(StartFence, fence)
