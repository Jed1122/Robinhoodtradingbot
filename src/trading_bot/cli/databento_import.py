"""Credential-free import/verification of a locally supplied definitions-only batch."""

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Never, cast

from trading_bot.market_data.databento_batch import DatabentoImportError, DefinitionRequest
from trading_bot.market_data.databento_stage import stage_batch, verify_staged

ROOT = Path(__file__).resolve().parents[3]


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise DatabentoImportError("databento_command_invalid")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("stage", allow_abbrev=False)
    stage.add_argument("--source", type=Path, required=True)
    stage.add_argument("--output-root", type=Path, required=True)
    stage.add_argument("--parent", required=True)
    stage.add_argument("--start", type=date.fromisoformat, required=True)
    stage.add_argument("--end", type=date.fromisoformat, required=True)
    verify = commands.add_parser("verify", allow_abbrev=False)
    verify.add_argument("--manifest", type=Path, required=True)
    return parser


def _ns(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp()) * 10**9


def main(argv: Sequence[str] | None = None) -> int:
    result: dict[str, object] = {
        "schema": "databento-import-command-v1",
        "status": "denied",
        "network_used": False,
        "economic_evidence": False,
        "production_eligible": False,
    }
    exit_code = 2
    try:
        args = _parser().parse_args(argv)
        if args.command == "stage":
            request = DefinitionRequest(args.parent, _ns(args.start), _ns(args.end))
            path = stage_batch(
                args.source, args.output_root, expected=request, repository_root=ROOT
            )
            result["status"] = "definitions_staged"
        else:
            path = args.manifest
            result["status"] = "staged_integrity_verified"
        manifest = verify_staged(path, repository_root=ROOT)
        result["manifest"] = str(path)
        result["record_count"] = cast(dict[str, object], manifest["validation"])["record_count"]
        exit_code = 0
    except DatabentoImportError as error:
        result["status"] = "denied"
        result["error"] = error.code
    except (OSError, ValueError, TypeError):
        result["status"] = "denied"
        result["error"] = "databento_command_invalid"
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
