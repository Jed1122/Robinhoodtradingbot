"""Synthetic adapter for canonical economic checks; never the production pretrade engine."""

from datetime import datetime
from decimal import Decimal

from trading_bot.domain import (
    CheckResult,
    OrderIntent,
    PortfolioSnapshot,
    Side,
    canonical_decimal_text,
)
from trading_bot.portfolio.sizing import SizingDecision, SizingRequest
from trading_bot.risk.limits import evaluate_exposure_limits
from trading_bot.risk.losses import evaluate_activity_limits
from trading_bot.risk.models import ExposureProjection
from trading_bot.simulation.equity_replay_models import EquityStrategyReplayRequest, checked, deny
from trading_bot.simulation.equity_replay_portfolio_checks import intent_slots
from trading_bot.simulation.equity_replay_risk_state import ReplayRiskState

ZERO = Decimal(0)


def _check(
    code: str,
    allowed: bool,
    reason: str,
    now: datetime,
    observed: str = "synthetic_only",
    limit: str = "canonical_configuration",
) -> CheckResult:
    return CheckResult(code, allowed, observed, limit, reason, now)


def _projection(
    intent: OrderIntent,
    state: ReplayRiskState,
    request: EquityStrategyReplayRequest,
    snapshot: PortfolioSnapshot,
    now: datetime,
    allocation: Decimal,
) -> ExposureProjection:
    instruments = {i.id: i for i in request.instruments}
    notionals = {p.instrument_id: p.market_value for p in snapshot.positions}
    for record in state.orders:
        if not record.lifecycle.order_terminal and record.intent.side is Side.BUY:
            if record.intent.limit_price is None:
                deny()
            symbol = record.intent.instrument_id
            notionals[symbol] = notionals.get(symbol, ZERO) + (
                record.lifecycle.snapshot.remaining_quantity * record.intent.limit_price
            )
    if intent.limit_price is None:
        deny()
    if intent.side is Side.BUY:
        notionals[intent.instrument_id] = notionals.get(intent.instrument_id, ZERO) + (
            intent.quantity * intent.limit_price
        )
    else:
        position = next(
            (p for p in snapshot.positions if p.instrument_id == intent.instrument_id), None
        )
        if position is not None:
            # Subtract bid-marked shares, not an optimistic limit-price receipt.
            bid = position.market_value / position.quantity
            notionals[intent.instrument_id] = max(
                ZERO, position.market_value - intent.quantity * bid
            )
    group = instruments[intent.instrument_id].correlation_group
    return ExposureProjection(
        request.account_id,
        intent.id,
        intent.instrument_id,
        intent.asset_class,
        group,
        snapshot.equity,
        request.initial_cash,
        max(ZERO, state.allocatable_cash - allocation),
        sum(notionals.values(), ZERO),
        sum(n > 0 for n in notionals.values()),
        notionals.get(intent.instrument_id, ZERO),
        sum(
            (
                n
                for symbol, n in notionals.items()
                if instruments[symbol].correlation_group == group
            ),
            ZERO,
        ),
        ZERO,
        ZERO,
        now,
    )


def economic_checks(
    intent: OrderIntent,
    portfolio_state: ReplayRiskState,
    request: EquityStrategyReplayRequest,
    now: datetime,
) -> tuple[CheckResult, ...]:
    """Read current state afresh for each candidate; never reserve, resize or submit it.

    Failed funding gets an explicit denial; zero cash is used only to obtain the remaining
    canonical diagnostic checks. No saturated projection can become an allowed candidate.
    """
    with checked():
        if type(portfolio_state) is not ReplayRiskState or type(intent) is not OrderIntent:
            deny()
        state = portfolio_state
        snapshot = state.current(request, now)
        count = sum(
            intent.created_at < t < intent.expires_at
            for s in request.sessions
            if s.instrument_id == intent.instrument_id
            for t in s.opportunity_times
        )
        instrument, slots = intent_slots(request, intent, count)
        if intent.created_at != now or intent.limit_price is None:
            deny("replay_risk_identity_invalid")
        position = next(
            (p for p in snapshot.positions if p.instrument_id == intent.instrument_id), None
        )
        no_active = not any(
            o.intent.instrument_id == intent.instrument_id and not o.lifecycle.order_terminal
            for o in state.orders
        )
        unused = not any(o.intent.id == intent.id for o in state.orders)
        position_ok = (
            position is None
            if intent.side is Side.BUY
            else position is not None and intent.quantity <= position.quantity
        )
        results = [
            _check(
                "replay_order_state",
                no_active and unused and position_ok,
                "fresh_entry_or_reduce_only_exit"
                if no_active and unused and position_ok
                else "active_or_conflicting_position",
                now,
            )
        ]
        config = request.loaded.config
        allocation = (
            intent.quantity * intent.limit_price + config.costs.equity_commission_usd * len(slots)
            if intent.side is Side.BUY
            else ZERO
        )
        results.append(
            _check(
                "replay_funding",
                allocation <= state.allocatable_cash,
                "within_allocation"
                if allocation <= state.allocatable_cash
                else "insufficient_cash",
                now,
                canonical_decimal_text(allocation),
                canonical_decimal_text(state.allocatable_cash),
            )
        )
        projection = _projection(intent, state, request, snapshot, now, allocation)
        results.extend(
            evaluate_exposure_limits(
                projection,
                portfolio=config.portfolio,
                position_risk=config.position_risk,
                crypto=config.crypto,
            )
        )
        loss = state.loss_decision(intent.purpose)
        results.append(_check("replay_loss_limits", loss.allowed, loss.reason_code, now))
        if intent.side is Side.BUY:
            results.append(
                evaluate_activity_limits(
                    state.activity_snapshot(intent.instrument_id), settings=config.activity
                )
            )
            policy = state.policy(intent.exit_policy_version)
            if (
                policy is None
                or policy.instrument_id != intent.instrument_id
                or policy.entry_limit != intent.limit_price
                or policy.observed_at != now
            ):
                results.append(
                    _check("replay_final_sizing", False, "entry_policy_missing_or_mismatched", now)
                )
            else:
                sizing = SizingRequest.from_config(
                    reconciled_equity=snapshot.equity,
                    authorized_risk_equity=request.initial_cash,
                    stop_distance_per_unit=policy.stop_distance,
                    entry_price=intent.limit_price,
                    instrument=instrument,
                    position_risk=config.position_risk,
                    activity=config.activity,
                )
                final = SizingDecision.validate_final(quantity=intent.quantity, request=sizing)
                results.append(
                    _check(
                        "replay_final_sizing",
                        final.allowed,
                        final.denial_code or "within_sizing_limits",
                        now,
                        canonical_decimal_text(intent.quantity),
                    )
                )
                results.append(
                    _check(
                        "replay_reward_risk",
                        config.equity_strategies.exit_reward_to_initial_risk
                        >= config.position_risk.minimum_reward_to_initial_risk,
                        "canonical_reward_risk",
                        now,
                    )
                )
        else:
            results.append(
                _check("replay_exit_activity", True, "not_applicable_reduce_only_exit", now)
            )
        return tuple(results)


__all__ = ["ReplayRiskState", "economic_checks"]
