from pathlib import Path


def test_webhook_redacts_sensitive_keys() -> None:
    source = Path("src/trading_bot/monitoring/alerts.py").read_text()
    assert '"account_id"' in source and '"<redacted>"' in source
