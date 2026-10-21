"""Operator-run single official refresh; no MCP tools, accounts or orders."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
from mcp.shared.auth import OAuthClientMetadata
from pydantic import AnyUrl

from trading_bot.brokers.robinhood_mcp_sdk import (
    OAUTH_CALLBACK_HOST,
    OAUTH_CALLBACK_PATH,
    OAUTH_CALLBACK_PORT,
    ROBINHOOD_MCP_OAUTH_SCOPE,
    EncryptedFileTokenStorage,
)
from trading_bot.brokers.robinhood_mcp_transport import OFFICIAL_MCP_ENDPOINT
from trading_bot.brokers.robinhood_oauth_lifecycle import (
    AS_METADATA_URL,
    RESOURCE_METADATA_URL,
    PrivateOAuthStoreLease,
    validate_metadata,
)
from trading_bot.brokers.robinhood_oauth_provider import (
    LifecycleOAuthClientProvider,
    PinnedOAuthTransport,
)
from trading_bot.runtime.capability_capture import _suppress_untrusted_dependency_logs


class OAuthRenewalError(RuntimeError):
    """Sanitized operator boundary; uncertain refresh outcomes require owner recovery."""


async def renew_oauth_grant(
    *,
    oauth_store: Path,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Persist pending, POST once, commit generation, verify encrypted restart data.

    The injected transport and clock support fictional offline fixtures. The CLI
    permits no endpoint overrides. No browser fallback, retries or MCP calls occur.
    A pending/denied record is never replayed or repaired by this command.
    """
    try:
        with _suppress_untrusted_dependency_logs(), PrivateOAuthStoreLease(oauth_store):
            storage = EncryptedFileTokenStorage(oauth_store)
            redirect = f"http://{OAUTH_CALLBACK_HOST}:{OAUTH_CALLBACK_PORT}{OAUTH_CALLBACK_PATH}"
            provider = LifecycleOAuthClientProvider(
                OFFICIAL_MCP_ENDPOINT,
                OAuthClientMetadata(
                    redirect_uris=[AnyUrl(redirect)],
                    token_endpoint_auth_method="none",  # nosec B106
                    scope=ROBINHOOD_MCP_OAUTH_SCOPE,
                ),
                storage,
                clock=clock,
            )
            await provider._initialize()
            client = httpx.AsyncClient(
                auth=None,
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(30.0),
                transport=PinnedOAuthTransport(
                    transport
                    if transport is not None
                    else httpx.AsyncHTTPTransport(retries=0, trust_env=False)
                ),
            )
            try:
                prm_response = await client.get(RESOURCE_METADATA_URL)
                as_response = await client.get(AS_METADATA_URL)
                if prm_response.status_code != 200 or as_response.status_code != 200:
                    raise OAuthRenewalError("official OAuth metadata unavailable")
                protected, authorization = prm_response.json(), as_response.json()
                if type(protected) is not dict or type(authorization) is not dict:
                    raise OAuthRenewalError("official OAuth metadata invalid")
                validate_metadata(authorization, protected)
                request = await provider.prepare_explicit_refresh(authorization, protected)
                response = await client.send(request, follow_redirects=False)
                await provider._handle_refresh_response(response)
                # New storage instance verifies the durable encrypted generation.
                reopened = EncryptedFileTokenStorage(oauth_store)
                record = await reopened.get_lifecycle()
                tokens = await reopened.get_tokens()
                if (
                    record is None
                    or record.state != "active"
                    or record.flow != "explicit_refresh"
                    or record.expires_at is None
                    or tokens is None
                    or tokens != provider.context.current_tokens
                    or provider.refreshes_completed != 1
                ):
                    raise OAuthRenewalError("official OAuth commit verification failed")
                return {
                    "status": "oauth_refresh_committed",
                    "provider_contacted": transport is None,
                    "refresh_posts": 1,
                    "absolute_expiry_retained": True,
                    "expires_at": record.expires_at.isoformat(),
                    "refresh_credential_retained": bool(tokens.refresh_token),
                    "natural_expiry_observed": False,
                    "runtime_reuse_verified": False,
                    "tools_invoked": False,
                    "account_bound": False,
                    "live_enabled": False,
                }
            finally:
                # Keep the process lease until bounded transport cleanup completes.
                await asyncio.wait_for(client.aclose(), timeout=5.0)
    except Exception:
        raise OAuthRenewalError("official OAuth renewal failed safely") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oauth-store", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(renew_oauth_grant(oauth_store=args.oauth_store))
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print('{"status":"failed","reason":"oauth_renewal_requires_review","live_enabled":false}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
