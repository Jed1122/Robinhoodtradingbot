from pathlib import Path


def test_heartbeat_contains_runtime_identity() -> None:
    source = Path("src/trading_bot/monitoring/heartbeat.py").read_text()
    assert "instance_id" in source and "runtime_state" in source
