"""Observed ranges select original records, never manufacture source receipts."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, Inexact, localcontext
from importlib import import_module, util
from typing import Any

import pytest

from tests.unit.config.test_capital_research import capital_loaded
from tests.unit.market_data.test_etf_capital_features import inputs
from tests.unit.market_data.test_etf_capital_inventory import calendar
from trading_bot.market_data.alpaca_capital_native import (
    CapitalDailyRequest,
    parse_capital_daily_page,
)
from trading_bot.market_data.etf_calendar import EtfCalendarArchive
from trading_bot.market_data.etf_capital_actions import (
    CapitalActionArchive,
    CapitalDistribution,
    CapitalSplit,
)
from trading_bot.market_data.etf_capital_archive import CapitalDailyArchive
from trading_bot.market_data.etf_capital_dataset import build_capital_dataset
from trading_bot.market_data.etf_capital_features import capital_split_feature_bars
from trading_bot.market_data.etf_capital_inventory import capital_daily_inventory
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import canonical_json


def api() -> Any:
    name = "trading_bot.market_data.etf_capital_observed"
    assert util.find_spec(name) is not None, "observed range admission is not implemented"
    return import_module(name)


def originals(symbol: str = "QQQ", *, before_price: int = 30, missing: bool = False):
    request = CapitalDailyRequest(
        symbol,
        _ns(datetime(2022, 1, 1, tzinfo=UTC)),
        _ns(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    rows = [
        dict(t="2022-12-30T05:00:00Z", o=before_price, h=40, l=1, c=30, v=100, n=1, vw=30),
        dict(t="2023-01-03T05:00:00Z", o=20, h=24, l=18, c=22, v=100, n=1, vw=21),
        dict(t="2023-01-04T05:00:00Z", o=10, h=12, l=9, c=11, v=100, n=1, vw=10),
        dict(t="2023-01-06T05:00:00Z", o=12, h=15, l=10, c=13, v=100, n=1, vw=12),
    ]
    if missing:
        rows.pop(2)
    pages = []
    for i, chunk in enumerate((rows[:2], rows[2:])):
        body = json.dumps(
            {"symbol": symbol, "bars": chunk, "next_page_token": "next" if i == 0 else None}
        ).encode()
        pages.append(
            parse_capital_daily_page(
                body,
                request=request,
                expected_sha256=hashlib.sha256(body).hexdigest(),
                page_index=i,
                requested_page_token=None if i == 0 else "next",
            )
        )
    return CapitalDailyArchive(
        "a" * 64,
        request,
        tuple(pages),
        (datetime(2026, 10, 8, tzinfo=UTC), datetime(2026, 10, 8, tzinfo=UTC)),
    )


def selected_calendar() -> EtfCalendarArchive:
    return replace(calendar(), sessions=calendar().sessions[:2])


def view(archive=None, *, declared=None, start=date(2023, 1, 3), end=date(2023, 1, 6)):
    return api().CapitalDailyRangeView(
        originals() if archive is None else archive,
        selected_calendar() if declared is None else declared,
        start,
        end,
    )


def observed_dataset(*, splits=(), distributions=()):
    declared = selected_calendar()
    # The full observed study range selects every supplied calendar date.
    # The narrow range-view fixture's Jan6 suffix must therefore be included.
    last = replace(
        declared.sessions[-1],
        session_date=date(2023, 1, 6),
        opens_at=datetime(2023, 1, 6, 14, 30, tzinfo=UTC),
        closes_at=datetime(2023, 1, 6, 21, tzinfo=UTC),
    )
    declared = replace(declared, sessions=(*declared.sessions, last))
    archives = tuple(originals(s) for s in ("SPY", "QQQ", "IWM", "SHY", "IEF"))
    actions = tuple(
        CapitalActionArchive(
            s,
            "c" * 64,
            date(2023, 1, 1),
            date(2026, 1, 1),
            datetime(2026, 10, 8, tzinfo=UTC),
            splits,
            distributions,
        )
        for s in ("SPY", "QQQ", "IWM", "SHY", "IEF")
    )
    return api().build_capital_observed_dataset(
        loaded=capital_loaded(), archives=archives, actions=actions, calendar=declared
    )


def test_range_keeps_original_archive_pages_and_selected_record_origins():
    archive = originals()
    before = canonical_json(archive)
    result = view(archive)
    assert result.archive is archive
    assert result.selected_records == (archive.pages[0].records[1], archive.pages[1].records[0])
    assert [
        (r.bar.body_sha256, r.bar.page_index, r.bar.row_index) for r in result.selected_records
    ] == [(archive.pages[0].body_sha256, 0, 1), (archive.pages[1].body_sha256, 1, 0)]
    assert canonical_json(archive) == before
    assert result.source_qualified is result.evidence_promotable is False
    assert result.view_hash != archive.archive_hash
    with pytest.raises(ValueError):
        capital_daily_inventory(
            (archive,), selected_calendar(), start=date(2023, 1, 3), end=date(2023, 1, 6)
        )


def test_excluded_originals_and_selection_bounds_remain_in_provenance():
    first = view()
    changed = view(originals(before_price=31))
    assert first.view_hash != changed.view_hash
    assert first.archive.archive_hash != changed.archive.archive_hash
    assert first.view_hash != view(start=date(2023, 1, 2)).view_hash
    assert (
        first.view_hash
        != view(declared=replace(selected_calendar(), source_hash="d" * 64)).view_hash
    )


@pytest.mark.parametrize("fault", ["missing", "pagination", "containment", "duplicate"])
def test_missing_selected_rows_or_incomplete_originals_deny(fault):
    archive = originals(missing=fault == "missing")
    if fault == "pagination":
        archive = replace(
            archive, pages=(*archive.pages[:-1], replace(archive.pages[-1], next_page_token="more"))
        )
    elif fault == "containment":
        # Original response remains valid; requested view starts before it.
        with pytest.raises(ValueError):
            view(archive, start=date(2021, 12, 31))
        return
    elif fault == "duplicate":
        object.__setattr__(
            archive.pages[1].records[0].bar,
            "timestamp_ns",
            archive.pages[0].records[-1].bar.timestamp_ns,
        )
    with pytest.raises(ValueError):
        view(archive)


@pytest.mark.parametrize("fault", ["publication", "price", "page_flag", "calendar_flag", "clock"])
def test_bad_excluded_original_or_forged_flag_is_not_laundered(fault):
    archive, declared = originals(), selected_calendar()
    if fault == "publication":
        object.__setattr__(archive.pages[0].records[0].bar, "publication_at_ns", 1)
    elif fault == "price":
        object.__setattr__(archive.pages[0].records[0].bar, "high", Decimal("0"))
    elif fault == "page_flag":
        object.__setattr__(archive.pages[0], "source_qualified", True)
    elif fault == "calendar_flag":
        object.__setattr__(declared, "source_qualified", True)
    else:
        object.__setattr__(archive, "received_at", (datetime(2026, 10, 8),) * 2)
    with pytest.raises(ValueError):
        view(archive, declared=declared)


def test_observed_features_use_only_selected_originals_and_effective_splits():
    dataset = observed_dataset(splits=(CapitalSplit(date(2023, 1, 4), Decimal("2"), "d" * 64),))
    earlier = api().capital_observed_features(dataset, as_of_session=date(2023, 1, 3))[0]
    later = api().capital_observed_features(dataset, as_of_session=date(2023, 1, 4))[0]
    assert [b.close for b in earlier.raw_bars] == [Decimal("22")]
    assert [b.close for b in earlier.feature_bars] == [Decimal("22")]
    assert [b.close for b in later.raw_bars] == [Decimal("22"), Decimal("11")]
    assert [b.close for b in later.feature_bars] == [Decimal("11"), Decimal("11")]
    assert [b.volume for b in later.feature_bars] == [Decimal("200"), Decimal("100")]
    assert later.archive_hash == dataset.archives[0].archive_hash
    assert (
        dataset.source_qualified
        is dataset.evidence_promotable
        is dataset.execution_enabled
        is False
    )
    assert "conditional_on_no_unobserved_actions" in dataset.action_model.limitations
    with pytest.raises(ValueError):
        api().capital_observed_features(dataset, as_of_session=date(2023, 1, 5))


def test_equal_range_projection_preserves_legacy_bytes():
    archive, action = inputs((CapitalSplit(date(2023, 1, 4), Decimal("2"), "d" * 64),))
    selection = view(archive)
    result = api().capital_range_feature_bars(selection, action, as_of_session=date(2023, 1, 4))
    legacy = capital_split_feature_bars(
        archive, selected_calendar(), action, as_of_session=date(2023, 1, 4)
    )
    assert canonical_json(result) == canonical_json(legacy)


def test_observed_model_and_dataset_tampering_fail_at_consumption():
    dataset = observed_dataset()
    object.__setattr__(dataset.action_model, "limitations", ())
    with pytest.raises(ValueError):
        api().capital_observed_features(dataset, as_of_session=date(2023, 1, 3))
    dataset = observed_dataset()
    object.__setattr__(dataset, "source_qualified", True)
    with pytest.raises(ValueError):
        _ = dataset.dataset_hash


def test_observed_action_unknown_or_ambiguous_dates_stay_denied():
    with pytest.raises(ValueError):
        observed_dataset(splits=None)
    dividend = CapitalDistribution(
        date(2023, 1, 4), date(2023, 1, 4), date(2023, 1, 6), Decimal("1"), "d" * 64
    )
    with pytest.raises(ValueError):
        observed_dataset(distributions=(dividend, replace(dividend, record_hash="e" * 64)))
    object.__setattr__(dividend, "pay_date", None)
    with pytest.raises(ValueError):
        observed_dataset(distributions=(dividend,))


def test_observed_order_is_canonical_and_legacy_dataset_still_denies():
    dataset = observed_dataset()
    same = api().build_capital_observed_dataset(
        loaded=capital_loaded(),
        archives=tuple(reversed(dataset.archives)),
        actions=tuple(reversed(dataset.actions)),
        calendar=dataset.calendar,
    )
    assert dataset.dataset_hash == same.dataset_hash
    with pytest.raises(ValueError):
        build_capital_dataset(
            loaded=capital_loaded(),
            archives=dataset.archives,
            actions=dataset.actions,
            calendar=dataset.calendar,
            start=date(2023, 1, 1),
            end=date(2026, 1, 1),
        )
    with pytest.raises(ValueError):
        api().build_capital_observed_dataset(
            loaded=capital_loaded(),
            archives=(*dataset.archives[:-1], dataset.archives[0]),
            actions=dataset.actions,
            calendar=dataset.calendar,
        )


def test_observed_projection_owns_decimal_context():
    original = observed_dataset()
    expected = original.dataset_hash
    loaded = capital_loaded()
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.Emax = 1
        ctx.traps[Inexact] = True
        dataset = api().build_capital_observed_dataset(
            loaded=loaded,
            archives=original.archives,
            actions=original.actions,
            calendar=original.calendar,
        )
        assert dataset.dataset_hash == expected
        assert api().capital_observed_features(dataset, as_of_session=date(2023, 1, 3))[0].raw_bars[
            0
        ].close == Decimal("22")
