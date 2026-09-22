"""Mode-aware deterministic strategy registry."""

from trading_bot.domain import ExecutionMode
from trading_bot.strategies.crypto import CryptoTrendStrategy
from trading_bot.strategies.mean_reversion import MeanReversionStrategy
from trading_bot.strategies.momentum import MomentumStrategy
from trading_bot.strategies.protocol import Strategy
from trading_bot.strategies.relative_strength import RelativeStrengthStrategy


class StrategyNotAllowed(RuntimeError):
    pass


class StrategyRegistry:
    def __init__(self) -> None:
        strategies: tuple[Strategy, ...] = (
            MomentumStrategy(),
            RelativeStrengthStrategy(),
            MeanReversionStrategy(),
            CryptoTrendStrategy(),
        )
        self._strategies = {strategy.descriptor.strategy_id: strategy for strategy in strategies}

    def get(self, strategy_id: str, *, mode: ExecutionMode) -> Strategy:
        strategy = self._strategies[strategy_id]
        if strategy.descriptor.research_only and mode not in {
            ExecutionMode.BACKTEST,
            ExecutionMode.SIMULATION,
        }:
            raise StrategyNotAllowed("research-only strategy is unavailable in this mode")
        return strategy


__all__ = ["StrategyNotAllowed", "StrategyRegistry"]
