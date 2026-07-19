"""Long-only crypto trend/breakout candidate with a cash negative regime."""

from decimal import Decimal

from trading_bot.market_data import content_hash
from trading_bot.strategies.protocol import (
    StrategyAction,
    StrategyContext,
    StrategyDecision,
    StrategyDescriptor,
)


class CryptoTrendStrategy:
    @property
    def descriptor(self) -> StrategyDescriptor:
        return StrategyDescriptor(
            "crypto_trend",
            "trend_breakout",
            "crypto_trend-v1",
            "positive trend and breakout; otherwise remain in cash",
            False,
            content_hash({"cash_negative_regime": True}),
        )

    def decide(self, context: StrategyContext) -> tuple[StrategyDecision, ...]:
        result = []
        for vector in context.features.vectors:
            values = dict(vector.values)
            total = values.get("total_return_pct")
            action = (
                StrategyAction.ENTER_LONG
                if isinstance(total, Decimal) and total > 0
                else StrategyAction.HOLD
            )
            result.append(
                StrategyDecision(
                    vector.instrument_id,
                    context.as_of,
                    action,
                    total if isinstance(total, Decimal) and total > 0 else Decimal("0"),
                    ("positive_crypto_trend",)
                    if action is StrategyAction.ENTER_LONG
                    else ("negative_trend_cash",),
                    self.descriptor.version,
                    context.config_hash,
                    vector.data_hash,
                )
            )
        return tuple(result)


__all__ = ["CryptoTrendStrategy"]
