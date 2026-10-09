"""Private synthetic account checkpoints reconstructed from original events.

Declared hashes identify inputs, not authenticated market or executable evidence.
This single-host offline store never grants execution or promotion authority.
"""

import fcntl
import hashlib
import os
import re
import stat
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from trading_bot.config.loader import LoadedConfig
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.bundle_codec import _json
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.bundle_store import (
    _open_root,
    _private,
    _publish,
    _read_descriptor,
    _subdirectory,
)
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.etf_capital_feasibility import _config
from trading_bot.simulation.etf_capital_account import (
    CapitalAccountEvent,
    CapitalAccountReplay,
    replay_capital_account,
)

_MAX_BYTES = 8 * 1048576
_LIMITS = BundleLimits(_MAX_BYTES, _MAX_BYTES, _MAX_BYTES, 100000, 64)
_NAME = re.compile(r"[0-9]{8}\.capital-account-checkpoint\.json")
_TEMP = re.compile(r"\.tmp-[0-9a-f]{32}")
_GENESIS = "0" * 64


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("capital_account_checkpoint_invalid")


@dataclass(frozen=True, slots=True)
class CapitalAccountCheckpoint:
    sequence: int
    request_hash: str
    head_hash: str
    result: CapitalAccountReplay


def _body(
    request_hash: str, sequence: int, previous: str, count: int, result: CapitalAccountReplay
) -> bytes:
    body = canonical_json(
        {
            "schema": "capital-account-checkpoint-v1",
            "request_hash": request_hash,
            "sequence": sequence,
            "previous_hash": previous,
            "source_count": count,
            "result": result,
            "execution_enabled": False,
            "evidence_promotable": False,
        }
    ).encode()
    _require(len(body) <= _MAX_BYTES)
    return body


def _single_file(child: int, name: str, limit: int) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=child)
    try:
        metadata = os.fstat(descriptor)
        _require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink in (1, 2))
        return _read_descriptor(descriptor, limit)
    finally:
        os.close(descriptor)


def _inventory(child: int) -> tuple[set[str], int]:
    names = set(os.listdir(child))
    _require(len(names) <= 8196)
    groups: dict[tuple[int, int], list[str]] = {}
    links: dict[tuple[int, int], int] = {}
    sizes: dict[tuple[int, int], int] = {}
    for name in names:
        _require(
            name in {"owner.json", "writer.lock"}
            or bool(_NAME.fullmatch(name))
            or bool(_TEMP.fullmatch(name))
        )
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=child)
        try:
            _private(descriptor, directory=False)
            metadata = os.fstat(descriptor)
            _require(metadata.st_nlink in (1, 2) and metadata.st_size <= _MAX_BYTES)
            identity = (metadata.st_dev, metadata.st_ino)
            groups.setdefault(identity, []).append(name)
            links[identity] = metadata.st_nlink
            sizes[identity] = metadata.st_size
        finally:
            os.close(descriptor)
    for identity, aliases in groups.items():
        _require(len(aliases) == links[identity])
        if len(aliases) == 2:
            _require(
                sum(bool(_TEMP.fullmatch(n)) for n in aliases) == 1
                and all(n != "writer.lock" for n in aliases)
            )
    total = sum(sizes.values())
    _require(total <= 64 * 1048576)
    return names, total


def advance_capital_account_checkpoint(
    root: Path,
    *,
    loaded: LoadedConfig,
    initial_cash: Decimal,
    events: tuple[CapitalAccountEvent, ...],
    code_hash: str,
    repository_root: Path,
    through_count: int,
    expected_head: str | None = None,
) -> CapitalAccountCheckpoint:
    """Publish a later prefix; reject stale writers, altered owners and corruption.

    Original full inputs are validated before touching storage. Persisted balances
    are compared against independent reconstruction, never adopted as state.
    Recognized staging files are verified, retained and never adopted as state.
    """
    descriptor = child = lock = -1
    try:
        _config(loaded)
        _require_sha256_hex(code_hash, "declared code hash")
        if expected_head is not None:
            _require_sha256_hex(expected_head, "checkpoint head")
        _require(type(through_count) is int and 0 < through_count <= len(events))
        replay_capital_account(initial_cash=initial_cash, events=events)
        source = canonical_json(
            (
                "capital-account-input-v1",
                loaded.config_hash,
                code_hash,
                initial_cash,
                events,
            )
        ).encode()
        _require(len(source) <= _MAX_BYTES)
        request_hash = content_hash(("capital-account-input-v1", source.decode()))
        result = replay_capital_account(initial_cash=initial_cash, events=events[:through_count])
        # Bound the complete input/envelope pair before any publication.
        _require(
            len(source) + len(_body(request_hash, 4096, _GENESIS, through_count, result))
            <= _MAX_BYTES
        )
        descriptor = _open_root(root, repository_root)
        child = _subdirectory(descriptor, "capital-account-checkpoints-v1", create=True)
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
        names, occupancy = _inventory(child)
        owner = canonical_json(
            {
                "schema": "capital-account-owner-v1",
                "request_hash": request_hash,
                "execution_enabled": False,
                "evidence_promotable": False,
            }
        ).encode()
        if "owner.json" in names:
            _require(_single_file(child, "owner.json", 16384) == owner)
        else:
            _require(all(n == "writer.lock" or _TEMP.fullmatch(n) for n in names))
            first_body = _body(request_hash, 1, _GENESIS, through_count, result)
            _require(
                len(names) + 4 <= 8196 and occupancy + len(owner) + len(first_body) <= 64 * 1048576
            )
        previous = _GENESIS
        prior_count = 0
        checkpoint = None
        heads = [_GENESIS]
        counts = [0]
        files = sorted(n for n in names if _NAME.fullmatch(n))
        for sequence, name in enumerate(files, 1):
            _require(name == f"{sequence:08d}.capital-account-checkpoint.json")
            encoded = _single_file(child, name, _MAX_BYTES)
            row = _json(encoded, max_bytes=_MAX_BYTES, limits=_LIMITS)
            if not isinstance(row, dict):
                raise ValueError("capital_account_checkpoint_invalid")
            count = row.get("source_count")
            if type(count) is not int:
                raise ValueError("capital_account_checkpoint_invalid")
            _require(prior_count < count <= len(events))
            restored = replay_capital_account(initial_cash=initial_cash, events=events[:count])
            _require(encoded == _body(request_hash, sequence, previous, count, restored))
            previous = hashlib.sha256(encoded).hexdigest()
            prior_count = count
            checkpoint = CapitalAccountCheckpoint(sequence, request_hash, previous, restored)
            heads.append(previous)
            counts.append(count)
        for name in sorted(n for n in names if _TEMP.fullmatch(n)):
            staging = _single_file(child, name, _MAX_BYTES)
            if staging == owner:
                continue
            row = _json(staging, max_bytes=_MAX_BYTES, limits=_LIMITS)
            if not isinstance(row, dict):
                raise ValueError("capital_account_checkpoint_invalid")
            stage_sequence, stage_count = row.get("sequence"), row.get("source_count")
            if type(stage_sequence) is not int or type(stage_count) is not int:
                raise ValueError("capital_account_checkpoint_invalid")
            _require(
                1 <= stage_sequence <= len(files) + 1
                and counts[stage_sequence - 1] < stage_count <= len(events)
            )
            reconstructed = replay_capital_account(
                initial_cash=initial_cash, events=events[:stage_count]
            )
            _require(
                staging
                == _body(
                    request_hash,
                    stage_sequence,
                    heads[stage_sequence - 1],
                    stage_count,
                    reconstructed,
                )
            )
        exact_retry = through_count == prior_count and len(heads) > 1 and expected_head == heads[-2]
        _require(expected_head is None or expected_head == previous or exact_retry)
        _require(through_count >= prior_count)
        os.fsync(child)
        if through_count == prior_count:
            if checkpoint is None:
                raise ValueError("capital_account_checkpoint_invalid")
            return checkpoint
        if "owner.json" not in names:
            _publish(child, "owner.json", owner)
            occupancy += len(owner)
            names.add("owner.json")
        sequence = len(files) + 1
        encoded = _body(request_hash, sequence, previous, through_count, result)
        _require(len(names) + 2 <= 8196 and occupancy + len(encoded) <= 64 * 1048576)
        _publish(child, f"{sequence:08d}.capital-account-checkpoint.json", encoded)
        return CapitalAccountCheckpoint(
            sequence, request_hash, hashlib.sha256(encoded).hexdigest(), result
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError, OSError, RuntimeError):
        raise ValueError("capital_account_checkpoint_invalid") from None
    finally:
        for opened in (lock, child, descriptor):
            if opened >= 0:
                os.close(opened)
