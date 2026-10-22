"""Configuration-only observation for an inert image; no fabricated code authority."""

import importlib
import json
from pathlib import Path

import pytest

from trading_bot.config import load_config

ROOT = Path(__file__).resolve().parents[3]


def module():
    try:
        return importlib.import_module("trading_bot.runtime.stock_research_identity")
    except ModuleNotFoundError:
        pytest.fail("Stock image configuration-only observation is not implemented")


def test_configuration_only_observation_reuses_full_policy_without_code_or_sdk(monkeypatch, capsys):
    cli = module()
    worker = importlib.import_module("trading_bot.runtime.stock_research_worker")
    monkeypatch.setattr(
        worker, "resolve_code_identity", lambda *a: pytest.fail("no code proof requested")
    )
    monkeypatch.setattr(
        worker,
        "verify_deployed_image_attestation",
        lambda *a, **kw: pytest.fail("no fabricated attestation"),
    )
    monkeypatch.setattr(worker, "RobinhoodMcpSdkConnection", lambda **kw: pytest.fail("no SDK"))
    loaded = load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=ROOT / "configs/hybrid/stock-research.yaml",
        stock_worker_policy_path=ROOT / "configs/hybrid/stock-worker.yaml",
    )
    assert cli.main(["--config-root", str(ROOT / "configs")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "status": "succeeded",
        "schema_version": 1,
        "kind": "stock_research_configuration_identity",
        "config_hash": str(loaded.config_hash),
        "scan_interval_seconds": 3600,
        "max_run_seconds": 450,
        "max_daily_calls": 512,
        "max_calls_per_cycle": 32,
        "maximum_source_age_seconds": 7200,
        "live_enabled": False,
    }


def test_missing_configuration_denies_without_private_path_or_directory_creation(tmp_path, capsys):
    cli = module()
    absent = tmp_path.resolve() / "private-missing-config"
    assert cli.main(["--config-root", str(absent)]) == 2
    output = capsys.readouterr().out
    assert str(absent) not in output
    assert json.loads(output) == {
        "status": "blocked",
        "reason": "stock_configuration_unavailable",
        "live_enabled": False,
    }
    assert not absent.exists()


def test_live_environment_override_cannot_be_presented_as_safe_configuration(monkeypatch, capsys):
    cli = module()
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    assert cli.main(["--config-root", str(ROOT / "configs")]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "blocked" and result["live_enabled"] is False


def test_container_false_safety_flags_preserve_the_immutable_policy(monkeypatch, capsys):
    cli = module()
    for key in ("LIVE_TRADING_ENABLED", "PREDICTION_LIVE_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    assert cli.main(["--config-root", str(ROOT / "configs")]) == 0
    expected = json.loads(capsys.readouterr().out)
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("PREDICTION_LIVE_ENABLED", "false")
    assert cli.main(["--config-root", str(ROOT / "configs")]) == 0
    assert json.loads(capsys.readouterr().out) == expected


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("LIVE_TRADING_ENABLED", "true"),
        ("PREDICTION_LIVE_ENABLED", "true"),
        ("LIVE_TRADING_ENABLED", "False"),
        ("PREDICTION_LIVE_ENABLED", "0"),
        ("LIVE_TRADING_ENABLED", ""),
        ("LIVE_TRADING_ENABLED", " false"),
        ("live_trading_enabled", "false"),
        ("TRADING_BOT__LIVE_TRADING_ENABLED", "false"),
    ],
)
def test_container_flags_do_not_admit_other_configuration_overrides(
    monkeypatch, capsys, key, value
):
    cli = module()
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("PREDICTION_LIVE_ENABLED", "false")
    monkeypatch.setenv(key, value)
    assert cli.main(["--config-root", str(ROOT / "configs")]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "blocked",
        "reason": "stock_configuration_unavailable",
        "live_enabled": False,
    }


def test_changed_canonical_stock_policy_changes_observed_hash_and_schedule(tmp_path, capsys):
    import shutil

    cli = module()
    assert cli.main(["--config-root", str(ROOT / "configs")]) == 0
    original = json.loads(capsys.readouterr().out)
    copied = tmp_path / "configs"
    shutil.copytree(ROOT / "configs", copied)
    policy = copied / "hybrid/stock-research.yaml"
    policy.write_text(policy.read_text() + "\nscan_minutes: 45\n")
    assert cli.main(["--config-root", str(copied)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["scan_interval_seconds"] == 2700 and result["live_enabled"] is False
    assert result["config_hash"] != original["config_hash"]
