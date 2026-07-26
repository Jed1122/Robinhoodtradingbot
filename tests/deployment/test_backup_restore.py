import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

from tests.unit.research.test_validation import report
from trading_bot.research.artifacts import persist_research_report


def test_restore_integrity_check(tmp_path) -> None:
    database = tmp_path / "db.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("create table x(id integer)")
    subprocess.run([sys.executable, "scripts/verify_restore.py", str(database)], check=True)


def test_evidence_archive_verifies_ledger_and_research_report(tmp_path: Path) -> None:
    database = tmp_path / "ledger.db"
    with sqlite3.connect(database) as connection:
        connection.execute("create table x(id integer)")
    artifact = persist_research_report(tmp_path / "research", report())
    archive_path = tmp_path / "evidence.tar"
    with tarfile.open(archive_path, mode="w") as archive:
        archive.add(database, arcname="ledger.db")
        archive.add(artifact, arcname=f"research/{artifact.name}")

    subprocess.run(
        [sys.executable, "scripts/verify_restore.py", str(archive_path)],
        check=True,
    )


def test_backup_includes_private_research_artifacts() -> None:
    script = Path("infra/digitalocean/backup.sh").read_text(encoding="utf-8")

    assert "TRADING_BOT_RESEARCH_ARTIFACT_DIR" in script
    assert "evidence.tar" in script
    assert "scripts/verify_restore.py" in script
