import asyncio
import os
import stat
from collections.abc import Mapping
from pathlib import Path

import pytest
from mcp import types
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from trading_bot.brokers.robinhood_mcp_schema_gate import JsonValue
from trading_bot.brokers.robinhood_mcp_sdk import (
    ROBINHOOD_MCP_OAUTH_SCOPE,
    EncryptedFileTokenStorage,
    LoopbackOAuthCallback,
    McpSdkConnectionError,
    OAuthStoreError,
    ReadOnlyMcpClientSession,
    initialize_private_oauth_store,
)


class LocalClientSession:
    def __init__(self, result: types.CallToolResult) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, JsonValue]]] = []

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
    ) -> types.CallToolResult:
        self.calls.append((name, dict(arguments)))
        return self.result


def _private_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.asyncio
async def test_encrypted_token_and_client_storage_round_trip_with_private_modes(
    tmp_path: Path,
) -> None:
    store_path = initialize_private_oauth_store(tmp_path / "oauth")
    storage = EncryptedFileTokenStorage(store_path)
    tokens = OAuthToken(
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        expires_in=900,
        scope=ROBINHOOD_MCP_OAUTH_SCOPE,
    )
    client_info = OAuthClientInformationFull(
        redirect_uris=["http://127.0.0.1:18765/callback"],
        token_endpoint_auth_method="none",
        client_name="local-test-client",
        scope=ROBINHOOD_MCP_OAUTH_SCOPE,
        client_id="test-client-id",
        client_secret="test-client-secret",
    )

    await storage.set_tokens(tokens)
    await storage.set_client_info(client_info)

    reopened = EncryptedFileTokenStorage(store_path)
    assert await reopened.get_tokens() == tokens
    assert await reopened.get_client_info() == client_info
    assert _private_mode(store_path) == 0o700
    for name in ("oauth-store.key", "tokens.json.box", "client.json.box"):
        state_path = store_path / name
        assert state_path.is_file()
        assert _private_mode(state_path) == 0o600
    encrypted_bytes = (store_path / "tokens.json.box").read_bytes()
    assert b"test-access-token" not in encrypted_bytes
    assert b"test-refresh-token" not in encrypted_bytes
    encrypted_client_bytes = (store_path / "client.json.box").read_bytes()
    assert b"test-client-id" not in encrypted_client_bytes
    assert b"test-client-secret" not in encrypted_client_bytes


@pytest.mark.asyncio
async def test_encrypted_storage_rejects_tampered_ciphertext(tmp_path: Path) -> None:
    store_path = initialize_private_oauth_store(tmp_path / "oauth")
    storage = EncryptedFileTokenStorage(store_path)
    await storage.set_tokens(OAuthToken(access_token="test-access-token"))
    token_path = store_path / "tokens.json.box"
    ciphertext = bytearray(token_path.read_bytes())
    ciphertext[-1] ^= 1
    token_path.write_bytes(ciphertext)
    os.chmod(token_path, 0o600)

    with pytest.raises(OAuthStoreError, match="encrypted OAuth state is invalid"):
        await storage.get_tokens()


@pytest.mark.asyncio
async def test_encrypted_storage_rejects_scope_outside_pinned_contract(tmp_path: Path) -> None:
    store_path = initialize_private_oauth_store(tmp_path / "oauth")
    storage = EncryptedFileTokenStorage(store_path)

    with pytest.raises(OAuthStoreError, match="scope"):
        await storage.set_tokens(OAuthToken(access_token="test-access-token", scope="write"))


def test_oauth_store_rejects_symlinked_directory(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    linked = tmp_path / "oauth"
    linked.symlink_to(target, target_is_directory=True)

    with pytest.raises(OAuthStoreError, match="service-owned directory"):
        initialize_private_oauth_store(linked)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name",
    ["review_equity_order", "place_equity_order", "cancel_equity_order"],
)
async def test_read_only_session_rejects_write_tools_before_sdk_call(tool_name: str) -> None:
    sdk_session = LocalClientSession(types.CallToolResult(content=[]))
    session = ReadOnlyMcpClientSession(sdk_session)  # type: ignore[arg-type]

    with pytest.raises(PermissionError, match="read-only allowlist"):
        await session.call_tool(tool_name, {})

    assert sdk_session.calls == []


@pytest.mark.asyncio
async def test_read_only_session_maps_allowed_structured_read_from_local_sdk() -> None:
    structured = {
        "results": [
            {
                "symbol": "SPY",
                "price": 123,
                "eligible": True,
                "detail": None,
            }
        ]
    }
    sdk_session = LocalClientSession(
        types.CallToolResult(content=[], structuredContent=structured, isError=False)
    )
    session = ReadOnlyMcpClientSession(sdk_session)  # type: ignore[arg-type]

    result = await session.call_tool("get_equity_quotes", {"symbols": ["SPY"]})

    assert sdk_session.calls == [("get_equity_quotes", {"symbols": ["SPY"]})]
    assert result.content == ()
    assert result.is_error is False
    assert result.structured_content == structured


async def _callback_request(target: str) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", 18765)
    writer.write(f"GET {target} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    return response


@pytest.mark.asyncio
async def test_callback_ignores_unrelated_and_wrong_state_requests() -> None:
    expected_state = "s" * 32
    callback = LoopbackOAuthCallback(open_browser=lambda _: True, timeout_seconds=1)
    await callback.start()
    try:
        await callback.redirect_handler(f"https://example.test/authorize?state={expected_state}")
        unrelated = await _callback_request("/wrong?code=" + "c" * 32)
        wrong_state = await _callback_request("/callback?code=" + "c" * 32 + "&state=" + "x" * 32)
        valid = await _callback_request("/callback?code=" + "c" * 32 + "&state=" + expected_state)

        assert b"400 Bad Request" in unrelated
        assert b"400 Bad Request" in wrong_state
        assert b"200 OK" in valid
        assert await callback.callback_handler() == ("c" * 32, expected_state)
    finally:
        await callback.close()


@pytest.mark.asyncio
async def test_callback_wait_is_bounded() -> None:
    callback = LoopbackOAuthCallback(open_browser=lambda _: True, timeout_seconds=0.01)
    await callback.start()
    try:
        await callback.redirect_handler("https://example.test/authorize?state=" + "s" * 32)
        with pytest.raises(McpSdkConnectionError, match="timed out"):
            await callback.callback_handler()
    finally:
        await callback.close()
