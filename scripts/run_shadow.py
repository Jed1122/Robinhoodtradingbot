"""Compatibility entry point for the fail-closed connected-shadow CLI command."""

from __future__ import annotations

import sys

from trading_bot.cli.main import app


def main() -> None:
    app(args=["shadow", *sys.argv[1:]], prog_name="run_shadow.py")


if __name__ == "__main__":
    main()
