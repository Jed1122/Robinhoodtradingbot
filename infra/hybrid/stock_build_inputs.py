"""Bounded supplied build inputs; never extraction, native I/O or release authority."""

from __future__ import annotations

import hashlib
import re
import tarfile
from dataclasses import dataclass
from typing import NoReturn

from infra.hybrid.stock_container import _object

_SOURCE_LIMIT = 16 * 1024 * 1024
_FILE_LIMIT = 1024 * 1024
_ENTRY_LIMIT = 2048
_ROOT_FILES = frozenset(
    {"Dockerfile", ".docker-base-image", "pyproject.toml", "uv.lock", "alembic.ini",
     "compose.stock-research.yml"}
)
_TREES = frozenset({"src", "configs", "migrations"})
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_BASE = re.compile(rb"python:3\.12-slim-bookworm@sha256:[0-9a-f]{64}\n\Z")
_IMAGE_LINE = re.compile(r"sha256:[0-9a-f]{64}\n\Z")


def _deny() -> NoReturn:
    raise ValueError("stock_build_inputs_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


@dataclass(frozen=True, slots=True, repr=False)
class SourceArchive:
    digest: str
    commit: str
    raw: bytes
    base_ref: str
    dockerfile: bytes
    compose_template: bytes


def _header(raw: bytes, offset: int) -> tarfile.TarInfo:
    block = raw[offset : offset + 512]
    _require(len(block) == 512 and block[257:265] == b"ustar\x0000")
    _require(not any(block[345:500]))  # Fixed Git profile has no USTAR path prefix.
    return tarfile.TarInfo.frombuf(block, encoding="utf-8", errors="strict")


def _end(raw: bytes, offset: int, size: int) -> tuple[bytes, int]:
    _require(type(size) is int and 0 <= size <= _FILE_LIMIT)
    end = offset + 512 + size
    padded = offset + 512 + ((size + 511) // 512) * 512
    _require(padded <= len(raw) and not any(raw[end:padded]))
    return raw[offset + 512 : end], padded


def _name(raw: bytes, offset: int, info: tarfile.TarInfo) -> str:
    field = raw[offset : offset + 100]
    original, separator, rest = field.partition(b"\0")
    _require(separator == b"\0" and not any(rest))
    name = original.decode("ascii")
    if info.isdir():
        _require(name.endswith("/") and name == info.name + "/")
        name = name[:-1]
    else:
        _require(name == info.name)
    _require(re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", name) is not None)
    parts = name.split("/")
    _require(all(part not in (".", "..") for part in parts))
    _require(name in _ROOT_FILES or parts[0] in _TREES)
    _require(name == ".docker-base-image" or all(not part.startswith(".") for part in parts))
    return name


def inspect_source(raw: bytes, *, expected_sha256: str) -> SourceArchive:
    """Parse the one-global-comment Git/USTAR profile, without host extraction."""
    try:
        _require(type(raw) is bytes and 0 < len(raw) <= _SOURCE_LIMIT and len(raw) % 512 == 0)
        _require(type(expected_sha256) is str and _HEX.fullmatch(expected_sha256) is not None)
        _require(hashlib.sha256(raw).hexdigest() == expected_sha256)
        first = _header(raw, 0)
        _require(first.type == tarfile.XGLTYPE and first.uid == first.gid == 0)
        _require(0 < first.size <= 128)
        comment, offset = _end(raw, 0, first.size)
        match = re.fullmatch(rb"([1-9][0-9]{1,2}) comment=([0-9a-f]{40}|[0-9a-f]{64})\n", comment)
        if match is None:
            _deny()
        _require(int(match[1]) == len(comment))
        commit = match[2].decode("ascii")
        entries: dict[str, bool] = {}
        assets: dict[str, bytes] = {}
        while raw[offset : offset + 512] != bytes(512):
            _require(len(entries) < _ENTRY_LIMIT)
            info = _header(raw, offset)
            _require(info.type in (tarfile.REGTYPE, tarfile.DIRTYPE))
            _require(info.uid == info.gid == 0 and not info.linkname and info.sparse is None)
            _require(info.mode == 0o755 if info.isdir() else info.mode in (0o644, 0o755))
            _require(not info.isdir() or info.size == 0)
            name = _name(raw, offset, info)
            _require(name not in entries)
            body, offset = _end(raw, offset, info.size)
            entries[name] = info.isdir()
            if name in _ROOT_FILES:
                _require(not info.isdir() and bool(body))
                assets[name] = body
        _require(len(raw) - offset >= 1024 and not any(raw[offset:]))
        _require(assets.keys() == _ROOT_FILES)
        _require(all(entries.get(tree) is True for tree in _TREES))
        for name in entries:
            parts = name.split("/")
            _require(all(entries.get("/".join(parts[:i])) is True for i in range(1, len(parts))))
        _require(
            all(
                any(
                    name.startswith(tree + "/") and not directory
                    for name, directory in entries.items()
                )
                for tree in _TREES
            )
        )
        base = assets[".docker-base-image"]
        _require(_BASE.fullmatch(base) is not None)
        return SourceArchive(
            expected_sha256, commit, raw, base[:-1].decode("ascii"), assets["Dockerfile"],
            assets["compose.stock-research.yml"],
        )
    except (OSError, ValueError, TypeError, OverflowError, tarfile.TarError):
        _deny()


def build_image_id(raw: bytes) -> str:
    """Data-only decode of version1/q=true's sole terminal stdout record."""
    try:
        _require(type(raw) is bytes and raw.endswith(b"\r\n"))
        value = _object(raw)
        _require(set(value) == {"stream"})
        line = value["stream"]
        _require(type(line) is str and _IMAGE_LINE.fullmatch(line) is not None)
        return str(line[:-1])
    except (ValueError, TypeError, OverflowError):
        _deny()
