from pathlib import Path


def test_shutdown_has_no_liquidation_operation() -> None:
    source = Path("src/trading_bot/runtime/shutdown.py").read_text()
    assert "place_order" not in source
    assert "reconcile_inflight" in source
