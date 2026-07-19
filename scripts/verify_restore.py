import sqlite3
import sys


def main() -> int:
    with sqlite3.connect(sys.argv[1]) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if result != ("ok",):
        raise SystemExit("SQLite integrity check failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
