"""Saved-input daily projection is synthetic here and never execution evidence."""

import importlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from tests.unit.research.test_etf_benchmark_screen import inputs
from trading_bot.domain import BarInterval
from trading_bot.market_data.alpaca_native import AlpacaStockRequest
from trading_bot.market_data.etf_issuer_distributions import _archive_hash
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.etf_history import _policy

D = Decimal
BOUNDARY = date(2024, 1, 1)


def api():
    try:
        return importlib.import_module("trading_bot.research.etf_daily_intake")
    except ModuleNotFoundError:
        pytest.fail("Daily ETF saved-input intake is missing")


def frozen(package, *, archive=None, calendar=None, issuer=None):
    source = package.archive if archive is None else archive
    sessions = package.calendar if calendar is None else calendar
    actions = package.issuer if issuer is None else issuer
    return replace(
        package.study,
        policy=_policy(package.study),
        source_plan_hash=api().etf_daily_source_plan_hash(source, sessions, actions),
    )


def altered_issuer(original, rows):
    return replace(
        original,
        distributions=rows,
        archive_hash=_archive_hash(
            original.source_hash,
            original.start_date,
            original.end_date,
            rows,
            original.excluded_spy_rows,
            original.limitations,
        ),
    )


def test_projection_uses_calendar_session_times_and_identical_raw_feature_prices():
    module = api()
    package = inputs()
    study = frozen(package)
    result = module.make_etf_daily_request(study, package.archive, package.calendar, package.issuer)
    expected_sessions = tuple(s for s in package.calendar.sessions if s.session_date < BOUNDARY)
    expected_rows = tuple(
        row for row in package.archive.bars if row.timestamp_ns < _ns(study.holdout_start)
    )
    assert tuple(row.session_date for row in result.bars) == tuple(
        session.session_date for session in expected_sessions
    )
    assert result.protocol.sessions == tuple(s.session_date for s in expected_sessions)
    assert len(result.bars) == len(expected_rows) < len(package.archive.bars)
    for projected, raw, session in zip(result.bars, expected_rows, expected_sessions, strict=True):
        assert projected.raw == projected.feature
        assert projected.raw.starts_at == session.opens_at
        assert projected.raw.ends_at == session.closes_at
        assert projected.raw.interval is BarInterval.ONE_DAY
        assert projected.raw.instrument_id == "SPY"
        assert projected.raw.interpolated is False
        assert (projected.raw.open, projected.raw.high, projected.raw.low, projected.raw.close) == (
            raw.open,
            raw.high,
            raw.low,
            raw.close,
        )
        assert projected.raw.volume == D(raw.volume)
        assert projected.source_qualified is False and projected.evidence_promotable is False
    assert result.protocol.study.source_plan_hash == study.source_plan_hash
    assert result.protocol.first_rebalance == date(2016, 5, 26)
    assert result.protocol.warmup_bars == 100 and result.protocol.rebalance_sessions == 5
    assert result.protocol.price_basis == "raw-unadjusted-assumption"
    assert result.protocol.fractional_terms_verified is False
    for record in (result, result.protocol):
        assert record.source_qualified is False and record.cost_qualified is False
        assert record.execution_enabled is False and record.economic_admitted is False
        assert record.evidence_promotable is False
    assert tuple(row.ex_date for row in result.distributions) == tuple(
        row.ex_date for row in package.issuer.distributions if row.ex_date < BOUNDARY
    )
    assert all(day < BOUNDARY for day in result.protocol.sessions)


def test_missing_calendar_session_is_denied_even_with_valid_source_hashes():
    module = api()
    package = inputs()
    calendar = replace(package.calendar, sessions=package.calendar.sessions[1:])
    with pytest.raises(ValueError):
        module.make_etf_daily_request(
            frozen(package, calendar=calendar), package.archive, calendar, package.issuer
        )


def test_equally_truncated_price_calendar_packages_do_not_pass_full_window_admission():
    module = api()
    package = inputs()
    source = replace(package.archive, bars=package.archive.bars[:760])
    calendar = replace(package.calendar, sessions=package.calendar.sessions[:760])
    with pytest.raises(ValueError):
        module.make_etf_daily_request(
            frozen(package, archive=source, calendar=calendar), source, calendar, package.issuer
        )


def test_study_source_plan_hash_must_match_this_projection_not_the_old_benchmark():
    module = api()
    package = inputs()
    with pytest.raises(ValueError):
        module.make_etf_daily_request(
            package.study, package.archive, package.calendar, package.issuer
        )
    wrong = replace(frozen(package), policy=_policy(package.study), source_plan_hash="0" * 64)
    with pytest.raises(ValueError):
        module.make_etf_daily_request(wrong, package.archive, package.calendar, package.issuer)


@pytest.mark.parametrize("removed", [0, 20, 39])
def test_missing_issuer_quarter_denies_including_an_inventory_only_holdout_quarter(removed):
    module = api()
    package = inputs()
    rows = tuple(row for i, row in enumerate(package.issuer.distributions) if i != removed)
    issuer = altered_issuer(package.issuer, rows)
    with pytest.raises(ValueError):
        module.make_etf_daily_request(
            frozen(package, issuer=issuer), package.archive, package.calendar, issuer
        )


def test_forty_issuer_rows_cannot_hide_a_missing_quarter_with_an_extra_same_quarter_row():
    module = api()
    package = inputs()
    first = package.issuer.distributions[0]
    extra = replace(
        first,
        ex_date=first.ex_date + timedelta(days=7),
        record_date=first.record_date + timedelta(days=7),
        pay_date=first.pay_date + timedelta(days=7),
        row_hash=content_hash("synthetic-extra-quarter-row"),
    )
    rows = (first, extra, *package.issuer.distributions[2:])
    issuer = altered_issuer(package.issuer, rows)
    assert len(issuer.distributions) == 40
    with pytest.raises(ValueError):
        module.make_etf_daily_request(
            frozen(package, issuer=issuer), package.archive, package.calendar, issuer
        )


def test_issuer_ex_date_missing_from_full_calendar_denies_action_projection():
    module = api()
    package = inputs()
    first = package.issuer.distributions[0]
    shifted = replace(
        first,
        ex_date=date(2016, 3, 19),
        record_date=date(2016, 3, 20),
        pay_date=date(2016, 3, 24),
        row_hash=content_hash("synthetic-weekend-ex-date"),
    )
    issuer = altered_issuer(package.issuer, (shifted, *package.issuer.distributions[1:]))
    with pytest.raises(ValueError):
        module.make_etf_daily_request(
            frozen(package, issuer=issuer), package.archive, package.calendar, issuer
        )


def test_changed_valid_holdout_prices_change_source_identity_not_development_projection():
    module = api()
    package = inputs()
    first = module.make_etf_daily_request(
        frozen(package), package.archive, package.calendar, package.issuer
    )
    last = package.archive.bars[-1]
    future = replace(last, open=D("1"), high=D("3"), low=D(".5"), close=D("2"))
    changed = replace(package.archive, bars=(*package.archive.bars[:-1], future))
    revised_study = frozen(package, archive=changed)
    assert revised_study.source_plan_hash != first.protocol.study.source_plan_hash
    second = module.make_etf_daily_request(revised_study, changed, package.calendar, package.issuer)
    assert first.bars == second.bars
    assert first.protocol.sessions == second.protocol.sessions
    assert first.distributions == second.distributions
    assert all(row.session_date < BOUNDARY for row in second.bars)


class AdjustedStockRequest(AlpacaStockRequest):
    """Fabricated incompatible request; no method performs a transport call."""

    def query(self, page_token=None):
        return tuple(
            (key, "all" if key == "adjustment" else value)
            for key, value in super().query(page_token)
        )


def test_source_with_unsupported_adjustment_request_is_not_labeled_raw():
    module = api()
    package = inputs()
    request = package.archive.request
    unsupported = AdjustedStockRequest(
        request.kind, request.start_ns, request.end_ns, request.limit
    )
    assert dict(unsupported.query())["adjustment"] == "all"
    source = replace(package.archive, request=unsupported)
    with pytest.raises(ValueError):
        module.make_etf_daily_request(
            frozen(package, archive=source), source, package.calendar, package.issuer
        )


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "quotes"},
        {"start_ns": _ns(datetime(2017, 1, 1, tzinfo=UTC))},
        {"end_ns": _ns(datetime(2025, 1, 1, tzinfo=UTC))},
    ],
)
def test_non_bar_or_non_full_window_native_requests_deny(change):
    module = api()
    package = inputs()
    source = replace(package.archive, request=replace(package.archive.request, **change))
    with pytest.raises(ValueError):
        module.make_etf_daily_request(
            frozen(package, archive=source), source, package.calendar, package.issuer
        )
