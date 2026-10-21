"""Explicit browser grant and schema capture; no provider-tool invocation authority."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

from trading_bot.brokers.robinhood_mcp_sdk import (
    OAUTH_FLOW_TIMEOUT_SECONDS,
    EncryptedFileTokenStorage,
    LoopbackOAuthCallback,
    RobinhoodMcpSchemaConnection,
    initialize_private_oauth_store,
)
from trading_bot.capabilities import write_tools_snapshot
from trading_bot.runtime.capability_capture import _suppress_untrusted_dependency_logs


class SchemaBootstrapError(RuntimeError):
    """Safe operator boundary; provider exception text is never propagated."""


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def bootstrap_schema_oauth(*, oauth_store: str | Path) -> dict[str, object]:
    """Create an independent encrypted grant and complete sanitized tools/list.

    This credential is trading-capable at the provider. This bootstrap exposes a
    schema-only facade, invokes no tools, binds no account and grants no trading
    authority. Existing stores and legacy read-schema gates remain unchanged.
    """
    previous_umask = os.umask(0o077)
    staging: Path | None = None
    try:
        destination = Path(oauth_store)
        parent = destination.parent
        if not destination.is_absolute():
            raise SchemaBootstrapError("schema OAuth bootstrap failed safely")
        metadata = parent.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
            or destination.exists()
            or destination.is_symlink()
        ):
            raise SchemaBootstrapError("schema OAuth bootstrap failed safely")
        staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.bootstrap.", dir=parent))
        staging.chmod(0o700)
        store = initialize_private_oauth_store(staging)

        async def capture() -> dict[str, object]:
            callback = LoopbackOAuthCallback()
            try:
                await callback.start()
                async with RobinhoodMcpSchemaConnection(
                    oauth_store_dir=store,
                    callback=callback,
                    timeout_seconds=OAUTH_FLOW_TIMEOUT_SECONDS,
                ) as connection:
                    snapshot = await write_tools_snapshot(
                        connection.session, store / "tools-list.json", omit_descriptions=True
                    )
                storage = EncryptedFileTokenStorage(store)
                tokens = await storage.get_tokens()
                client = await storage.get_client_info()
                if tokens is None or client is None:
                    raise SchemaBootstrapError("schema OAuth bootstrap failed safely")
                return {
                    "status": "schema_oauth_bootstrap_complete",
                    "tool_count": len(snapshot.tools),
                    "artifact_sha256": hashlib.sha256(
                        (store / "tools-list.json").read_bytes()
                    ).hexdigest(),
                    "tools_invoked": False,
                    "account_bound": False,
                    "live_enabled": False,
                    "expires_in_seconds_at_issue": tokens.expires_in,
                    "refresh_credential_supplied": tokens.refresh_token is not None,
                    "lifetime_reuse_verified": False,
                }
            finally:
                await callback.close()

        with _suppress_untrusted_dependency_logs():
            result = asyncio.run(capture())
        _sync_directory(store)
        # Never replace/adopt a store created during the human authorization flow.
        if destination.exists() or destination.is_symlink():
            raise SchemaBootstrapError("schema OAuth bootstrap failed safely")
        os.rename(store, destination)
        staging = None
        _sync_directory(parent)
        return result
    except Exception:
        raise SchemaBootstrapError("schema OAuth bootstrap failed safely") from None
    finally:
        if staging is not None:
            shutil.rmtree(staging)
        os.umask(previous_umask)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oauth-store", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = bootstrap_schema_oauth(oauth_store=args.oauth_store)
    except SchemaBootstrapError:
        print("schema_oauth_bootstrap_failed")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
