"""Authenticated tools/list capture with no provider-tool invocation authority."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from trading_bot.brokers.robinhood_mcp_sdk import RobinhoodMcpSchemaConnection
from trading_bot.capabilities import write_tools_snapshot

_DEPENDENCY_LOG_DISABLE_LEVEL = logging.CRITICAL


class AuthenticatedCapabilityCaptureError(RuntimeError):
    """Stable failure boundary for authenticated schema-only discovery."""


@contextmanager
def _suppress_untrusted_dependency_logs() -> Iterator[None]:
    previous_level = logging.root.manager.disable
    logging.disable(_DEPENDENCY_LOG_DISABLE_LEVEL)
    try:
        yield
    finally:
        logging.disable(previous_level)


def _validate_private_artifact_path(output: Path, *, require_file: bool) -> None:
    parent = output.parent
    parent_metadata = parent.lstat()
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.geteuid()
        or parent_metadata.st_mode & 0o022
    ):
        raise AuthenticatedCapabilityCaptureError(
            "authenticated schema capture failed safely"
        )
    if output.is_symlink():
        raise AuthenticatedCapabilityCaptureError(
            "authenticated schema capture failed safely"
        )
    if not output.exists():
        if require_file:
            raise AuthenticatedCapabilityCaptureError(
                "authenticated schema capture failed safely"
            )
        return
    metadata = output.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
    ):
        raise AuthenticatedCapabilityCaptureError(
            "authenticated schema capture failed safely"
        )


def run_authenticated_schema_capture(
    *,
    oauth_store: str | Path,
    output: str | Path,
) -> dict[str, object]:
    """Capture all declarations once and return only non-sensitive status."""

    destination = Path(output)
    previous_umask = os.umask(0o077)
    try:
        _validate_private_artifact_path(destination, require_file=False)

        async def capture() -> dict[str, object]:
            async with RobinhoodMcpSchemaConnection(
                oauth_store_dir=oauth_store,
            ) as connection:
                snapshot = await write_tools_snapshot(
                    connection.session,
                    destination,
                    omit_descriptions=True,
                )
            _validate_private_artifact_path(destination, require_file=True)
            artifact = destination.read_bytes()
            return {
                "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
                "method": "tools/list",
                "status": "authenticated_schema_capture_complete",
                "tool_count": len(snapshot.tools),
                "tools_invoked": False,
                "transport_authenticated": True,
            }

        with _suppress_untrusted_dependency_logs():
            return asyncio.run(capture())
    except AuthenticatedCapabilityCaptureError:
        raise
    except Exception:
        raise AuthenticatedCapabilityCaptureError(
            "authenticated schema capture failed safely"
        ) from None
    finally:
        os.umask(previous_umask)


__all__ = [
    "AuthenticatedCapabilityCaptureError",
    "run_authenticated_schema_capture",
]
