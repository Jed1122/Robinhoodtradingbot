import json
from importlib import import_module
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from trading_bot.runtime.connected_shadow import ConnectedShadowNotReady

main = import_module("trading_bot.cli.main")


def test_shadow_command_delegates_to_sanitized_runtime_boundary(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    observed: dict[str, Any] = {}

    def run_once(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {
            "live_enabled": False,
            "status": "connected_shadow_nonpromotable",
            "write_capabilities_present": False,
        }

    monkeypatch.setattr(main, "run_connected_shadow_once", run_once)
    result = CliRunner().invoke(
        main.app,
        [
            "shadow",
            "--config",
            "configs/shadow.yaml",
            "--once",
            "--oauth-store",
            str(tmp_path / "oauth"),
            "--account-fingerprint-file",
            str(tmp_path / "fingerprint"),
            "--ledger",
            str(tmp_path / "ledger.db"),
            "--image-digest",
            f"sha256:{'a' * 64}",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "live_enabled": False,
        "status": "connected_shadow_nonpromotable",
        "write_capabilities_present": False,
    }
    assert observed["probe_symbol"] is None
    assert observed["strategy_version"] is None
    assert observed["research_evidence_hash"] is None
    assert observed["image_digest"] == f"sha256:{'a' * 64}"
    assert observed["loaded"].config.crypto.enabled is False


def test_shadow_command_requires_complete_pinned_research_identity(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    called = False

    def run_once(**kwargs: object) -> dict[str, object]:
        nonlocal called
        del kwargs
        called = True
        return {}

    monkeypatch.setattr(main, "run_connected_shadow_once", run_once)
    result = CliRunner().invoke(
        main.app,
        [
            "shadow",
            "--config",
            "configs/shadow.yaml",
            "--once",
            "--image-digest",
            f"sha256:{'a' * 64}",
            "--strategy-version",
            "equity_momentum-v1",
        ],
        terminal_width=180,
    )

    assert result.exit_code == 2
    assert not called


def test_shadow_command_fails_before_runtime_without_immutable_digest(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    called = False

    def run_once(**kwargs: object) -> dict[str, object]:
        nonlocal called
        del kwargs
        called = True
        return {}

    monkeypatch.setattr(main, "run_connected_shadow_once", run_once)
    result = CliRunner().invoke(
        main.app,
        ["shadow", "--config", "configs/shadow.yaml", "--once"],
    )

    assert result.exit_code != 0
    assert "requires TRADING_BOT_IMAGE_DIGEST" in result.output
    assert not called


def test_shadow_runtime_failure_emits_only_stable_status(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail(**kwargs: object) -> dict[str, object]:
        del kwargs
        raise ConnectedShadowNotReady("sensitive provider detail")

    monkeypatch.setattr(main, "run_connected_shadow_once", fail)
    result = CliRunner().invoke(
        main.app,
        [
            "shadow",
            "--config",
            "configs/shadow.yaml",
            "--once",
            "--image-digest",
            f"sha256:{'a' * 64}",
        ],
    )

    assert result.exit_code == 2
    assert result.output == "connected_shadow_not_ready\n"
    assert "sensitive" not in result.output


def test_oauth_bootstrap_delegates_without_exposing_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    def bootstrap(**kwargs: object) -> dict[str, object]:
        assert kwargs["oauth_store"] == tmp_path / "oauth"
        assert kwargs["account_fingerprint_file"] == tmp_path / "fingerprint"
        return {"status": "oauth_bootstrap_complete"}

    monkeypatch.setattr(main, "bootstrap_read_only_oauth", bootstrap)
    result = CliRunner().invoke(
        main.app,
        [
            "mcp-oauth-bootstrap",
            "--oauth-store",
            str(tmp_path / "oauth"),
            "--account-fingerprint-file",
            str(tmp_path / "fingerprint"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"status": "oauth_bootstrap_complete"}
    assert str(tmp_path) not in result.stdout
