"""Security composition and offline backup tests for isolated hybrid artifacts."""

import importlib.util
import sqlite3
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_isolated_compose_contract() -> None:
    config = yaml.safe_load((ROOT / "compose.hybrid.yml").read_text())
    assert config["name"] == "hybrid-paper"
    assert list(config["services"]) == ["hybrid-paper"]
    service = config["services"]["hybrid-paper"]
    assert service["image"] == "${HYBRID_IMAGE:?immutable image ID required}"
    assert service["pull_policy"] == "never"
    assert service["ports"] == ["127.0.0.1:8081:8000"]
    assert service["user"] == "10001:10001"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["pids_limit"] == 128
    assert service["cpus"] == 0.5
    assert service["mem_limit"] == "512m"
    assert service["volumes"] == [
        {
            "type": "bind",
            "source": "/var/lib/hybrid-paper",
            "target": "/state",
            "bind": {"create_host_path": False},
        }
    ]
    assert service["environment"] == {
        "LIVE_TRADING_ENABLED": "false",
        "PREDICTION_LIVE_ENABLED": "false",
    }
    assert service["command"] == [
        "--state-dir",
        "/state",
        "--config-root",
        "/app/configs",
        "serve",
        "--host",
        "0.0.0.0",
        "--container-loopback-publish",
        "--port",
        "8000",
        "--dashboard-dir",
        "/app/dashboard/dist",
    ]
    assert "network_mode" not in service and "privileged" not in service


def test_image_context_and_remote_syntax() -> None:
    dockerfile = (ROOT / "Dockerfile.hybrid").read_text()
    assert "ARG PYTHON_BASE_IMAGE" in dockerfile
    assert dockerfile.count("FROM ${PYTHON_BASE_IMAGE}") == 2
    assert "uv==0.11.28" in dockerfile
    assert "uv sync --frozen --no-dev --no-install-project" in dockerfile
    assert 'ENTRYPOINT ["python", "-m", "trading_bot.hybrid.cli"]' in dockerfile
    assert "COPY dashboard/dist /app/dashboard/dist" in dockerfile
    assert "@sha256:" in (ROOT / ".docker-base-image").read_text()
    ignore = (ROOT / "Dockerfile.hybrid.dockerignore").read_text().splitlines()
    assert ignore[0] == "**" and "!dashboard/dist/**" in ignore
    assert not any("oauth" in line or "evidence" in line for line in ignore)
    remote = ROOT / "infra/hybrid/deploy-remote.sh"
    subprocess.run(["sh", "-n", str(remote)], check=True)
    text = remote.read_text()
    assert "sha256sum" in text and "--iidfile" in text
    assert "filter='data'" in text and "--project-name hybrid-paper" in text
    assert "trading-bot-deploy" not in text and "docker push" not in text


def test_private_backup_restores_real_sqlite(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("hybrid_backup", ROOT / "infra/hybrid/backup.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tmp_path.chmod(0o700)
    source = tmp_path / "ledger.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE fixture (value TEXT)")
        db.execute("INSERT INTO fixture VALUES ('paper')")
    destination = tmp_path / "backup.db"
    module.backup(source, destination)
    assert destination.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(destination) as restored:
        assert restored.execute("SELECT value FROM fixture").fetchall() == [("paper",)]
    with pytest.raises(FileExistsError):
        module.backup(source, destination)
    linked = tmp_path / "linked.db"
    linked.symlink_to(source)
    with pytest.raises(ValueError):
        module.backup(linked, tmp_path / "unsafe.db")
