import hashlib
import json
import re
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _content_hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _verify_sqlite(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if result != ("ok",):
        raise SystemExit("SQLite integrity check failed")


def _mapping(value: object, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise SystemExit(f"{name} has an invalid shape")
    return value


def _verify_report(name: str, encoded: bytes) -> None:
    match = re.fullmatch(r"research/([0-9a-f]{64})\.json", name)
    if match is None:
        raise SystemExit("research artifact name is invalid")
    try:
        report = _mapping(json.loads(encoded), "research report")
    except (UnicodeDecodeError, ValueError):
        raise SystemExit("research report JSON is invalid") from None
    report_hash = report.get("report_hash")
    payload = {
        "attempts": report.get("attempts"),
        "disclaimer": report.get("disclaimer"),
        "run": report.get("run"),
    }
    if (
        type(report_hash) is not str
        or SHA256_HEX.fullmatch(report_hash) is None
        or report_hash != match.group(1)
        or _content_hash(payload) != report_hash
    ):
        raise SystemExit("research report content address is invalid")
    run = _mapping(report.get("run"), "research run")
    manifest = _mapping(run.get("data_manifest"), "research data manifest")
    manifest_hash = manifest.get("manifest_hash")
    manifest_preimage = dict(manifest)
    manifest_preimage.pop("manifest_hash", None)
    if (
        type(manifest_hash) is not str
        or _content_hash(manifest_preimage) != manifest_hash
        or run.get("data_manifest_hash") != manifest_hash
    ):
        raise SystemExit("research data manifest content address is invalid")
    snapshot = _mapping(run.get("dataset_snapshot"), "research dataset snapshot")
    rows = snapshot.get("bars_by_symbol")
    if type(rows) is not list:
        raise SystemExit("research dataset bars are invalid")
    cleaned_hashes: list[str] = []
    for row in rows:
        if type(row) is not list or len(row) != 2 or type(row[0]) is not str:
            raise SystemExit("research dataset symbol row is invalid")
        cleaned_hashes.append(_content_hash({"bars": row[1], "symbol": row[0]}))
    if (
        cleaned_hashes != manifest.get("cleaned_hashes")
        or snapshot.get("raw_hashes") != manifest.get("raw_hashes")
        or snapshot.get("provider_evidence_hash") != run.get("provider_evidence_hash")
    ):
        raise SystemExit("research dataset does not match its manifest")


def _verify_archive(path: Path) -> None:
    with tarfile.open(path, mode="r:*") as archive:
        members = archive.getmembers()
        names = [
            member.name.removeprefix("./").rstrip("/")
            if member.isdir()
            else member.name.removeprefix("./")
            for member in members
        ]
        if len(names) != len(set(names)):
            raise SystemExit("evidence archive contains duplicate paths")
        allowed_directories = {"research"}
        for member, name in zip(members, names, strict=True):
            if member.isdir() and name in allowed_directories:
                continue
            if not member.isfile() or (
                name != "ledger.db"
                and re.fullmatch(r"research/[0-9a-f]{64}\.json", name) is None
            ):
                raise SystemExit("evidence archive contains an unsafe path")
        ledger_members = [
            member
            for member, name in zip(members, names, strict=True)
            if name == "ledger.db"
        ]
        if len(ledger_members) != 1:
            raise SystemExit("evidence archive must contain one ledger")
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "ledger.db"
            source = archive.extractfile(ledger_members[0])
            if source is None:
                raise SystemExit("evidence ledger is unreadable")
            ledger.write_bytes(source.read())
            _verify_sqlite(ledger)
        for member, name in zip(members, names, strict=True):
            if not name.startswith("research/") or not member.isfile():
                continue
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit("research artifact is unreadable")
            _verify_report(name, source.read())


def main() -> int:
    path = Path(sys.argv[1])
    if tarfile.is_tarfile(path):
        _verify_archive(path)
    else:
        _verify_sqlite(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
