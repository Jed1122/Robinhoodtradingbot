"""Source-only negative-facts CLI, with no native mutation or replay surface."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import suppress

from infra.hybrid.stock_failed_build import _completed_reconciliation
from infra.hybrid.stock_release_producer import _ERRORS, _require


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile one spent failed stock build")
    parser.add_argument("source_sha256")
    arguments = parser.parse_args(argv)
    writing = False
    try:
        with _completed_reconciliation(arguments.source_sha256) as finished:
            payload = (
                json.dumps(
                    {"status": "spent_failed_build_reconciled", "facts": str(finished.facts)},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            _require(0 < len(payload.encode()) <= 1024)
        finished.check()
        writing = True
        sys.stdout.write(payload)
        sys.stdout.flush()
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
