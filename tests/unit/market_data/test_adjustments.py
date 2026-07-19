from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from trading_bot.domain import Bar, BarInterval, CorporateAction, DataHash, InstrumentId
from trading_bot.market_data import adjust_bars, content_hash

NOW = datetime(2026, 7, 17, tzinfo=UTC)
ID = InstrumentId("AAPL")


def bar() -> Bar:
    return Bar(
        ID,
        BarInterval.ONE_DAY,
        NOW - timedelta(days=2),
        NOW - timedelta(days=1),
        Decimal("100"),
        Decimal("110"),
        Decimal("90"),
        Decimal("105"),
        Decimal("1000"),
        "fixture",
        DataHash("a" * 64),
    )


def test_manifest_hash_is_key_order_independent() -> None:
    assert content_hash({"b": 2, "a": 1}) == content_hash({"a": 1, "b": 2})


def test_split_is_applied_only_after_announcement_is_known() -> None:
    action = CorporateAction(
        ID,
        "split",
        date(2026, 7, 17),
        NOW - timedelta(hours=1),
        Decimal("2"),
        None,
        DataHash("b" * 64),
    )
    adjusted = adjust_bars((bar(),), (action,), as_of=NOW)[0]
    assert adjusted.close == Decimal("52.5")
    assert adjusted.volume == Decimal("2000")
    assert adjust_bars((bar(),), (action,), as_of=NOW - timedelta(hours=2))[0].close == Decimal(
        "105"
    )
