"""Strict streaming offline DBN definitions; provider-native research observations only."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import Any, BinaryIO

from trading_bot.market_data.databento_batch import DatabentoImportError, DefinitionRequest, require
from trading_bot.market_data.databento_metadata import scan_metadata


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


_INTEGER_FIELDS = {
    "publisher_id": None,
    "instrument_id": None,
    "raw_instrument_id": None,
    "ts_event": 2**64 - 1,
    "ts_recv": 2**64 - 1,
    "expiration": 2**64 - 1,
    "activation": 2**64 - 1,
    "strike_price": 2**63 - 1,
    "min_price_increment": 2**63 - 1,
    "display_factor": 2**63 - 1,
    "unit_of_measure_qty": 2**63 - 1,
    "contract_multiplier": 2**31 - 1,
    "contract_multiplier_unit": 127,
    "original_contract_size": 2**31 - 1,
    "underlying_id": None,
}
_TEXT_FIELDS = (
    "raw_symbol",
    "underlying",
    "asset",
    "security_type",
    "cfi",
    "currency",
    "settl_currency",
    "strike_price_currency",
    "unit_of_measure",
    "instrument_class",
    "security_update_action",
)


def _row(record: Any, ordinal: int, version: int) -> dict[str, object]:
    result: dict[str, object] = {
        "record_ordinal": ordinal,
        "dbn_version": version,
        "record_sha256": hashlib.sha256(bytes(record)).hexdigest(),
    }
    for key, sentinel in _INTEGER_FIELDS.items():
        value = int(getattr(record, key))
        result[key] = None if value == sentinel else value
    for key in _TEXT_FIELDS:
        result[key] = str(getattr(record, key))
    # V1/V2 do not contain package-leg fields. Missing is not a verified zero-leg count.
    result["leg_count"] = int(record.leg_count) if version == 3 else None
    return result


def scan_definitions(
    source: BinaryIO,
    *,
    expected: DefinitionRequest,
    expected_sha256: str,
    limits: DefinitionLimits,
    consume: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Visit native rows and return evidence only after complete compressed/DBN EOF.

    A consumer must treat all callbacks as provisional until this function returns;
    a late checksum/truncation failure invalidates the entire attempted import.
    """
    try:
        require(type(expected) is DefinitionRequest and type(limits) is DefinitionLimits)
        require(re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None)
        dbn = _dependency("databento_dbn", "databento-dbn", "0.69.0")
        reader = _Reader(_decompressed(source, digest=expected_sha256, limits=limits))
        version, metadata = scan_metadata(
            reader.read, expected=expected, max_bytes=limits.max_metadata_bytes
        )
        decoder = dbn.DBNDecoder(
            has_metadata=False,
            input_version=version,
            ts_out=False,
            upgrade_policy=dbn.VersionUpgradePolicy.AS_IS,
            compression=dbn.Compression.NONE,
        )
        record_type = {
            1: dbn.InstrumentDefMsgV1,
            2: dbn.InstrumentDefMsgV2,
            3: dbn.InstrumentDefMsg,
        }[version]
        count = outside = receive_regressions = 0
        low = high = previous = None
        symbols: set[str] = set()
        dates: Counter[str] = Counter()
        classes: Counter[str] = Counter()
        actions: Counter[str] = Counter()
        record_digest = hashlib.sha256()
        while block := reader.read(65536):
            for record in decoder.write_and_decode(block):
                require(
                    type(record) is record_type and int(record.rtype) == 19, "databento_dbn_invalid"
                )
                require(
                    len(bytes(record)) == {1: 360, 2: 400, 3: 520}[version], "databento_dbn_invalid"
                )
                row = _row(record, count, version)
                count += 1
                require(count <= limits.max_records, "databento_limit_exceeded")
                stamp = int(record.ts_recv)
                require(0 < stamp < 2**63, "databento_dbn_invalid")
                low = stamp if low is None else min(low, stamp)
                high = stamp if high is None else max(high, stamp)
                receive_regressions += int(previous is not None and stamp < previous)
                previous = stamp
                outside += int(not expected.start_ns <= stamp < expected.end_ns)
                dates[datetime.fromtimestamp(stamp // 10**9, UTC).date().isoformat()] += 1
                symbols.add(str(record.raw_symbol))
                require(len(symbols) <= limits.max_unique_symbols, "databento_limit_exceeded")
                classes[str(record.instrument_class)] += 1
                actions[str(record.security_update_action)] += 1
                record_digest.update(bytes(record))
                if consume is not None:
                    consume(row)
        require(not decoder.buffer() and count > 0, "databento_dbn_invalid")
        return {
            "schema": "databento-definitions-validation-v1",
            "dbn_version": version,
            "decoder": "databento-dbn==0.69.0",
            "compression_decoder": "zstandard==0.25.0",
            "raw_sha256": expected_sha256,
            "metadata": metadata,
            "request": expected.query(),
            "record_count": count,
            "record_bytes_sha256": record_digest.hexdigest(),
            "unique_raw_symbols": len(symbols),
            "receive_date_counts": dict(sorted(dates.items())),
            "instrument_class_counts": dict(sorted(classes.items())),
            "security_update_action_counts": dict(sorted(actions.items())),
            "min_ts_recv": low,
            "max_ts_recv": high,
            "receive_timestamp_regressions": receive_regressions,
            "outside_requested_receive_window_rows": outside,
            "unknown_premium_multiplier_rows": count,
            "record_validation_complete": True,
            "complete_chains_verified": False,
            "historical_availability_verified": False,
            "contract_enrichment_complete": False,
            "economic_evidence": False,
            "production_eligible": False,
        }
    except DatabentoImportError:
        raise
    except Exception:
        # Decoder exceptions may contain provider strings: never propagate those payloads.
        raise DatabentoImportError("databento_dbn_invalid") from None
