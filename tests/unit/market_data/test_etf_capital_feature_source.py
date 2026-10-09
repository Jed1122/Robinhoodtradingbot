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


def test_owned_raw_rows_preserve_complete_fields_hashes_and_original_date_basis():
    from trading_bot.market_data.etf_capital_features import (
        _capital_feature_source,
        _capital_features_at,
        _capital_owned_raw_source,
    )

    dataset = long_source(12)
    days = tuple(row.session_date for row in dataset.calendar.sessions)
    actions = replace(dataset.actions[0], splits=(CapitalSplit(days[5], D(3), "e" * 64),))
    source = _capital_feature_source(
        dataset.archives[0], dataset.calendar, actions, as_of_session=days[0]
    )
    owned = _capital_owned_raw_source(source)
    for day in (days[0], days[5], days[-1]):
        expected = _capital_features_at(source, as_of_session=day)
        actual = _capital_features_at(owned, as_of_session=day)
        assert actual == expected
        assert actual.projection_hash == expected.projection_hash


def test_owned_preparation_raw_build_count_does_not_grow_with_requested_prefixes(monkeypatch):
    import trading_bot.market_data.etf_capital_features as module
    from trading_bot.research.etf_capital_prepared import _prepare_capital_days

    build = module._capital_raw_bar
    calls = []

    def observed(*args):
        calls.append(1)
        return build(*args)

    monkeypatch.setattr(module, "_capital_raw_bar", observed)
    dataset = long_source(12)
    days = tuple(row.session_date for row in dataset.calendar.sessions)
    calls.clear()
    _prepare_capital_days(dataset, sessions=(days[-1],))
    one = len(calls)
    calls.clear()
    _prepare_capital_days(dataset, sessions=days)
    assert len(calls) == one
    assert one > 0


def test_public_early_asof_still_skips_future_native_zero_prices():
    dataset = long_source(4)
    archive = dataset.archives[0]
    rows = archive.pages[0].records
    zero = replace(rows[-1].bar, open=D(0), high=D(0), low=D(0), close=D(0), vwap=D(0))
    changed = replace(
        archive,
        pages=(replace(archive.pages[0], records=(*rows[:-1], replace(rows[-1], bar=zero))),),
    )
    days = tuple(row.session_date for row in dataset.calendar.sessions)
    first = capital_split_feature_bars(
        changed, dataset.calendar, dataset.actions[0], as_of_session=days[0]
    )
    assert len(first.raw_bars) == 1 and first.raw_bars[0].close == D(100)
    with pytest.raises(ValueError):
        capital_split_feature_bars(
            changed, dataset.calendar, dataset.actions[0], as_of_session=days[-1]
        )
