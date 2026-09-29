"""Bounded DBN metadata and dated query identities; no historical-availability claim."""

import re
import struct
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from trading_bot.market_data.databento_batch import require
from trading_bot.market_data.databento_metadata import _text
from trading_bot.market_data.databento_native_io import DefinitionLimits, _Reader
from trading_bot.market_data.databento_quote_models import NativeQuoteRequest


@dataclass(frozen=True, slots=True)
class QuoteMetadata:
    version: int
    # Sorted intervals for each instrument ID. Dates are YYYYMMDD, end exclusive.
    mappings: dict[int, tuple[tuple[int, int, str], ...]]


def read_metadata(
    reader: _Reader, expected: NativeQuoteRequest, limits: DefinitionLimits
) -> QuoteMetadata:
    prefix = reader.read(8)
    require(len(prefix) == 8 and prefix[:3] == b"DBN", "databento_dbn_invalid")
    version = prefix[3]
    require(version in (1, 2, 3), "databento_dbn_invalid")
    length = struct.unpack("<I", prefix[4:])[0]
    require(length >= 120 and length + 8 <= limits.max_metadata_bytes, "databento_limit_exceeded")
    remaining = length

    def take(count: int) -> bytes:
        nonlocal remaining
        require(0 <= count <= remaining, "databento_dbn_invalid")
        value = reader.read(count)
        require(len(value) == count, "databento_dbn_invalid")
        remaining -= count
        return value

    def u32() -> int:
        return int(struct.unpack("<I", take(4))[0])

    fixed = prefix + take(100)
    require(_text(fixed[8:24]) == expected.dataset, "databento_dbn_invalid")
    schema_id = 14 if expected.schema == "cmbp-1" else 1
    require(struct.unpack("<H", fixed[24:26])[0] == schema_id, "databento_dbn_invalid")
    require(
        struct.unpack("<QQQ", fixed[26:50]) == (expected.start_ns, expected.end_ns, 0),
        "databento_dbn_invalid",
    )
    offset = 58 if version == 1 else 50
    require(fixed[offset : offset + 3] == bytes([1, 0, 0]), "databento_dbn_invalid")
    width = 22 if version == 1 else struct.unpack("<H", fixed[53:55])[0]
    require(2 <= width <= 1024 and u32() == 0, "databento_dbn_invalid")
    count = u32()
    require(
        count == len(expected.symbols) and count <= limits.max_unique_symbols,
        "databento_dbn_invalid",
    )
    require(
        tuple(_text(take(width)) for _ in range(count)) == expected.symbols, "databento_dbn_invalid"
    )
    require(u32() == 0 and u32() == 0, "databento_dbn_invalid")
    require(u32() == count, "databento_dbn_invalid")
    seen = set()
    mappings: dict[int, list[tuple[int, int, str]]] = {}
    total = 0
    for _ in range(count):
        symbol = _text(take(width))
        require(symbol in expected.symbols and symbol not in seen, "databento_dbn_invalid")
        seen.add(symbol)
        intervals = u32()
        total += intervals
        require(0 < intervals <= remaining // (width + 8), "databento_dbn_invalid")
        require(total <= limits.max_unique_symbols, "databento_limit_exceeded")
        dates = []
        for _ in range(intervals):
            start, end = struct.unpack("<II", take(8))
            date(start // 10000, start // 100 % 100, start % 100)
            date(end // 10000, end // 100 % 100, end % 100)
            require(start < end, "databento_dbn_invalid")
            identity = _text(take(width))
            require(re.fullmatch(r"[1-9][0-9]{0,9}", identity) is not None, "databento_dbn_invalid")
            instrument = int(identity)
            require(instrument < 2**32 - 1, "databento_dbn_invalid")
            mappings.setdefault(instrument, []).append((start, end, symbol))
            dates.append((start, end))
        require(all(a[1] <= b[0] for a, b in pairwise(sorted(dates))), "databento_dbn_invalid")
    for values in mappings.values():
        values.sort()
        # Two symbols cannot identify the same instrument at the same native date.
        require(all(a[1] <= b[0] for a, b in pairwise(values)), "databento_dbn_invalid")
    if version == 3:
        require(remaining == (-(length - remaining)) % 8, "databento_dbn_invalid")
        require(not any(take(remaining)), "databento_dbn_invalid")
    require(remaining == 0, "databento_dbn_invalid")
    return QuoteMetadata(version, {key: tuple(value) for key, value in mappings.items()})
