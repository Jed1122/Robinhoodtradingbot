from pathlib import Path


def test_production_mutex_uses_nonblocking_exclusive_flock() -> None:
    source = Path("src/trading_bot/persistence/submission_mutex.py").read_text()
    assert "fcntl.LOCK_EX | fcntl.LOCK_NB" in source
