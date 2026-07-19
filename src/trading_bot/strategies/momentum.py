"""Interpretable long-only time-series momentum candidate."""

from decimal import Decimal

from trading_bot.market_data import content_hash
from trading_bot.strategies.protocol import (
    StrategyAction,
    StrategyContext,
    StrategyDecision,
    StrategyDescriptor,
)


class MomentumStrategy:
    def __init__(self, *, version: str = "equity_momentum-v1") -> None:
        self._descriptor = StrategyDescriptor(
            "equity_momentum",
            "momentum",
            version,
            "positive return, short average above long average, and price above long average",
            False,
            content_hash({"version": version}),
        )

    @property
    def descriptor(self) -> StrategyDescriptor:
        return self._descriptor

    def decide(self, context: StrategyContext) -> tuple[StrategyDecision, ...]:
        decisions = []
        for vector in context.features.vectors:
            if vector.instrument_id not in context.eligible_instruments:
                continue
            values = dict(vector.values)
            total = values.get("total_return_pct")
            short = values.get("moving_average_short")
            long = values.get("moving_average_long")
            price = values.get("breakout_high")
            ready = all(isinstance(value, Decimal) for value in (total, short, long, price))
            enter = ready and total > 0 and short > long and price > long  # type: ignore[operator]
            action = StrategyAction.ENTER_LONG if enter else StrategyAction.HOLD
            score = total if isinstance(total, Decimal) and total > 0 else Decimal("0")
            decisions.append(
                StrategyDecision(
                    vector.instrument_id,
                    context.as_of,
                    action,
                    score,
                    ("momentum_confirmed",) if enter else ("momentum_not_confirmed",),
                    self.descriptor.version,
                    context.config_hash,
                    vector.data_hash,
                )
            )
        return tuple(decisions)


__all__ = ["MomentumStrategy"]
