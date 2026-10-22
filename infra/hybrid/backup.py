"""Offline SQLite backup and restored-copy integrity check; never handles dashboard tokens."""

import argparse
import os
import sqlite3
import tempfile
from pathlib import Path


def backup(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError("source must be a regular ledger")
    if destination.parent.is_symlink() or destination.parent.stat().st_mode & 0o077:
        raise ValueError("backup parent must be private")
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with (
            sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src,
            sqlite3.connect(destination) as dst,
        ):
            src.backup(dst)
        with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
            restored = Path(directory) / "restored.db"
            with sqlite3.connect(destination) as saved, sqlite3.connect(restored) as check:
                saved.backup(check)
                if check.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("restore integrity failed")
    except BaseException:
        destination.unlink()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    backup(args.source, args.destination)
    print("Private ledger backup and offline restore integrity check passed.")
