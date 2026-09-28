"""Private native SPY bar staging; successful publication is integrity, not usability."""

from __future__ import annotations

import hashlib
import os
from contextlib import ExitStack
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from trading_bot.config import LoadedConfig
from trading_bot.domain import DataHash
from trading_bot.market_data.bundle_codec import _array, _json, _mapping, _string
from trading_bot.market_data.bundle_store import (
    _open_root,
    _private,
    _publish,
    _read_descriptor,
    _subdirectory,
)
from trading_bot.market_data.databento_bar_models import (
    NativeBarBatch,
    NativeBarDataset,
    NativeBarPart,
    NativeBarRequest,
    NativeBarRow,
    native_limits,
)
from trading_bot.market_data.databento_bar_wire import (
    COLUMNS,
    bounds,
    decode_conditions,
    decode_request,
    encode_manifest,
)
from trading_bot.market_data.databento_bars import scan_bars
from trading_bot.market_data.databento_batch import (
    BatchFile,
    DatabentoImportError,
    _file,
    _fingerprint,
    require,
)
from trading_bot.market_data.options_parquet import _connection, _private_temp_directory
from trading_bot.market_data.recording import canonical_json

_CUSTOMIZATIONS = {
    "pretty_px": False,
    "pretty_ts": False,
    "map_symbols": False,
    "split_symbols": False,
    "split_duration": None,
    "split_size": None,
    "packaging": None,
    "delivery": "download",
}


def _private_root(path: Path, repository_root: Path) -> int:
    # The existing traversal denies symlink aliases. Also deny ANY Git ancestor,
    # rather than relying only on the supplied checkout's lexical path.
    require(isinstance(path, Path) and path.is_absolute() and ".." not in path.parts)
    require(all(not os.path.lexists(parent / ".git") for parent in (path, *path.parents)))
    return _open_root(path, repository_root)


def _private_file(parent: int, name: str, maximum: int) -> BinaryIO:
    stream = _file(parent, name, maximum)
    try:
        _private(stream.fileno(), directory=False)
        require(os.fstat(stream.fileno()).st_nlink == 1)
        return stream
    except BaseException:
        stream.close()
        raise


def _read(parent: int, name: str, maximum: int) -> bytes:
    with _private_file(parent, name, maximum) as stream:
        return _read_descriptor(stream.fileno(), maximum)


def _publish_checked(parent: int, name: str, body: bytes) -> None:
    _publish(parent, name, body)
    # Existing artifacts may be reused only with the stricter native link policy.
    # The original publisher still owns atomic no-overwrite publication and fsync.
    require(_read(parent, name, len(body)) == body)


def validate_bar_batch(
    source: Path, *, expected: NativeBarRequest, loaded: LoadedConfig, repository_root: Path
) -> NativeBarBatch:
    """Validate exactly three listed provider files plus their receipt, never fetch URLs."""
    try:
        limits = native_limits(loaded)
        require(type(expected) is NativeBarRequest)
        json_limits = bounds(loaded)
        with ExitStack() as stack:
            parent = _private_root(source, repository_root)
            stack.callback(os.close, parent)
            body = _read(parent, "manifest.json", json_limits.max_envelope_bytes)
            manifest = _mapping(
                _json(body, max_bytes=json_limits.max_envelope_bytes, limits=json_limits),
                {"job_id", "files"},
            )
            job = _string(manifest["job_id"])
            require(
                0 < len(job) <= 128
                and all(char.isascii() and (char.isalnum() or char in "-_.") for char in job)
            )
            files = [BatchFile("manifest.json", len(body), hashlib.sha256(body).hexdigest())]
            entries = _array(manifest["files"])
            require(len(entries) == 3)
            snapshots = {}
            for value in entries:
                entry = _mapping(value, {"filename", "size", "hash", "urls"})
                name = _string(entry["filename"])
                require(
                    type(entry["size"]) is int and 0 < entry["size"] <= limits.max_compressed_bytes
                )
                require(type(entry["urls"]) is dict)  # Inert receipt fields, never reported.
                if name in ("metadata.json", "condition.json"):
                    encoded = _read(parent, name, json_limits.max_envelope_bytes)
                    observed = BatchFile(name, len(encoded), hashlib.sha256(encoded).hexdigest())
                    snapshots[name] = _json(
                        encoded, max_bytes=json_limits.max_envelope_bytes, limits=json_limits
                    )
                else:
                    require(name.endswith(".ohlcv-1m.dbn.zst"))
                    with _private_file(parent, name, limits.max_compressed_bytes) as stream:
                        observed = _fingerprint(stream, name, limits.max_compressed_bytes)
                require(
                    observed.size == entry["size"] and "sha256:" + observed.sha256 == entry["hash"]
                )
                files.append(observed)
            names = {item.name for item in files}
            require(len(names) == 4 and set(os.listdir(parent)) == names)
            require({"manifest.json", "metadata.json", "condition.json"} < names)
            bar_file = next(name for name in names if name.endswith(".ohlcv-1m.dbn.zst"))
            meta = _mapping(
                snapshots["metadata.json"], {"version", "job_id", "query", "customizations"}
            )
            require(type(meta["version"]) is int and meta["version"] == 1 and meta["job_id"] == job)
            require(decode_request(meta["query"]) == expected)
            require(canonical_json(meta["customizations"]) == canonical_json(_CUSTOMIZATIONS))
            conditions = decode_conditions(snapshots["condition.json"], provider=True)
            for condition in conditions:
                day = condition.trading_date
                # Exact calendar-date arithmetic, never floating Unix timestamps.
                epoch_day = (day - datetime(1970, 1, 1, tzinfo=UTC).date()).days
                require(expected.start_ns <= epoch_day * 86400 * 10**9 < expected.end_ns)
            return NativeBarBatch(
                expected, tuple(sorted(files, key=lambda item: item.name)), bar_file, conditions
            )
    except DatabentoImportError:
        raise
    except Exception:
        raise DatabentoImportError() from None


def _part(directory: Path, rows: list[NativeBarRow], index: int, maximum: int) -> Path:
    raw = directory / f"{index}.jsonl"
    target = directory / f"{index}.parquet"
    with raw.open("x", encoding="utf-8") as output:
        os.chmod(raw, 0o600)
        for row in rows:
            output.write(canonical_json(asdict(row)) + "\n")
    connection = _connection(directory)
    try:
        connection.execute(
            "COPY (SELECT * FROM read_json(?, format='newline_delimited', columns=?)) "
            "TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(target), str(raw), COLUMNS],
        )
        os.chmod(target, 0o600)
    finally:
        connection.close()
        raw.unlink()  # Only this function's exclusive temporary file.
    require(target.stat().st_size <= maximum, "databento_limit_exceeded")
    return target


def stage_bars(
    source: Path,
    root: Path,
    *,
    expected: NativeBarRequest,
    loaded: LoadedConfig,
    repository_root: Path,
) -> Path:
    """Validate the full source before publishing parts, then publish the manifest last."""
    try:
        limits = native_limits(loaded)
        settings = loaded.config.options.native_data
        batch = validate_bar_batch(
            source, expected=expected, loaded=loaded, repository_root=repository_root
        )
        artifact = next(item for item in batch.files if item.name == batch.bar_file)
        with ExitStack() as stack:
            parent = _private_root(root, repository_root)
            stack.callback(os.close, parent)
            source_fd = _private_root(source, repository_root)
            stack.callback(os.close, source_fd)
            temporary = Path(stack.enter_context(_private_temp_directory()))
            buffer: list[NativeBarRow] = []
            parts: list[tuple[Path, NativeBarPart]] = []
            byte_count = 0
            current_day = ""

            def flush() -> None:
                nonlocal byte_count
                if not buffer:
                    return
                require(len(parts) < settings.max_parts, "databento_limit_exceeded")
                path = _part(temporary, buffer, len(parts), settings.max_part_bytes)
                body = path.read_bytes()
                digest = DataHash(hashlib.sha256(body).hexdigest())
                descriptor = NativeBarPart(
                    f"parts/interval_date={current_day}/{digest}.parquet",
                    digest,
                    len(body),
                    len(buffer),
                )
                parts.append((path, descriptor))
                buffer.clear()
                byte_count = 0

            def consume(row: NativeBarRow) -> None:
                nonlocal byte_count, current_day
                day = datetime.fromtimestamp(row.interval_start_ns // 10**9, UTC).date().isoformat()
                size = len(canonical_json(asdict(row)).encode()) + 1
                if buffer and (
                    day != current_day
                    or len(buffer) >= settings.max_part_rows
                    or byte_count + size > settings.max_part_bytes
                ):
                    flush()
                require(size <= settings.max_part_bytes, "databento_limit_exceeded")
                current_day = day
                buffer.append(row)
                byte_count += size

            with _private_file(source_fd, artifact.name, artifact.size) as stream:
                profile = scan_bars(
                    stream,
                    expected=expected,
                    expected_sha256=artifact.sha256,
                    limits=limits,
                    consume=consume,
                )
            flush()
            # A changed receipt/metadata cannot be combined with the earlier profile.
            require(
                validate_bar_batch(
                    source, expected=expected, loaded=loaded, repository_root=repository_root
                )
                == batch
            )
            body = encode_manifest(profile, batch, tuple(item for _, item in parts), loaded)
            require(len(body) <= settings.max_manifest_bytes, "databento_limit_exceeded")
            digest = hashlib.sha256(body).hexdigest()
            for path, item in parts:
                with ExitStack() as directories:
                    directory = parent
                    components = item.path.split("/")
                    for component in components[:-1]:
                        directory = _subdirectory(directory, component, create=True)
                        directories.callback(os.close, directory)
                    _publish_checked(directory, components[-1], path.read_bytes())
            manifests = _subdirectory(parent, "manifests", create=True)
            stack.callback(os.close, manifests)
            _publish_checked(manifests, digest + ".json", body)
            return root / "manifests" / (digest + ".json")
    except DatabentoImportError:
        raise
    except Exception:
        raise DatabentoImportError() from None


def verify_bar_stage(
    manifest_path: Path, *, loaded: LoadedConfig, repository_root: Path
) -> NativeBarDataset:
    from trading_bot.market_data.databento_native_rows import _bar_snapshots

    try:
        with _bar_snapshots(
            manifest_path, loaded=loaded, repository_root=repository_root
        ) as result:
            return result[0]
    except DatabentoImportError:
        raise
    except Exception:
        raise DatabentoImportError() from None
