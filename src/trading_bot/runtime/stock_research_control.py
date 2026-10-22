"""Explicit operator commands for the separate stock collector; no live capability."""

import argparse
import json
from pathlib import Path
from typing import cast

from trading_bot.runtime.stock_research_controls import (
    Action,
    StockResearchControlError,
    StockResearchControls,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--expected-state-sha256")
    parser.add_argument(
        "--config-root", type=Path, default=Path(__file__).resolve().parents[3] / "configs"
    )
    parser.add_argument("--image-digest")
    parser.add_argument("--image-attestation", type=Path)
    parser.add_argument("action", choices=("initialize", "status", "pause", "kill", "resume"))
    args = parser.parse_args(argv)
    try:
        changes = args.action not in {"initialize", "status"}
        if changes != (args.expected_state_sha256 is not None) or (
            args.action != "resume"
            and (args.image_digest is not None or args.image_attestation is not None)
        ):
            raise StockResearchControlError("stock_control_denied")
        binding = {}
        if args.action == "resume":
            from trading_bot.runtime.stock_research_worker import load_stock_worker_identity

            loaded, code = load_stock_worker_identity(
                args.config_root,
                image_digest=args.image_digest,
                image_attestation=args.image_attestation,
            )
            binding = {"config_hash": str(loaded.config_hash), "code_hash": str(code)}
        owner = StockResearchControls(args.control_dir)
        if args.action == "initialize":
            state = owner.initialize()
        elif args.action == "status":
            state = owner.read()
        else:
            state = owner.change(
                cast(Action, args.action), expected_sha256=args.expected_state_sha256, **binding
            )
        print(
            json.dumps(
                {
                    "status": "succeeded",
                    "control_status": state.record.status,
                    "generation": state.record.generation,
                    "state_sha256": state.sha256,
                    "changed_at": state.record.changed_at.isoformat(),
                    "config_hash": state.record.config_hash,
                    "code_hash": state.record.code_hash,
                    "live_enabled": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        reason = (
            "stock_control_busy"
            if isinstance(exc, StockResearchControlError) and str(exc) == "stock_control_busy"
            else "stock_control_denied"
        )
        print(
            json.dumps(
                {"status": "blocked", "reason": reason, "live_enabled": False}, sort_keys=True
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
