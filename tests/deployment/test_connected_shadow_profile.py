from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _compose() -> dict[str, Any]:
    document = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _command_value(command: list[str], option: str) -> str:
    position = command.index(option)
    assert position + 1 < len(command), f"{option} must have a value"
    return command[position + 1]


def _volume_for_target(service: dict[str, Any], target: str) -> dict[str, Any]:
    matches = [
        volume
        for volume in service.get("volumes", [])
        if isinstance(volume, dict) and volume.get("target") == target
    ]
    assert len(matches) == 1, f"expected exactly one volume mounted at {target}"
    return matches[0]


def test_connected_shadow_is_explicit_and_does_not_change_paused_default() -> None:
    services = _compose()["services"]
    paused = services["trading-bot"]
    connected = services["connected-shadow"]

    assert not paused.get("profiles")
    assert "command" not in paused
    assert connected["profiles"] == ["connected-shadow"]
    assert connected["restart"] == "no"

    for name, service in services.items():
        if name != "trading-bot":
            assert service.get("profiles"), f"{name} must not start in the default profile"


def test_connected_shadow_runs_only_the_one_shot_read_only_command() -> None:
    service = _compose()["services"]["connected-shadow"]
    command = service["command"]

    assert isinstance(command, list), "use exec-form arguments, not a shell command"
    assert command[0] == "shadow"
    assert "--once" in command
    assert _command_value(command, "--config") == "/app/configs/shadow.yaml"
    assert "mcp-oauth-bootstrap" not in command
    assert "enable-live" not in command
    assert "run" not in command
    assert "--probe-symbol" not in command

    environment = service["environment"]
    assert environment["LIVE_TRADING_ENABLED"] == "false"
    assert environment["PREDICTION_LIVE_ENABLED"] == "false"
    image_digest = environment["TRADING_BOT_IMAGE_DIGEST"]
    assert isinstance(image_digest, str) and "${TRADING_BOT_IMAGE" in image_digest
    assert not image_digest.startswith("sha256:")
    assert "?" not in image_digest, "inactive profiles cannot require extra interpolation"
    assert not any("PRIVATE_KEY" in name or "SIGNING_KEY" in name for name in environment)
    assert "ports" not in service and "expose" not in service


def test_connected_shadow_mounts_only_required_mutable_state() -> None:
    service = _compose()["services"]["connected-shadow"]
    command = service["command"]
    oauth_target = _command_value(command, "--oauth-store")
    fingerprint_target = _command_value(command, "--account-fingerprint-file")
    ledger_path = _command_value(command, "--ledger")
    ledger_target = str(Path(ledger_path).parent)

    assert ledger_path == "/var/lib/trading-bot/evidence/ledger.db"
    assert ledger_path in Path("infra/digitalocean/backup.sh").read_text(encoding="utf-8")

    oauth = _volume_for_target(service, oauth_target)
    fingerprint = _volume_for_target(service, fingerprint_target)
    ledger = _volume_for_target(service, ledger_target)

    assert oauth["type"] == "bind" and oauth.get("read_only") is not True
    assert fingerprint["type"] == "bind" and fingerprint["read_only"] is True
    assert ledger["type"] == "bind" and ledger.get("read_only") is not True

    for volume in (oauth, fingerprint):
        source = volume.get("source")
        assert isinstance(source, str)
        assert source.startswith("${") or source.startswith("/var/lib/trading-bot/")
        assert "?" not in source, "inactive profiles cannot require extra interpolation"


def test_connected_shadow_preserves_container_hardening() -> None:
    service = _compose()["services"]["connected-shadow"]

    assert service["read_only"] is True
    assert service["user"] == "10001:10001"
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["tmpfs"] == ["/tmp"]
    assert service["pids_limit"] <= 256
    assert service["init"] is True


def test_connected_research_is_explicit_read_only_and_never_changes_default() -> None:
    service = _compose()["services"]["connected-research"]
    command = service["command"]

    assert service["profiles"] == ["connected-research"]
    assert service["restart"] == "no"
    assert command[0] == "research-equities"
    assert "--once" in command
    assert _command_value(command, "--config") == "/app/configs/shadow.yaml"
    assert _command_value(command, "--artifact-dir").startswith(
        "/var/lib/trading-bot/evidence/"
    )
    assert "enable-live" not in command
    assert "run" not in command
    assert "mcp-oauth-bootstrap" not in command
    assert service["read_only"] is True
    assert service["user"] == "10001:10001"
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert "ports" not in service and "expose" not in service
    assert service["environment"]["LIVE_TRADING_ENABLED"] == "false"
    assert service["environment"]["PREDICTION_LIVE_ENABLED"] == "false"


def test_connected_research_mounts_only_private_oauth_and_evidence_state() -> None:
    service = _compose()["services"]["connected-research"]
    command = service["command"]
    oauth_target = _command_value(command, "--oauth-store")
    fingerprint_target = _command_value(command, "--account-fingerprint-file")
    ledger_target = str(Path(_command_value(command, "--ledger")).parent)

    oauth = _volume_for_target(service, oauth_target)
    fingerprint = _volume_for_target(service, fingerprint_target)
    evidence = _volume_for_target(service, ledger_target)
    assert oauth["type"] == "bind" and oauth.get("read_only") is not True
    assert fingerprint["read_only"] is True
    assert evidence["type"] == "bind" and evidence.get("read_only") is not True


def test_promotion_status_profile_is_networkless_and_can_only_read_evidence() -> None:
    service = _compose()["services"]["promotion-status"]
    command = service["command"]

    assert service["profiles"] == ["promotion-status"]
    assert service["restart"] == "no"
    assert service["network_mode"] == "none"
    assert command == [
        "promotion-status",
        "--config",
        "/app/configs/micro_live.yaml",
        "--ledger",
        "/var/lib/trading-bot/evidence/ledger.db",
    ]
    evidence = _volume_for_target(service, "/var/lib/trading-bot/evidence")
    assert evidence["type"] == "bind"
    assert evidence["read_only"] is True
    assert "oauth" not in str(service).lower()
    assert not any("KEY" in name or "SECRET" in name for name in service["environment"])
    assert service["environment"] == {
        "LIVE_TRADING_ENABLED": "false",
        "PREDICTION_LIVE_ENABLED": "false",
    }
    assert service["read_only"] is True
    assert service["user"] == "10001:10001"
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert "ports" not in service and "expose" not in service


def test_shadow_image_contains_ledger_migration_assets() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "COPY alembic.ini /app/alembic.ini" in dockerfile
    assert "COPY migrations /app/migrations" in dockerfile


def test_connected_shadow_profile_explicitly_disables_crypto() -> None:
    overlay = yaml.safe_load(Path("configs/shadow.yaml").read_text(encoding="utf-8"))

    assert overlay["mode"] == "shadow"
    assert overlay["live_trading_enabled"] is False
    assert overlay["runtime"]["start_paused"] is True
    assert overlay["crypto"]["enabled"] is False


def test_legacy_shadow_script_delegates_to_the_cli_instead_of_stubbing() -> None:
    script = Path("scripts/run_shadow.py").read_text(encoding="utf-8")

    assert "external_capability_missing" not in script
    assert "trading_bot.cli.main" in script
    assert "shadow" in script
    assert "mcp-oauth-bootstrap" not in script
