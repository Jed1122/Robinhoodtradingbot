"""Non-promotable local shadow composition smoke test."""

import argparse
import json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.parse_args()
    print(json.dumps({"evidence_eligible": False, "official_write_calls": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
