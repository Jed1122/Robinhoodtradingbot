import asyncio
import importlib
import json
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from trading_bot.brokers.robinhood_mcp_sdk import (
    EncryptedFileTokenStorage,
    initialize_private_oauth_store,
)
from trading_bot.brokers.robinhood_oauth_lifecycle import (
    AS_METADATA_URL,
    OFFICIAL_MCP_ENDPOINT,
    RESOURCE_METADATA_URL,
    TOKEN_ENDPOINT,
    PrivateOAuthStoreLease,
)
from trading_bot.brokers.robinhood_oauth_provider import LifecycleOAuthClientProvider

NOW = datetime(2026, 10, 21, 16, tzinfo=UTC)
REDIRECT = "http://127.0.0.1:18765/callback"


def authorization():
    return {
        "issuer": OFFICIAL_MCP_ENDPOINT,
        "authorization_endpoint": "https://robinhood.com/oauth",
        "token_endpoint": TOKEN_ENDPOINT,
        "registration_endpoint": "https://agent.robinhood.com/oauth/trading/register",
        "scopes_supported": ["internal"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "response_types_supported": ["code"],
    }


def protected():
    return {
        "resource": OFFICIAL_MCP_ENDPOINT,
        "authorization_servers": [OFFICIAL_MCP_ENDPOINT],
        "scopes_supported": ["internal"],
        "bearer_methods_supported": ["header"],
    }


async def legacy_store(tmp_path):
    root = initialize_private_oauth_store(tmp_path / "store").resolve()
    storage = EncryptedFileTokenStorage(root)
    await storage.set_client_info(
        OAuthClientInformationFull(
            client_id="fictional-client",
            issuer=OFFICIAL_MCP_ENDPOINT,
            redirect_uris=[REDIRECT],
            token_endpoint_auth_method="none",
            scope="internal",
        )
    )
    await storage.set_tokens(
        OAuthToken(
            access_token="fictional-old-access",
            refresh_token="fictional-old-refresh",
            expires_in=900,
            scope="internal",
        )
    )
    return root, storage


def reply():
    return {
        "access_token": "fictional-new-access",
        "refresh_token": "fictional-new-refresh",
        "expires_in": 900,
        "token_type": "Bearer",
        "scope": "internal",
    }


def handler_for(calls, response=None):
    def handle(request):
        calls.append(str(request.url))
        assert "Authorization" not in request.headers
        if str(request.url) == RESOURCE_METADATA_URL:
            return httpx.Response(200, json=protected())
        if str(request.url) == AS_METADATA_URL:
            return httpx.Response(200, json=authorization())
        assert str(request.url) == TOKEN_ENDPOINT
        return response(request) if response else httpx.Response(200, json=reply())

    return handle


@pytest.mark.asyncio
async def test_legacy_migration_single_post_persists_and_restarts(tmp_path, caplog, capsys):
    module = importlib.import_module("trading_bot.runtime.oauth_renewal")
    root, storage = await legacy_store(tmp_path)
    calls = []
    base_handler = handler_for(calls)

    async def handle(request):
        if str(request.url) == TOKEN_ENDPOINT:
            assert (await storage.get_lifecycle()).state == "refresh_pending"
            with pytest.raises(RuntimeError), PrivateOAuthStoreLease(root):
                pass
            assert request.method == "POST"
            fields = parse_qs(request.content.decode(), keep_blank_values=True)
            assert fields["grant_type"] == ["refresh_token"]
            assert fields["refresh_token"] == ["fictional-old-refresh"]
            assert fields["client_id"] == ["fictional-client"]
            assert "client_secret" not in fields
        return base_handler(request)

    result = await module.renew_oauth_grant(
        oauth_store=root, transport=httpx.MockTransport(handle), clock=lambda: NOW
    )
    assert calls == [RESOURCE_METADATA_URL, AS_METADATA_URL, TOKEN_ENDPOINT]
    assert result["status"] == "oauth_refresh_committed"
    assert result["natural_expiry_observed"] is False
    assert result["live_enabled"] is False
    assert "fictional" not in json.dumps(result) + caplog.text + capsys.readouterr().out
    restarted = EncryptedFileTokenStorage(root)
    record = await restarted.get_lifecycle()
    assert record.state == "active" and record.flow == "explicit_refresh"
    assert (await restarted.get_tokens()).access_token == "fictional-new-access"
    provider = LifecycleOAuthClientProvider(
        OFFICIAL_MCP_ENDPOINT,
        OAuthClientMetadata(
            redirect_uris=[REDIRECT], token_endpoint_auth_method="none", scope="internal"
        ),
        restarted,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    await provider._initialize()
    assert provider.context.token_expiry_time == record.expires_at.timestamp()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["file_sync", "replace", "directory_sync"])
async def test_pending_commit_failure_sends_zero_posts(tmp_path, monkeypatch, fault):
    module = importlib.import_module("trading_bot.runtime.oauth_renewal")
    root, storage = await legacy_store(tmp_path)
    calls = []
    original_sync = os.fsync
    sync_count = 0

    def sync(fd):
        nonlocal sync_count
        sync_count += 1
        if sync_count == (1 if fault == "file_sync" else 2):
            raise OSError("fictional-secret-fsync-error")
        original_sync(fd)

    def replace(*args):
        raise OSError("fictional-secret-replace-error")

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", replace) if fault == "replace" else patch.setattr(
            os, "fsync", sync
        )
        with pytest.raises(module.OAuthRenewalError, match="failed safely"):
            await module.renew_oauth_grant(
                oauth_store=root,
                transport=httpx.MockTransport(handler_for(calls)),
                clock=lambda: NOW,
            )
    assert TOKEN_ENDPOINT not in calls
    record = await storage.get_lifecycle()
    if record is not None:
        assert record.state == "refresh_pending"
        with pytest.raises(RuntimeError):
            await storage.get_tokens()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["timeout", "cancel", "redirect", "malformed", "scope", "expiry", "null", "empty"]
)
async def test_uncertain_response_one_post_and_no_replay(tmp_path, failure, caplog, capsys):
    module = importlib.import_module("trading_bot.runtime.oauth_renewal")
    root, storage = await legacy_store(tmp_path)
    calls = []

    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("fictional-private-response")
        if failure == "cancel":
            raise asyncio.CancelledError
        if failure == "redirect":
            return httpx.Response(307, headers={"Location": TOKEN_ENDPOINT})
        if failure == "malformed":
            return httpx.Response(200, content=b"fictional-private-response")
        data = reply()
        data.update(
            {
                "scope": {"scope": "internal other"},
                "expiry": {"expires_in": True},
                "null": {"refresh_token": None},
                "empty": {"refresh_token": ""},
            }[failure]
        )
        return httpx.Response(200, json=data)

    error_type = asyncio.CancelledError if failure == "cancel" else module.OAuthRenewalError
    with pytest.raises(error_type) as error:
        await module.renew_oauth_grant(
            oauth_store=root,
            transport=httpx.MockTransport(handler_for(calls, respond)),
            clock=lambda: NOW,
        )
    assert calls.count(TOKEN_ENDPOINT) == 1
    assert (await storage.get_lifecycle()).state == "refresh_pending"
    retry_calls = []
    with pytest.raises(module.OAuthRenewalError):
        await module.renew_oauth_grant(
            oauth_store=root,
            transport=httpx.MockTransport(handler_for(retry_calls)),
            clock=lambda: NOW,
        )
    assert retry_calls == []
    assert "fictional" not in str(error.value) + caplog.text + capsys.readouterr().out
    with PrivateOAuthStoreLease(root):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["file_sync", "replace", "directory_sync"])
async def test_new_generation_commit_failure_never_replays_old_refresh(
    tmp_path, monkeypatch, fault
):
    module = importlib.import_module("trading_bot.runtime.oauth_renewal")
    root, storage = await legacy_store(tmp_path)
    calls = []
    original_sync, original_replace = os.fsync, os.replace
    sync_count = 0

    def sync(fd):
        nonlocal sync_count
        sync_count += 1
        if sync_count == (3 if fault == "file_sync" else 4):
            raise OSError("fictional-secret-sync-error")
        original_sync(fd)

    def replace(source, destination):
        if calls and calls[-1] == TOKEN_ENDPOINT:
            raise OSError("fictional-secret-replace-error")
        original_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", replace) if fault == "replace" else patch.setattr(
            os, "fsync", sync
        )
        with pytest.raises(module.OAuthRenewalError):
            await module.renew_oauth_grant(
                oauth_store=root,
                transport=httpx.MockTransport(handler_for(calls)),
                clock=lambda: NOW,
            )
    assert calls.count(TOKEN_ENDPOINT) == 1
    record = await storage.get_lifecycle()
    if record.state == "active":
        assert (await storage.get_tokens()).refresh_token == "fictional-new-refresh"
    else:
        assert record.state == "refresh_pending"
        retry_calls = []
        with pytest.raises(module.OAuthRenewalError):
            await module.renew_oauth_grant(
                oauth_store=root,
                transport=httpx.MockTransport(handler_for(retry_calls)),
                clock=lambda: NOW,
            )
        assert retry_calls == []


@pytest.mark.asyncio
async def test_lease_held_through_transport_close_after_cancel(tmp_path):
    module = importlib.import_module("trading_bot.runtime.oauth_renewal")
    root, storage = await legacy_store(tmp_path)
    calls = []
    closed = False

    class Transport(httpx.MockTransport):
        async def aclose(self):
            nonlocal closed
            with pytest.raises(RuntimeError), PrivateOAuthStoreLease(root):
                pass
            closed = True
            await super().aclose()

    def respond(request):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await module.renew_oauth_grant(
            oauth_store=root,
            transport=Transport(handler_for(calls, respond)),
            clock=lambda: NOW,
        )
    assert closed and (await storage.get_lifecycle()).state == "refresh_pending"
    with PrivateOAuthStoreLease(root):
        pass


@pytest.mark.asyncio
async def test_crash_after_durable_pending_before_post_blocks_restart(tmp_path, monkeypatch):
    module = importlib.import_module("trading_bot.runtime.oauth_renewal")
    root, storage = await legacy_store(tmp_path)
    original = LifecycleOAuthClientProvider.prepare_explicit_refresh
    calls = []

    async def crash(self, *args):
        await original(self, *args)
        raise asyncio.CancelledError

    with monkeypatch.context() as patch:
        patch.setattr(LifecycleOAuthClientProvider, "prepare_explicit_refresh", crash)
        with pytest.raises(asyncio.CancelledError):
            await module.renew_oauth_grant(
                oauth_store=root,
                transport=httpx.MockTransport(handler_for(calls)),
                clock=lambda: NOW,
            )
    assert TOKEN_ENDPOINT not in calls
    assert (await storage.get_lifecycle()).state == "refresh_pending"
    restart_calls = []
    with pytest.raises(module.OAuthRenewalError):
        await module.renew_oauth_grant(
            oauth_store=root,
            transport=httpx.MockTransport(handler_for(restart_calls)),
            clock=lambda: NOW,
        )
    assert restart_calls == []
