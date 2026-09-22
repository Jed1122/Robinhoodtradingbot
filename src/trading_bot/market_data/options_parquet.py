"""Bounded, credential-free Parquet storage for offline options research data."""

from __future__ import annotations

import hashlib
import importlib
import os
import re
import tempfile
from contextlib import ExitStack, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn, cast

from trading_bot.market_data.bundle_codec import (
    _array,
    _boolean,
    _digest,
    _integer,
    _json,
    _mapping,
    _string,
)
from trading_bot.market_data.bundle_models import BundleError, BundleLimits
from trading_bot.market_data.bundle_store import _open_root, _publish, _read, _subdirectory
from trading_bot.market_data.options_data_codec import decode_record, encode_record
from trading_bot.market_data.options_records import OptionsDataRecord
from trading_bot.market_data.recording import canonical_json

_DUCKDB_VERSION = "1.5.5"
_MANIFEST_SCHEMA = "options-parquet-dataset-v1"
_PART_SCHEMA = "options-parquet-part-v1"
_KINDS = frozenset(
    {"chain", "contract", "option_quote", "session", "underlying_quote", "corporate_action"}
)
_SOURCE_KINDS = frozenset({"synthetic", "imported"})
_PART_RE = re.compile(
    r"partitions/kind=([a-z_]+)/event_date=(\d{4}-\d{2}-\d{2})/"
    r"source_kind=(synthetic|imported)/([0-9a-f]{64})\.parquet\Z"
)
_COLUMNS = (
    ("ordinal", "UBIGINT"),
    ("record_hash", "VARCHAR"),
    ("kind", "VARCHAR"),
    ("source", "VARCHAR"),
    ("source_kind", "VARCHAR"),
    ("raw_hash", "VARCHAR"),
    ("entity_id", "VARCHAR"),
    ("event_at", "TIMESTAMP WITH TIME ZONE"),
    ("available_at", "TIMESTAMP WITH TIME ZONE"),
    ("record_json", "VARCHAR"),
)
_MANIFEST_KEYS = {
    "schema",
    "dataset_hash",
    "record_count",
    "record_hashes",
    "source_kinds",
    "production_eligible",
    "evidence_promotable",
    "columns",
    "files",
}
_FILE_KEYS = {
    "schema",
    "kind",
    "event_date",
    "source_kind",
    "path",
    "sha256",
    "byte_count",
    "record_count",
    "record_hashes",
}


class OptionsParquetError(ValueError):
    """A sanitized storage failure that never includes rejected data or paths."""

    def __init__(self, code: str = "options_dataset_invalid") -> None:
        if code not in {"options_dataset_invalid", "options_dataset_dependency_missing"}:
            code = "options_dataset_invalid"
        super().__init__(code)
        self.code = code


def _fail() -> NoReturn:
    raise OptionsParquetError()


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _duckdb() -> Any:
    try:
        module = importlib.import_module("duckdb")
    except (ImportError, OSError):
        raise OptionsParquetError("options_dataset_dependency_missing") from None
    if getattr(module, "__version__", None) != _DUCKDB_VERSION:
        raise OptionsParquetError("options_dataset_dependency_missing")
    return module


def _connection(directory: Path) -> Any:
    module = _duckdb()
    connection = None
    try:
        connection = module.connect(
            ":memory:",
            config={
                "allow_community_extensions": "false",
                "autoinstall_known_extensions": "false",
                "autoload_known_extensions": "false",
                "enable_external_file_cache": "false",
                "memory_limit": "64MB",
                "threads": "1",
            },
        )
        connection.execute("SET allowed_directories = ?", [[str(directory)]])
        connection.execute("SET enable_external_access = false")
        return connection
    except Exception:
        if connection is not None:
            with suppress(Exception):
                connection.close()
        _fail()


def _private_temp_directory() -> tempfile.TemporaryDirectory[str]:
    temporary = tempfile.TemporaryDirectory(prefix="options-parquet-")
    os.chmod(temporary.name, 0o700)
    info = os.stat(temporary.name, follow_symlinks=False)
    if info.st_uid != os.geteuid() or (info.st_mode & 0o777) != 0o700:
        temporary.cleanup()
        _fail()
    return temporary


def _create_part(path: Path, rows: list[tuple[object, ...]]) -> bytes:
    connection = _connection(path.parent)
    try:
        connection.execute(
            """
            CREATE TABLE records (
                ordinal UBIGINT NOT NULL,
                record_hash VARCHAR NOT NULL,
                kind VARCHAR NOT NULL,
                source VARCHAR NOT NULL,
                source_kind VARCHAR NOT NULL,
                raw_hash VARCHAR NOT NULL,
                entity_id VARCHAR NOT NULL,
                event_at TIMESTAMPTZ NOT NULL,
                available_at TIMESTAMPTZ NOT NULL,
                record_json VARCHAR NOT NULL
            )
            """
        )
        connection.executemany("INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        connection.execute(
            "COPY records TO ? (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880)",
            [str(path)],
        )
    except Exception:
        _fail()
    finally:
        connection.close()
    try:
        return path.read_bytes()
    except OSError:
        _fail()


def _manifest_body(
    *, files: list[dict[str, object]], records: tuple[OptionsDataRecord, ...]
) -> tuple[str, bytes]:
    preimage: dict[str, object] = {
        "schema": _MANIFEST_SCHEMA,
        "record_count": len(records),
        "record_hashes": [record.record_hash for record in records],
        "source_kinds": sorted({record.source_kind for record in records}),
        "production_eligible": False,
        "evidence_promotable": False,
        "columns": [{"name": name, "type": sql_type} for name, sql_type in _COLUMNS],
        "files": files,
    }
    dataset_hash = _sha256(canonical_json(preimage).encode("utf-8"))
    body = canonical_json({**preimage, "dataset_hash": dataset_hash}).encode("utf-8")
    return dataset_hash, body


def _publish_part(root: int, relative: str, body: bytes) -> None:
    components = relative.split("/")
    with ExitStack() as stack:
        parent = root
        for component in components[:-1]:
            parent = _subdirectory(parent, component, create=True)
            stack.callback(os.close, parent)
        _publish(parent, components[-1], body)


def publish_dataset(
    root: Path,
    records: tuple[OptionsDataRecord, ...],
    *,
    repository_root: Path,
    limits: BundleLimits,
) -> Path:
    """Publish immutable partitioned Parquet plus a content-addressed manifest."""

    try:
        if (
            type(limits) is not BundleLimits
            or type(records) is not tuple
            or not records
            or len(records) > limits.max_records
            or any(type(record) is not OptionsDataRecord for record in records)
        ):
            _fail()

        encoded_total = 0
        groups: dict[tuple[str, str, str], list[tuple[object, ...]]] = {}
        for ordinal, record in enumerate(records):
            body = encode_record(record)
            if type(body) is not bytes or len(body) > limits.max_blob_bytes:
                _fail()
            if decode_record(body, limits=limits) != record:
                _fail()
            encoded_total += len(body)
            if encoded_total > limits.max_total_bytes:
                _fail()
            key = (record.kind, record.event_at.date().isoformat(), record.source_kind)
            groups.setdefault(key, []).append(
                (
                    ordinal,
                    record.record_hash,
                    record.kind,
                    record.source,
                    record.source_kind,
                    record.raw_hash,
                    record.entity_id,
                    record.event_at,
                    record.available_at,
                    body.decode("utf-8"),
                )
            )

        parts: list[tuple[str, bytes]] = []
        files: list[dict[str, object]] = []
        artifact_total = 0
        with _private_temp_directory() as temporary_name:
            temporary = Path(temporary_name)
            for index, ((kind, event_date, source_kind), rows) in enumerate(sorted(groups.items())):
                staged = temporary / f"part-{index}.parquet"
                body = _create_part(staged, rows)
                if not body or len(body) > limits.max_blob_bytes:
                    _fail()
                artifact_total += len(body)
                if artifact_total > limits.max_total_bytes:
                    _fail()
                digest = _sha256(body)
                relative = (
                    f"partitions/kind={kind}/event_date={event_date}/"
                    f"source_kind={source_kind}/{digest}.parquet"
                )
                hashes = [cast(str, row[1]) for row in rows]
                parts.append((relative, body))
                files.append(
                    {
                        "schema": _PART_SCHEMA,
                        "kind": kind,
                        "event_date": event_date,
                        "source_kind": source_kind,
                        "path": relative,
                        "sha256": digest,
                        "byte_count": len(body),
                        "record_count": len(rows),
                        "record_hashes": hashes,
                    }
                )

        dataset_hash, manifest_body = _manifest_body(files=files, records=records)
        if (
            len(manifest_body) > limits.max_envelope_bytes
            or artifact_total + len(manifest_body) > limits.max_total_bytes
        ):
            _fail()
        _parse_manifest(manifest_body, limits=limits, expected_hash=dataset_hash)

        with ExitStack() as stack:
            parent = _open_root(root, repository_root)
            stack.callback(os.close, parent)
            for relative, body in parts:
                _publish_part(parent, relative, body)
            manifests = _subdirectory(parent, "manifests", create=True)
            stack.callback(os.close, manifests)
            _publish(manifests, dataset_hash + ".json", manifest_body)
        return root / "manifests" / (dataset_hash + ".json")
    except OptionsParquetError:
        raise
    except (BundleError, OSError, UnicodeError, ValueError, TypeError, OverflowError):
        _fail()


def _manifest_location(manifest: Path) -> tuple[Path, str]:
    if (
        not isinstance(manifest, Path)
        or not manifest.is_absolute()
        or ".." in manifest.parts
        or manifest.parent.name != "manifests"
        or not manifest.name.endswith(".json")
    ):
        _fail()
    digest = manifest.name.removesuffix(".json")
    try:
        _digest(digest)
    except BundleError:
        _fail()
    return manifest.parents[1], digest


def _parse_manifest(body: bytes, *, limits: BundleLimits, expected_hash: str) -> dict[str, object]:
    wire = _mapping(_json(body, max_bytes=limits.max_envelope_bytes, limits=limits), _MANIFEST_KEYS)
    if (
        _string(wire["schema"]) != _MANIFEST_SCHEMA
        or _digest(wire["dataset_hash"]) != expected_hash
        or _boolean(wire["production_eligible"])
        or _boolean(wire["evidence_promotable"])
    ):
        _fail()
    columns = _array(wire["columns"])
    parsed_columns = []
    for item in columns:
        column = _mapping(item, {"name", "type"})
        parsed_columns.append((_string(column["name"]), _string(column["type"])))
    if tuple(parsed_columns) != _COLUMNS:
        _fail()
    preimage = {key: value for key, value in wire.items() if key != "dataset_hash"}
    if _sha256(canonical_json(preimage).encode("utf-8")) != expected_hash:
        _fail()
    return wire


def _part_metadata(value: object) -> dict[str, object]:
    item = _mapping(value, _FILE_KEYS)
    kind = _string(item["kind"])
    event_date = _string(item["event_date"])
    source_kind = _string(item["source_kind"])
    relative = _string(item["path"])
    digest = _digest(item["sha256"])
    match = _PART_RE.fullmatch(relative)
    if (
        _string(item["schema"]) != _PART_SCHEMA
        or kind not in _KINDS
        or source_kind not in _SOURCE_KINDS
        or match is None
        or match.groups() != (kind, event_date, source_kind, digest)
    ):
        _fail()
    try:
        parsed_date = datetime.strptime(event_date, "%Y-%m-%d").date()
    except ValueError:
        _fail()
    if parsed_date.isoformat() != event_date:
        _fail()
    byte_count = _integer(item["byte_count"])
    record_count = _integer(item["record_count"])
    hashes = [_digest(value) for value in _array(item["record_hashes"])]
    if byte_count <= 0 or record_count <= 0 or len(hashes) != record_count:
        _fail()
    return item


def _read_part(root: int, relative: str, max_bytes: int) -> bytes:
    components = relative.split("/")
    with ExitStack() as stack:
        parent = root
        for component in components[:-1]:
            parent = _subdirectory(parent, component, create=False)
            stack.callback(os.close, parent)
        return _read(parent, components[-1], max_bytes)


def _materialize(path: Path, body: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(body):
            count = os.write(descriptor, memoryview(body)[written:])
            if count <= 0:
                _fail()
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _decode_part(
    path: Path,
    *,
    limits: BundleLimits,
    expected_count: int,
    remaining_record_bytes: int,
) -> tuple[list[tuple[int, OptionsDataRecord]], int]:
    connection = _connection(path.parent)
    try:
        description = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
        ).fetchall()
        actual_columns = tuple((row[0], row[1]) for row in description)
        if actual_columns != _COLUMNS:
            _fail()
        summary = connection.execute(
            """
            SELECT count(*), coalesce(max(strlen(record_json)), 0),
                   coalesce(sum(strlen(record_json)), 0)
            FROM read_parquet(?)
            """,
            [str(path)],
        ).fetchone()
        if summary is None or any(type(value) is not int for value in summary):
            _fail()
        row_count, max_record_bytes, total_record_bytes = summary
        if (
            row_count != expected_count
            or row_count > limits.max_records
            or max_record_bytes > limits.max_blob_bytes
            or total_record_bytes > remaining_record_bytes
        ):
            _fail()
        rows = connection.execute(
            """
            SELECT ordinal, record_hash, kind, source, source_kind, raw_hash, entity_id,
                   CAST(event_at AS VARCHAR), CAST(available_at AS VARCHAR), record_json
            FROM read_parquet(?) ORDER BY ordinal LIMIT ?
            """,
            [str(path), expected_count + 1],
        ).fetchall()
    except OptionsParquetError:
        raise
    except Exception:
        _fail()
    finally:
        connection.close()
    if len(rows) != expected_count:
        _fail()
    result: list[tuple[int, OptionsDataRecord]] = []
    decoded_bytes = 0
    for row in rows:
        ordinal = row[0]
        encoded_text = row[9]
        if type(ordinal) is not int or type(encoded_text) is not str:
            _fail()
        try:
            event_at = datetime.fromisoformat(row[7])
            available_at = datetime.fromisoformat(row[8])
        except (TypeError, ValueError):
            _fail()
        encoded = encoded_text.encode("utf-8")
        decoded_bytes += len(encoded)
        if (
            len(encoded) > limits.max_blob_bytes
            or decoded_bytes > total_record_bytes
            or decoded_bytes > remaining_record_bytes
        ):
            _fail()
        record = decode_record(encoded, limits=limits)
        actual_record_metadata = (
            *row[1:7],
            event_at,
            available_at,
        )
        expected = (
            record.record_hash,
            record.kind,
            record.source,
            record.source_kind,
            record.raw_hash,
            record.entity_id,
            record.event_at,
            record.available_at,
        )
        if actual_record_metadata != expected:
            _fail()
        result.append((ordinal, record))
    if decoded_bytes != total_record_bytes:
        _fail()
    return result, decoded_bytes


def read_dataset(
    manifest: Path,
    *,
    repository_root: Path,
    limits: BundleLimits,
) -> tuple[OptionsDataRecord, ...]:
    """Verify and read a locally published dataset without acquisition or network access."""

    try:
        if type(limits) is not BundleLimits:
            _fail()
        root_path, expected_hash = _manifest_location(manifest)
        with ExitStack() as stack:
            root = _open_root(root_path, repository_root)
            stack.callback(os.close, root)
            manifests = _subdirectory(root, "manifests", create=False)
            stack.callback(os.close, manifests)
            body = _read(manifests, expected_hash + ".json", limits.max_envelope_bytes)
            wire = _parse_manifest(body, limits=limits, expected_hash=expected_hash)
            declared_count = _integer(wire["record_count"])
            if declared_count <= 0 or declared_count > limits.max_records:
                _fail()
            declared_hashes = [_digest(item) for item in _array(wire["record_hashes"])]
            source_kinds = [_string(item) for item in _array(wire["source_kinds"])]
            if (
                len(declared_hashes) != declared_count
                or source_kinds != sorted(set(source_kinds))
                or any(item not in _SOURCE_KINDS for item in source_kinds)
            ):
                _fail()

            metadata = [_part_metadata(item) for item in _array(wire["files"])]
            paths = [_string(item["path"]) for item in metadata]
            file_counts = [_integer(item["record_count"]) for item in metadata]
            if (
                not metadata
                or len(metadata) > declared_count
                or sum(file_counts) != declared_count
                or any(count > limits.max_records for count in file_counts)
                or paths != sorted(paths)
                or len(paths) != len(set(paths))
            ):
                _fail()
            artifact_total = len(body)
            staged: list[tuple[dict[str, object], bytes]] = []
            for item in metadata:
                byte_count = _integer(item["byte_count"])
                if byte_count > limits.max_blob_bytes:
                    _fail()
                remaining = limits.max_total_bytes - artifact_total
                if remaining < 0:
                    _fail()
                part = _read_part(
                    root,
                    _string(item["path"]),
                    min(limits.max_blob_bytes, remaining),
                )
                artifact_total += len(part)
                if len(part) != byte_count or _sha256(part) != _digest(item["sha256"]):
                    _fail()
                staged.append((item, part))

        decoded: list[tuple[int, OptionsDataRecord]] = []
        decoded_total = 0
        with _private_temp_directory() as temporary_name:
            temporary = Path(temporary_name)
            for index, (item, part) in enumerate(staged):
                staged_path = temporary / f"part-{index}.parquet"
                _materialize(staged_path, part)
                remaining_record_bytes = limits.max_total_bytes - decoded_total
                if remaining_record_bytes < 0:
                    _fail()
                rows, part_decoded_bytes = _decode_part(
                    staged_path,
                    limits=limits,
                    expected_count=_integer(item["record_count"]),
                    remaining_record_bytes=remaining_record_bytes,
                )
                decoded_total += part_decoded_bytes
                hashes = [_digest(value) for value in _array(item["record_hashes"])]
                if (
                    len(rows) != _integer(item["record_count"])
                    or [record.record_hash for _, record in rows] != hashes
                    or any(record.kind != _string(item["kind"]) for _, record in rows)
                    or any(
                        record.event_at.date().isoformat() != _string(item["event_date"])
                        for _, record in rows
                    )
                    or any(record.source_kind != _string(item["source_kind"]) for _, record in rows)
                ):
                    _fail()
                decoded.extend(rows)

        decoded.sort(key=lambda item: item[0])
        if [ordinal for ordinal, _ in decoded] != list(range(declared_count)):
            _fail()
        records = tuple(record for _, record in decoded)
        if [record.record_hash for record in records] != declared_hashes or sorted(
            {record.source_kind for record in records}
        ) != source_kinds:
            _fail()
        return records
    except OptionsParquetError:
        raise
    except (BundleError, OSError, UnicodeError, ValueError, TypeError, OverflowError):
        _fail()


__all__ = ["OptionsParquetError", "publish_dataset", "read_dataset"]
