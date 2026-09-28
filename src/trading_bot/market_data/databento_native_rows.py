"""Byte-bound native readers. File integrity never supplies missing contract terms."""

from __future__ import annotations

import hashlib
import os
import re
import struct
from collections import Counter
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from trading_bot.config import LoadedConfig
from trading_bot.market_data.bundle_codec import _array, _json, _mapping
from trading_bot.market_data.bundle_store import _subdirectory
from trading_bot.market_data.databento_bar_models import (
    NativeBarDataset,
    NativeBarRow,
    _hash,
    _integer,
    native_limits,
)
from trading_bot.market_data.databento_bar_store import _private_root, _read
from trading_bot.market_data.databento_bar_wire import COLUMNS, bounds, decode_manifest, decode_row
from trading_bot.market_data.databento_batch import DatabentoImportError, require
from trading_bot.market_data.databento_stage import _COLUMNS as DEFINITION_COLUMNS
from trading_bot.market_data.databento_stage import verify_staged
from trading_bot.market_data.options_parquet import _connection, _private_temp_directory
from trading_bot.market_data.recording import canonical_json, content_hash


@dataclass(frozen=True, slots=True)
class NativeDefinitionRow:
    record_ordinal: int
    dbn_version: int
    record_sha256: str
    publisher_id: int
    instrument_id: int
    raw_instrument_id: int
    ts_event: int | None
    ts_recv: int | None
    expiration: int | None
    activation: int | None
    strike_price: int | None
    min_price_increment: int | None
    display_factor: int | None
    unit_of_measure_qty: int | None
    contract_multiplier: int | None
    contract_multiplier_unit: int | None
    original_contract_size: int | None
    underlying_id: int
    raw_symbol: str
    underlying: str
    asset: str
    security_type: str
    cfi: str
    currency: str
    settl_currency: str
    strike_price_currency: str
    unit_of_measure: str
    instrument_class: str
    security_update_action: str
    leg_count: int | None

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            kind = DEFINITION_COLUMNS[item.name]
            if kind == "VARCHAR":
                require(type(value) is str and len(value) <= 1024)
            elif value is not None:
                require(type(value) is int)
                require(-(2**63) <= value < 2**64)
                if kind.startswith("U"):
                    require(value >= 0)
        for name in (
            "record_ordinal",
            "dbn_version",
            "publisher_id",
            "instrument_id",
            "raw_instrument_id",
            "underlying_id",
        ):
            require(type(getattr(self, name)) is int)
        require(_integer(self.dbn_version, 1, 3) and _hash(self.record_sha256))


def definition_projection_hash(row: NativeDefinitionRow) -> str:
    """Bind the exact projection, not omitted native bytes or file-order diagnostics."""
    require(type(row) is NativeDefinitionRow)
    value = asdict(row)
    value.pop("record_ordinal")
    return content_hash({"schema": "native-definition-projection-v1", "fields": value})


def _snapshot(parent: int, relative: str, size: int, digest: str, target: Path) -> Path:
    require(type(relative) is str and ".." not in relative and not relative.startswith("/"))
    with ExitStack() as directories:
        directory = parent
        components = relative.split("/")
        for component in components[:-1]:
            directory = _subdirectory(directory, component, create=False)
            directories.callback(os.close, directory)
        body = _read(directory, components[-1], size)
    require(len(body) == size and hashlib.sha256(body).hexdigest() == digest)
    with target.open("xb") as output:
        os.chmod(target, 0o600)
        output.write(body)
    return target


def _rows(connection: Any, snapshot: Path, columns: dict[str, str]) -> Iterator[dict[str, object]]:
    observed = connection.execute(
        "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)", [str(snapshot)]
    ).fetchall()
    require(tuple((row[0], row[1]) for row in observed) == tuple(columns.items()))
    cursor = connection.execute(
        "SELECT * FROM read_parquet(?, hive_partitioning=false)", [str(snapshot)]
    )
    while values := cursor.fetchmany(512):
        for row in values:
            yield dict(zip(columns, row, strict=True))


@contextmanager
def _bar_snapshots(
    path: Path, *, loaded: LoadedConfig, repository_root: Path
) -> Iterator[tuple[NativeBarDataset, tuple[Path, ...], Any]]:
    """Validate all parts before yielding; queries use private snapshots until context exit."""
    with ExitStack() as stack:
        settings = loaded.config.options.native_data
        limits = bounds(loaded)
        require(
            path.parent.name == "manifests"
            and re.fullmatch(r"[0-9a-f]{64}\.json", path.name) is not None
        )
        parent = _private_root(path.parent.parent, repository_root)
        stack.callback(os.close, parent)
        manifests = _subdirectory(parent, "manifests", create=False)
        stack.callback(os.close, manifests)
        encoded = _read(manifests, path.name, limits.max_envelope_bytes)
        require(hashlib.sha256(encoded).hexdigest() == path.stem)
        dataset = decode_manifest(encoded, path, loaded)
        temporary = Path(stack.enter_context(_private_temp_directory()))
        connection = _connection(temporary)
        stack.callback(connection.close)
        snapshots = []
        ordinal = accepted = rejected = duplicates = total_bytes = 0
        first = previous = None
        seen: dict[tuple[int, int], str] = {}
        quality: Counter[str] = Counter()
        for index, part in enumerate(dataset.parts):
            total_bytes += part.byte_count
            require(total_bytes <= settings.max_decompressed_bytes, "databento_limit_exceeded")
            snapshot = _snapshot(
                parent, part.path, part.byte_count, part.sha256, temporary / f"{index}.parquet"
            )
            snapshots.append(snapshot)
            count = 0
            for value in _rows(connection, snapshot, COLUMNS):
                row = decode_row(value)
                require(
                    row.record_ordinal == ordinal and row.dbn_version == dataset.profile.dbn_version
                )
                require(row.raw_hash == dataset.profile.raw_hash)
                require(dataset.request.start_ns <= row.interval_start_ns < dataset.request.end_ns)
                require(previous is None or previous <= row.interval_start_ns)
                if previous != row.interval_start_ns:
                    seen.clear()
                previous = row.interval_start_ns
                first = previous if first is None else first
                day = datetime.fromtimestamp(previous // 10**9, UTC).date().isoformat()
                require(part.path.split("/")[1] == "interval_date=" + day)
                prices = (row.open_nanos, row.high_nanos, row.low_nanos, row.close_nanos)
                raw = struct.pack(
                    "<BBHIQqqqqQ",
                    14,
                    33,
                    row.publisher_id,
                    row.instrument_id,
                    row.interval_start_ns,
                    *(2**63 - 1 if price is None else price for price in prices),
                    row.volume,
                )
                require(hashlib.sha256(raw).hexdigest() == row.record_hash)
                key = (row.publisher_id, row.instrument_id)
                duplicate = key in seen
                require(not duplicate or seen[key] == row.record_hash)
                require((row.disposition == "duplicate") == duplicate)
                seen[key] = row.record_hash
                require(len(seen) <= settings.max_unique_symbols, "databento_limit_exceeded")
                ordinal += 1
                count += 1
                require(
                    count <= part.record_count and ordinal <= settings.max_records,
                    "databento_limit_exceeded",
                )
                accepted += int(row.disposition == "accepted")
                rejected += int(row.disposition == "rejected")
                duplicates += int(duplicate)
                quality.update(row.reasons)
            require(count == part.record_count)
        profile = dataset.profile
        require(
            (ordinal, accepted, rejected, duplicates, first, previous)
            == (
                profile.decoded_count,
                profile.accepted_count,
                profile.rejected_count,
                profile.duplicate_count,
                profile.first_interval_ns,
                profile.last_interval_ns,
            )
        )
        require(tuple(sorted(quality.items())) == profile.quality_counts)
        yield dataset, tuple(snapshots), connection


def _window(start: int, end: int, low: int, high: int) -> None:
    require(type(start) is int and type(end) is int and low <= start < end <= high)


def read_bar_rows(
    dataset: NativeBarDataset,
    *,
    start_ns: int,
    end_ns: int,
    loaded: LoadedConfig,
    repository_root: Path,
) -> Iterator[NativeBarRow]:
    try:
        require(type(dataset) is NativeBarDataset)
        _window(start_ns, end_ns, dataset.request.start_ns, dataset.request.end_ns)
        with _bar_snapshots(
            dataset.manifest_path, loaded=loaded, repository_root=repository_root
        ) as result:
            verified, snapshots, connection = result
            require(verified == dataset)
            for snapshot in snapshots:
                for value in _rows(connection, snapshot, COLUMNS):
                    row = decode_row(value)
                    if start_ns <= row.interval_start_ns < end_ns:
                        yield row
    except DatabentoImportError:
        raise
    except Exception:
        raise DatabentoImportError() from None


def read_definition_rows(
    manifest_path: Path, *, start_ns: int, end_ns: int, loaded: LoadedConfig, repository_root: Path
) -> Iterator[NativeDefinitionRow]:
    try:
        limits = native_limits(loaded)
        settings = loaded.config.options.native_data
        with ExitStack() as stack:
            parent = _private_root(manifest_path.parent.parent, repository_root)
            stack.callback(os.close, parent)
            manifest = verify_staged(manifest_path, repository_root=repository_root)
            manifests = _subdirectory(parent, "manifests", create=False)
            stack.callback(os.close, manifests)
            body = _read(manifests, manifest_path.name, settings.max_manifest_bytes)
            require(hashlib.sha256(body).hexdigest() == manifest_path.stem)
            require(
                canonical_json(
                    _json(body, max_bytes=settings.max_manifest_bytes, limits=bounds(loaded))
                )
                == canonical_json(manifest)
            )
            profile = cast(dict[str, object], manifest["validation"])
            request = cast(dict[str, object], profile["request"])
            require(request["symbols"] == ["SPY.OPT"])
            _window(start_ns, end_ns, cast(int, request["start"]), cast(int, request["end"]))
            require(profile["record_count"] <= limits.max_records, "databento_limit_exceeded")  # type: ignore[operator]
            entries = _array(manifest["files"])
            require(len(entries) <= settings.max_parts, "databento_limit_exceeded")
            temporary = Path(stack.enter_context(_private_temp_directory()))
            connection = _connection(temporary)
            stack.callback(connection.close)
            snapshots = []
            count = total_bytes = 0
            for index, value in enumerate(entries):
                part = _mapping(value, {"path", "sha256", "byte_count", "record_count"})
                size = cast(int, part["byte_count"])
                require(
                    size <= settings.max_part_bytes
                    and part["record_count"] <= settings.max_part_rows,  # type: ignore[operator]
                    "databento_limit_exceeded",
                )
                total_bytes += size
                require(total_bytes <= limits.max_decompressed_bytes, "databento_limit_exceeded")
                snapshot = _snapshot(
                    parent,
                    cast(str, part["path"]),
                    size,
                    cast(str, part["sha256"]),
                    temporary / f"{index}.parquet",
                )
                snapshots.append(snapshot)
                observed = 0
                for native in _rows(connection, snapshot, DEFINITION_COLUMNS):
                    NativeDefinitionRow(**native)  # type: ignore[arg-type]
                    observed += 1
                    require(observed <= cast(int, part["record_count"]), "databento_limit_exceeded")
                require(observed == part["record_count"])
                count += observed
            require(count == profile["record_count"])
            for snapshot in snapshots:
                for value in _rows(connection, snapshot, DEFINITION_COLUMNS):
                    row = NativeDefinitionRow(**value)  # type: ignore[arg-type]
                    if row.ts_recv is not None and start_ns <= row.ts_recv < end_ns:
                        yield row
    except DatabentoImportError:
        raise
    except Exception:
        raise DatabentoImportError() from None
