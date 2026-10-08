"""Calendar-selected monthly inputs remain causal, bounded and unqualified."""

import importlib
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tests.unit.research.test_etf_daily_protocol import daily_bar
from tests.unit.research.test_etf_monthly_study import study

D = Decimal


def api():
    return importlib.import_module("trading_bot.research.etf_monthly_protocol")


def sessions(end=date(2017, 2, 28)):
    days = []
    day = date(2016, 1, 4)
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return tuple(days)  # Fabricated calendar, not real exchange evidence.


def protocol(end=date(2017, 2, 28), **changes):
    p = api().EtfMonthlyProtocol(
        study(), sessions(end), "d" * 64, "e" * 64, "f" * 64, D("0"), D(".01"), D(".10")
    )
    return replace(p, **changes)


def request(end=date(2017, 2, 28), **changes):
    p = protocol(end)
    bars = tuple(daily_bar(day, D("100") + D(i) / 100, D("1")) for i, day in enumerate(p.sessions))
    return replace(api().EtfMonthlyRequest(p, bars, (), D("500")), **changes)


def test_fixed_monthly_protocol_anchor_and_first_evaluation():
    p = protocol()
    assert p.first_rebalance == date(2016, 10, 31)
    assert p.first_evaluation_session == date(2016, 11, 1)
    assert p.months == 10 and p.warmup_bars == 100 and p.settlement_sessions == 2
    assert p.month_end_sessions[:10] == (
        date(2016, 1, 29),
        date(2016, 2, 29),
        date(2016, 3, 31),
        date(2016, 4, 29),
        date(2016, 5, 31),
        date(2016, 6, 30),
        date(2016, 7, 29),
        date(2016, 8, 31),
        date(2016, 9, 30),
        date(2016, 10, 31),
    )
    assert replace(p) == p and len(p.protocol_hash) == 64
    assert p.live_authorized is p.source_qualified is p.execution_enabled is False


@pytest.mark.parametrize(
    "changes",
    [
        {"sessions": (*sessions()[1:], date(2024, 1, 2))},
        {"sessions": tuple(d for d in sessions() if d != date(2016, 10, 31))},
        {"sessions": (*sessions(), sessions()[-1])},
        {"sessions": sessions(date(2016, 9, 30))},
        {"side_fee": D(".06")},
        {"per_side_cost_bps": D("NaN")},
        {"calendar_hash": "private"},
        {"price_basis": "adjusted"},
    ],
)
def test_bad_protocol_denies_sanitized(changes):
    p = protocol()
    with pytest.raises(ValueError, match="etf_monthly_invalid"):
        replace(p, **changes)


@pytest.mark.parametrize(
    "marker",
    [
        "source_qualified",
        "cost_qualified",
        "execution_enabled",
        "economic_admitted",
        "evidence_promotable",
        "live_authorized",
        "fractional_terms_verified",
        "first_rebalance",
        "months",
        "warmup_bars",
        "settlement_sessions",
        "limitations",
    ],
)
def test_nested_mutation_does_not_survive_request_construction(marker):
    p = protocol()
    object.__setattr__(p, marker, True)
    with pytest.raises(ValueError, match="etf_monthly_invalid"):
        api().EtfMonthlyRequest(p, (), (), D("500"))


def test_request_preserves_missing_bar_without_substitution_and_denies_holdout():
    req = request()
    missing = tuple(r for r in req.bars if r.session_date != date(2016, 1, 29))
    out = replace(req, bars=missing)
    assert date(2016, 1, 29) in out.protocol.month_end_sessions
    assert date(2016, 1, 29) not in tuple(r.session_date for r in out.bars)
    with pytest.raises(ValueError):
        replace(req, bars=(*req.bars, daily_bar(date(2024, 1, 2))))
    with pytest.raises(ValueError):
        replace(req, bars=tuple(reversed(req.bars)))
    with pytest.raises(ValueError):
        replace(req, initial_cash=D("1500"))


def test_monthly_atr_slice_uses_exact_100_completed_bars_including_decision():
    req = request()
    rows = api().monthly_atr_inputs(req, date(2016, 10, 31))
    index = req.protocol.sessions.index(date(2016, 10, 31))
    assert tuple(r.session_date for r in rows) == req.protocol.sessions[index - 99 : index + 1]
    assert len(rows) == 100 and rows[-1].session_date == date(2016, 10, 31)
    missing = replace(
        req, bars=tuple(r for r in req.bars if r.session_date != rows[1].session_date)
    )
    with pytest.raises(ValueError, match="etf_monthly_invalid"):
        api().monthly_atr_inputs(missing, date(2016, 10, 31))
    with pytest.raises(ValueError, match="etf_monthly_invalid"):
        api().monthly_atr_inputs(req, date(2016, 11, 1))
