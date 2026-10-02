"""Native daily completion midnight must not move dividend effectivity."""

from datetime import date, timedelta
from decimal import Decimal

from tests.unit.simulation.test_etf_history import bar
from trading_bot.domain import CorporateAction
from trading_bot.market_data.adjustments import adjust_bars
from trading_bot.market_data.recording import content_hash


def test_explicit_native_session_date_adjusts_previous_day_but_not_ex_date():
    previous = bar(1, Decimal("100")).payload
    ex_day = previous.ends_at.date()
    action = CorporateAction(
        "SPY",
        "dividend",
        ex_day,
        previous.starts_at,
        None,
        Decimal("1"),
        content_hash("distribution"),
    )
    result = adjust_bars(
        (previous,),
        (action,),
        as_of=previous.ends_at + timedelta(days=1),
        session_dates=(date(2016, 1, 1),),
    )
    assert result[0].close == 99 and result[0].data_hash != previous.data_hash
