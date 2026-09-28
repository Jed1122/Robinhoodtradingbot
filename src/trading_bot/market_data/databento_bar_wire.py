"""Closed native bars manifest and row schemas. No historical trust switches."""

from dataclasses import asdict, fields
from pathlib import Path
from typing import Literal, cast

from trading_bot.config import LoadedConfig
from trading_bot.domain import ConfigHash, DataHash
from trading_bot.market_data.bundle_codec import _array, _date, _digest, _json, _mapping, _string
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.databento_bar_models import (
    NativeBarBatch,
    NativeBarDataset,
    NativeBarPart,
    NativeBarProfile,
    NativeBarRequest,
    NativeBarRow,
    NativeCondition,
    native_limits,
)
from trading_bot.market_data.databento_batch import BatchFile, require
from trading_bot.market_data.recording import canonical_json

SCHEMA = "databento-native-bars-parquet-v1"
PART_SCHEMA = "databento-native-bars-part-v1"
FALSE_FLAGS = (
    "production_eligible",
    "evidence_promotable",
    "download_authorized",
    "live_authorized",
    "economic_evidence",
)
COLUMNS = {
    "record_ordinal": "UBIGINT",
    "dbn_version": "UINTEGER",
    "publisher_id": "UINTEGER",
    "instrument_id": "UINTEGER",
    "interval_start_ns": "UBIGINT",
    "open_nanos": "BIGINT",
    "high_nanos": "BIGINT",
    "low_nanos": "BIGINT",
    "close_nanos": "BIGINT",
    "volume": "UBIGINT",
    "record_hash": "VARCHAR",
    "raw_hash": "VARCHAR",
    "disposition": "VARCHAR",
    "reasons": "VARCHAR[]",
}


def bounds(loaded: LoadedConfig) -> BundleLimits:
    native_limits(loaded)
    settings = loaded.config.options.native_data
    return BundleLimits(
        settings.max_manifest_bytes,
        settings.max_part_bytes,
        settings.max_decompressed_bytes,
        settings.max_records,
        16,
    )


def decode_request(value: object) -> NativeBarRequest:
    query = _mapping(value, set(NativeBarRequest(1, 2).query()))
    result = NativeBarRequest(cast(int, query["start"]), cast(int, query["end"]))
    require(canonical_json(query) == canonical_json(result.query()))
    return result


def decode_conditions(value: object, *, provider: bool = False) -> tuple[NativeCondition, ...]:
    result = []
    for item in _array(value):
        names = ("date", "condition") if provider else ("trading_date", "state")
        row = _mapping(item, {*names, "last_modified_date"})
        modified = row["last_modified_date"]
        result.append(
            NativeCondition(
                _date(row[names[0]]),
                cast(Literal["available", "degraded", "missing"], row[names[1]]),
                None if modified is None else _date(modified),
            )
        )
    return tuple(sorted(result, key=lambda item: item.trading_date))


def encode_manifest(
    profile: NativeBarProfile,
    batch: NativeBarBatch,
    parts: tuple[NativeBarPart, ...],
    loaded: LoadedConfig,
) -> bytes:
    payload = {
        "schema": SCHEMA,
        "config_hash": loaded.config_hash,
        "request": batch.request.query(),
        "profile": asdict(profile),
        "columns": COLUMNS,
        "files": [{"schema": PART_SCHEMA, **asdict(item)} for item in parts],
        "input_files": [asdict(item) for item in batch.files],
        "conditions": [asdict(item) for item in batch.conditions],
        **dict.fromkeys(FALSE_FLAGS, False),
    }
    return canonical_json(payload).encode()


def decode_manifest(body: bytes, path: Path, loaded: LoadedConfig) -> NativeBarDataset:
    limits = bounds(loaded)
    wire = _mapping(
        _json(body, max_bytes=limits.max_envelope_bytes, limits=limits),
        {
            "schema",
            "config_hash",
            "request",
            "profile",
            "columns",
            "files",
            "input_files",
            "conditions",
            *FALSE_FLAGS,
        },
    )
    require(wire["schema"] == SCHEMA and wire["columns"] == COLUMNS)
    require(all(wire[key] is False for key in FALSE_FLAGS))
    require(wire["config_hash"] == loaded.config_hash)
    request = decode_request(wire["request"])
    profile_wire = _mapping(wire["profile"], {item.name for item in fields(NativeBarProfile)})
    require(
        all(profile_wire[item.name] is False for item in fields(NativeBarProfile) if not item.init)
    )
    parameters = {
        item.name: profile_wire[item.name] for item in fields(NativeBarProfile) if item.init
    }
    request_wire = _mapping(parameters["request"], {"start_ns", "end_ns"})
    require(request_wire == asdict(request))
    parameters["request"] = request
    for name in ("mapping_counts", "quality_counts"):
        pairs = []
        for value in _array(parameters[name]):
            pair = _array(value)
            require(len(pair) == 2)
            pairs.append((_string(pair[0]), pair[1]))
        parameters[name] = tuple(pairs)
    profile = NativeBarProfile(**parameters)  # type: ignore[arg-type]
    parts = []
    for item in _array(wire["files"]):
        value = _mapping(item, {"schema", "path", "sha256", "byte_count", "record_count"})
        require(value.pop("schema") == PART_SCHEMA)
        parts.append(NativeBarPart(**value))  # type: ignore[arg-type]
    files = tuple(
        BatchFile(**_mapping(item, {"name", "size", "sha256"}))  # type: ignore[arg-type]
        for item in _array(wire["input_files"])
    )
    dataset = NativeBarDataset(
        path,
        DataHash(path.stem),
        ConfigHash(_string(wire["config_hash"])),
        request,
        profile,
        tuple(parts),
        files,
        decode_conditions(wire["conditions"]),
    )
    settings = loaded.config.options.native_data
    require(dataset.profile.decoded_count <= settings.max_records, "databento_limit_exceeded")
    require(len(dataset.parts) <= settings.max_parts, "databento_limit_exceeded")
    require(
        all(
            item.byte_count <= settings.max_part_bytes
            and item.record_count <= settings.max_part_rows
            for item in dataset.parts
        ),
        "databento_limit_exceeded",
    )
    require(
        all(item.size <= settings.max_compressed_bytes for item in dataset.files),
        "databento_limit_exceeded",
    )
    _digest(dataset.manifest_hash)
    return dataset


def decode_row(value: dict[str, object]) -> NativeBarRow:
    row = _mapping(value, set(COLUMNS))
    row["reasons"] = tuple(_string(item) for item in _array(row["reasons"]))
    return NativeBarRow(**row)  # type: ignore[arg-type]
