"""Explicit local credential entry and cost estimates; no data downloads or trading."""

import argparse
import asyncio
import getpass
import json
import os

# Only a fixed absolute osascript executable and fixed script are launched below.
import subprocess  # nosec B404
import sys
import warnings
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Never

from trading_bot.clock import SystemClock
from trading_bot.diagnostics.databento_preflight import (
    CostRequest,
    DatabentoCredential,
    DatabentoPreflightError,
    _credential_directory,
    estimate_cost,
    load_credential,
    save_credential,
)

ROOT = Path(__file__).resolve().parents[3]
_DIALOG = (
    'text returned of (display dialog "Enter the NEW Databento API key. '
    "It will be stored in a restricted local file, not sent to chat. "
    'No downloads or trading will occur." with title "Databento local setup" '
    'default answer "" with hidden answer buttons {"Cancel", "Save locally"} '
    'default button "Save locally" cancel button "Cancel")'
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        # Never echo argv: the operator may have accidentally supplied a credential.
        raise DatabentoPreflightError("command_invalid")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    store = commands.add_parser("store-key", allow_abbrev=False)
    store.add_argument("--credential-directory", type=Path, required=True)
    store.add_argument("--native-dialog", action="store_true")
    cost = commands.add_parser("estimate", allow_abbrev=False)
    cost.add_argument("--credential-directory", type=Path, required=True)
    cost.add_argument("--symbol", action="append", required=True)
    cost.add_argument("--stype-in", choices=("parent", "raw_symbol"), default="parent")
    cost.add_argument("--schema", choices=("definition", "cbbo-1m"), required=True)
    cost.add_argument("--start", type=date.fromisoformat, required=True)
    cost.add_argument("--end", type=date.fromisoformat, required=True)
    cost.add_argument("--allow-metadata-network", action="store_true")
    return parser


def _hidden_credential(*, native_dialog: bool) -> DatabentoCredential:
    if native_dialog:
        if sys.platform != "darwin":
            raise DatabentoPreflightError("terminal_required")
        # No key in shell history/argv; stdout is captured in this process, never printed.
        response = subprocess.run(  # nosec B603
            ["/usr/bin/osascript", "-e", _DIALOG],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=120,
            check=False,
        )
        if response.returncode != 0:
            raise DatabentoPreflightError("credential_invalid")
        return DatabentoCredential(response.stdout.removesuffix("\n"))
    if not sys.stdin.isatty():
        raise DatabentoPreflightError("terminal_required")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        key = getpass.getpass("NEW Databento API key (hidden): ")
        confirmed = getpass.getpass("Confirm API key (hidden): ")
    if key != confirmed:
        raise DatabentoPreflightError("credential_confirmation_mismatch")
    return DatabentoCredential(key)


def main(argv: Sequence[str] | None = None) -> int:
    result: dict[str, object] = {
        "schema": "databento-preflight-v1",
        "status": "denied",
        "download_authorized": False,
        "economic_evidence": False,
        "credits_remaining": None,
        "download_entitlement_verified": False,
        "network_used": False,
    }
    exit_code = 2
    try:
        args = _parser().parse_args(argv)
        if args.command == "store-key":
            # Validate private-directory permissions before prompting; no raw key in argv.
            descriptor = _credential_directory(args.credential_directory, ROOT)
            os.close(descriptor)
            save_credential(
                args.credential_directory,
                _hidden_credential(native_dialog=args.native_dialog),
                repository_root=ROOT,
            )
            result["status"] = "credential_stored_locally"
        else:
            request = CostRequest(
                tuple(args.symbol), args.schema, args.start, args.end, stype_in=args.stype_in
            )
            result["request"] = request.query()
            result["status"] = "offline_preview"
            if args.allow_metadata_network:
                credential = load_credential(args.credential_directory, repository_root=ROOT)
                result["network_used"] = True  # An attempt, not proof of successful egress.
                estimate = asyncio.run(
                    estimate_cost(
                        request,
                        credential,
                        clock=SystemClock(),
                        allow_metadata_network=True,
                    )
                )
                result["status"] = "cost_estimate_only"
                result["cost_usd"] = str(estimate.cost_usd)
                result["quoted_at"] = estimate.quoted_at.isoformat()
        exit_code = 0
    except DatabentoPreflightError as error:
        result["status"] = "denied"
        result["reason_code"] = str(error)
    except (Exception, KeyboardInterrupt):
        # No path, provider response, child output, exception object or credential escapes.
        result["status"] = "denied"
        result["reason_code"] = "command_invalid"
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
