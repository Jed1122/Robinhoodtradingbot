"""Closed native quote schemas. Integrity fields cannot grant economic/live eligibility."""

from dataclasses import asdict, fields
from pathlib import Path
from typing import cast

from trading_bot.config import LoadedConfig
from trading_bot.market_data.bundle_codec import _array, _json, _mapping, _string
from trading_bot.market_data.databento_bar_wire import FALSE_FLAGS, bounds, decode_conditions
from trading_bot.market_data.databento_batch import require
from trading_bot.market_data.databento_quote_models import (
    NativeQuotePart,
    NativeQuoteProfile,
    NativeQuoteRequest,
    NativeQuoteRow,
    QuoteArchive,
    QuoteChunk,
    VerifiedQuoteStage,
)
from trading_bot.market_data.recording import canonical_json

SCHEMA = "native-quotes-v1"
COLUMNS = {
    "record_ordinal": "UBIGINT",
    "dbn_version": "UINTEGER",
    "schema": "VARCHAR",
    "raw_symbol": "VARCHAR",
    "publisher_id": "UINTEGER",
    "instrument_id": "UINTEGER",
    "ts_event": "UBIGINT",
    "ts_recv": "UBIGINT",
    "price": "BIGINT",
    "size": "UINTEGER",
    "action": "VARCHAR",
    "side": "VARCHAR",
    "flags": "UINTEGER",
    "ts_in_delta": "INTEGER",
    "bid_px": "BIGINT",
    "ask_px": "BIGINT",
    "bid_sz": "UINTEGER",
    "ask_sz": "UINTEGER",
    "bid_pb": "UINTEGER",
    "ask_pb": "UINTEGER",
    "bid_ct": "UINTEGER",
    "ask_ct": "UINTEGER",
    "depth": "UINTEGER",
    "sequence": "UINTEGER",
    "raw_record_hex": "VARCHAR",
    "record_hash": "VARCHAR",
    "raw_hash": "VARCHAR",
    "disposition": "VARCHAR",
    "reasons": "VARCHAR[]",
}


def decode_request(value: object) -> NativeQuoteRequest:
    query = _mapping(
        value,
        {
            "dataset",
            "schema",
            "stype_in",
            "symbols",
            "stype_out",
            "start",
            "end",
            "limit",
            "encoding",
            "compression",
        },
    )
    result = NativeQuoteRequest(
        _string(query["dataset"]),
        _string(query["schema"]),
        _string(query["stype_in"]),
        tuple(_string(s) for s in _array(query["symbols"])),
        cast(int, query["start"]),
        cast(int, query["end"]),
    )
    require(canonical_json(query) == canonical_json(result.query()))
    return result


def encode_manifest(dataset: VerifiedQuoteStage) -> bytes:
    value = asdict(dataset)
    value.pop("manifest_path")
    value.pop("manifest_hash")
    value["request"] = dataset.request.query()
    return canonical_json({"schema": SCHEMA, "columns": COLUMNS, **value}).encode()


def decode_manifest(body: bytes, path: Path, loaded: LoadedConfig) -> VerifiedQuoteStage:
    limits = bounds(loaded)
    wire = _mapping(
        _json(body, max_bytes=limits.max_envelope_bytes, limits=limits),
        {
            "schema",
            "columns",
            "config_hash",
            "request",
            "profile",
            "parts",
            "archives",
            "conditions",
            *FALSE_FLAGS,
        },
    )
    require(wire["schema"] == SCHEMA and wire["columns"] == COLUMNS)
    require(wire["config_hash"] == loaded.config_hash)
    require(all(wire[name] is False for name in FALSE_FLAGS))
    request = decode_request(wire["request"])
    raw_profile = _mapping(wire["profile"], {f.name for f in fields(NativeQuoteProfile)})
    require(all(raw_profile[f.name] is False for f in fields(NativeQuoteProfile) if not f.init))
    require(canonical_json(raw_profile["request"]) == canonical_json(asdict(request)))
    parameters = {f.name: raw_profile[f.name] for f in fields(NativeQuoteProfile) if f.init}
    parameters["request"] = request
    quality = []
    for entry in _array(parameters["quality_counts"]):
        pair = _array(entry)
        require(len(pair) == 2)
        quality.append((_string(pair[0]), pair[1]))
    parameters["quality_counts"] = tuple(quality)
    profile = NativeQuoteProfile(**parameters)  # type: ignore[arg-type]
    parts = tuple(
        NativeQuotePart(**_mapping(value, {f.name for f in fields(NativeQuotePart)}))  # type: ignore[arg-type]
        for value in _array(wire["parts"])
    )
    archives = []
    for value in _array(wire["archives"]):
        item = _mapping(value, {f.name for f in fields(QuoteArchive)})
        chunks = tuple(
            QuoteChunk(**_mapping(c, {"sha256", "byte_count"}))  # type: ignore[arg-type]
            for c in _array(item["chunks"])
        )
        archives.append(
            QuoteArchive(
                _string(item["name"]), _string(item["sha256"]), cast(int, item["size"]), chunks
            )
        )
    result = VerifiedQuoteStage(
        path,
        path.stem,
        loaded.config_hash,
        request,
        profile,
        parts,
        tuple(archives),
        decode_conditions(wire["conditions"]),
    )
    settings = loaded.config.options.native_data
    require(
        profile.decoded_count <= settings.max_records and len(parts) <= settings.max_parts,
        "databento_limit_exceeded",
    )
    require(
        all(
            p.byte_count <= settings.max_part_bytes and p.record_count <= settings.max_part_rows
            for p in parts
        ),
        "databento_limit_exceeded",
    )
    require(
        sum(p.byte_count for p in parts) <= settings.max_decompressed_bytes,
        "databento_limit_exceeded",
    )
    require(
        all(a.size <= settings.max_compressed_bytes for a in archives), "databento_limit_exceeded"
    )
    require(
        sum(a.size for a in archives) <= settings.max_decompressed_bytes, "databento_limit_exceeded"
    )
    return result


def decode_row(value: dict[str, object]) -> NativeQuoteRow:
    row = _mapping(value, set(COLUMNS))
    row["reasons"] = tuple(_string(item) for item in _array(row["reasons"]))
    return NativeQuoteRow(**row)  # type: ignore[arg-type]
