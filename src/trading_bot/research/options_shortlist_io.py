"""Bounded private input and immutable research manifests, never order or ledger writes."""

import hashlib
import os
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

from trading_bot.config.models import OptionsShortlistSettings
from trading_bot.domain import DataHash
from trading_bot.market_data.bundle_models import BundleError
from trading_bot.market_data.bundle_store import (
    _directory_flags,
    _open_root,
    _publish,
    _read,
    _subdirectory,
)
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.options_shortlist_models import (
    OptionsShortlistResult,
    ShortlistSessionInput,
    _check,
)
from trading_bot.research.options_shortlist_wire import decode_shortlist_input, shortlist_limits

_CODES = frozenset(
    {
        "shortlist_input_invalid",
        "shortlist_path_invalid",
        "shortlist_storage_conflict",
        "shortlist_storage_unavailable",
    }
)
_SOURCE_FILES = (
    "research/options_shortlist_models.py",
    "research/options_shortlist.py",
    "research/options_shortlist_wire.py",
    "research/options_shortlist_io.py",
    "cli/options_research.py",
    "config/models.py",
    "config/loader.py",
    "domain/options.py",
    "domain/market.py",
    "domain/decimal_utils.py",
    "clock.py",
    "market_data/options_records.py",
    "market_data/options_data_codec.py",
    "market_data/bundle_codec.py",
    "market_data/bundle_models.py",
    "market_data/bundle_store.py",
    "market_data/recording.py",
)


class ShortlistFileError(ValueError):
    """Fixed public code; never exception text or filesystem paths."""

    def __init__(self, code: str = "shortlist_input_invalid") -> None:
        self.code = code if type(code) is str and code in _CODES else "shortlist_input_invalid"
        super().__init__(self.code)


def _bundle_code(error: BundleError) -> str:
    return {
        "bundle_path_invalid": "shortlist_path_invalid",
        "bundle_storage_conflict": "shortlist_storage_conflict",
        "bundle_storage_unavailable": "shortlist_storage_unavailable",
    }.get(error.code, "shortlist_input_invalid")


def _private_root(root: Path, repository_root: Path) -> int:
    """Retain no-symlink traversal, then reject repository aliases by inode ancestry."""
    with ExitStack() as cleanup:
        descriptor = _open_root(root, repository_root)
        cleanup.callback(os.close, descriptor)
        repository = repository_root.stat()
        repository_identity = (repository.st_dev, repository.st_ino)
        cursor = os.dup(descriptor)
        previous_identity = None
        try:
            while True:
                info = os.fstat(cursor)
                identity = (info.st_dev, info.st_ino)
                if identity == repository_identity:
                    raise BundleError("bundle_path_invalid")
                if identity == previous_identity:
                    break  # The filesystem root is its own parent.
                parent = os.open("..", _directory_flags(), dir_fd=cursor)
                os.close(cursor)
                cursor = parent
                previous_identity = identity
        finally:
            os.close(cursor)
        cleanup.pop_all()  # Transfer the original descriptor to the caller's ExitStack.
        return descriptor


def read_shortlist_input(
    input_path: Path, *, settings: OptionsShortlistSettings, repository_root: Path
) -> tuple[ShortlistSessionInput, DataHash]:
    code = "shortlist_input_invalid"
    try:
        limits = shortlist_limits(settings)
        if (
            not isinstance(input_path, Path)
            or not input_path.is_absolute()
            or ".." in input_path.parts
            or input_path.name in {"", ".", ".."}
        ):
            raise ShortlistFileError("shortlist_path_invalid")
        with ExitStack() as stack:
            parent = _private_root(input_path.parent, repository_root)
            stack.callback(os.close, parent)
            encoded = _read(parent, input_path.name, limits.max_envelope_bytes)
        session = decode_shortlist_input(encoded, settings=settings)
        return session, DataHash(hashlib.sha256(encoded).hexdigest())
    except ShortlistFileError as error:
        code = error.code
    except BundleError as error:
        code = _bundle_code(error)
    except OSError:
        code = "shortlist_path_invalid"
    except (ValueError, TypeError, ArithmeticError):
        pass
    raise ShortlistFileError(code)


def write_shortlist_manifest(
    root: Path,
    result: OptionsShortlistResult,
    *,
    repository_root: Path,
    settings: OptionsShortlistSettings,
) -> DataHash:
    code = "shortlist_input_invalid"
    try:
        limits = shortlist_limits(settings)
        _check(type(result) is OptionsShortlistResult)
        result.__post_init__()
        _check(
            not any(
                (
                    result.live_authorized,
                    result.download_authorized,
                    result.production_eligible,
                    result.evidence_promotable,
                )
            )
        )
        row = {
            **asdict(result),
            "decision_sessions": 1,
            "candidate_count": len(result.candidates),
            "denied_sessions": int(result.status == "no_candidate"),
        }
        payload = {"schema": "options-shortlist-manifest-v1", "result": row}
        body = canonical_json(payload).encode("utf-8")
        _check(len(body) <= limits.max_envelope_bytes)
        digest = content_hash(payload)
        with ExitStack() as stack:
            parent = _private_root(root, repository_root)
            stack.callback(os.close, parent)
            child = _subdirectory(parent, "options-shortlists", create=True)
            stack.callback(os.close, child)
            _publish(child, digest + ".json", body)
        return digest
    except BundleError as error:
        code = _bundle_code(error)
    except OSError:
        code = "shortlist_storage_unavailable"
    except (ValueError, TypeError, ArithmeticError):
        pass
    raise ShortlistFileError(code)


def shortlist_code_hash() -> DataHash:
    """Hash a fixed installed-source inventory, not a release or image attestation."""
    try:
        root = Path(__file__).resolve().parents[1]
        return content_hash(
            tuple(
                (name, hashlib.sha256((root / name).read_bytes()).hexdigest())
                for name in _SOURCE_FILES
            )
        )
    except (OSError, ValueError, TypeError):
        pass
    raise ShortlistFileError()
