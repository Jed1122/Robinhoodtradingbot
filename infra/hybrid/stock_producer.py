"""Source-SHA-only release CLI; no installation, credential or trading surface."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import suppress
from pathlib import Path

from infra.hybrid.stock_release_producer import _ERRORS, _completed_release, _require


def _success(manifest: Path) -> str:
    return (
        json.dumps(
            {"status": "succeeded", "manifest": str(manifest)},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Produce one fixed stock research release")
    parser.add_argument("source_sha256")
    arguments = parser.parse_args(argv)
    writing = False
    try:
        with _completed_release(arguments.source_sha256) as finished:
            payload = _success(finished.manifest)
            _require(type(payload) is str and 0 < len(payload.encode("utf-8")) <= 1024)
        finished.check()
        writing = True
        sys.stdout.write(payload)
        sys.stdout.flush()
        # Consumers require exit0 as well as the complete JSON. Output alone does
        # not acknowledge success if its own blocking/cleanup exceeded the window.
        finished.check()
        return 0
    except _ERRORS:
        if not writing:
            with suppress(*_ERRORS):
                sys.stdout.write('{"reason":"stock_producer_unavailable","status":"blocked"}\n')
                sys.stdout.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
