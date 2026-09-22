from pathlib import Path


def test_mutable_context_is_loaded_inside_submission_exclusion() -> None:
    source = Path("src/trading_bot/execution/service.py").read_text()
    exclusion = source.index("async with self._exclusion.acquire(intent.account_id)")
    refresh = source.index("load_final(intent, review)", exclusion)
    reserve = source.index("_reserve_submission(", refresh)
    assert exclusion < refresh < reserve
