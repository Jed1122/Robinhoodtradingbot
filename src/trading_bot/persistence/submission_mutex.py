"""Single-host nonblocking account submission exclusion using ``flock``."""

import fcntl
import hashlib
import os
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from trading_bot.domain import AccountId, DomainValidationError
from trading_bot.execution.exclusion import SubmissionAlreadyInProgress


class AccountSubmissionMutex:
    """Serialize lease and submission critical sections on one host only."""

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)
        metadata = self._directory.stat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise PermissionError("submission lock directory must be service-owned")
        if metadata.st_mode & 0o077:
            raise PermissionError("submission lock directory must use mode 0700 or stricter")

    @asynccontextmanager
    async def acquire(self, account_id: AccountId) -> AsyncIterator[None]:
        if type(account_id) is not str or not account_id.strip():
            raise DomainValidationError("account_id must be a nonempty exact string")
        digest = hashlib.sha256(account_id.encode()).hexdigest()
        path = self._directory / f"{digest}.lock"
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SubmissionAlreadyInProgress() from None
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


__all__ = ["AccountSubmissionMutex"]
