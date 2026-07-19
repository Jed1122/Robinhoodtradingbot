from pathlib import Path


def test_final_pretrade_refresh_requires_exactly_twenty_four_checks() -> None:
    source = Path("src/trading_bot/execution/service.py").read_text()
    refresh = source.index("load_final(intent, review)")
    evaluation = source.index("expected_check_count=24", refresh)
    reservation = source.index("_reserve_submission(", evaluation)
    assert refresh < evaluation < reservation
