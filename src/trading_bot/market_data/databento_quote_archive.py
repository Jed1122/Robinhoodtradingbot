"""Bounded private raw snapshots; source URLs remain inert and never leave private blobs."""

import hashlib
import os
import re
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from typing import BinaryIO

from trading_bot.config import LoadedConfig
from trading_bot.market_data.bundle_codec import _array, _json, _mapping, _string
from trading_bot.market_data.bundle_store import _subdirectory
from trading_bot.market_data.databento_bar_models import NativeCondition, native_limits
from trading_bot.market_data.databento_bar_store import (
    _CUSTOMIZATIONS,
    _private_file,
    _private_root,
    _read,
)
from trading_bot.market_data.databento_bar_wire import bounds, decode_conditions
from trading_bot.market_data.databento_batch import require
from trading_bot.market_data.databento_quote_models import (
    NativeQuoteRequest,
    QuoteArchive,
    QuoteChunk,
)
from trading_bot.market_data.databento_quote_wire import decode_request
from trading_bot.market_data.recording import canonical_json

CHUNK_BYTES = 1024 * 1024


def _receipt(body: bytes, expected: NativeQuoteRequest, loaded: LoadedConfig) -> dict[str, object]:
    limits = bounds(loaded)
    result = _mapping(
        _json(body, max_bytes=limits.max_envelope_bytes, limits=limits), {"job_id", "files"}
    )
    job = _string(result["job_id"])
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", job) is not None)
    entries = _array(result["files"])
    require(len(entries) == 3)
    names = []
    for value in entries:
        item = _mapping(value, {"filename", "size", "hash", "urls"})
        name = _string(item["filename"])
        require(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name) is not None and ".." not in name
        )
        require(
            type(item["size"]) is int
            and 0 < item["size"] <= loaded.config.options.native_data.max_compressed_bytes
        )
        require(
            type(item["hash"]) is str
            and re.fullmatch(r"sha256:[0-9a-f]{64}", item["hash"]) is not None
        )
        require(type(item["urls"]) is dict)
        names.append(name)
    require(len(set(names)) == 3 and {"metadata.json", "condition.json"} < set(names))
    require(sum(n.endswith("." + expected.schema + ".dbn.zst") for n in names) == 1)
    return result


def _describe(stream: BinaryIO, name: str, maximum: int) -> QuoteArchive:
    digest = hashlib.sha256()
    chunks = []
    count = 0
    while body := stream.read(CHUNK_BYTES):
        count += len(body)
        require(count <= maximum, "databento_limit_exceeded")
        digest.update(body)
        chunks.append(QuoteChunk(hashlib.sha256(body).hexdigest(), len(body)))
    return QuoteArchive(name, digest.hexdigest(), count, tuple(chunks))


def describe_snapshot(
    source: Path, *, expected: NativeQuoteRequest, loaded: LoadedConfig, repository_root: Path
) -> tuple[tuple[QuoteArchive, ...], tuple[NativeCondition, ...], str]:
    native_limits(loaded)
    settings = loaded.config.options.native_data
    with ExitStack() as stack:
        parent = _private_root(source, repository_root)
        stack.callback(os.close, parent)
        manifest = _receipt(
            _read(parent, "manifest.json", settings.max_manifest_bytes), expected, loaded
        )
        entries = [
            _mapping(e, {"filename", "size", "hash", "urls"}) for e in _array(manifest["files"])
        ]
        names = sorted(["manifest.json", *(_string(e["filename"]) for e in entries)])
        require(set(os.listdir(parent)) == set(names))
        archives = []
        for name in names:
            with _private_file(parent, name, settings.max_compressed_bytes) as stream:
                archives.append(_describe(stream, name, settings.max_compressed_bytes))
        require(
            sum(a.size for a in archives) <= settings.max_decompressed_bytes,
            "databento_limit_exceeded",
        )
        by_name = {a.name: a for a in archives}
        for item in entries:
            actual = by_name[_string(item["filename"])]
            require(actual.size == item["size"] and "sha256:" + actual.sha256 == item["hash"])
        limit = bounds(loaded)
        metadata = _mapping(
            _json(
                _read(parent, "metadata.json", settings.max_manifest_bytes),
                max_bytes=settings.max_manifest_bytes,
                limits=limit,
            ),
            {"version", "job_id", "query", "customizations"},
        )
        require(type(metadata["version"]) is int and metadata["version"] == 1)
        require(
            metadata["job_id"] == manifest["job_id"]
            and decode_request(metadata["query"]) == expected
        )
        require(canonical_json(metadata["customizations"]) == canonical_json(_CUSTOMIZATIONS))
        conditions = decode_conditions(
            _json(
                _read(parent, "condition.json", settings.max_manifest_bytes),
                max_bytes=settings.max_manifest_bytes,
                limits=limit,
            ),
            provider=True,
        )
        days = tuple(c.trading_date for c in conditions)
        require(0 < len(days) <= 10000 and days == tuple(sorted(set(days))))
        for day in days:
            start = (day - date(1970, 1, 1)).days * 86400 * 10**9
            require(start < expected.end_ns and expected.start_ns < start + 86400 * 10**9)
        artifact = next(n for n in names if n.endswith(".dbn.zst"))
        return tuple(archives), conditions, artifact


def capture(
    source: Path,
    target: Path,
    *,
    expected: NativeQuoteRequest,
    loaded: LoadedConfig,
    repository_root: Path,
) -> tuple[tuple[QuoteArchive, ...], tuple[NativeCondition, ...], str]:
    """Snapshot from no-follow descriptors, then authenticate all bytes against the receipt."""
    native_limits(loaded)
    settings = loaded.config.options.native_data
    with ExitStack() as stack:
        parent = _private_root(source, repository_root)
        stack.callback(os.close, parent)
        body = _read(parent, "manifest.json", settings.max_manifest_bytes)
        receipt = _receipt(body, expected, loaded)
        names = [
            _string(_mapping(e, {"filename", "size", "hash", "urls"})["filename"])
            for e in _array(receipt["files"])
        ]
        require(set(os.listdir(parent)) == {"manifest.json", *names})
        with (target / "manifest.json").open("xb") as stream:
            os.chmod(target / "manifest.json", 0o600)
            stream.write(body)
        total = len(body)
        for name in names:
            count = 0
            with (
                _private_file(parent, name, settings.max_compressed_bytes) as incoming,
                (target / name).open("xb") as outgoing,
            ):
                os.chmod(target / name, 0o600)
                while chunk := incoming.read(CHUNK_BYTES):
                    count += len(chunk)
                    total += len(chunk)
                    require(
                        count <= settings.max_compressed_bytes
                        and total <= settings.max_decompressed_bytes,
                        "databento_limit_exceeded",
                    )
                    outgoing.write(chunk)
    return describe_snapshot(
        target, expected=expected, loaded=loaded, repository_root=repository_root
    )


def restore(parent: int, target: Path, archives: tuple[QuoteArchive, ...]) -> None:
    with ExitStack() as stack:
        blobs = _subdirectory(parent, "blobs", create=False)
        stack.callback(os.close, blobs)
        for archive in archives:
            digest = hashlib.sha256()
            with (target / archive.name).open("xb") as output:
                os.chmod(target / archive.name, 0o600)
                for chunk in archive.chunks:
                    body = _read(blobs, chunk.sha256 + ".raw", chunk.byte_count)
                    require(
                        len(body) == chunk.byte_count
                        and hashlib.sha256(body).hexdigest() == chunk.sha256
                    )
                    digest.update(body)
                    output.write(body)
            require(digest.hexdigest() == archive.sha256)
