"""Separate strategy direction from broker-neutral target construction."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_bot.domain import ConfigHash, DataHash, InstrumentId, PortfolioSnapshot
from trading_bot.market_data import content_hash
from trading_bot.strategies.protocol import StrategyAction, StrategyDecision


@dataclass(frozen=True, slots=True)
class ExitPolicy:
    version: str
    stop_kind: str
    stop_distance_per_unit: Decimal
    minimum_reward_risk: Decimal
    maximum_holding_bars: int | None


@dataclass(frozen=True, slots=True)
class TargetPosition:
    instrument_id: InstrumentId
    target_notional: Decimal
    exit_policy: ExitPolicy | None
    source_strategy_version: str


@dataclass(frozen=True, slots=True)
class TargetPortfolio:
    as_of: datetime
    positions: tuple[TargetPosition, ...]
    cash_target: Decimal
    config_hash: ConfigHash
    data_hash: DataHash


class PortfolioConstructor:
    def construct(
        self,
        decisions: tuple[StrategyDecision, ...],
        snapshot: PortfolioSnapshot,
        *,
        as_of: datetime,
        config_hash: ConfigHash,
        exposure_multiplier: Decimal,
        exit_policy: ExitPolicy,
    ) -> TargetPortfolio:
        entries = tuple(
            item
            for item in decisions
            if item.action is StrategyAction.ENTER_LONG and item.score > 0
        )
        exits = tuple(item for item in decisions if item.action is StrategyAction.EXIT_LONG)
        budget = snapshot.equity * exposure_multiplier
        score_total = sum((item.score for item in entries), Decimal("0"))
        targets = [
            TargetPosition(
                item.instrument_id,
                budget * item.score / score_total if score_total else Decimal("0"),
                exit_policy,
                item.strategy_version,
            )
            for item in entries
        ]
        targets.extend(
            TargetPosition(item.instrument_id, Decimal("0"), None, item.strategy_version)
            for item in exits
        )
        targets.sort(key=lambda item: item.instrument_id)
        cash_target = snapshot.equity - sum(
            (item.target_notional for item in targets), Decimal("0")
        )
        payload = {
            "as_of": as_of,
            "cash_target": cash_target,
            "config_hash": config_hash,
            "positions": tuple(targets),
        }
        return TargetPortfolio(
            as_of, tuple(targets), cash_target, config_hash, content_hash(payload)
        )


__all__ = ["ExitPolicy", "PortfolioConstructor", "TargetPortfolio", "TargetPosition"]
