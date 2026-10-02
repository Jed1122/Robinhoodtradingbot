"""Dated statutory reference rates are not customer fees or cost calibration."""

import importlib
from datetime import date, datetime, timedelta
from decimal import Decimal, Inexact, Rounded, localcontext

import pytest


def api():
    return importlib.import_module("trading_bot.research.etf_fee_reference")


@pytest.mark.parametrize(
    "day,rate",
    [
        ("2016-01-01", "18.40"),
        ("2016-02-15", "18.40"),
        ("2016-02-16", "21.80"),
        ("2017-07-04", "23.10"),
        ("2018-05-22", "13.00"),
        ("2019-04-16", "20.70"),
        ("2020-02-18", "22.10"),
        ("2021-02-25", "5.10"),
        ("2022-05-14", "22.90"),
        ("2023-02-27", "8.00"),
        ("2024-05-22", "27.80"),
        ("2025-05-13", "27.80"),
        ("2025-05-14", "0.00"),
        ("2025-12-31", "0.00"),
    ],
)
def test_sec_rates_bind_charge_date_not_an_assumed_trade_timestamp(day, rate):
    result = api().sec_equity_reference(charge_date=date.fromisoformat(day))
    assert result.rate == Decimal(rate)
    assert result.unit == "USD/million_USD_covered_sales"
    assert result.date_basis == "charge_date"
    assert result.customer_costs_qualified is False
    assert result.source_url.startswith("https://www.sec.gov/")


@pytest.mark.parametrize(
    "year,rate,cap",
    [
        (2016, ".000119", "5.95"),
        (2021, ".000119", "5.95"),
        (2022, ".000130", "6.49"),
        (2023, ".000145", "7.27"),
        (2024, ".000166", "8.30"),
        (2025, ".000166", "8.30"),
    ],
)
def test_finra_member_rates_preserve_trade_date_cap_and_no_customer_rounding(year, rate, cap):
    result = api().taf_equity_reference(trade_date=date(year, 1, 1))
    assert result.rate == Decimal(rate) and result.maximum_usd == Decimal(cap)
    assert result.unit == "USD/share_covered_sales"
    assert result.date_basis == "trade_date"
    assert result.customer_costs_qualified is False
    assert result.rounding_rule is None


def test_reference_window_has_no_gaps_and_lookup_does_not_use_ambient_decimal_context():
    with localcontext() as context:
        context.prec = 1
        context.traps[Inexact] = context.traps[Rounded] = True
        day = date(2016, 1, 1)
        while day < date(2026, 1, 1):
            sec = api().sec_equity_reference(charge_date=day)
            taf = api().taf_equity_reference(trade_date=day)
            assert sec.starts_on <= day < sec.ends_before
            assert taf.starts_on <= day < taf.ends_before
            day += timedelta(days=1)
    assert len(api().fee_reference_catalog()) == 15
    assert len(api().fee_reference_catalog_hash()) == 64


@pytest.mark.parametrize(
    "day", [date(2015, 12, 31), date(2026, 1, 1), datetime(2025, 1, 1), "2025-01-01", None]
)
def test_lookup_denies_unsupported_dates_instead_of_extending_a_stale_rate(day):
    with pytest.raises(ValueError, match="etf_fee_reference_invalid"):
        api().sec_equity_reference(charge_date=day)
    with pytest.raises(ValueError, match="etf_fee_reference_invalid"):
        api().taf_equity_reference(trade_date=day)


def test_no_customer_fee_or_known_at_is_invented_from_reference_lookup():
    row = api().sec_equity_reference(charge_date=date(2025, 5, 14))
    assert row.rate == 0
    assert not hasattr(row, "known_at") and not hasattr(row, "fee_usd")
    assert row.scope == "statutory_reference_only"
    assert row.execution_enabled is False and row.evidence_promotable is False
