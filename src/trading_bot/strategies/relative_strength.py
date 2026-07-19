"""Cross-sectional relative-strength ranking over already eligible instruments."""

from decimal import Decimal

from trading_bot.market_data import content_hash
from trading_bot.strategies.protocol import (
    StrategyAction,
    StrategyContext,
    StrategyDecision,
    StrategyDescriptor,
)


class RelativeStrengthStrategy:
    def __init__(self, *, top_n: int = 3) -> None:
        if top_n < 1:
            raise ValueError("top_n must be positive")
        self._top_n = top_n
        self._descriptor = StrategyDescriptor(
            "equity_relative_strength",
            "relative_strength",
            "equity_relative_strength-v1",
            "rank eligible liquid instruments by total return",
            False,
            content_hash({"top_n": top_n}),
        )

    @property
    def descriptor(self) -> StrategyDescriptor:
        return self._descriptor

    def decide(self, context: StrategyContext) -> tuple[StrategyDecision, ...]:
        ranked = sorted(
            (
                (value, vector)
                for vector in context.features.vectors
                if vector.instrument_id in context.eligible_instruments
                and isinstance((value := dict(vector.values).get("total_return_pct")), Decimal)
            ),
            key=lambda item: (-item[0], item[1].instrument_id),
        )
        selected = {vector.instrument_id for score, vector in ranked[: self._top_n] if score > 0}
        return tuple(
            StrategyDecision(
                vector.instrument_id,
                context.as_of,
                StrategyAction.ENTER_LONG
                if vector.instrument_id in selected
                else StrategyAction.HOLD,
                score,
                ("relative_strength_rank",),
                self.descriptor.version,
                context.config_hash,
                vector.data_hash,
            )
            for score, vector in ranked
        )


__all__ = ["RelativeStrengthStrategy"]
