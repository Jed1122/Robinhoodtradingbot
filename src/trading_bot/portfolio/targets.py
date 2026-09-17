"""Separate strategy direction from broker-neutral target construction."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_bot.domain import (
    ConfigHash,
    DataHash,
    DomainValidationError,
    InstrumentId,
    PortfolioSnapshot,
)
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
        exit_policy: ExitPolicy | None = None,
        exit_policies: tuple[tuple[InstrumentId, ExitPolicy], ...] | None = None,
    ) -> TargetPortfolio:
        policies = _policy_map(exit_policy, exit_policies)
        entries = tuple(
            item
            for item in decisions
            if item.action is StrategyAction.ENTER_LONG and item.score > 0
        )
        exits = tuple(item for item in decisions if item.action is StrategyAction.EXIT_LONG)
        if policies is not None and any(item.instrument_id not in policies for item in entries):
            raise DomainValidationError("entry_exit_policy_missing")
        budget = snapshot.equity * exposure_multiplier
        score_total = sum((item.score for item in entries), Decimal("0"))
        targets = [
            TargetPosition(
                item.instrument_id,
                budget * item.score / score_total if score_total else Decimal("0"),
                exit_policy if policies is None else policies[item.instrument_id],
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


def _policy_map(
    exit_policy: ExitPolicy | None,
    exit_policies: tuple[tuple[InstrumentId, ExitPolicy], ...] | None,
) -> dict[InstrumentId, ExitPolicy] | None:
    """Reject ambiguous ownership; an explicit empty map supports exit-only cycles."""
    if exit_policies is None:
        if type(exit_policy) is not ExitPolicy:
            raise DomainValidationError("exit_policy_required")
        return None
    if exit_policy is not None or type(exit_policies) is not tuple:
        raise DomainValidationError("exit_policy_map_invalid")
    result: dict[InstrumentId, ExitPolicy] = {}
    for row in exit_policies:
        if (
            type(row) is not tuple
            or len(row) != 2
            or type(row[0]) is not str
            or not row[0].strip()
            or type(row[1]) is not ExitPolicy
            or row[0] in result
        ):
            raise DomainValidationError("exit_policy_map_invalid")
        result[row[0]] = row[1]
    return result


__all__ = ["ExitPolicy", "PortfolioConstructor", "TargetPortfolio", "TargetPosition"]
