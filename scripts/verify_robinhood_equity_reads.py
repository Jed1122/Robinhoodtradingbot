"""Shape-only authenticated equity read verifier; never persists provider values."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

READ_ONLY_ALLOWLIST = frozenset(
    {
        "get_accounts",
        "get_portfolio",
        "get_equity_positions",
        "get_equity_quotes",
        "get_equity_orders",
        "get_equity_tradability",
        "get_equity_historicals",
        "get_equity_fundamentals",
        "get_earnings_results",
        "get_earnings_calendar",
    }
)
_SENSITIVE_SEGMENTS = frozenset(
    {"account", "balance", "quantity", "price", "symbol", "order", "token", "authorization"}
)


def _shape(value: object, path: str = "$") -> object:
    if isinstance(value, dict):
        fields = {}
        for key, child in sorted(value.items()):
            normalized = str(key).casefold()
            if any(segment in normalized for segment in _SENSITIVE_SEGMENTS):
                fields[str(key)] = {"nullable": child is None, "type": type(child).__name__}
            else:
                fields[str(key)] = _shape(child, f"{path}.{key}")
        return {"fields": fields, "type": "object"}
    if isinstance(value, list):
        cardinality = "empty" if not value else "one" if len(value) == 1 else "many"
        item_shapes = [] if not value else [_shape(value[0], f"{path}[]")]
        return {"cardinality": cardinality, "items": item_shapes, "type": "array"}
    return {"nullable": value is None, "type": "null" if value is None else type(value).__name__}


def shape_only_artifact(results: dict[str, object]) -> dict[str, object]:
    tools = {name: _shape(value) for name, value in sorted(results.items())}
    payload = {"format_version": 1, "tools": tools}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {**payload, "shape_sha256": hashlib.sha256(encoded).hexdigest()}


def assert_shape_only_artifact(artifact: dict[str, object]) -> None:
    encoded = json.dumps(artifact, sort_keys=True)
    for forbidden in ("RHC", "Bearer ", "access_token", "client_secret"):
        if forbidden.casefold() in encoded.casefold():
            raise ValueError("artifact contains prohibited account or secret material")


def write_atomic(output: Path, artifact: dict[str, object]) -> None:
    assert_shape_only_artifact(artifact)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=output.parent, prefix=f".{output.name}.")
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(artifact, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
        reread = json.loads(Path(temporary).read_text(encoding="utf-8"))
        assert_shape_only_artifact(reread)
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tool", action="append", default=[])
    args = parser.parse_args()
    unknown = set(args.tool) - READ_ONLY_ALLOWLIST
    if unknown or any(name.startswith(("review_", "place_", "cancel_")) for name in args.tool):
        parser.error("only reviewed read-only tools are allowed")
    parser.exit(2, "authenticated MCP verifier unavailable: configure reviewed session\n")


if __name__ == "__main__":
    raise SystemExit(main())
