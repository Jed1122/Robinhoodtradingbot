"""Original-prefix synthetic marked loss state; never execution authority."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from typing import cast

from trading_bot.config import LoadedConfig
from trading_bot.domain import AccountId, Instrument, OrderPurpose, require_bounded_decimal
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_feasibility import (
    _CONTEXT,
    CapitalEntryDecision,
    _config,
    size_capital_entry,
)
from trading_bot.risk.losses import LossDecision, LossSnapshot, evaluate_loss_limits
from trading_bot.simulation.etf_capital_account import (
    CapitalAccountEvent,
    CapitalAccountReplay,
    CapitalAccountSubmission,
    CapitalActionAccountReplay,
    replay_capital_account_prefixes,
    replay_capital_action_account_prefixes,
)
from trading_bot.simulation.etf_capital_action_events import (
    CapitalActionEvent,
    CapitalDistributionEntitled,
    CapitalSplitApplied,
)
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle_models import LifecycleFillEvent

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


def _check(condition: bool) -> None:
    if not condition:
        raise ValueError("capital_risk_invalid")


@dataclass(frozen=True, slots=True)
class CapitalRiskObservation:
    cursor: EventCursor
    source_count: int
    mark: Decimal | None
    daily_reset_reconciled: bool
    weekly_reset_reviewed: bool

    def __post_init__(self) -> None:
        _check(type(self.cursor) is EventCursor)
        self.cursor.__post_init__()
        _check(type(self.source_count) is int and 0 <= self.source_count <= 4096)
        _check(
            type(self.daily_reset_reconciled) is bool and type(self.weekly_reset_reviewed) is bool
        )
        if self.mark is not None:
            require_bounded_decimal(self.mark, "assumed mark", positive=True)


@dataclass(frozen=True, slots=True)
class CapitalRiskPoint:
    observation: CapitalRiskObservation
    account: CapitalAccountReplay
    equity: Decimal
    snapshot: LossSnapshot
    decision: LossDecision


@dataclass(frozen=True, slots=True)
class CapitalRiskReplay:
    points: tuple[CapitalRiskPoint, ...]
    result_hash: str
    execution_enabled: bool = field(default=False, init=False)
    evidence_promotable: bool = field(default=False, init=False)


def _cursor(event: CapitalAccountEvent | CapitalActionEvent) -> EventCursor:
    return event.request.submitted if isinstance(event, CapitalAccountSubmission) else event.cursor


def _boundary(at: datetime) -> datetime:
    return at.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _loss_pct(base: Decimal, equity: Decimal) -> Decimal:
    loss = max(_ZERO, base - equity) * _HUNDRED / base
    return loss.quantize(Decimal("1e-18"), rounding=ROUND_CEILING)


def replay_capital_risk(
    *,
    loaded: LoadedConfig,
    initial_cash: Decimal,
    events: tuple[CapitalAccountEvent, ...],
    observations: tuple[CapitalRiskObservation, ...],
    purpose: OrderPurpose = OrderPurpose.ENTRY,
) -> CapitalRiskReplay:
    """Reconstruct assumed NAV and latched losses from original account prefixes.

    Explicit UTC reset observations are synthetic declarations, not operational
    attestations. New windows use the last observed NAV as their baseline; gaps
    are therefore not silently absorbed by a reset. Weekly reset can clear its
    latch only on a newly observed reviewed week. Drawdown cannot reset here.
    Missing observations/actions/source coverage remain independent limitations.
    """
    return _replay_risk(
        loaded=loaded,
        initial_cash=initial_cash,
        events=events,
        observations=observations,
        purpose=purpose,
        actions=False,
    )


def replay_capital_action_risk(
    *,
    loaded: LoadedConfig,
    initial_cash: Decimal,
    events: tuple[CapitalAccountEvent | CapitalActionEvent, ...],
    observations: tuple[CapitalRiskObservation, ...],
    purpose: OrderPurpose = OrderPurpose.ENTRY,
) -> CapitalRiskReplay:
    """Opt-in v3 marked risk from originals; receivables are not buying power."""
    return _replay_risk(
        loaded=loaded,
        initial_cash=initial_cash,
        events=events,
        observations=observations,
        purpose=purpose,
        actions=True,
    )


def _replay_risk(
    *,
    loaded: LoadedConfig,
    initial_cash: Decimal,
    events: tuple[CapitalAccountEvent | CapitalActionEvent, ...],
    observations: tuple[CapitalRiskObservation, ...],
    purpose: OrderPurpose,
    actions: bool,
) -> CapitalRiskReplay:
    try:
        with localcontext(_CONTEXT):
            config = _config(loaded)
            accounts: tuple[CapitalAccountReplay, ...]
            if actions:
                accounts = replay_capital_action_account_prefixes(
                    initial_cash=initial_cash, events=events
                )
            else:
                # Public v2 remains strict; its reducer rejects action types even
                # if a caller violates the annotated input contract.
                accounts = replay_capital_account_prefixes(
                    initial_cash=initial_cash, events=cast(tuple[CapitalAccountEvent, ...], events)
                )
            # Raw deliveries can repeat old cursors. Only newly applied original
            # events advance the effective account clock or future boundary.
            frontiers: list[datetime | None] = [None]
            atomic_marks: list[Decimal | None] = [None]
            atomic_sources = [0]
            required_actions: set[int] = set()
            applied: list[bool] = []
            for index, event in enumerate(events):
                changed = accounts[index + 1].economic_hash != accounts[index].economic_hash
                applied.append(changed)
                frontiers.append(_cursor(event).occurred_at if changed else frontiers[-1])
                atomic = atomic_marks[-1]
                atomic_source = atomic_sources[-1]
                if changed:
                    if frontiers[-1] != frontiers[-2] or isinstance(event, LifecycleFillEvent):
                        atomic = None
                        atomic_source = 0
                    if actions and isinstance(
                        event, (CapitalSplitApplied, CapitalDistributionEntitled)
                    ):
                        value = accounts[index + 1]
                        _check(type(value) is CapitalActionAccountReplay)
                        atomic = cast(CapitalActionAccountReplay, value).mark
                        atomic_source = index + 1
                        required_actions.add(atomic_source)
                atomic_marks.append(atomic)
                atomic_sources.append(atomic_source)
            following: list[datetime | None] = [None] * (len(events) + 1)
            for index in range(len(events) - 1, -1, -1):
                following[index] = frontiers[index + 1] if applied[index] else following[index + 1]
            _check(type(observations) is tuple and 0 < len(observations) <= 4096)
            _check(type(purpose) is OrderPurpose)
            points: list[CapitalRiskPoint] = []
            prior: CapitalRiskObservation | None = None
            prior_account = accounts[0]
            consumed = 0
            prior_equity = daily_base = weekly_base = peak = episode_base = initial_cash
            daily_max = weekly_max = drawdown_max = _ZERO
            losses = 0
            last_loss: datetime | None = None
            daily_start: datetime | None = None
            weekly_start: datetime | None = None
            daily_ok = weekly_ok = False
            covered_actions: set[int] = set()
            for observation in observations:
                _check(type(observation) is CapitalRiskObservation)
                observation.__post_init__()
                count, at = observation.source_count, observation.cursor.occurred_at
                _check(count <= len(events))
                if prior is None:
                    _check(count == 0)
                else:
                    _check(
                        observation.cursor.sequence > prior.cursor.sequence
                        and (
                            at > prior.cursor.occurred_at
                            or (
                                actions
                                and at == prior.cursor.occurred_at
                                and count > prior.source_count
                            )
                        )
                        and count >= prior.source_count
                    )
                frontier, next_event = frontiers[count], following[count]
                if frontier is not None:
                    _check(frontier <= at)
                if next_event is not None:
                    _check(next_event >= at)
                for prefix in range(consumed + 1, count + 1):
                    account = accounts[prefix]
                    if prior_account.complete and not account.complete:
                        episode_base = prior_account.cash
                    if not prior_account.complete and account.complete:
                        pnl = account.cash - episode_base
                        if pnl < 0:
                            losses += 1
                            last_loss = _cursor(events[prefix - 1]).occurred_at
                        elif pnl > 0:
                            losses, last_loss = 0, None
                    prior_account = account
                consumed = count
                account = prior_account
                mark = observation.mark
                receivable = _ZERO
                if actions:
                    _check(type(account) is CapitalActionAccountReplay)
                    receivable = cast(CapitalActionAccountReplay, account).distribution_receivable
                    atomic = atomic_marks[count] if at == frontier else None
                    if at == frontier and atomic_sources[count]:
                        covered_actions.add(atomic_sources[count])
                    if atomic is not None and account.quantity:
                        _check(mark is None or mark == atomic)
                        mark = atomic
                if account.quantity:
                    _check(mark is not None)
                equity = account.cash + receivable + account.quantity * (mark or _ZERO)
                require_bounded_decimal(equity, "assumed equity", positive=True)
                day = _boundary(at)
                week = day - timedelta(days=day.weekday())
                if day != daily_start:
                    daily_start, daily_base = day, prior_equity
                    daily_max = _ZERO
                    daily_ok = observation.daily_reset_reconciled
                else:
                    daily_ok = daily_ok or observation.daily_reset_reconciled
                if week != weekly_start:
                    weekly_start, weekly_base = week, prior_equity
                    weekly_ok = observation.weekly_reset_reviewed
                    if weekly_ok:
                        weekly_max = _ZERO
                else:
                    weekly_ok = weekly_ok or observation.weekly_reset_reviewed
                daily_max = max(daily_max, _loss_pct(daily_base, equity))
                weekly_max = max(weekly_max, _loss_pct(weekly_base, equity))
                peak = max(peak, equity)
                drawdown_max = max(drawdown_max, _loss_pct(peak, equity))
                snapshot = LossSnapshot(
                    AccountId("capital-research:assumed-account"),
                    daily_max,
                    weekly_max,
                    drawdown_max,
                    losses,
                    last_loss,
                    daily_start,
                    weekly_start,
                    daily_ok,
                    weekly_ok,
                    at,
                )
                decision = evaluate_loss_limits(
                    snapshot=snapshot, settings=config.capital_research.loss_limits, purpose=purpose
                )
                points.append(CapitalRiskPoint(observation, account, equity, snapshot, decision))
                prior, prior_equity = observation, equity
            _check({count for count in required_actions if count <= consumed} <= covered_actions)
            return _risk_result(loaded, initial_cash, purpose, tuple(points), actions=actions)
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise ValueError("capital_risk_invalid") from None


def _risk_result(
    loaded: LoadedConfig,
    initial_cash: Decimal,
    purpose: OrderPurpose,
    points: tuple[CapitalRiskPoint, ...],
    *,
    actions: bool,
) -> CapitalRiskReplay:
    """Canonical result from internally reconstructed points, never external state."""
    return CapitalRiskReplay(
        points,
        content_hash(
            (
                "capital-risk-replay-v3" if actions else "capital-risk-replay-v2",
                loaded.config_hash,
                initial_cash,
                purpose,
                points,
            )
        ),
    )


def evaluate_capital_entry(
    *,
    loaded: LoadedConfig,
    initial_cash: Decimal,
    events: tuple[CapitalAccountEvent, ...],
    observations: tuple[CapitalRiskObservation, ...],
    instrument: Instrument,
    entry_price: Decimal,
    stop_distance: Decimal,
    fee_bound: Decimal | None,
) -> CapitalEntryDecision:
    """Recompute original loss state, then reuse canonical research sizing."""
    result = replay_capital_risk(
        loaded=loaded, initial_cash=initial_cash, events=events, observations=observations
    )
    return _entry(loaded, result, instrument, entry_price, stop_distance, fee_bound)


def evaluate_capital_action_entry(
    *,
    loaded: LoadedConfig,
    initial_cash: Decimal,
    events: tuple[CapitalAccountEvent | CapitalActionEvent, ...],
    observations: tuple[CapitalRiskObservation, ...],
    instrument: Instrument,
    entry_price: Decimal,
    stop_distance: Decimal,
    fee_bound: Decimal | None,
) -> CapitalEntryDecision:
    """Reconstruct action-aware losses before the shared entry/sizing gate."""
    result = replay_capital_action_risk(
        loaded=loaded, initial_cash=initial_cash, events=events, observations=observations
    )
    return _entry(loaded, result, instrument, entry_price, stop_distance, fee_bound)


def _entry(
    loaded: LoadedConfig,
    result: CapitalRiskReplay,
    instrument: Instrument,
    entry_price: Decimal,
    stop_distance: Decimal,
    fee_bound: Decimal | None,
) -> CapitalEntryDecision:
    current = result.points[-1]
    if not current.decision.new_entries_allowed:
        return CapitalEntryDecision(
            False, _ZERO, _ZERO, _ZERO, _ZERO, current.decision.reason_code, loaded.config_hash
        )
    if not current.account.complete:
        return CapitalEntryDecision(
            False, _ZERO, _ZERO, _ZERO, _ZERO, "account_episode_incomplete", loaded.config_hash
        )
    with localcontext(_CONTEXT):
        return size_capital_entry(
            loaded=loaded,
            instrument=instrument,
            equity=current.equity,
            settled_cash=current.account.available_cash,
            entry_price=entry_price,
            stop_distance=stop_distance,
            fee_bound=fee_bound,
            position_open=current.account.quantity > 0,
            daily_loss=current.snapshot.daily_loss_pct * current.equity / _HUNDRED,
        )
