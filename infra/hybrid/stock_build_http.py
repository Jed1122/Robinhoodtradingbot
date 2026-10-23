"""Bounded incremental framing for the fixed stock build response profile.

This is deliberately narrower than a general HTTP client: no close delimiting,
chunk extensions, trailers, compression, informational replies or pipelining.
It has no socket, filesystem, clock or dispatch authority.
"""

from __future__ import annotations

import re

BODY_LIMIT = 1048576
HEADER_LIMIT = 8192
WIRE_LIMIT = BODY_LIMIT + HEADER_LIMIT


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("stock_build_engine_unavailable") from None


class StockBuildHTTPResponse:
    """Consume one frame without interpreting its JSON or waiting for socket EOF."""

    def __init__(self) -> None:
        self._pending = bytearray()
        self._body = bytearray()
        self._wire_size = 0
        self._mode = "headers"
        self._length = 0

    def _headers(self, head: bytes) -> None:
        lines = head.split(b"\r\n")
        _require(re.fullmatch(rb"HTTP/1\.[01] 200(?: [\x20-\x7e]*)?", lines[0]) is not None)
        headers: dict[bytes, bytes] = {}
        for line in lines[1:]:
            name, colon, value = line.partition(b":")
            _require(
                colon == b":"
                and re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) is not None
                and all(character == 9 or 32 <= character <= 126 for character in value)
            )
            key = name.lower()
            _require(key not in headers)
            headers[key] = value.strip(b" \t")
        _require(headers.get(b"content-type") == b"application/json")
        _require(headers.get(b"content-encoding", b"identity") == b"identity")
        _require(b"trailer" not in headers)
        length, transfer = headers.get(b"content-length"), headers.get(b"transfer-encoding")
        _require((length is None) != (transfer is None))
        if length is not None:
            _require(re.fullmatch(rb"[1-9][0-9]{0,6}", length) is not None)
            self._length = int(length)
            _require(self._length <= BODY_LIMIT)
            self._mode = "length"
        else:
            _require(transfer == b"chunked" and lines[0].startswith(b"HTTP/1.1 "))
            self._mode = "chunk-size"

    def feed(self, data: bytes) -> bool:
        """Return true only at a complete frame; reject every captured extra byte."""
        _require(type(data) is bytes)
        self._wire_size += len(data)
        _require(self._wire_size <= WIRE_LIMIT)
        self._pending.extend(data)
        while True:
            if self._mode == "headers":
                end = self._pending.find(b"\r\n\r\n")
                if end < 0:
                    _require(len(self._pending) < HEADER_LIMIT)
                    return False
                _require(end + 4 <= HEADER_LIMIT)
                self._headers(bytes(self._pending[:end]))
                del self._pending[: end + 4]
            elif self._mode == "length":
                size = min(self._length - len(self._body), len(self._pending))
                self._body.extend(self._pending[:size])
                del self._pending[:size]
                if len(self._body) != self._length:
                    return False
                self._mode = "complete"
            elif self._mode == "chunk-size":
                end = self._pending.find(b"\r\n")
                if end < 0:
                    _require(len(self._pending) <= 17)
                    return False
                value = bytes(self._pending[:end])
                _require(re.fullmatch(rb"[0-9A-Fa-f]{1,16}", value) is not None)
                self._length = int(value, 16)
                _require(self._length <= BODY_LIMIT - len(self._body))
                del self._pending[: end + 2]
                self._mode = "chunk-data" if self._length else "chunk-end"
            elif self._mode == "chunk-data":
                if len(self._pending) < self._length + 2:
                    return False
                _require(self._pending[self._length : self._length + 2] == b"\r\n")
                self._body.extend(self._pending[: self._length])
                del self._pending[: self._length + 2]
                self._mode = "chunk-size"
            elif self._mode == "chunk-end":
                if len(self._pending) < 2:
                    return False
                _require(self._pending[:2] == b"\r\n" and bool(self._body))
                del self._pending[:2]
                self._mode = "complete"
            else:
                _require(not self._pending)
                return True

    def body(self) -> bytes:
        """Return decoded bytes only after a complete, nonempty frame."""
        _require(self._mode == "complete" and not self._pending and bool(self._body))
        return bytes(self._body)
