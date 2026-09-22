import hashlib
import importlib
import json
import os
import stat
from pathlib import Path

import pytest
from mcp import types

from trading_bot.brokers.robinhood_mcp_sdk import SchemaOnlyMcpClientSession


class LocalSdkSession:
    def __init__(self) -> None:
        self.list_calls = 0
        self.tool_calls = 0

    async def list_tools(
        self,
        *,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListToolsResult:
        assert params is None
        self.list_calls += 1
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="get_accounts",
                    inputSchema={"type": "object"},
                    _meta={"Authorization": "Bearer actual-secret-value"},
                ),
                types.Tool(name="review_equity_order", inputSchema={"type": "object"}),
                types.Tool(name="place_equity_order", inputSchema={"type": "object"}),
                types.Tool(name="cancel_equity_order", inputSchema={"type": "object"}),
            ]
        )

    async def call_tool(self, name: str, arguments: object) -> types.CallToolResult:
        del name, arguments
        self.tool_calls += 1
        raise AssertionError("schema capture must never invoke a provider tool")


class LocalSchemaConnection:
    sdk_session = LocalSdkSession()
    oauth_store_dir: Path | None = None

    def __init__(self, *, oauth_store_dir: str | Path) -> None:
        type(self).oauth_store_dir = Path(oauth_store_dir)
        self.session = SchemaOnlyMcpClientSession(self.sdk_session)  # type: ignore[arg-type]

    async def __aenter__(self) -> "LocalSchemaConnection":
        return self

    async def __aexit__(self, *args: object) -> None:
        del args


def _private_directory(path: Path) -> None:
    path.mkdir()
    os.chmod(path, 0o700)


def test_authenticated_capture_writes_only_sanitized_private_tools_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("trading_bot.runtime.capability_capture")
    oauth = tmp_path / "oauth"
    evidence = tmp_path / "evidence"
    _private_directory(oauth)
    _private_directory(evidence)
    output = evidence / "robinhood-tools.json"
    LocalSchemaConnection.sdk_session = LocalSdkSession()
    monkeypatch.setattr(module, "RobinhoodMcpSchemaConnection", LocalSchemaConnection)

    result = module.run_authenticated_schema_capture(oauth_store=oauth, output=output)

    artifact_bytes = output.read_bytes()
    artifact = json.loads(artifact_bytes)
    assert result == {
        "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "method": "tools/list",
        "status": "authenticated_schema_capture_complete",
        "tool_count": 4,
        "tools_invoked": False,
        "transport_authenticated": True,
    }
    assert [item["name"] for item in artifact["tools"]] == [
        "cancel_equity_order",
        "get_accounts",
        "place_equity_order",
        "review_equity_order",
    ]
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert LocalSchemaConnection.oauth_store_dir == oauth
    assert LocalSchemaConnection.sdk_session.list_calls == 1
    assert LocalSchemaConnection.sdk_session.tool_calls == 0
    assert "actual-secret-value" not in artifact_bytes.decode("utf-8")


def test_authenticated_capture_rejects_writable_artifact_parent_before_connecting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("trading_bot.runtime.capability_capture")
    oauth = tmp_path / "oauth"
    evidence = tmp_path / "evidence"
    _private_directory(oauth)
    evidence.mkdir()
    os.chmod(evidence, 0o777)
    output = evidence / "robinhood-tools.json"
    connected = False

    class UnexpectedConnection:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            nonlocal connected
            connected = True

    monkeypatch.setattr(module, "RobinhoodMcpSchemaConnection", UnexpectedConnection)

    with pytest.raises(module.AuthenticatedCapabilityCaptureError, match="failed safely"):
        module.run_authenticated_schema_capture(oauth_store=oauth, output=output)

    assert not connected
    assert not output.exists()
