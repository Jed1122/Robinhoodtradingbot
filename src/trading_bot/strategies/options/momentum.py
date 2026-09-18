"""Unvalidated directional long-option hypothesis using shared underlying features."""

from decimal import Decimal

from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.domain.options import OptionKind
from trading_bot.market_data.recording import content_hash
from trading_bot.strategies.momentum import MomentumStrategy
from trading_bot.strategies.protocol import (
    StrategyAction,
    StrategyContext,
    StrategyDecision,
    StrategyDescriptor,
)


class OptionsMomentumStrategy:
    """Calls require positive trend; puts require all three negative trend conditions.

    ENTER_LONG refers to a purchased option, never a short underlying position. A flat,
    missing or mixed signal does not become a put candidate by negating the call signal.
    """

    def __init__(self, *, kind: OptionKind, short_window: int, long_window: int) -> None:
        if type(kind) is not OptionKind:
            raise DomainValidationError("exact option kind required")
        prefix = (
            "unvalidated-options-momentum"
            if kind is OptionKind.CALL
            else "unvalidated-options-put-momentum"
        )
        version = f"{prefix}-{short_window}-{long_window}-v1"
        self._call = MomentumStrategy(
            short_window=short_window, long_window=long_window, version=version
        )
        self._kind = kind
        self._descriptor = StrategyDescriptor(
            f"options_directional_long_{kind.value}",
            "directional_long_options",
            version,
            "research hypothesis: aligned underlying return, moving averages and price trend",
            True,
            content_hash(
                {
                    "kind": kind,
                    "short_window": short_window,
                    "long_window": long_window,
                    "version": version,
                }
            ),
        )

    @property
    def descriptor(self) -> StrategyDescriptor:
        return self._descriptor

    def decide(self, context: StrategyContext) -> tuple[StrategyDecision, ...]:
        if self._kind is OptionKind.CALL:
            return self._call.decide(context)
        decisions = []
        for vector in context.features.vectors:
            if vector.instrument_id not in context.eligible_instruments:
                continue
            values = dict(vector.values)
            total = values.get("total_return_pct")
            short = values.get("moving_average_short")
            long = values.get("moving_average_long")
            price = values.get("latest_close")
            enter = (
                type(total) is Decimal
                and total.is_finite()
                and type(short) is Decimal
                and short.is_finite()
                and type(long) is Decimal
                and long.is_finite()
                and type(price) is Decimal
                and price.is_finite()
                and total < 0
                and short < long
                and price < long
            )
            decisions.append(
                StrategyDecision(
                    vector.instrument_id,
                    context.as_of,
                    StrategyAction.ENTER_LONG if enter else StrategyAction.HOLD,
                    -total if enter and isinstance(total, Decimal) else Decimal(0),
                    ("bearish_momentum_confirmed",)
                    if enter
                    else ("bearish_momentum_not_confirmed",),
                    self.descriptor.version,
                    context.config_hash,
                    vector.data_hash,
                )
            )
        return tuple(decisions)
