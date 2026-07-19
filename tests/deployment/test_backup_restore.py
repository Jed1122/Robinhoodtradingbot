import sqlite3
import subprocess
import sys


def test_restore_integrity_check(tmp_path) -> None:
    database = tmp_path / "db.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("create table x(id integer)")
    subprocess.run([sys.executable, "scripts/verify_restore.py", str(database)], check=True)
