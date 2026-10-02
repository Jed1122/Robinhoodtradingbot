"""Pre-effect paper reservations, not a broker ledger or promotion authority.

A claimed cycle is never reclaimed on timeout. Interrupted/uncertain effects
require reconciliation; absence of a durable observation is not permission to
execute again. Local immutable files complement, not replace, the observation
ledger. Both must be retained together by any future operational composition.
"""

import fcntl
import os
import re
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
_CLAIM_NAME = re.compile(r"([0-9a-f]{64})\.claim\.json")
_COMPLETE_NAME = re.compile(r"([0-9a-f]{64})\.complete\.json")
_PREPARED_NAME = re.compile(r"([0-9a-f]{64})\.prepared\.json")
_TEMP_NAME = re.compile(r"\.tmp-[0-9a-f]{32}")


class PaperCycleJournalError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("paper_cycle_journal_invalid")


class PaperCycleRecoveryRequired(RuntimeError):
    def __init__(self) -> None:
        super().__init__("paper_cycle_recovery_required")


class PaperCycleWriterBusy(RuntimeError):
    def __init__(self) -> None:
        super().__init__("paper_cycle_writer_busy")


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
        self._active_descriptor: int | None = None

    @contextmanager
    def _directory(self, *, normalize_body: bool = True) -> Iterator[int]:
        parent = child = lock = -1
        yielded = False
        try:
            if self._active_descriptor is not None:
                _check(self._active_descriptor >= 0)
                yielded = True
                yield self._active_descriptor
                return
            parent = _open_root(self._root, self._repository)
            child = _subdirectory(parent, _NAMESPACE, create=True)
            lock = os.open(
                "writer.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=child,
            )
            _private(lock, directory=False)
            metadata = os.fstat(lock)
            _check(metadata.st_nlink == 1 and metadata.st_size == 0)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PaperCycleWriterBusy() from None
            yielded = True
            yield child
        except (ValueError, TypeError, OSError, AttributeError, RecursionError):
            if yielded and not normalize_body:
                raise
            raise PaperCycleJournalError() from None
        finally:
            for descriptor in (lock, child, parent):
                if descriptor >= 0:
                    os.close(descriptor)

    @contextmanager
    def owner(self) -> Iterator["PaperCycleJournal"]:
        """Hold one directory/owner lease across execution and durable observation.

        This is nonwaiting local exclusion, not a distributed or expiring lease.
        The yielded descriptor-bound handle is invalid after context exit.
        """
        with self._directory(normalize_body=False) as directory:
            owned = PaperCycleJournal(self._root, repository_root=self._repository)
            owned._active_descriptor = directory
            try:
                yield owned
            finally:
                owned._active_descriptor = -1

    @staticmethod
    def _pending(directory: int, recorded_hashes: frozenset[str] | None = None) -> bool:
        names = set(os.listdir(directory))
        _check(len(names) <= 30001)
        claims: list[str] = []
        completions: set[str] = set()
        prepared: set[str] = set()
        for name in names - {"writer.lock"}:
            claim = _CLAIM_NAME.fullmatch(name)
            completed = _COMPLETE_NAME.fullmatch(name)
            preparation = _PREPARED_NAME.fullmatch(name)
            if claim is not None:
                claims.append(claim[1])
            elif completed is not None:
                completions.add(completed[1])
            elif preparation is not None:
                prepared.add(preparation[1])
            elif _TEMP_NAME.fullmatch(name):
                _read_record(directory, name)  # Never adopt interrupted staging bytes.
            else:
                raise PaperCycleJournalError()
        _check(completions <= prepared <= set(claims))
        pending = False
        for cycle_id in claims:
            body = _read_record(directory, cycle_id + ".claim.json")
            row = _mapping(
                _json(body, max_bytes=_MAX_BYTES, limits=_LIMITS),
                {"schema", "claim", "execution_enabled", "evidence_promotable"},
            )
            fields = _mapping(row["claim"], {"cycle_id", "context_hash", "started_at"})
            context = fields["context_hash"]
            if type(context) is not str:
                raise PaperCycleJournalError()
            _, completed_digest = PaperCycleJournal._state(directory, cycle_id, context)
            if (
                completed_digest is not None
                and recorded_hashes is not None
                and completed_digest not in recorded_hashes
            ):
                raise PaperCycleRecoveryRequired()
            pending = pending or completed_digest is None
        return pending

    def require_completed_observations(self, recorded_hashes: frozenset[str]) -> None:
        """Deny admission and promotion after unknown effects or partial-store loss."""
        with self._directory() as directory:
            _check(type(recorded_hashes) is frozenset and len(recorded_hashes) <= 10000)
            for digest in recorded_hashes:
                _require_sha256_hex(digest, "paper observation")
            if self._pending(directory, recorded_hashes):
                raise PaperCycleRecoveryRequired()

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
        try:
            prepared_body = _read_record(directory, cycle_id + ".prepared.json")
        except FileNotFoundError:
            prepared_body = None
        if claim_body is None:
            _check(completed_body is None and prepared_body is None)
            return None, None
        row = _mapping(
            _json(claim_body, max_bytes=_MAX_BYTES, limits=_LIMITS),
            {"schema", "claim", "execution_enabled", "evidence_promotable"},
        )
        fields = _mapping(row["claim"], {"cycle_id", "context_hash", "started_at"})
        claim = PaperCycleClaim(cycle_id, context_hash, _time(fields["started_at"]))
        _check(claim_body == _encoded_claim(claim))
        expected = _prepared_digest(claim, prepared_body)
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
        _check(expected == digest and completed_body == _encoded_completion(claim, digest))
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
            if self._pending(directory):
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
            prepared = _read_record(directory, claim.cycle_id + ".prepared.json")
            _check(_prepared_digest(claim, prepared) == observation_hash)
            _publish(
                directory,
                claim.cycle_id + ".complete.json",
                _encoded_completion(claim, observation_hash),
            )

    def prepare_observation(self, claim: PaperCycleClaim, observation_hash: str) -> None:
        """Bind computed evidence before ledger append; never release a reservation."""
        with self._directory() as directory:
            _check(type(claim) is PaperCycleClaim)
            replace(claim)
            _require_sha256_hex(observation_hash, "paper observation")
            stored, completed = self._state(directory, claim.cycle_id, claim.context_hash)
            _check(stored == claim and completed in (None, observation_hash))
            _publish(
                directory,
                claim.cycle_id + ".prepared.json",
                _encoded_prepared(claim, observation_hash),
            )

    def expected_observation(self, claim: PaperCycleClaim) -> str | None:
        with self._directory() as directory:
            _check(type(claim) is PaperCycleClaim)
            replace(claim)
            stored, _ = self._state(directory, claim.cycle_id, claim.context_hash)
            _check(stored == claim)
            try:
                body = _read_record(directory, claim.cycle_id + ".prepared.json")
            except FileNotFoundError:
                body = None
            return _prepared_digest(claim, body)


def _encoded_completion(claim: PaperCycleClaim, observation_hash: str) -> bytes:
    return canonical_json(
        {
            "schema": "paper-cycle-complete-v1",
            "claim_hash": claim.claim_hash,
            "observation_hash": observation_hash,
        }
    ).encode()


def _encoded_prepared(claim: PaperCycleClaim, observation_hash: str) -> bytes:
    return canonical_json(
        {
            "schema": "paper-cycle-prepared-v1",
            "claim_hash": claim.claim_hash,
            "observation_hash": observation_hash,
        }
    ).encode()


def _prepared_digest(claim: PaperCycleClaim, body: bytes | None) -> str | None:
    if body is None:
        return None
    row = _mapping(
        _json(body, max_bytes=_MAX_BYTES, limits=_LIMITS),
        {"schema", "claim_hash", "observation_hash"},
    )
    digest = row["observation_hash"]
    if type(digest) is not str:
        raise PaperCycleJournalError()
    _require_sha256_hex(digest, "paper observation")
    _check(body == _encoded_prepared(claim, digest))
    return digest
