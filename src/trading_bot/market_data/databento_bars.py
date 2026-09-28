"""Strict streaming SPY minute-bar intake; no canonical or historically verified bars."""

from __future__ import annotations

import hashlib
import re
import struct
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, date, datetime
from itertools import pairwise
from typing import BinaryIO

from trading_bot.domain import DataHash
from trading_bot.market_data.databento_bar_models import (
    MINUTE_NS,
    NativeBarProfile,
    NativeBarRequest,
    NativeBarRow,
    quality_reasons,
)
from trading_bot.market_data.databento_batch import DatabentoImportError, require
from trading_bot.market_data.databento_metadata import _text
from trading_bot.market_data.databento_native_io import (
    DefinitionLimits,
    _decompressed,
    _dependency,
    _Reader,
)


def _metadata(
    reader: _Reader,
    expected: NativeBarRequest,
    limits: DefinitionLimits,
) -> tuple[int, tuple[tuple[int, int, int], ...]]:
    """Resolve only the fixed SPY query's dated native identities, not availability."""
    prefix = reader.read(8)
    require(len(prefix) == 8 and prefix[:3] == b"DBN", "databento_dbn_invalid")
    version = prefix[3]
    require(version in (1, 2, 3), "databento_dbn_invalid")
    length = struct.unpack("<I", prefix[4:])[0]
    require(length >= 120, "databento_dbn_invalid")
    require(length + 8 <= limits.max_metadata_bytes, "databento_limit_exceeded")
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
    require(_text(fixed[8:24]) == "XNAS.ITCH", "databento_dbn_invalid")
    require(struct.unpack("<H", fixed[24:26])[0] == 6, "databento_dbn_invalid")
    require(
        struct.unpack("<QQQ", fixed[26:50]) == (expected.start_ns, expected.end_ns, 0),
        "databento_dbn_invalid",
    )
    offset = 58 if version == 1 else 50
    require(fixed[offset : offset + 3] == bytes([1, 0, 0]), "databento_dbn_invalid")
    width = 22 if version == 1 else struct.unpack("<H", fixed[53:55])[0]
    require(2 <= width <= 1024, "databento_dbn_invalid")
    require(u32() == 0, "databento_dbn_invalid")  # Unknown schema extensions denied.
    require(u32() == 1 and _text(take(width)) == "SPY", "databento_dbn_invalid")
    require(u32() == 0 and u32() == 0, "databento_dbn_invalid")  # No partial/missing symbols.
    require(u32() == 1 and _text(take(width)) == "SPY", "databento_dbn_invalid")
    count = u32()
    require(0 < count <= remaining // (width + 8), "databento_dbn_invalid")
    require(count <= limits.max_unique_symbols, "databento_limit_exceeded")
    intervals = []
    for _ in range(count):
        start, end = struct.unpack("<II", take(8))
        date(start // 10000, start // 100 % 100, start % 100)
        date(end // 10000, end // 100 % 100, end % 100)
        require(start < end, "databento_dbn_invalid")
        symbol = _text(take(width))
        require(re.fullmatch(r"[1-9][0-9]{0,9}", symbol) is not None, "databento_dbn_invalid")
        identifier = int(symbol)
        require(identifier < 2**32 - 1, "databento_dbn_invalid")
        intervals.append((start, end, identifier))
    intervals.sort()
    require(
        all(left[1] <= right[0] for left, right in pairwise(intervals)), "databento_dbn_invalid"
    )
    if version == 3:
        require(remaining == (-(length - remaining)) % 8, "databento_dbn_invalid")
        require(not any(take(remaining)), "databento_dbn_invalid")
    require(remaining == 0, "databento_dbn_invalid")
    return version, tuple(intervals)


def scan_bars(
    source: BinaryIO,
    *,
    expected: NativeBarRequest,
    expected_sha256: str,
    limits: DefinitionLimits,
    consume: Callable[[NativeBarRow], None] | None = None,
) -> NativeBarProfile:
    """Return integrity evidence only after complete DBN and compressed EOF validation.

    Callbacks are provisional. Consumers must discard the entire staged dataset if
    this call fails, including late footer/checksum/digest or conflicting-duplicate errors.
    """
    try:
        require(type(expected) is NativeBarRequest and type(limits) is DefinitionLimits)
        require(
            type(expected_sha256) is str
            and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None
        )
        ceiling = DefinitionLimits()
        require(
            all(
                getattr(limits, item.name) <= getattr(ceiling, item.name)
                for item in fields(ceiling)
            ),
            "databento_limit_exceeded",
        )
        dbn = _dependency("databento_dbn", "databento-dbn", "0.69.0")
        reader = _Reader(_decompressed(source, digest=expected_sha256, limits=limits))
        version, intervals = _metadata(reader, expected, limits)
        starts = tuple(interval[0] for interval in intervals)
        decoder = dbn.DBNDecoder(
            has_metadata=False,
            input_version=version,
            ts_out=False,
            upgrade_policy=dbn.VersionUpgradePolicy.AS_IS,
            compression=dbn.Compression.NONE,
        )
        count = accepted = rejected = duplicates = 0
        first = previous = None
        # Time is monotone, so keep only this minute's keys, not a whole-history set.
        seen: dict[tuple[int, int], str] = {}
        qualities: Counter[str] = Counter()
        while block := reader.read(65536):
            for record in decoder.write_and_decode(block):
                require(
                    type(record) is dbn.OHLCVMsg and int(record.rtype) == 33,
                    "databento_dbn_invalid",
                )
                raw = bytes(record)
                require(len(raw) == 56, "databento_dbn_invalid")
                count += 1
                require(count <= limits.max_records, "databento_limit_exceeded")
                stamp = int(record.ts_event)
                require(
                    expected.start_ns <= stamp < expected.end_ns and stamp % MINUTE_NS == 0,
                    "databento_dbn_invalid",
                )
                require(previous is None or previous <= stamp, "databento_dbn_invalid")
                if previous != stamp:
                    seen.clear()
                previous = stamp
                first = stamp if first is None else first
                day = datetime.fromtimestamp(stamp // 10**9, UTC).date()
                day_number = day.year * 10000 + day.month * 100 + day.day
                index = bisect_right(starts, day_number) - 1
                require(
                    index >= 0
                    and day_number < intervals[index][1]
                    and int(record.instrument_id) == intervals[index][2],
                    "databento_dbn_invalid",
                )
                key = (int(record.publisher_id), int(record.instrument_id))
                record_hash = hashlib.sha256(raw).hexdigest()
                duplicate = key in seen
                require(not duplicate or seen[key] == record_hash, "databento_dbn_invalid")
                seen[key] = record_hash
                require(len(seen) <= limits.max_unique_symbols, "databento_limit_exceeded")
                values = tuple(
                    int(getattr(record, key)) for key in ("open", "high", "low", "close")
                )
                prices = tuple(None if value == 2**63 - 1 else value for value in values)
                reasons = quality_reasons(prices)
                row = NativeBarRow(
                    record_ordinal=count - 1,
                    dbn_version=version,
                    publisher_id=key[0],
                    instrument_id=key[1],
                    interval_start_ns=stamp,
                    open_nanos=prices[0],
                    high_nanos=prices[1],
                    low_nanos=prices[2],
                    close_nanos=prices[3],
                    volume=int(record.volume),
                    record_hash=DataHash(record_hash),
                    raw_hash=DataHash(expected_sha256),
                    disposition="duplicate" if duplicate else "rejected" if reasons else "accepted",
                    reasons=reasons,
                )
                duplicates += int(duplicate)
                rejected += int(not duplicate and bool(reasons))
                accepted += int(not duplicate and not reasons)
                qualities.update(reasons)
                if consume is not None:
                    consume(row)
        require(not decoder.buffer() and count > 0, "databento_dbn_invalid")
        return NativeBarProfile(
            request=expected,
            raw_hash=DataHash(expected_sha256),
            dbn_version=version,
            decoded_count=count,
            accepted_count=accepted,
            rejected_count=rejected,
            duplicate_count=duplicates,
            first_interval_ns=first,
            last_interval_ns=previous,
            mapping_counts=(("mapping_count", 1), ("mapping_interval_count", len(intervals))),
            quality_counts=tuple(sorted(qualities.items())),
        )
    except DatabentoImportError:
        raise
    except Exception:
        # Decoder errors may contain raw provider payloads. Expose a fixed safe code only.
        raise DatabentoImportError("databento_dbn_invalid") from None
