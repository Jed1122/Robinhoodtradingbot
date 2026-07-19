from pathlib import Path


def test_admin_api_declares_get_routes_only() -> None:
    source = Path("src/trading_bot/monitoring/api.py").read_text()
    assert "@app.post" not in source and "@app.delete" not in source
