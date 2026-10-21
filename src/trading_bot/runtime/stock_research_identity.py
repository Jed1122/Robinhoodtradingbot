"""Observe canonical stock policy in an inert image; no code or broker authority."""

import argparse
import json
from pathlib import Path

from trading_bot.config.stock_research import StockWorkerAppConfig
from trading_bot.runtime.stock_research_worker import load_stock_worker_configuration


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-root", type=Path, default=Path(__file__).resolve().parents[3] / "configs"
    )
    args = parser.parse_args(argv)
    try:
        loaded = load_stock_worker_configuration(args.config_root)
        if type(loaded.config) is not StockWorkerAppConfig:
            raise ValueError
        policy = loaded.config
        result = {
            "status": "succeeded",
            "schema_version": 1,
            "kind": "stock_research_configuration_identity",
            "config_hash": str(loaded.config_hash),
            "scan_interval_seconds": policy.stock_research.scan_minutes * 60,
            "max_run_seconds": policy.stock_worker.max_run_seconds,
            "max_daily_calls": policy.stock_research.max_daily_calls,
            "max_calls_per_cycle": policy.stock_research.max_calls_per_cycle,
            "maximum_source_age_seconds": policy.stock_research.maximum_source_age_minutes * 60,
            "live_enabled": False,
        }
    except Exception:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "stock_configuration_unavailable",
                    "live_enabled": False,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
