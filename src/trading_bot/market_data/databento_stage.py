"""Private, content-addressed native definition staging; never an executable data adapter."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from trading_bot.market_data.bundle_codec import _array, _json, _mapping
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.bundle_store import _open_root, _publish, _read, _subdirectory
from trading_bot.market_data.databento_batch import (
    DatabentoImportError,
    DefinitionRequest,
    _file,
    _source_root,
    require,
    validate_batch,
)
from trading_bot.market_data.databento_definitions import DefinitionLimits, scan_definitions
from trading_bot.market_data.options_parquet import _connection, _private_temp_directory
from trading_bot.market_data.recording import canonical_json

_SCHEMA = "databento-native-definitions-parquet-v1"
_DEFAULT_LIMITS = DefinitionLimits()
_BOUNDS = BundleLimits(16 * 1024**2, 128 * 1024**2, 256 * 1024**2, 10000, 12)
_PART = re.compile(r"parts/receive_date=\d{4}-\d{2}-\d{2}/[0-9a-f]{64}\.parquet\Z")
_COLUMNS = {
    "record_ordinal": "UBIGINT",
    "dbn_version": "UINTEGER",
    "record_sha256": "VARCHAR",
    "publisher_id": "UINTEGER",
    "instrument_id": "UINTEGER",
    "raw_instrument_id": "UBIGINT",
    "ts_event": "UBIGINT",
    "ts_recv": "UBIGINT",
    "expiration": "UBIGINT",
    "activation": "UBIGINT",
    "strike_price": "BIGINT",
    "min_price_increment": "BIGINT",
    "display_factor": "BIGINT",
    "unit_of_measure_qty": "BIGINT",
    "contract_multiplier": "BIGINT",
    "contract_multiplier_unit": "INTEGER",
    "original_contract_size": "BIGINT",
    "underlying_id": "UINTEGER",
    "raw_symbol": "VARCHAR",
    "underlying": "VARCHAR",
    "asset": "VARCHAR",
    "security_type": "VARCHAR",
    "cfi": "VARCHAR",
    "currency": "VARCHAR",
    "settl_currency": "VARCHAR",
    "strike_price_currency": "VARCHAR",
    "unit_of_measure": "VARCHAR",
    "instrument_class": "VARCHAR",
    "security_update_action": "VARCHAR",
    "leg_count": "UINTEGER",
}
# SQL includes only this fixed, developer-owned schema; never provider strings or paths.
_SQL_COLUMNS = "{" + ",".join(f"'{key}':'{kind}'" for key, kind in _COLUMNS.items()) + "}"


def _part(directory: Path, rows: list[dict[str, object]], index: int) -> Path:
    raw = directory / f"{index}.jsonl"
    target = directory / f"{index}.parquet"
    with raw.open("x", encoding="utf-8") as output:
        os.chmod(raw, 0o600)
        for row in rows:
            output.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
    connection = _connection(directory)
    try:
        connection.execute(
            "COPY (SELECT * FROM read_json(?, format='newline_delimited', columns="
            + _SQL_COLUMNS
            + ")) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            # DuckDB binds COPY's destination before parameters in its SELECT.
            [str(target), str(raw)],
        )
        os.chmod(target, 0o600)
    finally:
        connection.close()
        raw.unlink()  # Only this function's exclusive temporary file.
    require(target.stat().st_size <= _BOUNDS.max_blob_bytes, "databento_limit_exceeded")
    return target


def stage_batch(
    source: Path,
    root: Path,
    *,
    expected: DefinitionRequest,
    repository_root: Path,
    limits: DefinitionLimits = _DEFAULT_LIMITS,
) -> Path:
    """Validate all input before publishing any final Parquet part or manifest.

    Original DBN is retained separately. Native rows are not canonical executable
    contracts; all missing enrichment and economic eligibility remain explicit.
    """
    try:
        batch = validate_batch(
            source, expected=expected, max_file_bytes=limits.max_compressed_bytes
        )
        artifact = next(item for item in batch.files if item.name == batch.definition_file)
        with ExitStack() as stack:
            destination = _open_root(root, repository_root)
            stack.callback(os.close, destination)
            source_fd = _source_root(source)
            stack.callback(os.close, source_fd)
            temporary = Path(stack.enter_context(_private_temp_directory()))
            buffer: list[dict[str, object]] = []
            parts: list[tuple[Path, dict[str, object]]] = []

            def flush() -> None:
                groups: dict[str, list[dict[str, object]]] = defaultdict(list)
                for row in buffer:
                    stamp = cast(int, row["ts_recv"])
                    day = datetime.fromtimestamp(stamp // 10**9, UTC).date().isoformat()
                    groups[day].append(row)
                for day, rows in sorted(groups.items()):
                    require(len(parts) < _BOUNDS.max_records, "databento_limit_exceeded")
                    path = _part(temporary, rows, len(parts))
                    body = path.read_bytes()
                    digest = hashlib.sha256(body).hexdigest()
                    parts.append(
                        (
                            path,
                            {
                                "path": f"parts/receive_date={day}/{digest}.parquet",
                                "sha256": digest,
                                "byte_count": len(body),
                                "record_count": len(rows),
                            },
                        )
                    )
                buffer.clear()

            def consume(row: dict[str, object]) -> None:
                buffer.append(row)
                if len(buffer) >= 10000:
                    flush()

            with _file(source_fd, artifact.name, artifact.size) as stream:
                profile = scan_definitions(
                    stream,
                    expected=expected,
                    expected_sha256=artifact.sha256,
                    limits=limits,
                    consume=consume,
                )
            flush()
            manifest: dict[str, object] = {
                "schema": _SCHEMA,
                "validation": profile,
                "input_files": [asdict(item) for item in batch.files],
                "conditions": batch.conditions,
                "columns": _COLUMNS,
                "files": [entry for _, entry in parts],
                "economic_evidence": False,
                "production_eligible": False,
            }
            body = canonical_json(manifest).encode()
            require(len(body) <= _BOUNDS.max_envelope_bytes, "databento_limit_exceeded")
            digest = hashlib.sha256(body).hexdigest()
            for path, entry in parts:
                components = str(entry["path"]).split("/")
                with ExitStack() as directories:
                    parent = destination
                    for component in components[:-1]:
                        parent = _subdirectory(parent, component, create=True)
                        directories.callback(os.close, parent)
                    _publish(parent, components[-1], path.read_bytes())
            manifests = _subdirectory(destination, "manifests", create=True)
            stack.callback(os.close, manifests)
            _publish(manifests, digest + ".json", body)
            return root / "manifests" / (digest + ".json")
    except DatabentoImportError:
        raise
    except Exception:
        raise DatabentoImportError() from None


def verify_staged(manifest_path: Path, *, repository_root: Path) -> dict[str, object]:
    """Verify private manifest/part identity and exact column/count contracts; no live grant."""
    try:
        root = manifest_path.parent.parent
        require(manifest_path.parent.name == "manifests")
        require(re.fullmatch(r"[0-9a-f]{64}\.json", manifest_path.name) is not None)
        with ExitStack() as stack:
            parent = _open_root(root, repository_root)
            stack.callback(os.close, parent)
            manifests = _subdirectory(parent, "manifests", create=False)
            stack.callback(os.close, manifests)
            body = _read(manifests, manifest_path.name, _BOUNDS.max_envelope_bytes)
            require(hashlib.sha256(body).hexdigest() == manifest_path.stem)
            manifest = _mapping(
                _json(body, max_bytes=_BOUNDS.max_envelope_bytes, limits=_BOUNDS),
                {
                    "schema",
                    "validation",
                    "input_files",
                    "conditions",
                    "columns",
                    "files",
                    "economic_evidence",
                    "production_eligible",
                },
            )
            require(manifest["schema"] == _SCHEMA and manifest["columns"] == _COLUMNS)
            require(
                manifest["economic_evidence"] is False and manifest["production_eligible"] is False
            )
            entries = _array(manifest["files"])
            require(0 < len(entries) <= _BOUNDS.max_records)
            count = 0
            seen = set()
            connection = _connection(root)
            stack.callback(connection.close)
            for value in entries:
                item = _mapping(value, {"path", "sha256", "byte_count", "record_count"})
                relative = str(item["path"])
                require(_PART.fullmatch(relative) is not None and relative not in seen)
                seen.add(relative)
                require(
                    type(item["byte_count"]) is int
                    and 0 < item["byte_count"] <= _BOUNDS.max_blob_bytes
                )
                require(type(item["record_count"]) is int and item["record_count"] > 0)
                with ExitStack() as directories:
                    directory = parent
                    components = relative.split("/")
                    for component in components[:-1]:
                        directory = _subdirectory(directory, component, create=False)
                        directories.callback(os.close, directory)
                    encoded = _read(directory, components[-1], cast(int, item["byte_count"]))
                require(
                    len(encoded) == item["byte_count"]
                    and hashlib.sha256(encoded).hexdigest() == item["sha256"]
                )
                require(Path(relative).stem == item["sha256"])
                columns = connection.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
                    [str(root / relative)],
                ).fetchall()
                require({row[0]: row[1] for row in columns} == _COLUMNS)
                observed = connection.execute(
                    "SELECT count(*) FROM read_parquet(?, hive_partitioning=false)",
                    [str(root / relative)],
                ).fetchone()[0]
                require(observed == item["record_count"])
                count += observed
            profile = cast(dict[str, object], manifest["validation"])
            require(type(profile) is dict and type(profile["record_count"]) is int)
            require(
                count == profile["record_count"] and profile["record_validation_complete"] is True
            )
            require(
                profile["economic_evidence"] is False and profile["production_eligible"] is False
            )
            return manifest
    except DatabentoImportError:
        raise
    except Exception:
        raise DatabentoImportError() from None
