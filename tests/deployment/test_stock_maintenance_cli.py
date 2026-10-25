"""The production CLI has only fixed monitor/backup actions and no live controls."""

import json

import pytest

from infra.hybrid import stock_maintenance as module


@pytest.fixture
def root_cli(monkeypatch):
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.sys, "platform", "linux")


@pytest.mark.parametrize("action", ["monitor", "backup"])
def test_native_cli_dispatches_one_fixed_operation(root_cli, monkeypatch, capsys, action):
    calls = []
    monkeypatch.setattr(module.sys, "argv", ["stock_maintenance", action, "/fixed/manifest.json"])

    def run(*args, **kwargs):
        calls.append(action)
        return {
            "status": "observed" if action == "monitor" else "backup_committed",
            "live_enabled": False,
        }

    monkeypatch.setattr(module, "monitor_stock", run)
    monkeypatch.setattr(module, "backup_stock", run)
    assert module.main() == 0
    assert calls == [action]
    assert json.loads(capsys.readouterr().out)["live_enabled"] is False


@pytest.mark.parametrize(
    "args", [[], ["trade"], ["resume", "/fixed"], ["backup", "/fixed", "--enable-live"]]
)
def test_unknown_commands_never_dispatch(root_cli, monkeypatch, capsys, args):
    monkeypatch.setattr(module.sys, "argv", ["stock_maintenance", *args])
    monkeypatch.setattr(
        module, "monitor_stock", lambda *args, **kwargs: pytest.fail("must not run")
    )
    assert module.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "stock_maintenance_unavailable"


def test_native_failure_does_not_print_internal_exception(root_cli, monkeypatch, capsys):
    monkeypatch.setattr(module.sys, "argv", ["stock_maintenance", "monitor", "/fixed"])

    def failed(*args, **kwargs):
        raise ValueError("private internal diagnostic")

    monkeypatch.setattr(module, "monitor_stock", failed)
    assert module.main() == 2
    assert "private" not in capsys.readouterr().out


def test_integrity_backup_command_explicitly_selects_recovery_policy(root_cli, monkeypatch, capsys):
    monkeypatch.setattr(
        module.sys, "argv", ["stock_maintenance", "backup-integrity", "/fixed/manifest.json"]
    )

    def backup(manifest, *, checkout, validation_policy):
        assert str(manifest) == "/fixed/manifest.json"
        assert validation_policy == "recovery_integrity_v1"
        return {"status": "backup_committed", "live_enabled": False}

    monkeypatch.setattr(module, "backup_stock", backup)
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "backup_committed",
        "live_enabled": False,
    }
