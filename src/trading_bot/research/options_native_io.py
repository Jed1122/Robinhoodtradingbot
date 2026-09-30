"""Bounded private documents and immutable diagnostic publication, never trading I/O."""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from trading_bot.config import LoadedConfig
from trading_bot.domain import DataHash
from trading_bot.market_data.bundle_codec import _array, _digest, _json, _mapping
from trading_bot.market_data.bundle_store import _subdirectory
from trading_bot.market_data.databento_bar_models import native_limits
from trading_bot.market_data.databento_bar_store import _private_root, _publish_checked, _read
from trading_bot.market_data.databento_bar_wire import bounds
from trading_bot.market_data.options_source_models import (
    PrivateArtifactRef,
    SourceEvidenceError,
    SourceVerification,
    check,
    hashes,
)
from trading_bot.market_data.options_source_wire import _reference, encode_source_verification
from trading_bot.research.options_acquisition_models import CoverageManifest
from trading_bot.research.options_acquisition_wire import encode_coverage_manifest
from trading_bot.research.options_shortlist_v2 import VerifiedShortlistResult
from trading_bot.research.options_shortlist_v2_wire import encode_verified_shortlist_result


def read_native_document(path: Path, *, loaded: LoadedConfig, repository_root: Path) -> bytes:
    """Read exactly one private regular single-link document without following aliases."""
    try:
        native_limits(loaded)
        check(isinstance(path, Path) and path.is_absolute() and ".." not in path.parts)
        parent = _private_root(path.parent, repository_root)
        try:
            return _read(
                parent, path.name, loaded.config.options.research_shortlist.max_input_bytes
            )
        finally:
            os.close(parent)
    except Exception:
        raise SourceEvidenceError() from None


def write_native_report(
    root: Path,
    result: SourceVerification | VerifiedShortlistResult | CoverageManifest,
    *,
    loaded: LoadedConfig,
    repository_root: Path,
) -> DataHash:
    """Publish a closed, authority-free report last; never replace an existing artifact."""
    try:
        native_limits(loaded)
        check(type(result) in (SourceVerification, VerifiedShortlistResult, CoverageManifest))
        check(
            result.production_eligible is False
            and result.evidence_promotable is False
            and result.download_authorized is False
            and result.live_authorized is False
        )
        if isinstance(result, SourceVerification):
            body = encode_source_verification(result)
        elif isinstance(result, VerifiedShortlistResult):
            body = encode_verified_shortlist_result(result)
        else:
            check(result.economic_eligible is False)
            body = encode_coverage_manifest(result)
        check(len(body) <= loaded.config.options.native_data.max_manifest_bytes)
        digest = DataHash(hashlib.sha256(body).hexdigest())
        parent = _private_root(root, repository_root)
        try:
            directory = _subdirectory(parent, "manifests", create=True)
            try:
                _publish_checked(directory, f"{digest}.json", body)
            finally:
                os.close(directory)
        finally:
            os.close(parent)
        return digest
    except Exception:
        raise SourceEvidenceError() from None


@dataclass(frozen=True, slots=True)
class ShortlistIndexEntry:
    input: PrivateArtifactRef
    expected_result_hash: DataHash

    def __post_init__(self) -> None:
        check(type(self.input) is PrivateArtifactRef)
        hashes((self.expected_result_hash,))


def decode_shortlist_index(body: bytes, *, loaded: LoadedConfig) -> tuple[ShortlistIndexEntry, ...]:
    """An index identifies inputs to recompute, not saved results to trust."""
    try:
        native_limits(loaded)
        settings = loaded.config.options.research_shortlist
        value = _mapping(
            _json(body, max_bytes=settings.max_input_bytes, limits=bounds(loaded)),
            {"schema", "entries"},
        )
        check(value["schema"] == "options-shortlist-index-v1")
        rows = _array(value["entries"])
        check(0 < len(rows) <= settings.max_input_records)
        entries = []
        for item in rows:
            row = _mapping(item, {"input", "expected_result_hash"})
            entries.append(
                ShortlistIndexEntry(_reference(row["input"]), _digest(row["expected_result_hash"]))
            )
        result = tuple(entries)
        check(len({row.input.path for row in result}) == len(result))
        check(len({row.input.sha256 for row in result}) == len(result))
        check(len({row.expected_result_hash for row in result}) == len(result))
        check(sum(row.input.byte_count for row in result) <= settings.max_input_bytes)
        return result
    except Exception:
        raise SourceEvidenceError() from None
