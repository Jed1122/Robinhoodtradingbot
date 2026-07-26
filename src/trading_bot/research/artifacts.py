"""Private, content-addressed persistence for complete research reports."""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from pathlib import Path

from trading_bot.research.report import (
    ResearchReport,
    render_json,
    report_integrity_reason_codes,
)


class ResearchArtifactError(RuntimeError):
    pass


def persist_research_report(
    directory: str | Path,
    report: ResearchReport,
) -> Path:
    """Create one immutable-by-name report artifact with private permissions."""

    if report_integrity_reason_codes(report):
        raise ResearchArtifactError("research report content addressing is invalid")
    root = Path(directory)
    if not root.exists() and not root.is_symlink():
        parent = root.parent
        try:
            parent_metadata = parent.lstat()
            if (
                not stat.S_ISDIR(parent_metadata.st_mode)
                or parent_metadata.st_uid != os.geteuid()
                or parent_metadata.st_mode & 0o022
            ):
                raise ResearchArtifactError(
                    "research artifact parent must be service-owned and not writable by others"
                )
            root.mkdir(mode=0o700, exist_ok=False)
            os.chmod(root, 0o700)
        except ResearchArtifactError:
            raise
        except OSError as exc:
            raise ResearchArtifactError(
                "research artifact directory could not be created"
            ) from exc
    try:
        metadata = root.lstat()
    except OSError as exc:
        raise ResearchArtifactError("research artifact directory is unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
    ):
        raise ResearchArtifactError(
            "research artifact directory must be service-owned and not writable by others"
        )
    destination = root / f"{report.report_hash}.json"
    encoded = f"{render_json(report)}\n".encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(destination, flags, 0o600)
    except FileExistsError:
        try:
            existing_metadata = destination.lstat()
            if (
                not stat.S_ISREG(existing_metadata.st_mode)
                or existing_metadata.st_uid != os.geteuid()
                or existing_metadata.st_mode & 0o077
            ):
                raise ResearchArtifactError(
                    "existing research artifact does not match its hash"
                )
            existing = destination.read_bytes()
        except ResearchArtifactError:
            raise
        except OSError as exc:
            raise ResearchArtifactError("existing research artifact is unreadable") from exc
        if existing != encoded:
            raise ResearchArtifactError(
                "existing research artifact does not match its hash"
            ) from None
        return destination
    except OSError as exc:
        raise ResearchArtifactError("research artifact could not be created") from exc
    try:
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("research artifact write made no progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except OSError as exc:
        with suppress(OSError):
            destination.unlink(missing_ok=True)
        raise ResearchArtifactError("research artifact could not be committed") from exc
    finally:
        os.close(descriptor)
    try:
        directory_descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        raise ResearchArtifactError(
            "research artifact directory could not be synchronized"
        ) from exc
    return destination


__all__ = ["ResearchArtifactError", "persist_research_report"]
