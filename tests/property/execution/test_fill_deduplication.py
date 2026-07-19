from pathlib import Path


def test_fill_application_has_explicit_deduplication_input() -> None:
    source = Path("src/trading_bot/execution/partial_fills.py").read_text()
    assert "applied_fill_ids" in source
    assert "if str(fill.id) in applied_fill_ids" in source
