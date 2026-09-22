"""Bounded structural DBN metadata scan; mapping identities are not resolved here."""

import hashlib
import struct
from collections.abc import Callable
from datetime import date

from trading_bot.market_data.databento_batch import DefinitionRequest, require


def _text(value: bytes) -> str:
    first = value.find(b"\0")
    require(first > 0 and not any(value[first:]), "databento_dbn_invalid")
    text = value[:first].decode("ascii")
    require(all(32 <= ord(char) <= 126 for char in text), "databento_dbn_invalid")
    return text


def scan_metadata(
    read: Callable[[int], bytes], *, expected: DefinitionRequest, max_bytes: int
) -> tuple[int, dict[str, object]]:
    """Validate framing, exact request fields and mapping dates with constant memory.

    Native mappings stay in the immutable raw file. Structural scanning does not
    certify cross-row uniqueness, conflict-free joins or historical availability.
    """
    prefix = read(8)
    require(len(prefix) == 8 and prefix[:3] == b"DBN", "databento_dbn_invalid")
    version = prefix[3]
    require(version in (1, 2, 3), "databento_dbn_invalid")
    length = struct.unpack("<I", prefix[4:])[0]
    require(length >= 120, "databento_dbn_invalid")
    require(length + 8 <= max_bytes, "databento_limit_exceeded")
    remaining = length
    digest = hashlib.sha256(prefix)

    def take(count: int) -> bytes:
        nonlocal remaining
        require(0 <= count <= remaining, "databento_dbn_invalid")
        value = read(count)
        require(len(value) == count, "databento_dbn_invalid")
        remaining -= count
        digest.update(value)
        return value

    def u32() -> int:
        return int(struct.unpack("<I", take(4))[0])

    fixed = prefix + take(100)
    require(_text(fixed[8:24]) == "OPRA.PILLAR", "databento_dbn_invalid")
    require(struct.unpack("<H", fixed[24:26])[0] == 9, "databento_dbn_invalid")
    require(
        struct.unpack("<QQQ", fixed[26:50]) == (expected.start_ns, expected.end_ns, 0),
        "databento_dbn_invalid",
    )
    position = 58 if version == 1 else 50
    require(fixed[position : position + 3] == bytes([4, 0, 0]), "databento_dbn_invalid")
    width = 22 if version == 1 else struct.unpack("<H", fixed[53:55])[0]
    require(2 <= width <= 1024, "databento_dbn_invalid")
    require(u32() == 0, "databento_dbn_invalid")  # schema extension unsupported
    require(u32() == 1, "databento_dbn_invalid")
    require(_text(take(width)) == expected.parent, "databento_dbn_invalid")
    partial = u32()
    require(partial <= remaining // width, "databento_dbn_invalid")
    for _ in range(partial):
        _text(take(width))
    require(u32() == 0, "databento_dbn_invalid")  # unresolved not-found requests
    mappings = u32()
    require(mappings <= remaining // (width + 4), "databento_dbn_invalid")
    intervals = 0
    for _ in range(mappings):
        _text(take(width))
        count = u32()
        require(count <= remaining // (width + 8), "databento_dbn_invalid")
        intervals += count
        for _ in range(count):
            start, end = struct.unpack("<II", take(8))
            date(start // 10000, start // 100 % 100, start % 100)
            date(end // 10000, end // 100 % 100, end % 100)
            require(start < end, "databento_dbn_invalid")
            _text(take(width))
    if version == 3:
        require(remaining == (-(length - remaining)) % 8, "databento_dbn_invalid")
        require(not any(take(remaining)), "databento_dbn_invalid")
    require(remaining == 0, "databento_dbn_invalid")
    return version, {
        "byte_count": length + 8,
        "sha256": digest.hexdigest(),
        "mapping_count": mappings,
        "mapping_interval_count": intervals,
        "partial_symbol_count": partial,
        "mapping_resolution_verified": False,
    }
