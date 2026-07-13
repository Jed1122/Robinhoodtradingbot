#!/usr/bin/env python3
"""Capture sanitized tools/list declarations from an injected configured session."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from trading_bot.capabilities import ToolsListSession, write_tools_snapshot

OFFICIAL_SETUP_COMMAND = (
    "codex mcp add robinhood-trading --url https://agent.robinhood.com/mcp/trading"
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command parser without inspecting configuration or network state."""
    parser = argparse.ArgumentParser(
        description=(
            "Capture Robinhood Trading MCP schemas using tools/list only; declared tools are "
            "never invoked and the artifact contains no account data."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("robinhood-mcp-tools-list.json"),
        help="Destination for the sanitized raw-schema artifact.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    configured_session: ToolsListSession | None = None,
) -> int:
    """Run capture only when a caller supplies a proven configured MCP session."""
    arguments = build_parser().parse_args(argv)
    if configured_session is None:
        print(OFFICIAL_SETUP_COMMAND, file=sys.stderr)
        return 2
    try:
        asyncio.run(write_tools_snapshot(configured_session, arguments.output))
    except Exception:
        print("capability capture failed safely", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
