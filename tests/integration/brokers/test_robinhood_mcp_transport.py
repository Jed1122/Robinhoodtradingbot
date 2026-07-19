from pathlib import Path

import pytest

from trading_bot.brokers.robinhood_mcp_schema_gate import DeclaredMcpTool
from trading_bot.brokers.robinhood_mcp_transport import (
    OFFICIAL_MCP_ENDPOINT,
    McpToolResult,
    RobinhoodMcpTransport,
)


class Session:
    tool = DeclaredMcpTool.create("local_fixture", None, {"type": "object"}, None)

    async def list_tools(self) -> tuple[DeclaredMcpTool, ...]:
        return (self.tool,)

    async def call_tool(self, name: str, arguments: object) -> McpToolResult:
        return McpToolResult(({"name": name},), False)


@pytest.mark.asyncio
async def test_transport_uses_injected_local_session_without_network(tmp_path: Path) -> None:
    store = tmp_path / "oauth"
    store.mkdir(mode=0o700)
    transport = RobinhoodMcpTransport(
        Session(), endpoint=OFFICIAL_MCP_ENDPOINT, oauth_store_dir=store
    )  # type: ignore[arg-type]
    assert (await transport.list_tools())[0].name == "local_fixture"
    assert not (await transport.call_tool("local_fixture", {})).is_error


def test_nonofficial_endpoint_is_rejected_before_session_use(tmp_path: Path) -> None:
    store = tmp_path / "oauth"
    store.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="official"):
        RobinhoodMcpTransport(Session(), endpoint="http://127.0.0.1:1", oauth_store_dir=store)
