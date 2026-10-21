"""The CLI must reject unsafe startup before it can create an SDK connection."""

import importlib
import json
import os
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from trading_bot.code_identity import CodeIdentity
from trading_bot.domain import CodeHash

ROOT = Path(__file__).resolve().parents[3]
IDENTITY = CodeIdentity(CodeHash("b" * 64), "a" * 40, False, None, False)


def arguments(root):
    return [
        "--config-root",
        str(ROOT / "configs"),
        "--database",
        str(root / "ledger.sqlite3"),
        "--oauth-store",
        str(root / "unused-oauth"),
        "--archive-dir",
        str(root / "unused-archive"),
    ]


@pytest.mark.parametrize(
    "changes", [{"dirty": True}, {"non_promotable": True}, {"git_commit": None}]
)
def test_cli_rejects_unverified_code_before_database_or_sdk(tmp_path, monkeypatch, capsys, changes):
    module = importlib.import_module("trading_bot.runtime.stock_research_worker")
    monkeypatch.setattr(module, "resolve_code_identity", lambda *args: replace(IDENTITY, **changes))
    assert module.main(arguments(tmp_path.resolve())) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "worker_startup_blocked"
    assert list(tmp_path.iterdir()) == []


def test_cli_does_not_create_a_missing_ledger(tmp_path, monkeypatch, capsys):
    module = importlib.import_module("trading_bot.runtime.stock_research_worker")
    monkeypatch.setattr(module, "resolve_code_identity", lambda *args: IDENTITY)
    assert module.main(arguments(tmp_path.resolve())) == 2
    assert json.loads(capsys.readouterr().out)["live_enabled"] is False
    assert list(tmp_path.iterdir()) == []


def test_cli_rejects_public_ledger_without_chmod_or_provider_access(tmp_path, monkeypatch, capsys):
    module = importlib.import_module("trading_bot.runtime.stock_research_worker")
    monkeypatch.setattr(module, "resolve_code_identity", lambda *args: IDENTITY)
    path = tmp_path / "ledger.sqlite3"
    path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    path.chmod(0o644)
    assert module.main(arguments(tmp_path.resolve())) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "worker_startup_blocked"
    assert path.stat().st_mode & 0o777 == 0o644
    assert not (tmp_path / "unused-oauth").exists()


def test_cli_validated_existing_ledger_reaches_fake_sdk_and_retains_charge(
    tmp_path, monkeypatch, capsys
):
    from trading_bot.persistence.migrations import migrate_sqlite_ledger

    module = importlib.import_module("trading_bot.runtime.stock_research_worker")
    monkeypatch.setattr(module, "resolve_code_identity", lambda *args: IDENTITY)
    root = tmp_path.resolve()
    root.chmod(0o700)
    (root / "unused-archive").mkdir(mode=0o700)
    path = root / "ledger.sqlite3"
    migrate_sqlite_ledger(
        path, alembic_ini=ROOT / "alembic.ini", migrations_dir=ROOT / "migrations"
    )
    calls = []

    def unavailable(**kwargs):
        calls.append(True)
        raise RuntimeError("fictional-private-auth-detail")

    monkeypatch.setattr(module, "RobinhoodMcpSdkConnection", unavailable)
    assert module.main(arguments(root)) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["reason"] == "auth_unavailable" and result["live_enabled"] is False
    assert result["planned_calls"] == 17 and result["attempted_calls"] == 0
    assert calls == [True]
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE category='stock_research'"
        ).fetchone() == (2,)
    assert path.stat().st_mode & 0o777 == 0o600
    assert not (root / "unused-oauth").exists()


@pytest.mark.parametrize("change", ["disappear", "replace", "symlink"])
def test_cli_pins_existing_ledger_through_connection(tmp_path, monkeypatch, capsys, change):
    module = importlib.import_module("trading_bot.runtime.stock_research_worker")
    monkeypatch.setattr(module, "resolve_code_identity", lambda *args: IDENTITY)
    root = tmp_path.resolve()
    root.chmod(0o700)
    (root / "unused-archive").mkdir(mode=0o700)
    path = root / "ledger.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT)")
    path.chmod(0o600)
    original_engine = module.create_engine
    descriptors = []

    def changed_engine(url, **kwargs):
        descriptor = kwargs.get("existing_file_descriptor")
        if descriptor is not None:
            descriptors.append(descriptor)
            assert os.fstat(descriptor).st_ino == path.stat().st_ino
        path.rename(root / "retained.sqlite3")
        if change == "replace":
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE unrelated (value TEXT)")
            path.chmod(0o600)
        elif change == "symlink":
            path.symlink_to(root / "retained.sqlite3")
        return original_engine(url, **kwargs)

    monkeypatch.setattr(module, "create_engine", changed_engine)
    monkeypatch.setattr(
        module,
        "RobinhoodMcpSdkConnection",
        lambda **kwargs: pytest.fail("changed ledger must not reach credentials"),
    )
    assert module.main(arguments(root)) == 2
    assert json.loads(capsys.readouterr().out)["live_enabled"] is False
    if change == "disappear":
        assert not path.exists()
    elif change == "replace":
        assert not Path(str(path) + "-wal").exists()
        with sqlite3.connect(path) as connection:
            assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    else:
        assert path.is_symlink()
    assert descriptors
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert not (root / "unused-oauth").exists()
