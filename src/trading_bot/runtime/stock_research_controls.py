"""Explicit local collector authority, independent of account and trading controls."""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from trading_bot.clock import require_utc
from trading_bot.market_data.bundle_store import _open_root
from trading_bot.market_data.recording import canonical_json
from trading_bot.runtime.stock_archive_lease import _private_file

_STATE = "stock-control.json"
_LOCK = ".stock-control.lock"
_LIMIT = 8192
_ZERO = "0" * 64
type Digest = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
type ControlId = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{32}$")]
type Action = Literal["pause", "kill", "resume"]


class StockResearchControlError(ValueError):
    """Closed local code; never provider errors, paths or credential material."""


@contextmanager
def _control_io() -> Iterator[None]:
    try:
        yield
    except StockResearchControlError:
        raise
    except Exception:
        raise StockResearchControlError("stock_control_denied") from None


class StockControlRecord(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", hide_input_in_errors=True)
    schema_version: Literal["stock-research-control-v1"]
    scope: Literal["robinhood_stock_research_v1"]
    control_id: ControlId
    generation: Annotated[StrictInt, Field(ge=0, le=1_000_000_000)]
    previous_sha256: Digest
    action: Literal["initialize", "pause", "kill", "resume"]
    status: Literal["paused", "running", "killed"]
    changed_at: datetime
    config_hash: Digest | None
    code_hash: Digest | None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        require_utc(self.changed_at)
        expected = {
            "initialize": "paused",
            "pause": "paused",
            "kill": "killed",
            "resume": "running",
        }
        if (
            self.status != expected[self.action]
            or (self.generation == 0) != (self.action == "initialize")
            or (self.previous_sha256 == _ZERO) != (self.generation == 0)
            or (self.status == "running")
            != (self.config_hash is not None and self.code_hash is not None)
            or (
                self.status != "running"
                and (self.config_hash is not None or self.code_hash is not None)
            )
        ):
            raise ValueError("stock_control_denied")
        return self


@dataclass(frozen=True, slots=True)
class StockControlState:
    record: StockControlRecord
    sha256: str


@dataclass(frozen=True, slots=True)
class StockControlGrant:
    state: StockControlState
    root_identity: tuple[int, int]


def _encode(record: StockControlRecord) -> bytes:
    checked = StockControlRecord.model_validate(record.model_dump())
    return canonical_json(checked.model_dump(mode="json")).encode()


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


class StockResearchControls:
    """Cooperating same-host dispatch barrier; missing state never enables work.

    All mutations and admitted operations use one independent nonblocking mutex.
    Busy means no acknowledgement. An operation already holding a permit can finish
    before pause/kill succeeds. A generation change permanently fences its old grant.
    """

    def __init__(
        self, root: Path, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._root, self._clock = root, clock
        self._last_observed: datetime | None = None

    def _now(self) -> datetime:
        now = require_utc(self._clock())
        if self._last_observed is not None and now < self._last_observed:
            raise ValueError
        self._last_observed = now
        return now

    def _named(self, directory: int) -> tuple[int, int]:
        current = _open_root(self._root, Path(__file__).resolve().parents[3])
        try:
            info = os.fstat(directory)
            named = os.fstat(current)
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700
                or _identity(info) != _identity(named)
            ):
                raise ValueError
            return _identity(info)
        finally:
            os.close(current)

    def _inventory(self, directory: int, *, temporary: str | None = None) -> None:
        allowed = {_STATE, _LOCK} | ({temporary} if temporary is not None else set())
        count = 0
        seen = set()
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                seen.add(entry.name)
                info = entry.stat(follow_symlinks=False)
                if count > len(allowed) or entry.name not in allowed or not _private_file(info):
                    raise ValueError
                if info.st_size > _LIMIT or (entry.name == _LOCK and info.st_size != 0):
                    raise ValueError
        if _STATE in seen and _LOCK not in seen:
            raise ValueError

    @contextmanager
    def _directory(self) -> Iterator[int]:
        descriptor = -1
        try:
            with _control_io():
                if not self._root.is_absolute() or self._root.resolve(strict=True) != self._root:
                    raise ValueError
                descriptor = _open_root(self._root, Path(__file__).resolve().parents[3])
                self._named(descriptor)
                self._inventory(descriptor)
            yield descriptor
        finally:
            if descriptor >= 0:
                with _control_io():
                    try:
                        self._named(descriptor)
                    finally:
                        os.close(descriptor)

    def _anchor(self, directory: int, descriptor: int) -> None:
        held = os.fstat(descriptor)
        named = os.stat(_LOCK, dir_fd=directory, follow_symlinks=False)
        if (
            not _private_file(held)
            or not _private_file(named)
            or held.st_size != 0
            or named.st_size != 0
            or _identity(held) != _identity(named)
        ):
            raise ValueError
        self._named(directory)

    @contextmanager
    def _locked(self, *, create: bool = False) -> Iterator[int]:
        with self._directory() as directory:
            descriptor = -1
            try:
                with _control_io():
                    if create:
                        try:
                            os.stat(_STATE, dir_fd=directory, follow_symlinks=False)
                        except FileNotFoundError:
                            pass
                        else:
                            raise ValueError
                    flags = os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
                    if create:
                        try:
                            descriptor = os.open(
                                _LOCK, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory
                            )
                        except FileExistsError:
                            descriptor = os.open(_LOCK, flags, dir_fd=directory)
                    else:
                        descriptor = os.open(_LOCK, flags, dir_fd=directory)
                    self._anchor(directory, descriptor)
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise StockResearchControlError("stock_control_busy") from None
                    self._anchor(directory, descriptor)
                    if create:
                        os.fsync(descriptor)
                        os.fsync(directory)
                yield directory
            finally:
                if descriptor >= 0:
                    with _control_io():
                        try:
                            self._anchor(directory, descriptor)
                        finally:
                            os.close(descriptor)

    def _read(self, directory: int) -> StockControlState:
        descriptor = os.open(
            _STATE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory
        )
        try:
            info = os.fstat(descriptor)
            if not _private_file(info) or not 0 < info.st_size <= _LIMIT:
                raise ValueError
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                body = stream.read(_LIMIT + 1)
            record = StockControlRecord.model_validate_json(body)
            named = os.stat(_STATE, dir_fd=directory, follow_symlinks=False)
            if (
                len(body) != info.st_size
                or _encode(record) != body
                or not _private_file(named)
                or _identity(info) != _identity(named)
                or record.changed_at > self._now()
            ):
                raise ValueError
            return StockControlState(record, hashlib.sha256(body).hexdigest())
        finally:
            os.close(descriptor)

    def read(self) -> StockControlState:
        """Read-only observation; mutation still requires compare-and-swap under lock."""
        with _control_io(), self._directory() as directory:
            return self._read(directory)

    def _publish(
        self, directory: int, record: StockControlRecord, *, initialize: bool
    ) -> StockControlState:
        body = _encode(record)
        temporary = ".pending-" + uuid.uuid4().hex
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            self._inventory(directory, temporary=temporary)
            self._named(directory)
            if initialize:
                os.link(
                    temporary,
                    _STATE,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
                os.unlink(temporary, dir_fd=directory)
            else:
                os.replace(temporary, _STATE, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
            state = self._read(directory)
            if _encode(state.record) != body:
                raise ValueError
            return state
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=directory)

    def initialize(self) -> StockControlState:
        with _control_io(), self._locked(create=True) as directory:
            record = StockControlRecord(
                schema_version="stock-research-control-v1",
                scope="robinhood_stock_research_v1",
                control_id=uuid.uuid4().hex,
                generation=0,
                previous_sha256=_ZERO,
                action="initialize",
                status="paused",
                changed_at=self._now(),
                config_hash=None,
                code_hash=None,
            )
            return self._publish(directory, record, initialize=True)

    def change(
        self,
        action: Action,
        *,
        expected_sha256: str,
        config_hash: str | None = None,
        code_hash: str | None = None,
    ) -> StockControlState:
        with _control_io(), self._locked() as directory:
            previous = self._read(directory)
            if (
                action not in {"pause", "kill", "resume"}
                or type(expected_sha256) is not str
                or previous.sha256 != expected_sha256
                or previous.record.status == "killed"
                or (action != "resume" and (config_hash is not None or code_hash is not None))
            ):
                raise StockResearchControlError("stock_control_denied")
            record = StockControlRecord(
                schema_version=previous.record.schema_version,
                scope=previous.record.scope,
                control_id=previous.record.control_id,
                generation=previous.record.generation + 1,
                previous_sha256=previous.sha256,
                action=action,
                status={"pause": "paused", "kill": "killed", "resume": "running"}[action],  # type: ignore[arg-type]
                changed_at=self._now(),
                config_hash=config_hash,
                code_hash=code_hash,
            )
            return self._publish(directory, record, initialize=False)

    def grant(self, *, config_hash: str, code_hash: str) -> StockControlGrant:
        with _control_io(), self._locked() as directory:
            state = self._read(directory)
            if (
                state.record.status != "running"
                or state.record.config_hash != config_hash
                or state.record.code_hash != code_hash
            ):
                raise StockResearchControlError("stock_control_denied")
            return StockControlGrant(state, self._named(directory))

    @contextmanager
    def permit(self, grant: StockControlGrant) -> Iterator[None]:
        with self._locked() as directory:
            with _control_io():
                if (
                    type(grant) is not StockControlGrant
                    or self._named(directory) != grant.root_identity
                ):
                    raise StockResearchControlError("stock_control_denied")
                state = self._read(directory)
                if state != grant.state or state.record.status != "running":
                    raise StockResearchControlError("stock_control_denied")
            try:
                yield None
            finally:
                with _control_io():
                    if self._read(directory) != state:
                        raise StockResearchControlError("stock_control_denied")
