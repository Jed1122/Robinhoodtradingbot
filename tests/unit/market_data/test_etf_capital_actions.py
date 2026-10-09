"""Fabricated action declarations never become qualified provider evidence."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from trading_bot.market_data.etf_capital_actions import (
    CapitalActionArchive,
    CapitalDistribution,
    CapitalSplit,
)


def archive(splits=None, distributions=None):
    return CapitalActionArchive(
        "QQQ",
        "c" * 64,
        date(2023, 1, 1),
        date(2023, 2, 1),
        datetime(2026, 10, 8, tzinfo=UTC),
        splits,
        distributions,
    )


def test_absence_is_unknown_and_explicit_empty_retains_zero():
    absent = archive()
    empty = archive((), ())
    assert absent.split_count is absent.distribution_count is None
    assert empty.split_count == empty.distribution_count == 0
    assert empty.archive_hash != absent.archive_hash
    assert empty.source_qualified is empty.evidence_promotable is False
    assert empty.point_in_time_qualified is False


def test_ex_date_entitlement_and_payment_date_are_separate_facts():
    row = CapitalDistribution(
        date(2023, 1, 4), date(2023, 1, 5), date(2023, 2, 10), Decimal("0.25"), "d" * 64
    )
    value = archive((), (row,))
    assert value.distribution_count == 1
    assert row.pay_date > value.end


@pytest.mark.parametrize("ratio", [Decimal("0"), Decimal("-1"), Decimal("NaN"), 2, True])
def test_bad_split_ratios_are_not_coerced(ratio):
    with pytest.raises(ValueError):
        CapitalSplit(date(2023, 1, 4), ratio, "d" * 64)


def test_duplicate_effective_dates_and_cross_window_records_are_denied():
    row = CapitalSplit(date(2023, 1, 4), Decimal("2"), "d" * 64)
    with pytest.raises(ValueError):
        archive((row, row), ())
    with pytest.raises(ValueError):
        archive((CapitalSplit(date(2023, 2, 1), Decimal("2"), "d" * 64),), ())


def test_impossible_distribution_dates_and_negative_amount_are_denied():
    with pytest.raises(ValueError):
        CapitalDistribution(
            date(2023, 1, 5), date(2023, 1, 4), date(2023, 2, 10), Decimal("0.25"), "d" * 64
        )
    with pytest.raises(ValueError):
        CapitalDistribution(
            date(2023, 1, 4), date(2023, 1, 5), date(2023, 2, 10), Decimal("-0.25"), "d" * 64
        )


def test_zero_amount_is_an_explicit_observation_not_an_absence():
    row = CapitalDistribution(
        date(2023, 1, 4), date(2023, 1, 5), date(2023, 2, 10), Decimal("0"), "d" * 64
    )
    assert archive((), (row,)).distribution_count == 1


def test_declared_receipt_clock_requires_utc():
    with pytest.raises(ValueError):
        CapitalActionArchive(
            "QQQ", "c" * 64, date(2023, 1, 1), date(2023, 2, 1), datetime(2026, 10, 8), (), ()
        )
