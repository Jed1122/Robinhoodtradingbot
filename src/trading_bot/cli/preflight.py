"""Fail-closed operator preflight reporting."""

import json
from pathlib import Path


def locked_preflight(config: Path) -> str:
    return json.dumps(
        {"config": str(config), "ready": False, "reason": "external_capability_missing"},
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = ["locked_preflight"]
