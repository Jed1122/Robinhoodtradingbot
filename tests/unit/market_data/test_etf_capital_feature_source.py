"""Shared full-asof builder, never caller-authoritative cached market evidence."""

from dataclasses import replace
from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_prepared import long_source
from trading_bot.market_data.etf_capital_actions import CapitalSplit
from trading_bot.market_data.etf_capital_features import capital_split_feature_bars


def test_source_preparation_preserves_complete_original_projection_fields_and_hashes():
    from trading_bot.market_data.etf_capital_features import (
        _capital_feature_source,
        _capital_features_at,
    )

    dataset = long_source(12)
    days = tuple(row.session_date for row in dataset.calendar.sessions)
    archive = dataset.archives[0]
    actions = replace(dataset.actions[0], splits=(CapitalSplit(days[5], D(3), "f" * 64),))
    source = _capital_feature_source(archive, dataset.calendar, actions, as_of_session=days[0])
    for day in (days[0], days[6], days[-1]):
        expected = capital_split_feature_bars(archive, dataset.calendar, actions, as_of_session=day)
        actual = _capital_features_at(source, as_of_session=day)
        assert actual == expected and actual.projection_hash == expected.projection_hash
    final = _capital_features_at(source, as_of_session=days[-1])
    assert final.feature_bars[0].close == D(
        "33.33333333333333333333333333333333333333333333333333333333333333"
    )
    assert final.raw_bars[0].close == D(100)
    assert final.feature_bars[-1].close == D(111)


def test_shared_builder_rejects_ancient_invalid_intermediate_basis_before_return():
    from trading_bot.market_data.etf_capital_features import (
        _capital_feature_source,
        _capital_features_at,
    )

    dataset = long_source(350, ancient=True)
    days = tuple(row.session_date for row in dataset.calendar.sessions)
    actions = replace(
        dataset.actions[0],
        splits=(
            CapitalSplit(days[299], D("1e-400"), "d" * 64),
            CapitalSplit(days[329], D("1e400"), "e" * 64),
        ),
    )
    source = _capital_feature_source(
        dataset.archives[0], dataset.calendar, actions, as_of_session=days[-1]
    )
    _capital_features_at(source, as_of_session=days[-1])
    with pytest.raises(ValueError):
        _capital_features_at(source, as_of_session=days[309])
