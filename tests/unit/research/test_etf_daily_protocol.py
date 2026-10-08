"""New development identity cannot unlock a historical or live factory."""

import importlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from tests.unit.simulation.test_etf_history import study
from trading_bot.domain import Bar, BarInterval
from trading_bot.market_data.recording import content_hash

D = Decimal
ANCHOR = date(2016, 5, 26)
DEFAULT_PRICE = D("100")
DEFAULT_WIDTH = D(".25")


def api():
    return importlib.import_module("trading_bot.research.etf_daily_protocol")


def session_dates(count=110):
    prior = []
    day = ANCHOR - timedelta(days=1)
    while len(prior) < 100:
        if day.weekday() < 5:
            prior.append(day)
        day -= timedelta(days=1)
    days = list(reversed(prior))
    day = ANCHOR
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return tuple(days[:count])


def protocol(count=110, **kwargs):
    return api().EtfDailyProtocol(
        study(),
        session_dates(count),
        "d" * 64,
        "e" * 64,
        "f" * 64,
        D("0"),
        D(".01"),
        D(".02"),
        **kwargs,
    )


def daily_bar(day, price=DEFAULT_PRICE, width=DEFAULT_WIDTH, *, opening=None, high=None, low=None):
    start = datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=14)
    end = start + timedelta(hours=7)
    raw = Bar(
        "SPY",
        BarInterval.ONE_DAY,
        start,
        end,
        price if opening is None else opening,
        price + width if high is None else high,
        price - width if low is None else low,
        price,
        D("10000"),
        "synthetic",
        content_hash((day, price, width, opening, high, low)),
    )
    return api().EtfDailyBar(day, raw, raw)


def test_protocol_fixed_identity_and_nonpromotability():
    p = protocol()
    assert p.first_rebalance == ANCHOR and p.warmup_bars == 100
    assert p.rebalance_sessions == 5
    assert p.protocol_id == "spy-cash-daily-development-v1"
    assert p.study.risk_equity_reference == D("100")
    assert p.study.windows == (20, 100)
    assert not p.source_qualified and not p.cost_qualified
    assert not p.execution_enabled and not p.evidence_promotable
    assert not p.economic_admitted
    assert replace(p) == p and len(p.protocol_hash) == 64
    assert replace(p, source_hash="1" * 64).protocol_hash != p.protocol_hash
    assert replace(p, side_fee=D(".005")).protocol_hash != p.protocol_hash


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sessions": session_dates(99)},
        {"sessions": (*session_dates(), date(2024, 1, 2))},
        {"sessions": (*session_dates(), session_dates()[-1])},
        {"side_fee": D(".02")},
        {"per_side_cost_bps": D("NaN")},
        {"source_hash": "private secret"},
        {"price_basis": "adjusted-total-return"},
    ],
)
def test_invalid_protocol_sanitized(kwargs):
    with pytest.raises(ValueError, match="etf_daily_invalid"):
        replace(protocol(), **kwargs)


def test_input_rejects_holdout_and_mismatched_feature_basis():
    p = protocol()
    rows = tuple(daily_bar(day) for day in p.sessions)
    request = api().EtfDailyRequest(p, rows, (), D("500"))
    assert replace(request) == request
    with pytest.raises(ValueError, match="etf_daily_invalid"):
        replace(request, bars=(*rows, daily_bar(date(2024, 1, 2))))
    with pytest.raises(ValueError, match="etf_daily_invalid"):
        replace(rows[0], feature=replace(rows[0].feature, close=D("100.1")))
    with pytest.raises(ValueError, match="etf_daily_invalid"):
        replace(request, initial_cash=D("1500"))


def test_missing_session_is_representable_not_fabricated():
    p = protocol()
    request = api().EtfDailyRequest(p, (daily_bar(p.sessions[0]),), (), D("500"))
    assert len(request.bars) == 1


def test_unsafe_false_marker_mutation_is_rejected():
    p = protocol()
    object.__setattr__(p, "execution_enabled", True)
    with pytest.raises(ValueError, match="etf_daily_invalid"):
        p.__post_init__()
