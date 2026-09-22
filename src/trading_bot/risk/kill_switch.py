"""Atomic local kill switch whose uncertain state always blocks entries."""

import json
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from trading_bot.clock import Clock, DomainValidationError, SystemClock, require_utc


class KillSwitchError(RuntimeError):
    """Raised when a kill-switch transition cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class KillSwitchStatus:
    active: bool
    reason: str | None
    changed_at: str | None
    state_valid: bool = True


@dataclass(frozen=True, slots=True)
class KillSwitchClearRequest:
    active_breach: bool
    reconciliation_clean: bool
    acknowledged: bool
    reason: str


class FileKillSwitch:
    def __init__(self, path: str | Path, *, clock: Clock | None = None) -> None:
        self._path = Path(path)
        self._clock = SystemClock() if clock is None else clock

    def status(self) -> KillSwitchStatus:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return KillSwitchStatus(False, None, None)
        except OSError:
            return KillSwitchStatus(True, "unreadable_kill_switch", None, False)
        try:
            payload = json.loads(raw)
            if (
                type(payload) is not dict
                or payload.get("active") is not True
                or type(payload.get("reason")) is not str
                or not payload["reason"].strip()
                or type(payload.get("changed_at")) is not str
            ):
                raise ValueError
        except (json.JSONDecodeError, ValueError, KeyError):
            return KillSwitchStatus(True, "invalid_kill_switch_state", None, False)
        return KillSwitchStatus(True, payload["reason"], payload["changed_at"])

    def activate(self, reason: str) -> KillSwitchStatus:
        if type(reason) is not str or not reason.strip():
            raise DomainValidationError("kill-switch reason must be nonempty")
        changed_at = require_utc(self._clock.now()).isoformat()
        payload = self._encode(reason, changed_at)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return self.status()
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return KillSwitchStatus(True, reason, changed_at)

    def clear(self, request: KillSwitchClearRequest) -> KillSwitchStatus:
        if type(request) is not KillSwitchClearRequest:
            raise DomainValidationError("clear request must be canonical")
        if request.active_breach or not request.reconciliation_clean or not request.acknowledged:
            raise KillSwitchError("kill switch cannot clear without complete safety evidence")
        if type(request.reason) is not str or not request.reason.strip():
            raise KillSwitchError("kill switch clear reason must be nonempty")
        if not self.status().active:
            return KillSwitchStatus(False, None, None)
        changed_at = require_utc(self._clock.now()).isoformat()
        cleared = self._path.with_name(f".{self._path.name}.clear.{os.getpid()}")
        try:
            descriptor = os.open(cleared, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(descriptor, self._encode(request.reason, changed_at, active=False))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(cleared, self._path)
            self._path.unlink()
        finally:
            with suppress(FileNotFoundError):
                cleared.unlink()
        return KillSwitchStatus(False, request.reason, changed_at)

    @staticmethod
    def _encode(reason: str, changed_at: str, *, active: bool = True) -> bytes:
        return json.dumps(
            {"active": active, "changed_at": changed_at, "reason": reason},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()


__all__ = [
    "FileKillSwitch",
    "KillSwitchClearRequest",
    "KillSwitchError",
    "KillSwitchStatus",
]
