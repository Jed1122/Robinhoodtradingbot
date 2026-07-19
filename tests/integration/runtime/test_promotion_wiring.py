from pathlib import Path


def test_place_factory_is_after_promotion_gate() -> None:
    source = Path("src/trading_bot/runtime/live.py").read_text()
    assert source.index("promotion is None") < source.rindex("place_factory()")
