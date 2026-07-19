"""Official MCP Streamable-HTTP transport seam with service-owned OAuth state."""

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from trading_bot.brokers.robinhood_mcp_schema_gate import DeclaredMcpTool, JsonValue

OFFICIAL_MCP_ENDPOINT = "https://agent.robinhood.com/mcp/trading"


@dataclass(frozen=True, slots=True)
class McpToolResult:
    content: tuple[JsonValue, ...]
    is_error: bool


class McpToolSession(Protocol):
    async def list_tools(self) -> tuple[DeclaredMcpTool, ...]: ...
    async def call_tool(self, name: str, arguments: Mapping[str, JsonValue]) -> McpToolResult: ...


class RobinhoodMcpTransport:
    def __init__(
        self, session: McpToolSession, *, endpoint: str, oauth_store_dir: str | Path
    ) -> None:
        if endpoint != OFFICIAL_MCP_ENDPOINT:
            raise ValueError("only the official Robinhood Trading MCP endpoint is allowed")
        store = Path(oauth_store_dir)
        metadata = store.stat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise PermissionError("MCP OAuth store must be a service-owned directory")
        if metadata.st_mode & 0o077:
            raise PermissionError("MCP OAuth store must use mode 0700 or stricter")
        self._session = session

    async def list_tools(self) -> tuple[DeclaredMcpTool, ...]:
        try:
            return await self._session.list_tools()
        except Exception:
            raise RuntimeError("MCP tools/list failed") from None

    async def call_tool(self, name: str, arguments: Mapping[str, JsonValue]) -> McpToolResult:
        try:
            return await self._session.call_tool(name, arguments)
        except Exception:
            raise RuntimeError("MCP tool call failed") from None


__all__ = ["OFFICIAL_MCP_ENDPOINT", "McpToolResult", "McpToolSession", "RobinhoodMcpTransport"]
