"""One private stock-archive writer and conservative pre-effect storage admission."""

from __future__ import annotations

import fcntl
import os
import re
import stat
from pathlib import Path
from types import TracebackType
from typing import Self

from trading_bot.config.stock_research import StockWorkerSettings
from trading_bot.runtime.stock_capture import (
    _MAX_ARTIFACT_BYTES,
    _duplicate_directory,
    _private_directory,
)

LOCK_NAME = ".stock-research.lock"
_FILE = re.compile(
    r"(?:[0-9a-f]{64}\.stock-(?:observation|capture|dossiers|screen)\.json"
    r"|\.pending-[0-9a-f]{32})\Z"
)


class StockArchiveError(ValueError):
    """Fixed local code; never paths, provider text or credentials."""


def _private_file(info: os.stat_result) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
    )


class StockArchiveLease:
    """A cooperating host-local flock, independent of config/code/phase identities.

    Never unlinks or repairs the anchor. The caller holds this outer lease before
    database admission or credential construction through all transport cleanup.
    Internal capture/report calls borrow its directory handle instead of relocking.
    """

    def __init__(self, root: Path, *, _directory_fd: int | None = None) -> None:
        self._root, self._borrowed = root, _directory_fd
        self._directory = self._lock = -1

    def __enter__(self) -> Self:
        if self._directory >= 0 or self._lock >= 0:
            raise StockArchiveError("stock_archive_already_owned")
        try:
            self._directory = (
                _private_directory(self._root)
                if self._borrowed is None
                else _duplicate_directory(self._borrowed)
            )
            self._lock = os.open(
                LOCK_NAME,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                0o600,
                dir_fd=self._directory,
            )
            self._owned()
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fsync(self._lock)
            os.fsync(self._directory)
            self._owned()
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise StockArchiveError("stock_archive_unavailable_or_owned") from None

    def _owned(self) -> None:
        try:
            if self._directory < 0 or self._lock < 0:
                raise ValueError
            directory = os.fstat(self._directory)
            anchor = os.fstat(self._lock)
            named = os.stat(LOCK_NAME, dir_fd=self._directory, follow_symlinks=False)
            if (
                not stat.S_ISDIR(directory.st_mode)
                or directory.st_uid != os.geteuid()
                or stat.S_IMODE(directory.st_mode) != 0o700
                or not _private_file(anchor)
                or anchor.st_size != 0
                or not _private_file(named)
                or (anchor.st_dev, anchor.st_ino) != (named.st_dev, named.st_ino)
            ):
                raise ValueError
        except Exception:
            raise StockArchiveError("stock_archive_ownership_denied") from None

    @property
    def directory_fd(self) -> int:
        self._owned()
        return self._directory

    def admit(self, *, remaining_calls: int, policy: StockWorkerSettings) -> dict[str, int]:
        """Reserve worst-case logical growth; filesystem space is not an OS reservation.

        Count every retained name, including crash orphans and pending publications.
        A max-sized temporary body/name is charged separately even for a cache hit.
        No deletion, deduplication credit or unsafe metadata normalization occurs.
        """
        try:
            self._owned()
            if (
                type(remaining_calls) is not int
                or not 0 <= remaining_calls <= 32
                or not isinstance(policy, StockWorkerSettings)
            ):
                raise ValueError
            checked = StockWorkerSettings.model_validate(policy.model_dump())
            existing_bytes = existing_files = 0
            with os.scandir(self._directory) as entries:
                for entry in entries:
                    existing_files += 1
                    if existing_files > checked.max_archive_files:
                        raise ValueError
                    if entry.name != LOCK_NAME and _FILE.fullmatch(entry.name) is None:
                        raise ValueError
                    metadata = entry.stat(follow_symlinks=False)
                    if not _private_file(metadata):
                        raise ValueError
                    existing_bytes += metadata.st_size
                    if existing_bytes > checked.max_archive_bytes:
                        raise ValueError
            files = remaining_calls + 3
            size = files * _MAX_ARTIFACT_BYTES
            available = os.fstatvfs(self._directory)
            values = (available.f_bavail, available.f_frsize, available.f_favail)
            if any(type(value) is not int or value <= 0 for value in values):
                raise ValueError
            metadata_margin = files * max(4096, available.f_frsize)
            if (
                existing_files + files > checked.max_archive_files
                or existing_bytes + size > checked.max_archive_bytes
                or available.f_bavail * available.f_frsize < size + metadata_margin
                or available.f_favail < files
            ):
                raise ValueError
            self._owned()
            return {
                "existing_bytes": existing_bytes,
                "existing_files": existing_files,
                "reserved_bytes": size,
                "reserved_files": files,
            }
        except Exception:
            raise StockArchiveError("stock_archive_capacity_denied") from None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        lock, directory = self._lock, self._directory
        self._lock = self._directory = -1
        try:
            if lock >= 0:
                os.close(lock)
        finally:
            if directory >= 0:
                os.close(directory)
