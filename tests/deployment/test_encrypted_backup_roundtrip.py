"""Local-only encrypted round-trip coverage for the deployment shell helpers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKUP_SCRIPT = ROOT / "infra/digitalocean/backup.sh"
RESTORE_SCRIPT = ROOT / "infra/digitalocean/restore.sh"
AGE_BINARY_ENV = "TRADING_BOT_TEST_AGE_BIN"
AGE_KEYGEN_BINARY_ENV = "TRADING_BOT_TEST_AGE_KEYGEN_BIN"


@dataclass(frozen=True)
class BackupFixture:
    age_binary: Path
    database: Path
    ciphertext: Path
    environment: dict[str, str]
    database_digest: str
    research_artifact: Path
    research_digest: str


def _local_executable(environment_name: str, executable_name: str) -> Path:
    configured = os.environ.get(environment_name)
    candidate = Path(configured) if configured else shutil.which(executable_name)
    if candidate is None:
        pytest.skip(f"requires local {executable_name}; set {environment_name} to an executable")
    executable = Path(candidate).resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        pytest.fail(f"{environment_name} does not name an executable")
    return executable


@pytest.fixture
def age_tools() -> tuple[Path, Path]:
    return (
        _local_executable(AGE_BINARY_ENV, "age"),
        _local_executable(AGE_KEYGEN_BINARY_ENV, "age-keygen"),
    )


def _private_mode(path: Path) -> None:
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def _identity_files(tmp_path: Path, age_keygen: Path) -> tuple[Path, Path]:
    tmp_path.mkdir(mode=0o700, exist_ok=True)
    identity = tmp_path / "identity.txt"
    generated = subprocess.run(
        [age_keygen, "-o", identity],
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert generated.returncode == 0
    identity.chmod(0o600)
    _private_mode(identity)
    public_line = next(
        line
        for line in identity.read_text(encoding="utf-8").splitlines()
        if line.startswith("# public key:")
    )
    recipient = tmp_path / "recipient.txt"
    recipient.write_text(f"{public_line.removeprefix('# public key:').strip()}\n", encoding="utf-8")
    recipient.chmod(0o600)
    _private_mode(recipient)
    return identity, recipient


def _script_environment(tmp_path: Path, age_binary: Path) -> dict[str, str]:
    tools = tmp_path / "tools"
    tools.mkdir(mode=0o700)
    (tools / "age").symlink_to(age_binary)
    # The scripts intentionally invoke `python`; point it to the test runner's pinned interpreter.
    (tools / "python").symlink_to(Path(sys.executable))
    return {
        **os.environ,
        # BSD tar otherwise emits macOS AppleDouble `._` records, which the verifier rejects.
        "COPYFILE_DISABLE": "1",
        "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
    }


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _synthetic_research_artifact(directory: Path) -> Path:
    """Write the smallest valid content-addressed report accepted by verify_restore.py."""

    directory.mkdir(mode=0o700)
    manifest = {"cleaned_hashes": [], "raw_hashes": []}
    manifest["manifest_hash"] = _canonical_hash(manifest)
    run = {
        "data_manifest": manifest,
        "data_manifest_hash": manifest["manifest_hash"],
        "dataset_snapshot": {
            "bars_by_symbol": [],
            "provider_evidence_hash": "e" * 64,
            "raw_hashes": [],
        },
        "provider_evidence_hash": "e" * 64,
    }
    payload = {"attempts": [], "disclaimer": None, "run": run}
    report_hash = _canonical_hash(payload)
    artifact = directory / f"{report_hash}.json"
    artifact.write_text(json.dumps({**payload, "report_hash": report_hash}), encoding="utf-8")
    artifact.chmod(0o600)
    return artifact


def _read_archive_member(archive: tarfile.TarFile, name: str) -> bytes:
    member = archive.getmember(name)
    assert member.isfile()
    source = archive.extractfile(member)
    assert source is not None
    return source.read()


@pytest.fixture
def encrypted_backup(tmp_path: Path, age_tools: tuple[Path, Path]) -> BackupFixture:
    age_binary, age_keygen = age_tools
    database = tmp_path / "ledger.db"
    with sqlite3.connect(database) as connection:
        connection.execute("create table ledger (entry text not null)")
        connection.execute("insert into ledger values ('original-row')")
    database.chmod(0o600)
    _private_mode(database)
    artifact = _synthetic_research_artifact(tmp_path / "research")
    _private_mode(artifact)
    identity, recipient = _identity_files(tmp_path, age_keygen)
    ciphertext = tmp_path / "evidence.tar.age"
    environment = _script_environment(tmp_path, age_binary)
    environment.update(
        {
            "TRADING_BOT_AGE_RECIPIENT_FILE": str(recipient),
            "TRADING_BOT_AGE_IDENTITY_FILE": str(identity),
            "TRADING_BOT_DATABASE": str(database),
            "TRADING_BOT_RESEARCH_ARTIFACT_DIR": str(artifact.parent),
            "BACKUP_OUTPUT": str(ciphertext),
        }
    )
    before = _digest(database)
    backup = subprocess.run(
        ["sh", str(BACKUP_SCRIPT)],
        check=False,
        cwd=ROOT,
        capture_output=True,
        env=environment,
        text=True,
    )
    assert backup.returncode == 0
    assert ciphertext.is_file()
    assert ciphertext.read_bytes().startswith(b"age-encryption.org/v1")
    _private_mode(ciphertext)
    assert _digest(database) == before
    return BackupFixture(
        age_binary,
        database,
        ciphertext,
        environment,
        before,
        artifact,
        _digest(artifact),
    )


def _restore(ciphertext: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(RESTORE_SCRIPT), str(ciphertext)],
        check=False,
        cwd=ROOT,
        capture_output=True,
        env=environment,
        text=True,
    )


def test_encrypted_backup_roundtrip_preserves_source_and_remains_paused(
    encrypted_backup: BackupFixture, tmp_path: Path
) -> None:
    restored = _restore(encrypted_backup.ciphertext, encrypted_backup.environment)

    assert restored.returncode == 0
    assert restored.stdout == "restore verified; service remains --paused\n"
    _private_mode(encrypted_backup.ciphertext)
    _private_mode(encrypted_backup.database)
    assert _digest(encrypted_backup.database) == encrypted_backup.database_digest
    with sqlite3.connect(encrypted_backup.database) as connection:
        assert connection.execute("select entry from ledger").fetchall() == [("original-row",)]

    recovered_archive = tmp_path / "recovered.tar"
    decrypted = subprocess.run(
        [
            encrypted_backup.age_binary,
            "-d",
            "-i",
            encrypted_backup.environment["TRADING_BOT_AGE_IDENTITY_FILE"],
            "-o",
            recovered_archive,
            encrypted_backup.ciphertext,
        ],
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert decrypted.returncode == 0
    with tarfile.open(recovered_archive, mode="r:") as archive:
        research_name = f"research/{encrypted_backup.research_artifact.name}"
        assert {member.name.rstrip("/") for member in archive.getmembers()} == {
            "ledger.db",
            "research",
            research_name,
        }
        recovered_database = tmp_path / "recovered-ledger.db"
        recovered_database.write_bytes(_read_archive_member(archive, "ledger.db"))
        recovered_research = _read_archive_member(archive, research_name)
    recovered_database.chmod(0o600)
    _private_mode(recovered_database)
    with sqlite3.connect(recovered_database) as connection:
        assert connection.execute("select entry from ledger").fetchall() == [("original-row",)]
    assert hashlib.sha256(recovered_research).hexdigest() == encrypted_backup.research_digest
    assert recovered_research == encrypted_backup.research_artifact.read_bytes()


def test_restore_rejects_wrong_identity_without_touching_source(
    encrypted_backup: BackupFixture, age_tools: tuple[Path, Path], tmp_path: Path
) -> None:
    _, age_keygen = age_tools
    wrong_identity, _ = _identity_files(tmp_path / "wrong", age_keygen)
    environment = dict(encrypted_backup.environment)
    environment["TRADING_BOT_AGE_IDENTITY_FILE"] = str(wrong_identity)

    restored = _restore(encrypted_backup.ciphertext, environment)

    assert restored.returncode != 0
    assert _digest(encrypted_backup.database) == encrypted_backup.database_digest


@pytest.mark.parametrize("damage", ("truncated", "corrupt"))
def test_restore_rejects_damaged_ciphertext_without_touching_source(
    encrypted_backup: BackupFixture, damage: str, tmp_path: Path
) -> None:
    damaged = tmp_path / f"{damage}.age"
    ciphertext = encrypted_backup.ciphertext.read_bytes()
    if damage == "truncated":
        damaged.write_bytes(ciphertext[: len(ciphertext) // 2])
    else:
        damaged.write_bytes(ciphertext[:-1] + bytes((ciphertext[-1] ^ 1,)))

    restored = _restore(damaged, encrypted_backup.environment)

    assert restored.returncode != 0
    assert _digest(encrypted_backup.database) == encrypted_backup.database_digest
