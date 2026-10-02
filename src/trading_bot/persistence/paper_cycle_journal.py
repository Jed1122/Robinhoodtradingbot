"""Pre-effect paper reservations, not a broker ledger or promotion authority.

A claimed cycle is never reclaimed on timeout. Interrupted/uncertain effects
require reconciliation; absence of a durable observation is not permission to
execute again. Local immutable files complement, not replace, the observation
ledger. Both must be retained together by any future operational composition.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.bundle_codec import _json, _mapping, _time
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.bundle_store import (
    _open_root,
    _private,
    _publish,
    _read_descriptor,
    _subdirectory,
)
from trading_bot.market_data.recording import canonical_json, content_hash

_NAMESPACE = "paper-cycle-journal-v1"
_MAX_BYTES = 4096
_LIMITS = BundleLimits(_MAX_BYTES, _MAX_BYTES, _MAX_BYTES, 32, 8)


class PaperCycleJournalError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("paper_cycle_journal_invalid")


class PaperCycleRecoveryRequired(RuntimeError):
    def __init__(self) -> None:
        super().__init__("paper_cycle_recovery_required")


def _check(ok: bool) -> None:
    if not ok:
        raise PaperCycleJournalError()


@dataclass(frozen=True, slots=True)
class PaperCycleClaim:
    cycle_id: str
    context_hash: str
    started_at: datetime

    def __post_init__(self) -> None:
        _require_sha256_hex(self.cycle_id, "paper cycle")
        _require_sha256_hex(self.context_hash, "paper context")
        _check(type(self.started_at) is datetime)
        require_utc(self.started_at)

    @property
    def claim_hash(self) -> str:
        return content_hash(("paper-cycle-claim-v1", self))


def _encoded_claim(claim: PaperCycleClaim) -> bytes:
    return canonical_json(
        {
            "schema": "paper-cycle-claim-v1",
            "claim": claim,
            "execution_enabled": False,
            "evidence_promotable": False,
        }
    ).encode()


def _read_record(directory: int, name: str) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        _check(os.fstat(descriptor).st_nlink == 1)
        return _read_descriptor(descriptor, _MAX_BYTES)
    finally:
        os.close(descriptor)


class PaperCycleJournal:
    """Descriptor-bound fail-closed reservation journal outside the repository."""

    def __init__(self, root: Path, *, repository_root: Path) -> None:
        self._root = root
        self._repository = repository_root

    @contextmanager
    def _directory(self) -> Iterator[int]:
        parent = child = -1
        try:
            parent = _open_root(self._root, self._repository)
            child = _subdirectory(parent, _NAMESPACE, create=True)
            yield child
        except (ValueError, TypeError, OSError, AttributeError, RecursionError):
            raise PaperCycleJournalError() from None
        finally:
            for descriptor in (child, parent):
                if descriptor >= 0:
                    os.close(descriptor)

    @staticmethod
    def _state(
        directory: int, cycle_id: str, context_hash: str
    ) -> tuple[PaperCycleClaim | None, str | None]:
        _require_sha256_hex(cycle_id, "paper cycle")
        _require_sha256_hex(context_hash, "paper context")
        try:
            claim_body = _read_record(directory, cycle_id + ".claim.json")
        except FileNotFoundError:
            claim_body = None
        try:
            completed_body = _read_record(directory, cycle_id + ".complete.json")
        except FileNotFoundError:
            completed_body = None
        if claim_body is None:
            _check(completed_body is None)
            return None, None
        row = _mapping(
            _json(claim_body, max_bytes=_MAX_BYTES, limits=_LIMITS),
            {"schema", "claim", "execution_enabled", "evidence_promotable"},
        )
        fields = _mapping(row["claim"], {"cycle_id", "context_hash", "started_at"})
        claim = PaperCycleClaim(cycle_id, context_hash, _time(fields["started_at"]))
        _check(claim_body == _encoded_claim(claim))
        if completed_body is None:
            return claim, None
        completed = _mapping(
            _json(completed_body, max_bytes=_MAX_BYTES, limits=_LIMITS),
            {"schema", "claim_hash", "observation_hash"},
        )
        digest = completed["observation_hash"]
        if type(digest) is not str:
            raise PaperCycleJournalError()
        _require_sha256_hex(digest, "paper observation")
        _check(completed_body == _encoded_completion(claim, digest))
        return claim, digest

    def inspect(
        self, cycle_id: str, context_hash: str
    ) -> tuple[PaperCycleClaim | None, str | None]:
        with self._directory() as directory:
            state = self._state(directory, cycle_id, context_hash)
            # Reestablish directory durability after a prior uncertain publication.
            os.fsync(directory)
            return state

    def begin(self, cycle_id: str, context_hash: str, started_at: datetime) -> PaperCycleClaim:
        with self._directory() as directory:
            claim = PaperCycleClaim(cycle_id, context_hash, started_at)
            existing, _ = self._state(directory, cycle_id, context_hash)
            if existing is not None:
                raise PaperCycleRecoveryRequired()
            # O_EXCL claims before writing; incomplete bytes are an unknown
            # reservation, never an unclaimed cycle. No effect precedes fsync.
            try:
                descriptor = os.open(
                    cycle_id + ".claim.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK,
                    0o600,
                    dir_fd=directory,
                )
            except FileExistsError:
                raise PaperCycleRecoveryRequired() from None
            try:
                _private(descriptor, directory=False)
                body = _encoded_claim(claim)
                written = 0
                while written < len(body):
                    count = os.write(descriptor, memoryview(body)[written:])
                    _check(count > 0)
                    written += count
                os.fsync(descriptor)
                os.fsync(directory)
            finally:
                os.close(descriptor)
            return claim

    def complete(self, claim: PaperCycleClaim, observation_hash: str) -> None:
        with self._directory() as directory:
            _check(type(claim) is PaperCycleClaim)
            replace(claim)
            _require_sha256_hex(observation_hash, "paper observation")
            stored, prior_hash = self._state(directory, claim.cycle_id, claim.context_hash)
            _check(stored == claim and prior_hash in (None, observation_hash))
            _publish(
                directory,
                claim.cycle_id + ".complete.json",
                _encoded_completion(claim, observation_hash),
            )


def _encoded_completion(claim: PaperCycleClaim, observation_hash: str) -> bytes:
    return canonical_json(
        {
            "schema": "paper-cycle-complete-v1",
            "claim_hash": claim.claim_hash,
            "observation_hash": observation_hash,
        }
    ).encode()
