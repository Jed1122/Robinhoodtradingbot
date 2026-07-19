from pathlib import Path

import yaml


def test_compose_hardening() -> None:
    service = yaml.safe_load(Path("docker-compose.yml").read_text())["services"]["trading-bot"]
    assert service["read_only"] is True and service["user"] == "10001:10001"
    assert service["ports"] == ["127.0.0.1:8080:8080"] and service["cap_drop"] == ["ALL"]
