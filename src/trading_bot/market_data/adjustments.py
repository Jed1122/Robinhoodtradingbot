"""Point-in-time split and dividend adjustments without future knowledge."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from trading_bot.domain import Bar, CorporateAction
from trading_bot.market_data.recording import content_hash


def adjust_bars(
    bars: tuple[Bar, ...], actions: tuple[CorporateAction, ...], *, as_of: datetime
) -> tuple[Bar, ...]:
    available = tuple(action for action in actions if action.announced_at <= as_of)
    adjusted: list[Bar] = []
    for bar in bars:
        price_divisor = Decimal("1")
        cash_adjustment = Decimal("0")
        for action in available:
            if action.effective_date <= bar.ends_at.date():
                continue
            if action.action_type == "split":
                if action.split_ratio is None:
                    raise ValueError("split action is missing its ratio")
                price_divisor *= action.split_ratio
            else:
                if action.cash_amount is None:
                    raise ValueError("dividend action is missing its cash amount")
                cash_adjustment += action.cash_amount
        provisional = replace(
            bar,
            open=(bar.open - cash_adjustment) / price_divisor,
            high=(bar.high - cash_adjustment) / price_divisor,
            low=(bar.low - cash_adjustment) / price_divisor,
            close=(bar.close - cash_adjustment) / price_divisor,
            volume=bar.volume * price_divisor,
        )
        adjusted.append(replace(provisional, data_hash=content_hash(provisional)))
    return tuple(adjusted)


__all__ = ["adjust_bars"]
