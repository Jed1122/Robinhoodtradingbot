"""The CLI must reject unsafe startup before it can create an SDK connection."""

import importlib
import json
import os
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from trading_bot.code_identity import CodeIdentity, _verify_deployed_image_attestation
from trading_bot.domain import CodeHash

ROOT = Path(__file__).resolve().parents[3]
IDENTITY = CodeIdentity(CodeHash("b" * 64), "a" * 40, False, None, False)


def arguments(root, *, control=True):
    result = [
        "--config-root",
        str(ROOT / "configs"),
        "--database",
        str(root / "ledger.sqlite3"),
        "--oauth-store",
        str(root / "unused-oauth"),
        "--archive-dir",
        str(root / "unused-archive"),
    ]
    if control:
        result += ["--control-dir", str(root / "unused-controls")]
    return result


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
    from trading_bot.runtime.stock_research_controls import StockResearchControls

    control_root = root / "unused-controls"
    control_root.mkdir(mode=0o700)
    controls = StockResearchControls(control_root)
    paused = controls.initialize()
    loaded, code = module.load_stock_worker_identity(ROOT / "configs")
    controls.change(
        "resume",
        expected_sha256=paused.sha256,
        config_hash=str(loaded.config_hash),
        code_hash=str(code),
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


@pytest.mark.parametrize("flag", ["--image-digest", "--image-attestation"])
def test_cli_rejects_incomplete_deployed_identity_pair(tmp_path, monkeypatch, capsys, flag):
    module = importlib.import_module("trading_bot.runtime.stock_research_worker")
    monkeypatch.setattr(
        module, "resolve_code_identity", lambda *args: pytest.fail("incomplete image identity")
    )
    assert module.main([*arguments(tmp_path.resolve()), flag, "unused"]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "worker_startup_blocked"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("variant", ["valid", "wrong_config", "wrong_image", "writable"])
def test_cli_attested_startup_uses_real_verifier_before_any_resources(
    tmp_path, monkeypatch, capsys, variant
):
    from trading_bot.config import load_config

    module = importlib.import_module("trading_bot.runtime.stock_research_worker")
    loaded = load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=ROOT / "configs/hybrid/stock-research.yaml",
        stock_worker_policy_path=ROOT / "configs/hybrid/stock-worker.yaml",
    )
    root = tmp_path.resolve()
    root.chmod(0o700)
    document = {
        "schema_version": 1,
        "image_digest": "sha256:" + "a" * 64,
        "deployment_config_hash": "b" * 64
        if variant == "wrong_config"
        else str(loaded.config_hash),
        "compose_sha256": "c" * 64,
    }
    document["release_key"] = "-".join(["a" * 64, document["deployment_config_hash"], "c" * 64])
    attestation = root / "image.json"
    attestation.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    attestation.chmod(0o600 if variant == "writable" else 0o400)
    monkeypatch.setattr(
        module,
        "resolve_code_identity",
        lambda *args: pytest.fail("deployed path must not depend on Git"),
    )
    observed = []

    def verify(path, *, expected_image_digest):
        observed.append(True)
        return _verify_deployed_image_attestation(
            path, expected_image_digest=expected_image_digest, trusted_owner_uid=os.geteuid()
        )

    monkeypatch.setattr(module, "verify_deployed_image_attestation", verify, raising=False)

    def ledger(path):
        observed.append("ledger")
        raise ValueError("stop before data or credentials")

    monkeypatch.setattr(module, "_existing_private_ledger", ledger)
    try:
        outcome = module.main(
            [
                *arguments(root),
                "--image-digest",
                "sha256:" + ("d" if variant == "wrong_image" else "a") * 64,
                "--image-attestation",
                str(attestation),
            ]
        )
    except SystemExit as stopped:
        pytest.fail(f"deployed identity options are missing: exit {stopped.code}")
    assert outcome == 2
    assert observed == ([True, "ledger"] if variant == "valid" else [True])
    assert json.loads(capsys.readouterr().out)["reason"] == "worker_startup_blocked"
    assert list(root.iterdir()) == [attestation]


def test_cli_passes_only_image_derived_hash_to_cycle_without_git(tmp_path, monkeypatch, capsys):
    from trading_bot.code_identity import deployed_image_code_hash
    from trading_bot.config import load_config

    module = importlib.import_module("trading_bot.runtime.stock_research_worker")
    loaded = load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=ROOT / "configs/hybrid/stock-research.yaml",
        stock_worker_policy_path=ROOT / "configs/hybrid/stock-worker.yaml",
    )
    root = tmp_path.resolve()
    root.chmod(0o700)
    path = root / "ledger.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT)")
    path.chmod(0o600)
    image = "sha256:" + "a" * 64
    document = {
        "schema_version": 1,
        "image_digest": image,
        "deployment_config_hash": str(loaded.config_hash),
        "compose_sha256": "c" * 64,
        "release_key": "-".join(["a" * 64, str(loaded.config_hash), "c" * 64]),
    }
    attestation = root / "image.json"
    attestation.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    attestation.chmod(0o400)
    monkeypatch.setattr(
        module,
        "verify_deployed_image_attestation",
        lambda path, *, expected_image_digest: _verify_deployed_image_attestation(
            path, expected_image_digest=expected_image_digest, trusted_owner_uid=os.geteuid()
        ),
    )
    monkeypatch.setattr(
        module, "resolve_code_identity", lambda *args: pytest.fail("must not fall back to Git")
    )
    observed = []

    async def cycle(**kwargs):
        observed.append((kwargs["code_hash"], kwargs["loaded"]))
        return {"status": "blocked", "reason": "not_due", "live_enabled": False}

    monkeypatch.setattr(module, "run_stock_research_cycle", cycle)
    assert (
        module.main(
            [*arguments(root), "--image-digest", image, "--image-attestation", str(attestation)]
        )
        == 0
    )
    assert observed == [(deployed_image_code_hash(image), loaded)]
    assert json.loads(capsys.readouterr().out)["live_enabled"] is False


def test_export_only_requires_a_destination_before_opening_resources(tmp_path, monkeypatch, capsys):
    module = importlib.import_module("trading_bot.runtime.stock_research_worker")
    monkeypatch.setattr(
        module, "resolve_code_identity", lambda *args: pytest.fail("invalid command")
    )
    assert module.main([*arguments(tmp_path.resolve()), "--export-only"]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "worker_startup_blocked"
    assert list(tmp_path.iterdir()) == []


def test_export_only_cli_reads_migrated_ledger_without_sdk_or_new_claim(
    tmp_path, monkeypatch, capsys
):
    from trading_bot.persistence.migrations import migrate_sqlite_ledger

    module = importlib.import_module("trading_bot.runtime.stock_research_worker")
    monkeypatch.setattr(module, "resolve_code_identity", lambda *args: IDENTITY)
    root = tmp_path.resolve()
    root.chmod(0o700)
    for name in ("unused-archive", "dashboard-export"):
        (root / name).mkdir(mode=0o700)
    migrate_sqlite_ledger(
        root / "ledger.sqlite3",
        alembic_ini=ROOT / "alembic.ini",
        migrations_dir=ROOT / "migrations",
    )
    monkeypatch.setattr(
        module,
        "RobinhoodMcpSdkConnection",
        lambda **kwargs: pytest.fail("export has no provider operation"),
    )
    assert (
        module.main(
            [
                *arguments(root, control=False),
                "--export-only",
                "--export-dir",
                str(root / "dashboard-export"),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["reason"] == "export_only" and result["live_enabled"] is False
    assert result["dashboard_export_status"] == "published"
    projection = json.loads((root / "dashboard-export/stock-research.json").read_text())
    assert projection["worker"]["status"] == "never_run"
    with sqlite3.connect(root / "ledger.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone() == (0,)
    assert not (root / "unused-oauth").exists()


def test_acquisition_cli_requires_control_path_before_identity_or_resource_access(
    tmp_path, monkeypatch, capsys
):
    module = importlib.import_module("trading_bot.runtime.stock_research_worker")
    monkeypatch.setattr(
        module, "resolve_code_identity", lambda *a: pytest.fail("missing required control")
    )
    assert module.main(arguments(tmp_path.resolve(), control=False)) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "worker_startup_blocked"
    assert list(tmp_path.iterdir()) == []


def test_export_failure_preserves_separate_completed_acquisition_result(
    tmp_path, monkeypatch, capsys
):
    from trading_bot.runtime import stock_dashboard_export as exporter

    module = importlib.import_module("trading_bot.runtime.stock_research_worker")
    monkeypatch.setattr(module, "resolve_code_identity", lambda *args: IDENTITY)
    root = tmp_path.resolve()
    root.chmod(0o700)
    with sqlite3.connect(root / "ledger.sqlite3") as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT)")
    (root / "ledger.sqlite3").chmod(0o600)

    async def cycle(**kwargs):
        return {"status": "succeeded", "reason": "complete", "live_enabled": False}

    async def failed(**kwargs):
        raise exporter.StockDashboardExportError("private-export-error")

    monkeypatch.setattr(module, "run_stock_research_cycle", cycle)
    monkeypatch.setattr(exporter, "export_stock_dashboard", failed)
    assert module.main([*arguments(root), "--export-dir", str(root / "unused-export")]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "succeeded" and result["reason"] == "complete"
    assert result["dashboard_export_status"] == "blocked"
    assert "private-export-error" not in json.dumps(result)
