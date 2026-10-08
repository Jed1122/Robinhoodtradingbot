"""Full native inventory admission with only fabricated prices and provenance."""

import importlib
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tests.fixtures.etf.monthly.fixtures import legacy_package
from tests.unit.research.test_etf_daily_intake import altered_issuer
from tests.unit.research.test_etf_monthly_study import study


def api():
    return importlib.import_module("trading_bot.research.etf_monthly_intake")


def frozen(p):
    return study(
        source_plan_hash=api().etf_monthly_source_plan_hash(p.archive, p.calendar, p.issuer)
    )


def test_monthly_projection_excludes_holdout_and_preserves_full_source_identity():
    p = legacy_package()
    req = api().make_etf_monthly_request(frozen(p), p.archive, p.calendar, p.issuer)
    assert req.protocol.first_rebalance == date(2016, 10, 31)
    assert all(r.session_date < date(2024, 1, 1) for r in req.bars)
    assert all(d.ex_date < date(2024, 1, 1) for d in req.distributions)
    assert req.protocol.month_end_sessions[-1] == date(2023, 12, 29)
    assert len(req.protocol.month_end_sessions) == 96
    assert req.protocol.first_evaluation_session == date(2016, 11, 1)
    last = p.archive.bars[-1]
    future = replace(
        last, open=Decimal("1"), high=Decimal("3"), low=Decimal(".5"), close=Decimal("2")
    )
    p2 = replace(
        p,
        archive=replace(p.archive, bars=(*p.archive.bars[:-1], future)),
        study=replace(
            p.study,
            policy=importlib.import_module("trading_bot.simulation.etf_history")._policy(p.study),
            source_plan_hash=importlib.import_module(
                "trading_bot.research.etf_benchmark_screen"
            ).etf_benchmark_screen_plan_hash(
                replace(p.archive, bars=(*p.archive.bars[:-1], future)), p.calendar, p.issuer
            ),
        ),
    )
    req2 = api().make_etf_monthly_request(frozen(p2), p2.archive, p2.calendar, p2.issuer)
    assert req2.bars == req.bars and req2.distributions == req.distributions
    assert req2.protocol.study.source_plan_hash != req.protocol.study.source_plan_hash
    assert req.live_authorized is req.cost_qualified is False
    assert req.bars[50].raw.ends_at == p.calendar.sessions[50].closes_at


@pytest.mark.parametrize("change", ["prices", "calendar", "quarter", "wrong_plan", "flags"])
def test_incomplete_inventory_or_unsupported_source_denies(change):
    p = legacy_package()
    archive, calendar, issuer = p.archive, p.calendar, p.issuer
    if change == "prices":
        archive = replace(archive, bars=archive.bars[:760])
    elif change == "calendar":
        calendar = replace(calendar, sessions=calendar.sessions[1:])
    elif change == "quarter":
        issuer = altered_issuer(issuer, issuer.distributions[:-1])
    s = study(source_plan_hash=api().etf_monthly_source_plan_hash(archive, calendar, issuer))
    if change == "wrong_plan":
        s = study()
    elif change == "flags":
        object.__setattr__(archive, "source_qualified", True)
    with pytest.raises(ValueError, match="etf_monthly_invalid"):
        api().make_etf_monthly_request(s, archive, calendar, issuer)


def test_declared_early_close_is_preserved_without_standard_close_substitution():
    p = legacy_package()
    early_day = date(2016, 11, 25)
    calendar = replace(
        p.calendar,
        sessions=tuple(
            replace(row, closes_at=datetime(2016, 11, 25, 18, tzinfo=UTC))
            if row.session_date == early_day
            else row
            for row in p.calendar.sessions
        ),
    )
    s = study(source_plan_hash=api().etf_monthly_source_plan_hash(p.archive, calendar, p.issuer))
    req = api().make_etf_monthly_request(s, p.archive, calendar, p.issuer)
    row = next(row for row in req.bars if row.session_date == early_day)
    assert row.raw.ends_at == datetime(2016, 11, 25, 18, tzinfo=UTC)
    assert row.raw.starts_at == datetime(2016, 11, 25, 14, 30, tzinfo=UTC)
