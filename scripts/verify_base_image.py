import re
import sys
from pathlib import Path

PATTERN = re.compile(r"python:3\.12-slim-bookworm@sha256:[0-9a-f]{64}\Z")


def main() -> int:
    value = Path(sys.argv[1]).read_text().strip()
    if not PATTERN.fullmatch(value):
        raise SystemExit("invalid pinned official Python base image")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
