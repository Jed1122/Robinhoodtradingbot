from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trading_bot.hybrid.accounting import buy_lot
from trading_bot.hybrid.models import Account, Quote


def test_invalid_safety_state_cannot_enter_journal():
    now = datetime(2026, 10, 21, tzinfo=UTC)
    with pytest.raises(ValueError):
        Quote(symbol="SPY", bid="100", ask="100", as_of=now, tradable="true")
    lot = buy_lot("a", "SPY", "tactical", Decimal(1), Decimal(100), now)
    with pytest.raises(ValueError):
        Account(lots=(lot, lot))
