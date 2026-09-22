"""Immutable synthetic replay audit records; completion is derived, never attested."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from trading_bot.app import DecisionCycleResult
from trading_bot.domain import CheckResult, DataHash, InstrumentId, PortfolioSnapshot, Quote
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.configured_results import ConfiguredDecision
from trading_bot.simulation.equity_replay_codec import ReplayIdentity, replay_identity
from trading_bot.simulation.equity_replay_models import (
    EquityStrategyReplayRequest,
    ReplayDecision,
    checked,
    deny,
)
from trading_bot.simulation.equity_replay_portfolio import ReplayOrderRecord, ReplayPortfolio


@dataclass(frozen=True, slots=True)
class ReplayCycleRecord:
    decision: ReplayDecision
    result: DecisionCycleResult
    economic_checks: tuple[tuple[str, tuple[CheckResult, ...]], ...]
    cancellation_reasons: tuple[tuple[InstrumentId, str], ...]


@dataclass(frozen=True, slots=True)
class ReplayOrderTransition:
    order_id: str
    decision: ConfiguredDecision


@dataclass(frozen=True, slots=True)
class ReplayCancellation:
    order_id: str
    occurred_at: datetime
    reason: str


@dataclass(frozen=True, slots=True, init=False)
class EquityStrategyReplayResult:
    identity: ReplayIdentity
    cycles: tuple[ReplayCycleRecord, ...]
    orders: tuple[ReplayOrderRecord, ...]
    transitions: tuple[ReplayOrderTransition, ...]
    cancellations: tuple[ReplayCancellation, ...]
    final_portfolio: PortfolioSnapshot
    fees: Decimal
    reserved_cash: Decimal
    reserved_shares: tuple[tuple[InstrumentId, Decimal], ...]
    unresolved_reasons: tuple[str, ...]
    result_hash: DataHash
    source_kind: Literal["synthetic-equity-replay-v1"] = field(
        default="synthetic-equity-replay-v1", init=False
    )
    assumptions_validated: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    production_pretrade_eligible: Literal[False] = field(default=False, init=False)
    run_valid: Literal[True] = field(default=True, init=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("replay results are derived by the coordinator")

    @property
    def orders_terminal(self) -> bool:
        return all(record.lifecycle.order_terminal for record in self.orders)

    @property
    def positions_flat(self) -> bool:
        return not self.final_portfolio.positions

    @property
    def strategy_outcomes_complete(self) -> bool:
        return self.orders_terminal and self.positions_flat

    @classmethod
    def _from_book(
        cls,
        request: EquityStrategyReplayRequest,
        book: ReplayPortfolio,
        cycles: tuple[ReplayCycleRecord, ...],
        transitions: tuple[ReplayOrderTransition, ...],
        cancellations: tuple[ReplayCancellation, ...],
        quotes: tuple[Quote, ...],
    ) -> Self:
        with checked():
            if (
                type(book) is not ReplayPortfolio
                or not book.valid
                or book.request_identity != replay_identity(request)
            ):
                deny("replay_result_invalid")
            if (
                type(cycles) is not tuple
                or type(transitions) is not tuple
                or type(cancellations) is not tuple
                or any(type(c) is not ReplayCycleRecord for c in cycles)
                or any(type(t) is not ReplayOrderTransition for t in transitions)
                or any(type(c) is not ReplayCancellation for c in cancellations)
                or tuple(c.decision for c in cycles) != request.decisions
            ):
                deny("replay_result_invalid")
            snapshot = book.snapshot(request.end_at, quotes)
            reasons = tuple(
                code
                for code, condition in (
                    ("replay_orders_nonterminal", not book.orders_terminal),
                    ("replay_positions_open", not book.positions_flat),
                )
                if condition
            )
            fields: dict[str, object] = {
                "source_kind": "synthetic-equity-replay-v1",
                "assumptions_validated": False,
                "evidence_promotable": False,
                "production_pretrade_eligible": False,
                "run_valid": True,
                "identity": book.request_identity,
                "cycles": cycles,
                "orders": book.orders,
                "transitions": transitions,
                "cancellations": cancellations,
                "final_portfolio": snapshot,
                "fees": book.fees,
                "reserved_cash": book.reserved_cash,
                "reserved_shares": book.reserved_shares,
                "unresolved_reasons": reasons,
            }
            # Delivery receipts remain visible, but cannot alter the economic result digest.
            payload = {
                **fields,
                "identity": (book.request_identity.run_key, book.request_identity.input_hash),
            }
            fields["result_hash"] = content_hash(
                {"domain": "synthetic-equity-replay-result-v1", "value": payload}
            )
            instance = object.__new__(cls)
            for name, value in fields.items():
                object.__setattr__(instance, name, value)
            return instance
