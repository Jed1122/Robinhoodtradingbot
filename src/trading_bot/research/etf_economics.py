"""Exact fixture outcome attribution; never a market-edge acceptance decision.

Simulated fill prices already include their spread/slippage assumptions. Fees are
already in reconciled cash. This report does not subtract either a second time.
Allocated operating cost is a separate, explicit input, not verified historical cost.
"""

from dataclasses import dataclass, field, replace
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.domain import Side
from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.market_data.recording import content_hash
from trading_bot.risk.options_economics import TrialLossState
from trading_bot.simulation.etf_account import EtfAccountResult
from trading_bot.simulation.lifecycle_accounting import _context


class EtfEconomicError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_economic_invalid")


@dataclass(frozen=True, slots=True)
class EtfAccountEconomicReport:
    account_state_hash: str
    initial_cash: Decimal
    cash_change: Decimal
    residual_shares: Decimal
    fees_paid: Decimal
    operating_cost: Decimal
    trading_pnl: Decimal | None
    operating_profit: Decimal | None
    completed_episodes: int
    consumed_trial_loss: Decimal
    reasons: tuple[str, ...]
    cash_baseline_pnl: Decimal = field(default=Decimal("0"), init=False)
    verdict: Literal["ECONOMIC_NO_GO"] = field(default="ECONOMIC_NO_GO", init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    @property
    def report_hash(self) -> str:
        return content_hash({"schema": "etf-account-economic-report-v1", "report": self})


def evaluate_etf_account_economics(
    result: EtfAccountResult, *, operating_cost: Decimal
) -> EtfAccountEconomicReport:
    try:
        if type(result) is not EtfAccountResult:
            raise EtfEconomicError()
        for name, value in (
            ("initial cash", result.initial_cash),
            ("cash", result.cash),
            ("settled cash", result.settled_cash),
            ("fees", result.fees),
        ):
            require_bounded_decimal(value, name, nonnegative=True)
        if result.initial_cash not in (Decimal("500"), Decimal("1000")):
            raise EtfEconomicError()
        replace(result.position)
        if type(result.trial) is not TrialLossState or type(result.orders) is not tuple:
            raise EtfEconomicError()
        replace(result.trial)
        for order in result.orders:
            replace(order.intent)
            replace(order.order)
            require_bounded_decimal(order.fees_paid, "paid fees", nonnegative=True)
            require_bounded_decimal(order.fee_bound, "reserved fees", nonnegative=True)
            if order.fees_paid > order.fee_bound:
                raise EtfEconomicError()
        for _, amount, _ in (*result.unsettled, *result.receivables):
            require_bounded_decimal(amount, "obligation", nonnegative=True)
        require_bounded_decimal(operating_cost, "operating cost", nonnegative=True)
        with localcontext(_context(exact=True)):
            cash_flows = sum(
                (
                    episode.net_cash_flow
                    for episode in result.trial.episodes
                    if episode.net_cash_flow is not None
                ),
                Decimal("0"),
            )
            fees = sum((order.fees_paid for order in result.orders), Decimal("0"))
            shares = sum(
                (
                    order.order.filled_quantity * (1 if order.order.side is Side.BUY else -1)
                    for order in result.orders
                ),
                Decimal("0"),
            )
            unsettled = sum((amount for _, amount, _ in result.unsettled), Decimal("0"))
            if (
                result.cash != result.initial_cash + cash_flows
                or result.fees != fees
                or result.shares != shares
                or result.settled_cash != result.cash - unsettled
                or result.execution_enabled is not False
                or result.evidence_promotable is not False
            ):
                raise EtfEconomicError()
            reasons = [
                "synthetic_account_facts",
                "qualified_event_history_unavailable",
                "execution_costs_uncalibrated",
                "matched_market_benchmarks_unavailable",
                "parameter_stability_unmeasured",
                "operating_allocation_unverified",
            ]
            completed = sum(episode.complete for episode in result.trial.episodes)
            if completed < 30:
                reasons.append("independent_opportunities_insufficient")
            pnl = result.cash - result.initial_cash if result.complete else None
            if not result.complete:
                reasons.append("account_outcome_incomplete")
            return EtfAccountEconomicReport(
                result.state_hash,
                result.initial_cash,
                result.cash - result.initial_cash,
                result.shares,
                result.fees,
                operating_cost,
                pnl,
                None if pnl is None else pnl - operating_cost,
                completed,
                result.trial.consumed_loss,
                tuple(reasons),
            )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise EtfEconomicError() from None
