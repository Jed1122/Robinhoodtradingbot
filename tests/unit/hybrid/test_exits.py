from datetime import UTC, datetime
from decimal import Decimal as D

from trading_bot.config.hybrid import HybridSettings
from trading_bot.hybrid.execution import fill_order, reserve_order
from trading_bot.hybrid.exits import propose_exit
from trading_bot.hybrid.models import Account, FillFact, PaperOrder, Quote

NOW = datetime(2026, 10, 21, 14, tzinfo=UTC)


def test_partial_entry_fills_share_one_episode_and_exit_uses_original_allocation():
    policy = HybridSettings()
    quote = Quote(
        symbol="SPY",
        bid=D(100),
        ask=D(100),
        as_of=NOW,
        tradable=True,
        fractional=True,
        regular_session=True,
        halted=False,
        diversified_etf=True,
        average_dollar_volume=D(100000000),
        earnings_clear=True,
    )
    entry = PaperOrder(id="episode", symbol="SPY", side="buy", sleeve="long_term", quantity=D(5))
    a = reserve_order(Account(paused=False), entry, quote, NOW, policy)
    for i, qty in enumerate((D(2), D(3))):
        a = fill_order(
            a,
            FillFact(id=f"f{i}", order_id="episode", quantity=qty, price=D(100), fee=D(0), at=NOW),
            policy,
        )
    assert len(a.episodes) == 1
    assert a.episodes[0].original_cash == 500
    assert a.episodes[0].original_quantity == 5
    # Long-term sleeve cannot accidentally receive a tactical profit-taking order.
    assert propose_exit(a, "episode", "principal", D(120), D(120), policy) is None
