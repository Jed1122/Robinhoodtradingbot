"""Observed preparation owns originals and reuses the declared signal kernels."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from tests.unit.config.test_capital_research import capital_loaded
from tests.unit.market_data.test_etf_capital_observed import observed_dataset
from tests.unit.market_data.test_etf_capital_owned import ForbiddenOffset, dataclass_ids
from trading_bot.market_data.alpaca_capital_native import parse_capital_daily_page
from trading_bot.market_data.etf_calendar import EtfCalendarSession
from trading_bot.market_data.etf_capital_observed import (
    build_capital_observed_dataset,
    capital_observed_features,
)
from trading_bot.research.etf_capital_protocol import CapitalStudyProtocol
from trading_bot.research.etf_capital_signals import capital_candidates, capital_strategy_signal


def own(source):
    from trading_bot.market_data import etf_capital_owned as module

    assert hasattr(module, "_own_capital_observed_source"), "observed ownership is missing"
    return module._own_capital_observed_source(source)


def prepare(source, sessions):
    from trading_bot.research import etf_capital_prepared as module

    assert hasattr(module, "_prepare_capital_observed_days"), "observed preparation is missing"
    return module._prepare_capital_observed_days(source, sessions=sessions)


def observed_long_source(count=715, *, last_close=None):
    source = observed_dataset()
    dates = []
    day = date(2023, 1, 3)
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day += timedelta(days=1)
    zone = ZoneInfo("America/New_York")
    calendar = replace(
        source.calendar,
        sessions=tuple(
            EtfCalendarSession(
                day,
                datetime.combine(day, time(9, 30), zone).astimezone(UTC),
                datetime.combine(day, time(16), zone).astimezone(UTC),
            )
            for day in dates
        ),
    )
    archives = []
    for archive in source.archives:
        request = replace(archive.request, limit=1000)
        rows = [dict(t="2022-12-30T05:00:00Z", o=30, h=40, l=1, c=30, v=100, n=1, vw=30)]
        for i, day in enumerate(dates):
            close = last_close if i == count - 1 and last_close is not None else 100 + i
            rows.append(
                dict(
                    t=datetime.combine(day, time(), zone).astimezone(UTC).isoformat(),
                    o=close,
                    h=close + 2,
                    l=close - 2,
                    c=close,
                    v=100,
                    n=1,
                    vw=close,
                )
            )
        raw = json.dumps({"symbol": request.symbol, "bars": rows, "next_page_token": None}).encode()
        page = parse_capital_daily_page(
            raw, request=request, expected_sha256=hashlib.sha256(raw).hexdigest()
        )
        archives.append(
            replace(archive, request=request, pages=(page,), received_at=archive.received_at[:1])
        )
    return build_capital_observed_dataset(
        loaded=capital_loaded(), archives=tuple(archives), actions=source.actions, calendar=calendar
    )


def test_observed_owner_detaches_every_node_including_action_model_and_excluded_originals():
    source = observed_dataset()
    owned = own(source)
    assert owned.dataset.dataset_hash == source.dataset_hash
    assert not dataclass_ids(source) & dataclass_ids(owned.dataset)
    assert owned.source_hash != source.dataset_hash
    original_hash = owned.dataset.dataset_hash
    object.__setattr__(source.action_model, "terms_qualified", True)
    object.__setattr__(source.archives[0], "manifest_hash", "f" * 64)
    assert owned.dataset.dataset_hash == original_hash
    assert owned.dataset.action_model.terms_qualified is False
    assert owned.dataset.archives[0].pages[0].records[0].bar.close == D(30)


@pytest.mark.parametrize(
    "fault", ["dataset", "model", "page", "excluded_bar", "calendar", "action"]
)
def test_observed_owner_rejects_original_flags_before_copy_resets_them(fault):
    source = observed_dataset()
    target, field, value = {
        "dataset": (source, "execution_enabled", True),
        "model": (source.action_model, "terms_qualified", True),
        "page": (source.archives[0].pages[0], "source_qualified", True),
        "excluded_bar": (source.archives[0].pages[0].records[0].bar, "publication_at_ns", 1),
        "calendar": (source.calendar, "source_qualified", True),
        "action": (source.actions[0], "source_qualified", True),
    }[fault]
    object.__setattr__(target, field, value)
    with pytest.raises(ValueError):
        own(source)


@pytest.mark.parametrize("fault", ["receipt", "session", "action"])
def test_observed_owner_denies_timezone_hooks_without_calling_them(fault):
    source = observed_dataset()
    if fault == "receipt":
        archive = source.archives[0]
        object.__setattr__(
            archive, "received_at", (archive.received_at[0].replace(tzinfo=ForbiddenOffset()),) * 2
        )
    else:
        target = source.calendar.sessions[0] if fault == "session" else source.actions[0]
        field = "opens_at" if fault == "session" else "received_at"
        object.__setattr__(target, field, getattr(target, field).replace(tzinfo=ForbiddenOffset()))
    with pytest.raises(ValueError):
        own(source)


def test_source_mutation_during_observed_copy_is_not_admitted(monkeypatch):
    from trading_bot.market_data import etf_capital_owned as module

    source = observed_dataset()
    actual = module.replace

    def change(record, **values):
        if record is source.action_model:
            object.__setattr__(source.archives[0], "manifest_hash", "f" * 64)
        return actual(record, **values)

    monkeypatch.setattr(module, "replace", change)
    with pytest.raises(ValueError):
        own(source)


def test_preparation_reads_all_selected_days_not_just_first_day_or_excluded_prefix():
    source = observed_dataset()
    dates = tuple(row.session_date for row in source.calendar.sessions)
    result = prepare(source, dates)
    assert tuple(d.session_ordinal for d in result.days) == (0, 1, 2)
    assert tuple(d.raw_bars[0].close for d in result.days) == (D(22), D(11), D(13))
    assert all(not d.history_ready for d in result.days)
    assert all(not d.source_qualified and not d.evidence_promotable for d in result.days)


def test_observed_prepared_and_legacy_owned_types_are_not_interchangeable():
    from tests.unit.market_data.test_etf_capital_dataset import dataset
    from trading_bot.market_data.etf_capital_owned import _own_capital_source
    from trading_bot.research.etf_capital_prepared import (
        _prepare_capital_days,
        _prepare_owned_capital_days,
        _validate_owned_capital_days,
    )

    source = observed_dataset()
    dates = tuple(row.session_date for row in source.calendar.sessions)
    result = prepare(source, dates)
    observed = own(source)
    legacy = _own_capital_source(dataset())
    _validate_owned_capital_days(observed, result, required_sessions=dates, exact=True)
    for invalid in (source, result, observed):
        with pytest.raises(ValueError):
            _prepare_capital_days(invalid, sessions=dates)
    for invalid in (dataset(), result, observed):
        with pytest.raises(ValueError):
            prepare(invalid, dates)
    with pytest.raises(ValueError):
        _validate_owned_capital_days(legacy, result, required_sessions=dates)
    object.__setattr__(observed, "dataset", legacy.dataset)
    with pytest.raises(ValueError):
        _prepare_owned_capital_days(observed, sessions=dates)


def test_short_history_readiness_and_later_training_keep_elapsed_prior_history():
    source = observed_long_source()
    dates = tuple(row.session_date for row in source.calendar.sessions)
    result = prepare(source, dates[:568])
    by_date = {d.session: d for d in result.days}
    assert by_date[dates[198]].history_ready is False
    assert by_date[dates[199]].history_ready is True
    folds = CapitalStudyProtocol("observed-252x84-v2").folds(dates)
    assert tuple(sum(by_date[d].history_ready for d in f.selection_sessions) for f in folds) == (
        33,
        117,
        201,
        232,
        232,
    )
    for index in (198, 199, 232, 567):
        day = by_date[dates[index]]
        full = capital_observed_features(source, as_of_session=dates[index])
        assert day.signals == tuple(
            capital_strategy_signal(c, full, config_hash=source.config_hash, as_of=day.as_of)
            for c in capital_candidates()
        )
        assert all(
            distance == (D(8) if index >= 199 else None) for _, distance in day.stop_distances
        )


def test_future_prices_change_provenance_not_earlier_signal_values():
    first, changed = observed_long_source(201), observed_long_source(201, last_close=900)
    day = first.calendar.sessions[199].session_date
    before, after = prepare(first, (day,)), prepare(changed, (day,))
    assert before.source_hash != after.source_hash
    assert tuple(b.close for b in before.days[0].raw_bars) == tuple(
        b.close for b in after.days[0].raw_bars
    )
    assert before.days[0].stop_distances == after.days[0].stop_distances
    assert tuple((s.entry_symbol, s.candidate) for s in before.days[0].signals) == tuple(
        (s.entry_symbol, s.candidate) for s in after.days[0].signals
    )


def test_excluded_original_identity_changes_owned_preparation_not_selected_prices():
    source = observed_dataset()
    dates = tuple(row.session_date for row in source.calendar.sessions)
    before = prepare(source, dates)
    object.__setattr__(source.archives[0], "manifest_hash", "e" * 64)
    after = prepare(source, dates)
    assert before.source_hash != after.source_hash
    assert tuple(d.raw_bars for d in before.days) == tuple(d.raw_bars for d in after.days)
