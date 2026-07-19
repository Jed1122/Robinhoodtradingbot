from pathlib import Path


def test_llm_has_no_execution_import() -> None:
    source = Path("src/trading_bot/reporting/llm.py").read_text()
    assert "brokers" not in source and "execution" not in source
