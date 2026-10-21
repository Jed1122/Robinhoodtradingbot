"""Stock-only container policy; no daemon, credentials or production resources."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "${STOCK_IMAGE:?immutable image ID required}"
ATTESTATION = "${STOCK_ATTESTATION_FILE:?trusted release attestation required}"


def service():
    path = ROOT / "compose.stock-research.yml"
    assert path.is_file(), "Isolated stock collector container policy is not implemented"
    model = yaml.safe_load(path.read_text())
    assert set(model) == {"name", "services"}
    assert model["name"] == "hybrid-stock-research"
    assert list(model["services"]) == ["stock-research"]
    return model["services"]["stock-research"]


def test_stock_container_has_no_autorestart_pull_ports_or_privileged_fallback():
    config = service()
    assert config["image"] == IMAGE and config["pull_policy"] == "never"
    assert config["restart"] == "no" and config["init"] is True
    assert config["healthcheck"] == {"disable": True}
    assert config["user"] == "10001:10001" and config["read_only"] is True
    assert config["cap_drop"] == ["ALL"]
    assert config["security_opt"] == ["no-new-privileges:true"]
    assert config["network_mode"] == "bridge"
    assert config["pids_limit"] == 128 and config["cpus"] == 0.5
    assert config["mem_limit"] == "512m" and config["memswap_limit"] == "512m"
    assert config["stop_signal"] == "SIGTERM" and config["stop_grace_period"] == "10s"
    assert config["tmpfs"] == ["/tmp:size=32m,mode=1777,noexec,nosuid,nodev"]
    assert config["logging"] == {
        "driver": "json-file",
        "options": {"max-size": "10m", "max-file": "3"},
    }
    for field in (
        "build",
        "ports",
        "expose",
        "privileged",
        "pid",
        "ipc",
        "devices",
        "env_file",
        "depends_on",
        "volumes_from",
        "extends",
        "post_start",
        "pre_start",
    ):
        assert field not in config


def test_stock_mounts_are_only_dedicated_siblings_with_worker_only_credentials():
    config = service()
    expected = []
    for host, target in (
        ("state", "state"),
        ("archive", "archive"),
        ("controls", "controls"),
        ("exports", "exports"),
        ("oauth", "oauth"),
    ):
        expected.append(
            {
                "type": "bind",
                "source": "/var/lib/hybrid-stock-research/" + host,
                "target": "/stock-" + target,
                "bind": {"create_host_path": False},
            }
        )
    expected.append(
        {
            "type": "bind",
            "source": ATTESTATION,
            "target": "/run/trading-bot/stock-image-attestation.json",
            "read_only": True,
            "bind": {"create_host_path": False},
        }
    )
    assert config["volumes"] == expected
    assert "hybrid-paper" not in str(config["volumes"])
    assert "docker.sock" not in str(config["volumes"])


def test_worker_command_cannot_initialize_resume_or_enable_execution():
    config = service()
    assert config["entrypoint"] == ["python", "-m", "trading_bot.runtime.stock_research_worker"]
    assert config["command"] == [
        "--config-root",
        "/app/configs",
        "--database",
        "/stock-state/ledger.sqlite3",
        "--oauth-store",
        "/stock-oauth",
        "--archive-dir",
        "/stock-archive",
        "--control-dir",
        "/stock-controls",
        "--export-dir",
        "/stock-exports",
        "--image-digest",
        IMAGE,
        "--image-attestation",
        "/run/trading-bot/stock-image-attestation.json",
    ]
    assert config["environment"] == {
        "LIVE_TRADING_ENABLED": "false",
        "PREDICTION_LIVE_ENABLED": "false",
    }
    assert (
        "install -d -m 0755 -o root -g root /run/trading-bot" in (ROOT / "Dockerfile").read_text()
    )
