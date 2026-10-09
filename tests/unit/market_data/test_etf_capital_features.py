"""Split feature prices are not raw execution prices or reinvested dividends."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tests.unit.market_data.test_alpaca_capital_native import body, request
from tests.unit.market_data.test_etf_capital_inventory import calendar
from trading_bot.market_data.alpaca_capital_native import parse_capital_daily_page
from trading_bot.market_data.etf_capital_actions import (
    CapitalActionArchive,
    CapitalDistribution,
    CapitalSplit,
)
from trading_bot.market_data.etf_capital_archive import CapitalDailyArchive
from trading_bot.market_data.etf_capital_features import capital_split_feature_bars


def inputs(splits=(), distributions=()):
    wire = json.loads(body())
    first = wire["bars"][0]
    first.update(o=20, h=24, l=18, c=22, vw=21)
    second = dict(first, t="2023-01-04T05:00:00Z", o=10, h=12, l=9, c=11, vw=10.5)
    wire["bars"] = [first, second]
    raw = json.dumps(wire).encode()
    page = parse_capital_daily_page(
        raw, request=request(), expected_sha256=hashlib.sha256(raw).hexdigest()
    )
    captured = CapitalDailyArchive(
        "a" * 64, request(), (page,), (datetime(2026, 10, 8, tzinfo=UTC),)
    )
    actions = CapitalActionArchive(
        "QQQ",
        "c" * 64,
        date(2023, 1, 3),
        date(2023, 1, 6),
        datetime(2026, 10, 8, tzinfo=UTC),
        splits,
        distributions,
    )
    return captured, actions


def test_two_for_one_normalizes_prior_features_not_execution_or_cash():
    captured, actions = inputs((CapitalSplit(date(2023, 1, 4), Decimal("2"), "d" * 64),))
    result = capital_split_feature_bars(
        captured, calendar(), actions, as_of_session=date(2023, 1, 4)
    )
    assert result.raw_bars[0].open == Decimal("20")
    assert result.feature_bars[0].open == Decimal("10")
    assert result.feature_bars[0].close == Decimal("11")
    assert result.feature_bars[0].volume == Decimal("200")
    assert result.feature_bars[1].volume == Decimal("100")
    assert result.raw_bars[0].instrument_id == "QQQ"
    assert result.source_qualified is result.evidence_promotable is False
    assert result.execution_enabled is False


def test_future_effective_split_is_not_used_in_prior_feature_slice():
    captured, actions = inputs((CapitalSplit(date(2023, 1, 5), Decimal("2"), "d" * 64),))
    result = capital_split_feature_bars(
        captured, calendar(), actions, as_of_session=date(2023, 1, 4)
    )
    assert result.feature_bars[0].close == Decimal("22")
    assert "announcement_and_correction_chronology_unknown" in result.limitations


def test_distribution_cash_is_not_subtracted_from_feature_prices():
    dividend = CapitalDistribution(
        date(2023, 1, 4), date(2023, 1, 5), date(2023, 2, 10), Decimal("1"), "d" * 64
    )
    captured, actions = inputs(distributions=(dividend,))
    result = capital_split_feature_bars(
        captured, calendar(), actions, as_of_session=date(2023, 1, 4)
    )
    assert result.feature_bars[0].close == Decimal("22")
    assert result.distributions == (dividend,)


def test_missing_actions_or_prior_session_cannot_produce_feature_slice():
    captured, actions = inputs(splits=None)
    with pytest.raises(ValueError):
        capital_split_feature_bars(captured, calendar(), actions, as_of_session=date(2023, 1, 4))
    captured, actions = inputs()
    with pytest.raises(ValueError):
        capital_split_feature_bars(captured, calendar(), actions, as_of_session=date(2023, 1, 5))


def test_action_effectivity_without_declared_session_is_denied():
    captured, actions = inputs((CapitalSplit(date(2023, 1, 5), Decimal("2"), "d" * 64),))
    declared = calendar()
    declared = replace(declared, sessions=declared.sessions[:2])
    with pytest.raises(ValueError):
        capital_split_feature_bars(captured, declared, actions, as_of_session=date(2023, 1, 4))
