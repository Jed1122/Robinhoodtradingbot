"""Private atomic joint prefixes for the incapable forward paper diagnostic.

The original typed tape and external latest head must be retained with this entire
namespace. This is single-host exclusion, not distributed leadership or broker
reconciliation. Recovery never creates a cycle or reclaims an incomplete claim.
"""

import fcntl
import hashlib
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.bundle_codec import _json, _mapping
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.bundle_store import (
    _open_root,
    _private,
    _publish,
    _read_descriptor,
    _subdirectory,
)
from trading_bot.market_data.recording import canonical_json
from trading_bot.runtime.etf_forward_paper import (
    MAX_CYCLES,
    ForwardPaperState,
    ForwardPaperTape,
    replay_forward_paper,
)

_NAMESPACE = "etf-forward-paper-owner-v1"
_GENESIS = "0" * 64
_MAX_BYTES = 8 * 1048576
_LIMITS = BundleLimits(_MAX_BYTES, _MAX_BYTES, _MAX_BYTES, 250000, 32)
_CLAIM = re.compile(r"([0-9]{8})\.claim\.json")
_JOINT = re.compile(r"([0-9]{8})\.joint\.json")
_TEMP = re.compile(r"\.tmp-[0-9a-f]{32}")


class ForwardPaperStoreError(ValueError):
    def __init__(self) -> None:
        super().__init__("forward_paper_store_invalid")


class ForwardPaperRecoveryRequired(RuntimeError):
    def __init__(self) -> None:
        super().__init__("forward_paper_recovery_required")


class ForwardPaperWriterBusy(RuntimeError):
    def __init__(self) -> None:
        super().__init__("forward_paper_writer_busy")


def _check(ok: bool) -> None:
    if not ok:
        raise ForwardPaperStoreError()


def _read(directory: int, name: str, bound: int = _MAX_BYTES) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        _check(os.fstat(descriptor).st_nlink == 1)
        return _read_descriptor(descriptor, bound)
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class ForwardPaperCheckpoint:
    sequence: int
    head_hash: str
    state: ForwardPaperState


def _claim(sequence: int, previous: str, state: ForwardPaperState) -> bytes:
    return canonical_json(
        {
            "schema": "etf-forward-paper-claim-v1",
            "sequence": sequence,
            "previous_hash": previous,
            "plan_hash": state.plan_hash,
            "cycle_count": state.cycle_count,
            "prefix_hash": state.prefix_hash,
        }
    ).encode()


def _joint(sequence: int, previous: str, tape: ForwardPaperTape, state: ForwardPaperState) -> bytes:
    body = canonical_json(
        {
            "schema": "etf-forward-paper-joint-v1",
            "sequence": sequence,
            "previous_hash": previous,
            "cycle_count": state.cycle_count,
            "tape": tape,
            "state": state,
            "execution_enabled": False,
            "evidence_promotable": False,
        }
    ).encode()
    _check(len(body) <= _MAX_BYTES)
    return body


def _restore(directory: int, tape: ForwardPaperTape) -> tuple[ForwardPaperCheckpoint, str]:
    names = set(os.listdir(directory))
    _check(len(names) <= 2 * MAX_CYCLES + 16)
    marker = canonical_json(
        {
            "schema": "etf-forward-paper-owner-v1",
            "plan_hash": tape.plan.plan_hash,
            "execution_enabled": False,
            "evidence_promotable": False,
        }
    ).encode()
    try:
        retained_marker = _read(directory, "owner.json", 4096)
    except FileNotFoundError:
        # No remaining journal can be silently attached to a new owner.
        _check(all(_TEMP.fullmatch(n) for n in names - {"writer.lock"}))
        _publish(directory, "owner.json", marker)
    else:
        _check(retained_marker == marker)
    claims: set[int] = set()
    joints: set[int] = set()
    for name in names - {"owner.json", "writer.lock"}:
        claim, joint = _CLAIM.fullmatch(name), _JOINT.fullmatch(name)
        if claim:
            claims.add(int(claim[1]))
        elif joint:
            joints.add(int(joint[1]))
        elif _TEMP.fullmatch(name):
            _read(directory, name)  # Verify but never adopt interrupted staging bytes.
        else:
            raise ForwardPaperStoreError()
    _check(len(claims) <= MAX_CYCLES and joints <= claims)
    _check(claims == set(range(1, len(claims) + 1)))
    _check(joints == set(range(1, len(joints) + 1)))
    _check(len(joints) <= len(claims) <= len(joints) + 1)
    state = replay_forward_paper(replace(tape, cycles=()))
    head = previous_head = _GENESIS
    for sequence in range(1, len(joints) + 1):
        body = _read(directory, f"{sequence:08d}.joint.json")
        row = _mapping(
            _json(body, max_bytes=_MAX_BYTES, limits=_LIMITS),
            {
                "schema",
                "sequence",
                "previous_hash",
                "cycle_count",
                "tape",
                "state",
                "execution_enabled",
                "evidence_promotable",
            },
        )
        count = row["cycle_count"]
        if type(count) is not int:
            raise ForwardPaperStoreError()
        _check(state.cycle_count < count <= len(tape.cycles))
        prefix = replace(tape, cycles=tape.cycles[:count])
        recomputed = replay_forward_paper(prefix)
        _check(body == _joint(sequence, head, prefix, recomputed))
        claim_body = _read(directory, f"{sequence:08d}.claim.json", 4096)
        _check(claim_body == _claim(sequence, head, recomputed))
        previous_head = head
        head = hashlib.sha256(body).hexdigest()
        state = recomputed
    if claims != joints:
        # A claim is never timeout-reclaimed, decoded as an effect, or bypassed.
        _read(directory, f"{len(claims):08d}.claim.json", 4096)
        raise ForwardPaperRecoveryRequired()
    os.fsync(directory)
    return ForwardPaperCheckpoint(len(joints), head, state), previous_head


def _operate(
    root: Path,
    tape: ForwardPaperTape,
    repository_root: Path,
    expected_head: str,
    *,
    advance: bool,
) -> ForwardPaperCheckpoint:
    parent = directory = lock = -1
    try:
        _check(type(tape) is ForwardPaperTape)
        _check(replace(tape) == tape)
        _require_sha256_hex(expected_head, "forward paper head")
        parent = _open_root(root, repository_root)
        directory = _subdirectory(parent, _NAMESPACE, create=True)
        lock = os.open(
            "writer.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=directory,
        )
        _private(lock, directory=False)
        info = os.fstat(lock)
        _check(info.st_nlink == 1 and info.st_size == 0)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ForwardPaperWriterBusy() from None
        current, previous = _restore(directory, tape)
        if not advance:
            _check(expected_head == current.head_hash)
            return current
        complete_prefix = len(tape.cycles) == current.state.cycle_count
        # Exact post-publication response-loss retry can return its verified
        # result. A stale head may never authorize a genuinely new suffix.
        if complete_prefix and current.sequence > 0 and expected_head == previous:
            return current
        _check(expected_head == current.head_hash)
        if complete_prefix:
            return current
        proposed = replay_forward_paper(tape)
        sequence = current.sequence + 1
        body = _joint(sequence, current.head_hash, tape, proposed)
        # All fallible reconstruction completes before the pre-effect claim.
        # Only this atomic local diagnostic commit is an effect; no callbacks.
        _publish(
            directory, f"{sequence:08d}.claim.json", _claim(sequence, current.head_hash, proposed)
        )
        _publish(directory, f"{sequence:08d}.joint.json", body)
        return ForwardPaperCheckpoint(sequence, hashlib.sha256(body).hexdigest(), proposed)
    except (ValueError, TypeError, ArithmeticError, AttributeError, OSError, RecursionError):
        raise ForwardPaperStoreError() from None
    finally:
        for opened in (lock, directory, parent):
            if opened >= 0:
                os.close(opened)


def advance_forward_paper(
    root: Path, tape: ForwardPaperTape, *, repository_root: Path, expected_head: str
) -> ForwardPaperCheckpoint:
    """Verify the prior joint prefix, then durably append this exact extension."""
    return _operate(root, tape, repository_root, expected_head, advance=True)


def recover_forward_paper(
    root: Path, tape: ForwardPaperTape, *, repository_root: Path, expected_head: str
) -> ForwardPaperCheckpoint:
    """Restore paused committed state only; never advance supplied future input."""
    return _operate(root, tape, repository_root, expected_head, advance=False)
