"""Matched exploratory references never become strategy or executable evidence."""

import hashlib
import importlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from tests.unit.market_data.test_etf_calendar import parse, wire
from tests.unit.market_data.test_etf_issuer_distributions import _ROW, _pack, _parts
from tests.unit.research.test_etf_latest_vintage import archive
from tests.unit.simulation.test_etf_history import study
from trading_bot.market_data.etf_issuer_distributions import parse_spy_issuer_distributions
from trading_bot.market_data.etf_source import _ns
from trading_bot.simulation.etf_history import _policy


def api():
    try:
        return importlib.import_module("trading_bot.research.etf_benchmark_screen")
    except ModuleNotFoundError:
        pytest.fail("Matched ETF benchmark screen is missing")


def inputs(count=None):
    # Explicit fixture dates, not a real exchange-calendar claim.
    days = []
    at = datetime(2016, 1, 4, 5, tzinfo=UTC)
    while at.year <= 2025 and (count is None or len(days) < count):
        if at.weekday() < 5:
            days.append(at)
        at += timedelta(days=1)
    source = archive(len(days))
    source = replace(
        source,
        bars=tuple(
            replace(
                row,
                timestamp_ns=_ns(
                    datetime.combine(
                        day.date(), datetime.min.time(), ZoneInfo("America/New_York")
                    ).astimezone(UTC)
                ),
            )
            for row, day in zip(source.bars, days, strict=True)
        ),
    )
    calendar = parse(
        wire(
            [
                {
                    "date": day.date().isoformat(),
                    "open": day.date().isoformat() + "T09:30:00",
                    "close": day.date().isoformat() + "T16:00:00",
                }
                for day in days
            ]
        )
    )
    rows = []
    for year in range(2016, 2026):
        for month in (3, 6, 9, 12):
            row = list(_ROW)
            ex_date = date(year, month, 15)
            while ex_date.weekday() >= 5:
                ex_date += timedelta(days=1)
            row[3] = ex_date.strftime("%m/%d/%Y")
            row[4] = (ex_date + timedelta(days=1)).strftime("%m/%d/%Y")
            row[5] = (ex_date + timedelta(days=5)).strftime("%m/%d/%Y")
            rows.append(tuple(row))
    body = _pack(_parts(tuple(rows)))
    issuer = parse_spy_issuer_distributions(
        body,
        hashlib.sha256(body).hexdigest(),
        start_date=date(2016, 1, 1),
        end_date=date(2025, 12, 31),
    )
    frozen = replace(
        study(),
        policy=_policy(study()),
        source_plan_hash=api().etf_benchmark_screen_plan_hash(source, calendar, issuer),
    )
    return api().EtfBenchmarkScreenRequest(frozen, source, calendar, issuer)


def test_fixed_all_scenarios_cash_tiers_and_unrealized_reference_labels():
    request = inputs()
    result = api().run_etf_benchmark_screen(request)
    development = sum(
        row.timestamp_ns < _ns(request.study.holdout_start) for row in request.archive.bars
    )
    assert result.evaluation_records == development - 750
    assert result.retained_holdout_records == len(request.archive.bars) - development
    assert len(result.scenarios) == 12
    assert {r.initial_cash for r in result.scenarios} == {500, 1000}
    assert {r.reference for r in result.scenarios} == {
        "exposure_capped_buy_hold",
        "fully_invested_unauthorized_reference",
    }
    assert all(r.terminal_shares > 0 for r in result.scenarios)
    assert all(r.realized_trading_pnl is None for r in result.scenarios)
    assert result.economic_verdict == "ECONOMIC_NO_GO"
    assert result.admitted_orders == 0
    assert not result.execution_enabled and not result.evidence_promotable
    assert "candidate_after_cost_outcomes_unavailable" in result.reasons


def test_changed_future_holdout_prices_do_not_change_development_reference():
    request = inputs()
    source = request.archive
    future = source.bars[-1]
    first = api().run_etf_benchmark_screen(request)
    changed = replace(
        source,
        bars=(
            *source.bars[:-1],
            replace(future, open=Decimal(1), low=Decimal(1), close=Decimal(1)),
        ),
    )
    frozen = replace(
        request.study,
        policy=_policy(request.study),
        source_plan_hash=api().etf_benchmark_screen_plan_hash(
            changed, request.calendar, request.issuer
        ),
    )
    second = api().run_etf_benchmark_screen(
        api().EtfBenchmarkScreenRequest(frozen, changed, request.calendar, request.issuer)
    )
    assert first.scenarios == second.scenarios
    assert first.retained_holdout_records == second.retained_holdout_records > 0


def test_incomplete_or_mismatched_dates_and_source_identity_deny():
    request = inputs()
    with pytest.raises(ValueError, match="etf_benchmark_screen_invalid"):
        api().run_etf_benchmark_screen(
            replace(
                request, calendar=replace(request.calendar, sessions=request.calendar.sessions[1:])
            )
        )
    with pytest.raises(ValueError, match="etf_benchmark_screen_invalid"):
        replace(request, study=study())
    with pytest.raises(ValueError, match="etf_benchmark_screen_invalid"):
        inputs(100)


def test_matching_truncated_price_and_calendar_packages_do_not_pass_full_window():
    with pytest.raises(ValueError, match="etf_benchmark_screen_invalid"):
        inputs(760)
