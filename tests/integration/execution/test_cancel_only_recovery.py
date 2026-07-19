from pathlib import Path


def test_recovery_never_imports_place_capability() -> None:
    source = Path("src/trading_bot/execution/recovery.py").read_text()
    assert "BrokerPlace" not in source
    assert "BrokerCancelOnly" in source
    assert "RuntimeState.PAUSED" in source
