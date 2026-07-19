"""Operator shadow entry point; unavailable providers fail with a stable code."""

import argparse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.parse_args()
    print("external_capability_missing")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
