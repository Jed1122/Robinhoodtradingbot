"""Explicitly research-only mean-reversion candidate."""

from trading_bot.market_data import content_hash
from trading_bot.strategies.protocol import StrategyContext, StrategyDecision, StrategyDescriptor


class MeanReversionStrategy:
    @property
    def descriptor(self) -> StrategyDescriptor:
        return StrategyDescriptor(
            "equity_mean_reversion",
            "mean_reversion",
            "equity_mean_reversion-research-v1",
            "research-only deviation candidate",
            True,
            content_hash({"research_only": True}),
        )

    def decide(self, context: StrategyContext) -> tuple[StrategyDecision, ...]:
        return ()


__all__ = ["MeanReversionStrategy"]
