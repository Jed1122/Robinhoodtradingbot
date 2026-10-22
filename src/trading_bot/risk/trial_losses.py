"""Asset-neutral, reconciled loss-budget history shared by equity accounting."""

from dataclasses import dataclass
from decimal import Decimal, localcontext

from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_exact_bool,
    _require_nonempty,
    _require_tuple,
    require_bounded_decimal,
)


@dataclass(frozen=True, slots=True)
class TrialEpisode:
    episode_id: str
    reserved_risk: Decimal
    net_cash_flow: Decimal | None
    flat: bool
    orders_terminal: bool
    settlement_and_fees_final: bool

    def __post_init__(self) -> None:
        _require_nonempty(self.episode_id, "episode_id")
        require_bounded_decimal(self.reserved_risk, "reserved_risk", nonnegative=True)
        if self.net_cash_flow is not None:
            require_bounded_decimal(self.net_cash_flow, "net_cash_flow")
        for value, name in (
            (self.flat, "flat"),
            (self.orders_terminal, "orders_terminal"),
            (self.settlement_and_fees_final, "settlement_and_fees_final"),
        ):
            _require_exact_bool(value, name)
        if self.complete and self.net_cash_flow is None:
            raise DomainValidationError("completed episode needs reconciled final cash flows")

    @property
    def complete(self) -> bool:
        return self.flat and self.orders_terminal and self.settlement_and_fees_final


@dataclass(frozen=True, slots=True)
class TrialLossState:
    """Reconstruct from complete episode history, never from a rolling P&L balance."""

    episodes: tuple[TrialEpisode, ...]

    def __post_init__(self) -> None:
        _require_tuple(self.episodes, "episodes")
        if any(type(item) is not TrialEpisode for item in self.episodes):
            raise DomainValidationError("invalid episode record")
        if len({item.episode_id for item in self.episodes}) != len(self.episodes):
            raise DomainValidationError("duplicate episode identity")

    @property
    def consumed_loss(self) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = 2048
            return sum(
                (
                    max(Decimal(0), -item.net_cash_flow)
                    for item in self.episodes
                    if item.complete and item.net_cash_flow is not None
                ),
                Decimal(0),
            )

    @property
    def reserved_risk(self) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = 2048
            return sum(
                (item.reserved_risk for item in self.episodes if not item.complete), Decimal(0)
            )

    def remaining(self, ceiling: Decimal) -> Decimal:
        require_bounded_decimal(ceiling, "ceiling", nonnegative=True)
        with localcontext() as ctx:
            ctx.prec = 2048
            return max(Decimal(0), ceiling - self.consumed_loss - self.reserved_risk)


