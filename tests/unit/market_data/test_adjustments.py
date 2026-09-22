from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_bot.clock import InvalidTimestamp
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


def test_content_hash_encodes_timedeltas_exactly() -> None:
    assert content_hash(timedelta(days=1, microseconds=1)) != content_hash(timedelta(days=1))


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


SPLIT = CorporateAction(
    ID,
    "split",
    NOW.date(),
    NOW - timedelta(hours=1),
    Decimal("2"),
    None,
    DataHash("b" * 64),
)
DIVIDEND = CorporateAction(
    ID,
    "dividend",
    NOW.date(),
    NOW - timedelta(hours=1),
    None,
    Decimal("2"),
    DataHash("c" * 64),
)


def ohlcv(value: Bar) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    return value.open, value.high, value.low, value.close, value.volume


@pytest.mark.parametrize("action", [SPLIT, DIVIDEND], ids=["split", "dividend"])
def test_another_instruments_action_cannot_adjust_a_bar(action: CorporateAction) -> None:
    unrelated_action = replace(action, instrument_id=InstrumentId("MSFT"))

    actual = adjust_bars((bar(),), (unrelated_action,), as_of=NOW)

    assert len(actual) == 1
    assert actual[0].instrument_id == ID
    assert ohlcv(actual[0]) == (
        Decimal("100"),
        Decimal("110"),
        Decimal("90"),
        Decimal("105"),
        Decimal("1000"),
    )


@pytest.mark.parametrize("action", [SPLIT, DIVIDEND], ids=["split", "dividend"])
@pytest.mark.parametrize("before_effective", [NOW, NOW + timedelta(days=1, microseconds=-1)])
def test_announced_future_action_is_not_applied_before_its_effective_date(
    action: CorporateAction, before_effective: datetime
) -> None:
    future_action = replace(action, effective_date=date(2026, 7, 18))

    actual = adjust_bars((bar(),), (future_action,), as_of=before_effective)[0]

    assert ohlcv(actual) == (
        Decimal("100"),
        Decimal("110"),
        Decimal("90"),
        Decimal("105"),
        Decimal("1000"),
    )


@pytest.mark.parametrize(
    "action, expected",
    [
        (SPLIT, (Decimal("50"), Decimal("55"), Decimal("45"), Decimal("52.5"), Decimal("2000"))),
        (DIVIDEND, (Decimal("98"), Decimal("108"), Decimal("88"), Decimal("103"), Decimal("1000"))),
    ],
    ids=["split", "dividend"],
)
def test_known_action_applies_at_its_effective_utc_date(
    action: CorporateAction, expected: tuple[Decimal, Decimal, Decimal, Decimal, Decimal]
) -> None:
    future_action = replace(action, effective_date=date(2026, 7, 18))

    actual = adjust_bars((bar(),), (future_action,), as_of=NOW + timedelta(days=1))[0]

    assert ohlcv(actual) == expected


@pytest.mark.parametrize(
    "action, expected",
    [
        (SPLIT, (Decimal("50"), Decimal("55"), Decimal("45"), Decimal("52.5"), Decimal("2000"))),
        (DIVIDEND, (Decimal("98"), Decimal("108"), Decimal("88"), Decimal("103"), Decimal("1000"))),
    ],
    ids=["split", "dividend"],
)
def test_already_effective_action_waits_until_its_late_announcement(
    action: CorporateAction, expected: tuple[Decimal, Decimal, Decimal, Decimal, Decimal]
) -> None:
    announced_at = NOW + timedelta(hours=1)
    late_action = replace(action, announced_at=announced_at)

    before = adjust_bars((bar(),), (late_action,), as_of=announced_at - timedelta(microseconds=1))[
        0
    ]
    at_announcement = adjust_bars((bar(),), (late_action,), as_of=announced_at)[0]

    assert ohlcv(before) == (
        Decimal("100"),
        Decimal("110"),
        Decimal("90"),
        Decimal("105"),
        Decimal("1000"),
    )
    assert ohlcv(at_announcement) == expected


def test_each_instrument_in_a_batch_receives_only_its_own_action() -> None:
    second_id = InstrumentId("MSFT")
    second_bar = replace(bar(), instrument_id=second_id)
    second_action = replace(DIVIDEND, instrument_id=second_id)

    actual = adjust_bars((bar(), second_bar), (SPLIT, second_action), as_of=NOW)

    assert tuple(value.instrument_id for value in actual) == (ID, second_id)
    assert ohlcv(actual[0]) == (
        Decimal("50"),
        Decimal("55"),
        Decimal("45"),
        Decimal("52.5"),
        Decimal("2000"),
    )
    assert ohlcv(actual[1]) == (
        Decimal("98"),
        Decimal("108"),
        Decimal("88"),
        Decimal("103"),
        Decimal("1000"),
    )


@pytest.mark.parametrize("action", [SPLIT, DIVIDEND], ids=["split", "dividend"])
@pytest.mark.parametrize("ends_at", [NOW, NOW + timedelta(days=1)])
def test_bars_ending_on_or_after_an_actions_effective_date_are_not_adjusted(
    action: CorporateAction, ends_at: datetime
) -> None:
    current_bar = replace(bar(), starts_at=ends_at - timedelta(days=1), ends_at=ends_at)

    actual = adjust_bars((current_bar,), (action,), as_of=NOW + timedelta(days=2))[0]

    assert ohlcv(actual) == (
        Decimal("100"),
        Decimal("110"),
        Decimal("90"),
        Decimal("105"),
        Decimal("1000"),
    )


@pytest.mark.parametrize(
    "as_of",
    [NOW.replace(tzinfo=None), NOW.astimezone(timezone(timedelta(hours=1)))],
    ids=["naive", "non-utc"],
)
@pytest.mark.parametrize("bars", [(), (bar(),)], ids=["empty", "nonempty"])
def test_adjustments_reject_noncanonical_query_times_even_without_actions(
    as_of: datetime, bars: tuple[Bar, ...]
) -> None:
    with pytest.raises(InvalidTimestamp):
        adjust_bars(bars, (), as_of=as_of)


def test_empty_adjustments_accept_a_utc_query_time() -> None:
    assert adjust_bars((), (), as_of=NOW) == ()
