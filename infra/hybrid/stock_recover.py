"""Fixed-namespace recovery-only post-stop CLI. No release or execution arguments."""

import json
import sys

from infra.hybrid.stock_attempts import operations
from infra.hybrid.stock_engine_mutation import _ERRORS
from infra.hybrid.stock_launcher import recover_research_cycle


def main() -> int:
    try:
        if len(sys.argv) != 1:
            raise ValueError("stock_recover_unavailable")
        with operations() as store:
            result = recover_research_cycle(store)
        print(json.dumps({"status": result.status}, sort_keys=True))
        return 0
    except _ERRORS:
        print('{"status": "unavailable"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
