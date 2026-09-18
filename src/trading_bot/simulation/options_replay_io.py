"""Private saved engineering inputs/reports; never a broker or live ledger writer."""

import json
import os
from contextlib import ExitStack
from pathlib import Path

from trading_bot.config import LoadedConfig
from trading_bot.domain import DataHash
from trading_bot.market_data.bundle_store import _open_root, _publish, _read, _subdirectory
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.simulation.options_replay import replay_options
from trading_bot.simulation.options_replay_models import OptionsReplayRequest
from trading_bot.simulation.options_replay_wire import (
    OptionsReplayFileError,
    decode_options_replay,
    encode_options_replay,
    replay_file_limits,
)


def _publish_artifact(
    root: Path,
    directory: str,
    digest: str,
    body: bytes,
    repository_root: Path,
) -> None:
    with ExitStack() as stack:
        parent = _open_root(root, repository_root)
        stack.callback(os.close, parent)
        child = _subdirectory(parent, directory, create=True)
        stack.callback(os.close, child)
        _publish(child, digest + ".json", body)


def write_options_replay_input(
    root: Path,
    request: OptionsReplayRequest,
    *,
    repository_root: Path,
) -> DataHash:
    try:
        body = encode_options_replay(request)
        digest = DataHash(json.loads(body)["document_hash"])
        _publish_artifact(root, "inputs", digest, body, repository_root)
        return digest
    except (OSError, ValueError, TypeError, ArithmeticError):
        pass
    raise OptionsReplayFileError()


def read_options_replay_file(
    path: Path,
    loaded: LoadedConfig,
    *,
    repository_root: Path,
) -> OptionsReplayRequest:
    try:
        limits = replay_file_limits(loaded)
        if not isinstance(path, Path) or path.name in ("", ".."):
            raise OptionsReplayFileError()
        with ExitStack() as stack:
            directory = _open_root(path.parent, repository_root)
            stack.callback(os.close, directory)
            body = _read(directory, path.name, limits.max_blob_bytes)
        return decode_options_replay(body, loaded)
    except (OSError, ValueError, TypeError, ArithmeticError):
        pass
    raise OptionsReplayFileError()


def replay_options_report(
    request: OptionsReplayRequest,
    *,
    report_dir: Path | None,
    repository_root: Path,
) -> dict[str, object]:
    """Recompute from bounded input. Caller cannot supply or promote a result."""
    try:
        source = json.loads(encode_options_replay(request))
        row: dict[str, object] = {
            "schema": "synthetic-options-replay-report-v1",
            "document_hash": source["document_hash"],
            "result": replay_options(request),
        }
        row["report_hash"] = content_hash(row)
        body = canonical_json(row).encode()
        if len(body) > replay_file_limits(request.loaded).max_blob_bytes:
            raise OptionsReplayFileError()
        if report_dir is not None:
            _publish_artifact(report_dir, "reports", str(row["report_hash"]), body, repository_root)
        return row
    except (OSError, ValueError, TypeError, ArithmeticError, RuntimeError):
        pass
    raise OptionsReplayFileError()
