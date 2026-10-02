"""Durable private source-neutral offline coordinator checkpoints, with paused reconstruction.

The authoritative coordinator reconstructs every committed prefix. A checkpoint
publishes all its accounting and source state together through the established
descriptor-bound, no-overwrite publisher. There is no provider side effect,
production ledger, distributed lease or strategy/promotion authority here.
"""

import fcntl
import hashlib
import os
import re
import stat
from dataclasses import dataclass, replace
from pathlib import Path

from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.bundle_codec import _json, _mapping
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.bundle_store import (
    _open_root,
    _private,
    _publish,
    _read,
    _subdirectory,
)
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.simulation.etf_native_history import _development as _observations
from trading_bot.simulation.etf_native_history import _run_count as _run
from trading_bot.simulation.etf_native_models import EtfHistoryRequest, EtfHistoryResult

_GENESIS = "0" * 64
_NAMESPACE = "etf-native-checkpoints-v1"
_MAX_BYTES = 8 * 1048576
_LIMITS = BundleLimits(_MAX_BYTES, _MAX_BYTES, _MAX_BYTES, 100000, 32)
_NAME = re.compile(r"[0-9]{8}\.etf-native-checkpoint\.json")
_TEMP = re.compile(r"\.tmp-[0-9a-f]{32}")


class EtfNativeCheckpointError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_native_checkpoint_invalid")


def _require(condition: bool) -> None:
    if not condition:
        raise EtfNativeCheckpointError()


@dataclass(frozen=True, slots=True)
class EtfNativeCheckpoint:
    sequence: int
    request_hash: str
    head_hash: str
    result: EtfHistoryResult


def _encode(
    request_hash: str, sequence: int, previous_hash: str, result: EtfHistoryResult
) -> bytes:
    body = canonical_json(
        {
            "schema": "etf-native-checkpoint-v1",
            "sequence": sequence,
            "request_hash": request_hash,
            "previous_hash": previous_hash,
            "source_count": result.source_count,
            "result": result,
            "execution_enabled": False,
            "evidence_promotable": False,
        }
    ).encode()
    _require(len(body) <= _MAX_BYTES)
    return body


def _restore(child: int, request: EtfHistoryRequest, request_hash: str) -> EtfNativeCheckpoint:
    names = set(os.listdir(child))
    _require(len(names) <= 20003)
    marker = canonical_json(
        {
            "schema": "etf-native-checkpoint-owner-v1",
            "request_hash": request_hash,
            "execution_enabled": False,
        }
    ).encode()
    try:
        owner = _read(child, "owner.json", 16384)
    except FileNotFoundError:
        _require(
            names <= {"writer.lock"} or all(_TEMP.fullmatch(n) for n in names - {"writer.lock"})
        )
        _publish(child, "owner.json", marker)
    else:
        _require(owner == marker)
    checkpoints = []
    for name in names - {"owner.json", "writer.lock"}:
        if _TEMP.fullmatch(name):
            # Interrupted publication may retain private staging bytes; they
            # never count as committed state and are not deleted or adopted.
            _read(child, name, _MAX_BYTES)
        else:
            _require(_NAME.fullmatch(name) is not None)
            checkpoints.append(name)
    checkpoints.sort()
    _require(len(checkpoints) <= len(_observations(request)) + 1)
    state = _run(request, 0)
    previous = _GENESIS
    for sequence, name in enumerate(checkpoints, 1):
        _require(name == f"{sequence:08d}.etf-native-checkpoint.json")
        body = _read(child, name, _MAX_BYTES)
        row = _mapping(
            _json(body, max_bytes=_MAX_BYTES, limits=_LIMITS),
            {
                "schema",
                "sequence",
                "request_hash",
                "previous_hash",
                "source_count",
                "result",
                "execution_enabled",
                "evidence_promotable",
            },
        )
        count = row["source_count"]
        if type(count) is not int:
            raise EtfNativeCheckpointError()
        _require(state.source_count < count <= len(_observations(request)))
        result = _run(request, count)
        _require(body == _encode(request_hash, sequence, previous, result))
        previous = hashlib.sha256(body).hexdigest()
        state = result
    # Re-establish directory durability after a prior uncertain publication.
    os.fsync(child)
    return EtfNativeCheckpoint(len(checkpoints), request_hash, previous, state)


def advance_etf_native_checkpoint(
    root: Path,
    request: EtfHistoryRequest,
    *,
    repository_root: Path,
    through_ordinal: int | None = None,
    expected_head: str | None = None,
) -> EtfNativeCheckpoint:
    """Reconstruct committed prefixes, then atomically publish a later prefix.

    An exact retry is idempotent. Earlier cursors and stale expected heads deny.
    Failure before publication leaves prior state; uncertainty after publication
    retains the complete new state for the next verified restore. The local
    non-waiting flock is held through validation, simulation and publication.
    """
    descriptor = child = lock = -1
    try:
        _require(type(request) is EtfHistoryRequest)
        replace(request)
        observations = _observations(request)
        count = len(observations)
        _require(count > 0)
        if through_ordinal is not None:
            _require(type(through_ordinal) is int and through_ordinal >= 0)
            matches = [i + 1 for i, e in enumerate(observations) if e.ordinal == through_ordinal]
            _require(len(matches) == 1)
            count = matches[0]
        if expected_head is not None:
            _require_sha256_hex(expected_head, "checkpoint head")
        request_hash = content_hash(("etf-native-checkpoint-request-v1", request))
        descriptor = _open_root(root, repository_root)
        child = _subdirectory(descriptor, _NAMESPACE, create=True)
        lock = os.open(
            "writer.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=child,
        )
        _private(lock, directory=False)
        metadata = os.fstat(lock)
        _require(
            stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1 and metadata.st_size == 0
        )
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = _restore(child, request, request_hash)
        _require(expected_head is None or expected_head == previous.head_hash)
        _require(count >= previous.result.source_count)
        if count == previous.result.source_count:
            return previous
        result = _run(request, count)
        sequence = previous.sequence + 1
        body = _encode(request_hash, sequence, previous.head_hash, result)
        _publish(child, f"{sequence:08d}.etf-native-checkpoint.json", body)
        return EtfNativeCheckpoint(sequence, request_hash, hashlib.sha256(body).hexdigest(), result)
    except (ValueError, TypeError, ArithmeticError, AttributeError, OSError, RuntimeError):
        raise EtfNativeCheckpointError() from None
    finally:
        for opened in (lock, child, descriptor):
            if opened >= 0:
                os.close(opened)
