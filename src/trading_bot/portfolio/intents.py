"""Plan candidate intents through production sizing without averaging down."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from trading_bot.config import ActivitySettings, PositionRiskSettings
from trading_bot.domain import (
    AccountId,
    Instrument,
    OrderIntent,
    OrderIntentId,
    OrderPurpose,
    OrderType,
    PortfolioSnapshot,
    Side,
    TimeInForce,
    new_order_intent_id,
    quantize_down,
)
from trading_bot.portfolio.sizing import SizingDecision, SizingRequest, size_position
from trading_bot.portfolio.targets import TargetPortfolio


@dataclass(frozen=True, slots=True)
class IntentPlanningContext:
    account_id: AccountId
    portfolio: PortfolioSnapshot
    instruments: tuple[Instrument, ...]
    prices: tuple[tuple[str, Decimal], ...]
    reconciled_equity: Decimal
    authorized_risk_equity: Decimal
    position_risk: PositionRiskSettings
    activity: ActivitySettings
    expires_after: timedelta


class IntentPlanner:
    def __init__(self, *, id_factory: Callable[[], OrderIntentId] = new_order_intent_id) -> None:
        self._id_factory = id_factory

    def plan(
        self, target: TargetPortfolio, context: IntentPlanningContext
    ) -> tuple[OrderIntent, ...]:
        instruments = {instrument.id: instrument for instrument in context.instruments}
        prices = dict(context.prices)
        positions = {position.instrument_id: position for position in context.portfolio.positions}
        intents: list[OrderIntent] = []
        for desired in target.positions:
            instrument = instruments[desired.instrument_id]
            price = prices[desired.instrument_id]
            current = positions.get(desired.instrument_id)
            if desired.target_notional > 0:
                if current is not None and current.quantity > 0:
                    continue
                if desired.exit_policy is None:
                    continue
                request = SizingRequest.from_config(
                    reconciled_equity=context.reconciled_equity,
                    authorized_risk_equity=context.authorized_risk_equity,
                    stop_distance_per_unit=desired.exit_policy.stop_distance_per_unit,
                    entry_price=price,
                    instrument=instrument,
                    position_risk=context.position_risk,
                    activity=context.activity,
                )
                sized = size_position(request)
                target_quantity = quantize_down(
                    desired.target_notional / price, instrument.quantity_increment
                )
                final = SizingDecision.validate_final(
                    quantity=min(sized.quantity, target_quantity), request=request
                )
                if not final.allowed:
                    continue
                intents.append(
                    OrderIntent(
                        self._id_factory(),
                        context.account_id,
                        instrument.id,
                        instrument.asset_class,
                        Side.BUY,
                        OrderPurpose.ENTRY,
                        OrderType.LIMIT,
                        TimeInForce.GOOD_FOR_DAY,
                        final.quantity,
                        price,
                        None,
                        target.as_of,
                        target.as_of + context.expires_after,
                        desired.source_strategy_version,
                        target.config_hash,
                        target.data_hash,
                        desired.exit_policy.version,
                    )
                )
            elif current is not None and current.quantity > 0:
                intents.append(
                    OrderIntent(
                        self._id_factory(),
                        context.account_id,
                        instrument.id,
                        instrument.asset_class,
                        Side.SELL,
                        OrderPurpose.STRATEGY_EXIT,
                        OrderType.LIMIT,
                        TimeInForce.GOOD_FOR_DAY,
                        current.quantity,
                        price,
                        None,
                        target.as_of,
                        target.as_of + context.expires_after,
                        desired.source_strategy_version,
                        target.config_hash,
                        target.data_hash,
                        None,
                    )
                )
        return tuple(intents)


__all__ = ["IntentPlanner", "IntentPlanningContext"]
