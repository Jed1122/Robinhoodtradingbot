"""Zero-tolerance options comparison and incidents, with no execution dependency."""

from dataclasses import fields
from datetime import datetime
from decimal import Decimal, localcontext

from trading_bot.clock import require_utc
from trading_bot.domain import AccountId, OrderState, Side
from trading_bot.domain.decimal_utils import DomainValidationError, require_bounded_decimal
from trading_bot.domain.options import OptionContract, PositionEffect
from trading_bot.domain.options_account import (
    ObservedOptionFill,
    ObservedOptionLifecycle,
    ObservedOptionOrder,
    ObservedOptionPosition,
    ObservedOptionSettlement,
    ObservedSharePosition,
    OptionsAccountSnapshot,
    OptionsCash,
    OptionsSnapshotSection,
    OwnedOptionPosition,
    observation_id,
    observation_rows,
)
from trading_bot.reconciliation.models import ReconciliationDifference, ReconciliationResult
from trading_bot.reconciliation.service import _compare_by_key


def _incident(items: list[ReconciliationDifference], code: str, identity: str) -> None:
    # Do not echo raw provider payloads, account numbers or exception text.
    items.append(ReconciliationDifference(code, identity, None, None))


def _inspect(
    snapshot: OptionsAccountSnapshot,
    side: str,
    expected: dict[str, int],
    as_of: datetime,
    max_age_seconds: Decimal,
    differences: list[ReconciliationDifference],
) -> None:
    def incident(code: str, identity: str = "snapshot") -> None:
        _incident(differences, f"{side}_{code}", identity)

    if set(snapshot.complete_sections) != set(OptionsSnapshotSection):
        incident("snapshot_incomplete")
    if snapshot.observed_at > as_of:
        incident("snapshot_future")
    if Decimal(str((as_of - snapshot.observed_at).total_seconds())) > max_age_seconds:
        incident("snapshot_stale")
    for field in fields(OptionsCash):
        if getattr(snapshot.cash, field.name) < 0:
            incident("negative_cash" if field.name == "settled_cash" else f"negative_{field.name}")
    contracts = {row.contract_id: row for row in snapshot.contracts}
    for contract in snapshot.contracts:
        if contract.available_at > snapshot.observed_at:
            incident("options_contract_future", contract.contract_id)
    positions = {row.contract_id: row for row in snapshot.positions}
    for identity in sorted(positions.keys() | expected.keys()):
        position = positions.get(identity)
        quantity = 0 if position is None else position.quantity
        if quantity != expected.get(identity, 0):
            incident("options_ownership_mismatch", identity)
    for position in snapshot.positions:
        if position.contract_id not in contracts:
            incident("options_contract_missing", position.contract_id)
        if position.quantity and position.broker_mark is None:
            incident("options_broker_mark_missing", position.contract_id)
        for name in ("pending_exercise", "pending_assignment", "pending_expiration"):
            if getattr(position, name):
                incident(f"options_{name}", position.contract_id)
    for share in snapshot.shares:
        if share.quantity:
            incident("unexpected_shares", share.symbol)
    orders = {row.order_id: row for row in snapshot.orders}
    filled: dict[tuple[str, str, Side, PositionEffect], int] = {}
    for fill in snapshot.fills:
        key = (fill.order_id, fill.contract_id, fill.side, fill.effect)
        filled[key] = filled.get(key, 0) + fill.quantity
    for order in snapshot.orders:
        if order.state in (
            OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
            OrderState.SUBMISSION_PENDING,
        ):
            incident("options_unknown_order", order.order_id)
        if (
            not snapshot.history_start
            <= order.created_at
            <= order.updated_at
            <= snapshot.observed_at
        ):
            incident("options_order_outside_history", order.order_id)
        if (
            order.filled_quantity > order.quantity
            or (order.state is OrderState.FILLED and order.filled_quantity != order.quantity)
            or (
                order.state is OrderState.PARTIALLY_FILLED
                and not 0 < order.filled_quantity < order.quantity
            )
            or (
                order.state
                in (
                    OrderState.PROPOSED,
                    OrderState.RISK_REJECTED,
                    OrderState.RISK_APPROVED,
                    OrderState.REVIEW_REQUESTED,
                    OrderState.REVIEWED,
                    OrderState.SUBMITTED,
                    OrderState.REJECTED,
                )
                and order.filled_quantity
            )
        ):
            incident("options_order_quantity_inconsistent", order.order_id)
        if len({leg.contract_id for leg in order.legs}) != len(order.legs):
            incident("options_duplicate_order_leg", order.order_id)
        for leg in order.legs:
            if leg.contract_id not in contracts:
                incident("options_contract_missing", leg.contract_id)
            key = (order.order_id, leg.contract_id, leg.side, leg.effect)
            if filled.get(key, 0) != order.filled_quantity * leg.ratio:
                incident("options_fill_quantity_mismatch", order.order_id)
    for fill in snapshot.fills:
        fill_order = orders.get(fill.order_id)
        if fill_order is None:
            incident("options_orphan_fill", fill.fill_id)
        elif not any(
            (fill.contract_id, fill.side, fill.effect) == (leg.contract_id, leg.side, leg.effect)
            for leg in fill_order.legs
        ):
            incident("options_fill_leg_mismatch", fill.fill_id)
        if not snapshot.history_start <= fill.occurred_at <= snapshot.observed_at:
            incident("options_fill_outside_history", fill.fill_id)
        elif (
            fill_order is not None
            and not fill_order.created_at <= fill.occurred_at <= fill_order.updated_at
        ):
            incident("options_fill_outside_order", fill.fill_id)
    for settlement in snapshot.settlements:
        if settlement.contract_id not in contracts:
            incident("options_contract_missing", settlement.contract_id)
        if not settlement.completed and settlement.due_at <= as_of:
            incident("options_settlement_overdue", settlement.settlement_id)
    # Existing financial values are bounded to 512 digits; 2048 digits retain
    # their complete magnitude range plus the 10,000-row format ceiling.
    with localcontext() as context:
        context.prec = 2048
        receivable = sum(
            (max(Decimal("0"), row.amount) for row in snapshot.settlements if not row.completed),
            Decimal("0"),
        )
        payable = sum(
            (max(Decimal("0"), -row.amount) for row in snapshot.settlements if not row.completed),
            Decimal("0"),
        )
    if (receivable, payable) != (
        snapshot.cash.unsettled_receivable,
        snapshot.cash.unsettled_payable,
    ):
        incident("options_settlement_cash_mismatch")
    for event in snapshot.lifecycle:
        # No acknowledgement/remediation authority exists in this development slice.
        incident(f"options_{event.kind.value}", event.event_id)
        if event.contract_id not in contracts:
            incident("options_contract_missing", event.contract_id)
        if not snapshot.history_start <= event.occurred_at <= snapshot.observed_at:
            incident("options_lifecycle_outside_history", event.event_id)


def reconcile_options(
    *,
    account_id: AccountId,
    local: OptionsAccountSnapshot,
    broker: OptionsAccountSnapshot,
    owned_positions: tuple[OwnedOptionPosition, ...],
    as_of: datetime,
    max_age_seconds: Decimal,
    reconciliation_id: str,
) -> ReconciliationResult:
    """Compare full-window observations. A clean result never authorizes an order.

    The caller must establish authentic snapshot completeness and local ownership.
    This function does not infer either from matching provider/local numbers.
    """
    observation_id(account_id)
    observation_id(reconciliation_id)
    require_utc(as_of)
    require_bounded_decimal(max_age_seconds, "max_age_seconds", positive=True)
    if type(local) is not OptionsAccountSnapshot or type(broker) is not OptionsAccountSnapshot:
        raise DomainValidationError("exact options snapshots required")
    observation_rows(owned_positions, OwnedOptionPosition)
    differences: list[ReconciliationDifference] = []
    if local.account_id != account_id or broker.account_id != account_id:
        _incident(differences, "options_account_mismatch", "account")
    if local.history_start != broker.history_start:
        _incident(differences, "options_history_window_mismatch", "history")
    expected: dict[str, int] = {}
    position_ids: set[str] = set()
    for position in owned_positions:
        if position.position_id in position_ids:
            _incident(differences, "ambiguous_options_ownership", position.position_id)
        position_ids.add(position.position_id)
        for leg in position.structure.legs:
            identity = leg.contract.contract_id
            if identity in expected:
                _incident(differences, "ambiguous_options_ownership", identity)
            expected[identity] = position.units * leg.ratio * (1 if leg.side is Side.BUY else -1)
            for observed in (local, broker):
                if leg.contract not in observed.contracts:
                    _incident(differences, "options_owned_contract_mismatch", identity)
    for field in fields(OptionsCash):
        if getattr(local.cash, field.name) != getattr(broker.cash, field.name):
            differences.append(
                ReconciliationDifference(
                    f"options_cash_{field.name}_mismatch",
                    "cash",
                    str(getattr(local.cash, field.name)),
                    str(getattr(broker.cash, field.name)),
                )
            )
    for name, kind, key, code in (
        ("contracts", OptionContract, "contract_id", "contract"),
        ("positions", ObservedOptionPosition, "contract_id", "position"),
        ("orders", ObservedOptionOrder, "order_id", "order"),
        ("fills", ObservedOptionFill, "fill_id", "fill"),
        ("shares", ObservedSharePosition, "symbol", "share"),
        ("settlements", ObservedOptionSettlement, "settlement_id", "settlement"),
        ("lifecycle", ObservedOptionLifecycle, "event_id", "lifecycle"),
    ):
        _compare_by_key(
            getattr(local, name),
            getattr(broker, name),
            key=key,
            code=f"options_{code}",
            values=tuple(field.name for field in fields(kind) if field.name != key),
            differences=differences,
        )
    _inspect(local, "local", expected, as_of, max_age_seconds, differences)
    _inspect(broker, "broker", expected, as_of, max_age_seconds, differences)
    return ReconciliationResult(
        reconciliation_id, account_id, not differences, tuple(differences), as_of
    )
