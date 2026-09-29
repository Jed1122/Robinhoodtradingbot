"""Private immutable native archives and bounded Parquet; never a qualified research feed."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.config import LoadedConfig
from trading_bot.market_data.bundle_store import _subdirectory
from trading_bot.market_data.databento_bar_models import native_limits
from trading_bot.market_data.databento_bar_store import (
    _private_file,
    _private_root,
    _publish_checked,
    _read,
)
from trading_bot.market_data.databento_batch import DatabentoImportError, require
from trading_bot.market_data.databento_native_rows import _rows, _snapshot
from trading_bot.market_data.databento_quote_archive import capture, describe_snapshot, restore
from trading_bot.market_data.databento_quote_models import (
    NativeQuotePart,
    NativeQuoteRequest,
    NativeQuoteRow,
    VerifiedQuoteStage,
)
from trading_bot.market_data.databento_quote_wire import (
    COLUMNS,
    decode_manifest,
    decode_row,
    encode_manifest,
)
from trading_bot.market_data.databento_quotes import scan_quotes
from trading_bot.market_data.options_parquet import _connection, _private_temp_directory
from trading_bot.market_data.recording import canonical_json


def _part(directory: Path, rows: list[NativeQuoteRow], index: int, maximum: int) -> Path:
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
        raw.unlink()  # Only this function's exclusively-created temporary file.
    require(target.stat().st_size <= maximum, "databento_limit_exceeded")
    return target


def stage_quotes(
    source: Path,
    output_root: Path,
    *,
    expected: NativeQuoteRequest,
    loaded: LoadedConfig,
    repository_root: Path,
) -> Path:
    """Validate raw snapshots first; publish raw chunks/parts, then the manifest last."""
    try:
        limits = native_limits(loaded)
        settings = loaded.config.options.native_data
        require(type(expected) is NativeQuoteRequest)
        require(not source.is_relative_to(output_root) and not output_root.is_relative_to(source))
        with ExitStack() as stack:
            parent = _private_root(output_root, repository_root)
            stack.callback(os.close, parent)
            temporary = Path(stack.enter_context(_private_temp_directory())).resolve(strict=True)
            inputs = temporary / "inputs"
            inputs.mkdir(mode=0o700)
            archives, conditions, artifact = capture(
                source, inputs, expected=expected, loaded=loaded, repository_root=repository_root
            )
            raw_identity = next(a for a in archives if a.name == artifact)
            source_fd = _private_root(inputs, repository_root)
            stack.callback(os.close, source_fd)
            buffer: list[NativeQuoteRow] = []
            parts: list[tuple[Path, NativeQuotePart]] = []
            byte_count = total_bytes = 0
            current_day = ""

            def flush() -> None:
                nonlocal byte_count, total_bytes
                if not buffer:
                    return
                require(len(parts) < settings.max_parts, "databento_limit_exceeded")
                path = _part(temporary, buffer, len(parts), settings.max_part_bytes)
                body = path.read_bytes()
                total_bytes += len(body)
                require(total_bytes <= settings.max_decompressed_bytes, "databento_limit_exceeded")
                digest = hashlib.sha256(body).hexdigest()
                part = NativeQuotePart(
                    f"parts/receive_date={current_day}/{digest}.parquet",
                    digest,
                    len(body),
                    len(buffer),
                )
                parts.append((path, part))
                buffer.clear()
                byte_count = 0

            def consume(row: NativeQuoteRow) -> None:
                nonlocal byte_count, current_day
                day = datetime.fromtimestamp(row.ts_recv // 10**9, UTC).date().isoformat()
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

            with _private_file(source_fd, artifact, raw_identity.size) as stream:
                profile = scan_quotes(
                    stream,
                    expected=expected,
                    expected_sha256=raw_identity.sha256,
                    limits=limits,
                    consume=consume,
                )
            flush()
            provisional = VerifiedQuoteStage(
                output_root / "manifests" / ("0" * 64 + ".json"),
                "0" * 64,
                loaded.config_hash,
                expected,
                profile,
                tuple(p for _, p in parts),
                archives,
                conditions,
            )
            body = encode_manifest(provisional)
            require(len(body) <= settings.max_manifest_bytes, "databento_limit_exceeded")
            digest = hashlib.sha256(body).hexdigest()
            blobs = _subdirectory(parent, "blobs", create=True)
            stack.callback(os.close, blobs)
            for archive in archives:
                with _private_file(source_fd, archive.name, archive.size) as stream:
                    for chunk in archive.chunks:
                        block = stream.read(chunk.byte_count)
                        require(
                            len(block) == chunk.byte_count
                            and hashlib.sha256(block).hexdigest() == chunk.sha256
                        )
                        _publish_checked(blobs, chunk.sha256 + ".raw", block)
                    require(stream.read(1) == b"")
            for path, part in parts:
                with ExitStack() as directories:
                    directory = parent
                    for component in part.path.split("/")[:-1]:
                        directory = _subdirectory(directory, component, create=True)
                        directories.callback(os.close, directory)
                    _publish_checked(directory, part.path.split("/")[-1], path.read_bytes())
            manifests = _subdirectory(parent, "manifests", create=True)
            stack.callback(os.close, manifests)
            _publish_checked(manifests, digest + ".json", body)
            return output_root / "manifests" / (digest + ".json")
    except DatabentoImportError:
        raise
    except Exception:
        raise DatabentoImportError() from None


@contextmanager
def quote_snapshots(
    path: Path, *, loaded: LoadedConfig, repository_root: Path
) -> Iterator[tuple[VerifiedQuoteStage, tuple[Path, ...], Any]]:
    """Recheck every blob and part, and compare every row to a fresh native decode.

    Consumers only receive private snapshots after the entire comparison succeeds;
    later path replacement cannot change the bytes consumed by their query.
    """
    try:
        limits = native_limits(loaded)
        with ExitStack() as stack:
            require(
                path.parent.name == "manifests"
                and re.fullmatch(r"[0-9a-f]{64}\.json", path.name) is not None
            )
            parent = _private_root(path.parent.parent, repository_root)
            stack.callback(os.close, parent)
            manifests = _subdirectory(parent, "manifests", create=False)
            stack.callback(os.close, manifests)
            body = _read(manifests, path.name, loaded.config.options.native_data.max_manifest_bytes)
            require(hashlib.sha256(body).hexdigest() == path.stem)
            dataset = decode_manifest(body, path, loaded)
            temporary = Path(stack.enter_context(_private_temp_directory())).resolve(strict=True)
            inputs = temporary / "inputs"
            inputs.mkdir(mode=0o700)
            restore(parent, inputs, dataset.archives)
            archives, conditions, artifact = describe_snapshot(
                inputs, expected=dataset.request, loaded=loaded, repository_root=repository_root
            )
            require(archives == dataset.archives and conditions == dataset.conditions)
            raw_identity = next(a for a in archives if a.name == artifact)
            require(raw_identity.sha256 == dataset.profile.raw_hash)
            connection = _connection(temporary)
            stack.callback(connection.close)
            snapshots = tuple(
                _snapshot(
                    parent, part.path, part.byte_count, part.sha256, temporary / f"{index}.parquet"
                )
                for index, part in enumerate(dataset.parts)
            )

            def observations() -> Iterator[NativeQuoteRow]:
                for snapshot, part in zip(snapshots, dataset.parts, strict=True):
                    count = 0
                    for value in _rows(connection, snapshot, COLUMNS):
                        row = decode_row(value)
                        count += 1
                        require(count <= part.record_count, "databento_limit_exceeded")
                        day = datetime.fromtimestamp(row.ts_recv // 10**9, UTC).date().isoformat()
                        require(part.path.split("/")[1] == "receive_date=" + day)
                        yield row
                    require(count == part.record_count)

            rows = observations()

            def compare(row: NativeQuoteRow) -> None:
                require(next(rows, None) == row)

            source_fd = _private_root(inputs, repository_root)
            stack.callback(os.close, source_fd)
            with _private_file(source_fd, artifact, raw_identity.size) as stream:
                profile = scan_quotes(
                    stream,
                    expected=dataset.request,
                    expected_sha256=raw_identity.sha256,
                    limits=limits,
                    consume=compare,
                )
            require(next(rows, None) is None and profile == dataset.profile)
            yield dataset, snapshots, connection
    except DatabentoImportError:
        raise
    except Exception:
        raise DatabentoImportError() from None


def verify_quote_stage(
    manifest: Path, *, loaded: LoadedConfig, repository_root: Path
) -> VerifiedQuoteStage:
    with quote_snapshots(manifest, loaded=loaded, repository_root=repository_root) as result:
        return result[0]
