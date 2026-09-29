"""Streaming native quote decoder. Callbacks are provisional until the complete EOF passes."""

from __future__ import annotations

import hashlib
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, datetime
from typing import Any, BinaryIO, Literal

from trading_bot.market_data.databento_bar_models import _hash
from trading_bot.market_data.databento_batch import DatabentoImportError, require
from trading_bot.market_data.databento_native_io import (
    DefinitionLimits,
    _decompressed,
    _dependency,
    _Reader,
)
from trading_bot.market_data.databento_quote_metadata import read_metadata
from trading_bot.market_data.databento_quote_models import (
    NativeQuoteProfile,
    NativeQuoteRequest,
    NativeQuoteRow,
    quality_reasons,
)

# Membership of the pinned DBN 0.69.0 schema, not current subscription/venue authority.
_OPRA_PUBLISHERS = frozenset((*range(20, 38), 61, 108, 109))


def _row(
    message: Any,
    raw: bytes,
    *,
    ordinal: int,
    version: int,
    expected: NativeQuoteRequest,
    symbol: str,
    raw_hash: str,
) -> NativeQuoteRow:
    publisher = int(message.publisher_id)
    require(
        publisher in (_OPRA_PUBLISHERS if expected.schema == "cmbp-1" else {2}),
        "databento_dbn_invalid",
    )
    values: dict[str, Any] = dict(
        record_ordinal=ordinal,
        dbn_version=version,
        schema=expected.schema,
        raw_symbol=symbol,
        publisher_id=publisher,
        instrument_id=int(message.instrument_id),
        ts_event=int(message.ts_event),
        ts_recv=int(message.ts_recv),
        price=int(message.price),
        size=int(message.size),
        action=str(message.action),
        side=str(message.side),
        flags=int(message.flags),
        ts_in_delta=int(message.ts_in_delta),
        bid_px=int(message.bid_px_00),
        ask_px=int(message.ask_px_00),
        bid_sz=int(message.bid_sz_00),
        ask_sz=int(message.ask_sz_00),
        raw_record_hex=raw.hex(),
        record_hash=hashlib.sha256(raw).hexdigest(),
        raw_hash=raw_hash,
        bid_pb=None,
        ask_pb=None,
        bid_ct=None,
        ask_ct=None,
        depth=None,
        sequence=None,
    )
    if expected.schema == "cmbp-1":
        values.update(bid_pb=int(message.bid_pb_00), ask_pb=int(message.ask_pb_00))
        require(
            all(
                values[name] == 0 or values[name] in _OPRA_PUBLISHERS
                for name in ("bid_pb", "ask_pb")
            ),
            "databento_dbn_invalid",
        )
    else:
        values.update(
            bid_ct=int(message.bid_ct_00),
            ask_ct=int(message.ask_ct_00),
            depth=int(message.depth),
            sequence=int(message.sequence),
        )
    reasons = quality_reasons(
        **{
            key: values[key]
            for key in (
                "schema",
                "publisher_id",
                "side",
                "ts_in_delta",
                "flags",
                "ts_event",
                "ts_recv",
                "action",
                "bid_px",
                "ask_px",
                "bid_sz",
                "ask_sz",
                "bid_pb",
                "ask_pb",
            )
        }
    )
    disposition: Literal["accepted", "rejected", "control"] = (
        "control" if values["action"] == "R" else "rejected" if reasons else "accepted"
    )
    return NativeQuoteRow(**values, reasons=reasons, disposition=disposition)


def scan_quotes(
    source: BinaryIO,
    *,
    expected: NativeQuoteRequest,
    expected_sha256: str,
    limits: DefinitionLimits,
    consume: Callable[[NativeQuoteRow], None] | None = None,
) -> NativeQuoteProfile:
    """Retain every occurrence, including identical bytes and nanosecond ties.

    No sequence/time tuple proves uniqueness for these normalized schemas. A repeat
    counter is diagnostic only. Source digest + ordinal identifies each occurrence.
    The caller must discard provisional output on ANY late digest/footer error.
    """
    try:
        require(type(expected) is NativeQuoteRequest and type(limits) is DefinitionLimits)
        require(_hash(expected_sha256))
        ceiling = DefinitionLimits()
        require(
            all(getattr(limits, f.name) <= getattr(ceiling, f.name) for f in fields(ceiling)),
            "databento_limit_exceeded",
        )
        dbn = _dependency("databento_dbn", "databento-dbn", "0.69.0")
        reader = _Reader(_decompressed(source, digest=expected_sha256, limits=limits))
        metadata = read_metadata(reader, expected, limits)
        decoder = dbn.DBNDecoder(
            has_metadata=False,
            input_version=metadata.version,
            upgrade_policy=dbn.VersionUpgradePolicy.AS_IS,
            ts_out=False,
            compression=dbn.Compression.NONE,
        )
        counts: Counter[str] = Counter()
        quality: Counter[str] = Counter()
        first = previous = None
        previous_raw = b""
        ordinal = repeats = 0
        rtype = 177 if expected.schema == "cmbp-1" else 1
        while header := reader.read(1):
            require(ordinal < limits.max_records, "databento_limit_exceeded")
            require(header[0] == 20, "databento_dbn_invalid")
            raw = header + reader.read(79)
            require(len(raw) == 80 and raw[1] == rtype, "databento_dbn_invalid")
            decoder.write(raw)
            messages = decoder.decode()
            require(len(messages) == 1 and bytes(messages[0]) == raw, "databento_dbn_invalid")
            message = messages[0]
            stamp = int(message.ts_recv)
            require(expected.start_ns <= stamp < expected.end_ns, "databento_dbn_invalid")
            require(previous is None or previous <= stamp, "databento_dbn_invalid")
            day = datetime.fromtimestamp(stamp // 10**9, UTC).date()
            date_key = day.year * 10000 + day.month * 100 + day.day
            intervals = metadata.mappings.get(int(message.instrument_id), ())
            index = bisect_right(intervals, date_key, key=lambda item: item[0]) - 1
            require(index >= 0 and date_key < intervals[index][1], "databento_dbn_invalid")
            row = _row(
                message,
                raw,
                ordinal=ordinal,
                version=metadata.version,
                expected=expected,
                symbol=intervals[index][2],
                raw_hash=expected_sha256,
            )
            counts[row.disposition] += 1
            quality.update(row.reasons)
            repeats += int(previous_raw == raw)
            previous_raw = raw
            first = stamp if first is None else first
            previous = stamp
            ordinal += 1
            if consume is not None:
                consume(row)
        return NativeQuoteProfile(
            expected,
            expected_sha256,
            metadata.version,
            ordinal,
            counts["accepted"],
            counts["rejected"],
            counts["control"],
            repeats,
            first,
            previous,
            tuple(sorted(quality.items())),
        )
    except DatabentoImportError:
        raise
    except Exception:
        raise DatabentoImportError() from None
