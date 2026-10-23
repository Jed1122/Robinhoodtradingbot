"""Frozen historical HTTP/1.0 quiet-build witnesses; never native authority.

These source-derived bytes and bounded body witnesses preserve past records.
They never establish clean transport completion, current producer success,
cleanup, replay eligibility or permission to dispatch another request.
"""

from __future__ import annotations

import json
import re
from typing import NoReturn
from urllib.parse import urlencode

from infra.hybrid.stock_build_inputs import SourceArchive


def _deny() -> NoReturn:
    raise ValueError("stock_build_engine_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


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
        "POST /v1.52/build?" + query + " HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n"
        "Content-Type: application/x-tar\r\nContent-Length: " + str(len(source.raw)) + "\r\n\r\n"
    ).encode("ascii") + source.raw


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
