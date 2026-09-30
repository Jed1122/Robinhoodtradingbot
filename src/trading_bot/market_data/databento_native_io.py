"""Shared bounded native byte I/O; no data-usability or source-verification authority."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
from collections.abc import Iterator
from dataclasses import dataclass, fields
from typing import Any, BinaryIO

from trading_bot.market_data.databento_batch import DatabentoImportError, require


@dataclass(frozen=True, slots=True)
class DefinitionLimits:
    """I/O resource bounds, never trading thresholds or an acquisition spending cap."""

    max_compressed_bytes: int = 512 * 1024**2
    max_decompressed_bytes: int = 4 * 1024**3
    max_metadata_bytes: int = 256 * 1024**2
    max_records: int = 10000000
    max_unique_symbols: int = 1000000

    def __post_init__(self) -> None:
        require(
            all(
                type(getattr(self, f.name)) is int and getattr(self, f.name) > 0
                for f in fields(self)
            ),
            "databento_limit_exceeded",
        )


def _dependency(name: str, distribution: str, version: str) -> Any:
    try:
        require(importlib.metadata.version(distribution) == version, "databento_dependency_missing")
        return importlib.import_module(name)
    except (ImportError, OSError):
        raise DatabentoImportError("databento_dependency_missing") from None


def _decompressed(source: BinaryIO, *, digest: str, limits: DefinitionLimits) -> Iterator[bytes]:
    zstd = _dependency("zstandard", "zstandard", "0.25.0")
    frame = None
    completed = compressed = expanded = 0
    observed = hashlib.sha256()
    # A tiny compressed feed bounds transient expansion even for extreme RLE input.
    # Window memory is independently capped at128MiB. No whole-file decompression.
    while block := source.read(512):
        observed.update(block)
        compressed += len(block)
        require(compressed <= limits.max_compressed_bytes, "databento_limit_exceeded")
        while block:
            if frame is None:
                # The pinned C backend passes this directly to ZSTD in bytes.
                frame = zstd.ZstdDecompressor(max_window_size=128 * 1024**2).decompressobj()
            decoded = frame.decompress(block)
            expanded += len(decoded)
            require(expanded <= limits.max_decompressed_bytes, "databento_limit_exceeded")
            if decoded:
                yield decoded
            if frame.eof:
                block = frame.unused_data
                completed += 1
                frame = None
            else:
                block = b""
    require(completed > 0 and frame is None, "databento_dbn_invalid")
    require(observed.hexdigest() == digest, "databento_dbn_invalid")


class _Reader:
    """Small sequential reader over bounded decoded chunks, including strict EOF checks."""

    def __init__(self, chunks: Iterator[bytes]) -> None:
        self.chunks = chunks
        self.pending = b""
        self.offset = 0

    def read(self, size: int) -> bytes:
        pieces = []
        while size:
            if self.offset == len(self.pending):
                self.pending = next(self.chunks, b"")
                self.offset = 0
                if not self.pending:
                    break
            count = min(size, len(self.pending) - self.offset)
            pieces.append(self.pending[self.offset : self.offset + count])
            self.offset += count
            size -= count
        return b"".join(pieces)
