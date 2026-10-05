"""Transaction-owned execution journal; no transport, cash owner or promotion writer."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import NoReturn

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.clock import require_utc
from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrder,
    BrokerOrderId,
    BrokerOrderReview,
    ClientOrderId,
    ConfigHash,
    DataHash,
    Fill,
    FillId,
    InstrumentId,
    OrderEvent,
    OrderId,
    OrderIntentId,
    OrderPurpose,
    OrderState,
    OrderType,
    Side,
    TimeInForce,
)
from trading_bot.domain.owned_order_lifecycle import (
    MAX_EVENTS,
    VERSION,
    OwnedOrderEvent,
    advance_owned_order,
    decode_owned_event,
    encode_owned_event,
)
from trading_bot.persistence.base import PersistenceDataError
from trading_bot.persistence.evidence import (
    canonical_broker_order_response_sha256,
    canonical_order_intent_sha256,
    canonical_review_response_sha256,
    order_intent_from_row,
)
from trading_bot.persistence.models import (
    BrokerReviewRow,
    FillRow,
    OrderIntentRow,
    OrderRow,
    OrderTransitionRow,
    OwnedOrderEventRow,
    SubmissionAttemptRow,
)
from trading_bot.risk.pretrade import canonical_review_payload_sha256


class OwnedOrderJournalError(PersistenceDataError):
    def __init__(self) -> None:
        super().__init__("owned_order_journal_invalid")


def _deny() -> NoReturn:
    raise OwnedOrderJournalError() from None


def _identity(value: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > 255:
        _deny()


def _hash(values: list[object]) -> str:
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode(
            "ascii"
        )
    ).hexdigest()


def _order(row: OrderRow) -> BrokerOrder:
    return BrokerOrder(
        OrderId(row.id),
        BrokerOrderId(row.broker_order_id),
        AccountId(row.account_id),
        None if row.intent_id is None else OrderIntentId(row.intent_id),
        None if row.client_order_id is None else ClientOrderId(row.client_order_id),
        InstrumentId(row.instrument_id),
        Side(row.side),
        OrderPurpose(row.purpose),
        OrderType(row.order_type),
        TimeInForce(row.time_in_force),
        row.requested_quantity,
        row.filled_quantity,
        row.limit_price,
        row.stop_price,
        OrderState(row.state),
        row.created_at,
        row.updated_at,
        DataHash(row.data_hash),
    )


def _fill(row: FillRow) -> Fill:
    return Fill(
        FillId(row.id),
        BrokerOrderId(row.broker_order_id),
        AccountId(row.account_id),
        InstrumentId(row.instrument_id),
        Side(row.side),
        row.quantity,
        row.price,
        row.fee,
        row.occurred_at,
        DataHash(row.data_hash),
    )


async def _anchor(
    session: AsyncSession, row: OrderRow
) -> tuple[BrokerOrder, OrderIntentRow, SubmissionAttemptRow]:
    if row.intent_id is None or row.review_id is None or row.submission_attempt_id is None:
        _deny()
    order = _order(row)
    intent = await session.get(OrderIntentRow, row.intent_id)
    review = await session.get(BrokerReviewRow, row.review_id)
    attempt = await session.get(SubmissionAttemptRow, row.submission_attempt_id)
    if (
        intent is None
        or review is None
        or attempt is None
        or intent.asset_class != AssetClass.EQUITY.value
        or order.state is not OrderState.SUBMITTED
        or order.filled_quantity != 0
        or row.average_fill_price is not None
        or attempt.outcome_class != "accepted"
        or attempt.completed_at is None
        or attempt.sanitized_response_hash != canonical_broker_order_response_sha256(order)
        or (
            attempt.intent_id,
            attempt.review_id,
            attempt.account_id,
            attempt.instrument_id,
            attempt.provider,
            attempt.provider_client_reference,
        )
        != (
            row.intent_id,
            row.review_id,
            row.account_id,
            row.instrument_id,
            row.provider,
            row.client_order_id,
        )
        or review.intent_id != intent.id
        or review.client_order_id != row.client_order_id
        or (
            intent.account_id,
            intent.instrument_id,
            intent.side,
            intent.purpose,
            intent.order_type,
            intent.time_in_force,
            intent.quantity,
            intent.limit_price,
            intent.stop_price,
        )
        != (
            row.account_id,
            row.instrument_id,
            row.side,
            row.purpose,
            row.order_type,
            row.time_in_force,
            row.requested_quantity,
            row.limit_price,
            row.stop_price,
        )
    ):
        _deny()
    normalized = order_intent_from_row(intent)
    reconstructed_review = BrokerOrderReview(
        normalized_order=normalized,
        source=review.source,
        reviewed_at=review.reviewed_at,
        expires_at=review.expires_at,
        estimated_notional=review.estimated_notional,
        estimated_fees=review.estimated_fees,
        client_order_id=(
            None if review.client_order_id is None else ClientOrderId(review.client_order_id)
        ),
        outbound_payload_sha256=review.outbound_payload_sha256,
        broker_review_id=review.broker_review_id,
    )
    if (
        review.normalized_intent_hash != canonical_order_intent_sha256(normalized)
        or review.sanitized_response_hash != canonical_review_response_sha256(reconstructed_review)
        or review.outbound_payload_sha256
        != canonical_review_payload_sha256(normalized, client_order_id=order.client_order_id)
        or not normalized.created_at <= review.reviewed_at <= attempt.attempt_started_at
        or not attempt.attempt_started_at < review.expires_at
        or attempt.completed_at < attempt.attempt_started_at
    ):
        _deny()
    return order, intent, attempt


async def _recover(
    session: AsyncSession, row: OrderRow
) -> tuple[BrokerOrder, list[OwnedOrderEventRow], str]:
    order, intent, attempt = await _anchor(session, row)
    head = _hash([VERSION, row.provider, canonical_broker_order_response_sha256(order)])
    journals = list(
        await session.scalars(
            select(OwnedOrderEventRow)
            .where(OwnedOrderEventRow.order_id == row.id)
            .order_by(OwnedOrderEventRow.sequence)
            .limit(MAX_EVENTS + 1)
        )
    )
    fills = list(
        await session.scalars(
            select(FillRow).where(FillRow.order_id == row.id).limit(MAX_EVENTS + 1)
        )
    )
    transitions = list(
        await session.scalars(
            select(OrderTransitionRow)
            .where(OrderTransitionRow.order_id == row.id)
            .limit(MAX_EVENTS + 2)
        )
    )
    if len(journals) > MAX_EVENTS or len(fills) > MAX_EVENTS or len(transitions) > MAX_EVENTS + 1:
        _deny()
    fill_map = {item.id: item for item in fills}
    transition_map = {item.id: item for item in transitions}
    consumed_fills: set[str] = set()
    consumed_transitions: set[str] = set()
    for ordinal, journal in enumerate(journals):
        event = decode_owned_event(journal.payload_json)
        if (
            journal.sequence != ordinal
            or journal.id != event.id
            or journal.intent_id != row.intent_id
            or event.order_id != row.id
            or journal.previous_hash != head
        ):
            _deny()
        fill = event.fill
        if fill is not None:
            stored_fill = fill_map.get(fill.id)
            if (
                stored_fill is None
                or journal.fill_id != fill.id
                or _fill(stored_fill) != fill
                or stored_fill.provider != row.provider
                or stored_fill.external_execution_key != event.external_execution_key
                or stored_fill.occurrence_ordinal != event.occurrence_ordinal
                or event.occurrence_ordinal != len(consumed_fills)
                or fill.id in consumed_fills
            ):
                _deny()
            consumed_fills.add(fill.id)
        elif journal.fill_id is not None:
            _deny()
        projected = advance_owned_order(order, event)
        expected_transition = _hash([VERSION, "transition", event.id])
        stored_transition = transition_map.get(expected_transition)
        if (
            journal.transition_id != expected_transition
            or stored_transition is None
            or (
                stored_transition.intent_id,
                stored_transition.from_state,
                stored_transition.event,
                stored_transition.to_state,
                stored_transition.occurred_at,
                stored_transition.actor,
                stored_transition.reason_code,
                stored_transition.correlation_id,
                stored_transition.corrects_id,
            )
            != (
                row.intent_id,
                order.state.value,
                event.event.value,
                projected.state.value,
                event.occurred_at,
                "owned_execution",
                "owned_lifecycle_fact",
                event.id,
                None,
            )
        ):
            _deny()
        if stored_transition.config_hash != intent.config_hash:
            _deny()
        consumed_transitions.add(expected_transition)
        order_hash = canonical_broker_order_response_sha256(projected)
        expected_head = _hash([VERSION, ordinal, head, journal.payload_json, order_hash])
        if journal.order_hash != order_hash or journal.event_hash != expected_head:
            _deny()
        head, order = expected_head, projected
    if consumed_fills != set(fill_map):
        _deny()
    original_acceptance = [item for item in transitions if item.id not in consumed_transitions]
    if len(original_acceptance) > 1:
        _deny()
    for item in original_acceptance:
        acceptance_id = (
            "transition-accepted-"
            + hashlib.sha256(f"{intent.id}|transition-accepted".encode()).hexdigest()
        )
        correlation_id = (
            "execution-" + hashlib.sha256(f"{intent.id}|execution".encode()).hexdigest()
        )
        if (
            item.id,
            item.intent_id,
            item.order_id,
            item.from_state,
            item.event,
            item.to_state,
            item.actor,
            item.reason_code,
            item.occurred_at,
            item.config_hash,
            item.correlation_id,
            item.corrects_id,
        ) != (
            acceptance_id,
            intent.id,
            row.id,
            OrderState.SUBMISSION_PENDING.value,
            OrderEvent.BROKER_ACCEPTED.value,
            OrderState.SUBMITTED.value,
            "execution-service",
            "broker_accepted",
            attempt.completed_at,
            intent.config_hash,
            correlation_id,
            None,
        ):
            _deny()
    return order, journals, head


async def get_owned_order(session: AsyncSession, order_id: OrderId) -> BrokerOrder | None:
    try:
        _identity(order_id)
        row = await session.get(OrderRow, order_id)
        return None if row is None else (await _recover(session, row))[0]
    except (ValueError, TypeError, AttributeError, SQLAlchemyError):
        _deny()


async def record_owned_event(
    session: AsyncSession, event: OwnedOrderEvent, ensure_config: Callable[[ConfigHash], None]
) -> bool:
    try:
        payload = encode_owned_event(event)
        row = await session.get(OrderRow, event.order_id)
        if row is None:
            _deny()
        order, journals, head = await _recover(session, row)
        intent = await session.get(OrderIntentRow, row.intent_id)
        if intent is None:
            _deny()
        ensure_config(ConfigHash(intent.config_hash))
        existing = await session.get(OwnedOrderEventRow, event.id)
        if existing is not None:
            if existing.order_id != row.id or existing.payload_json != payload:
                _deny()
            return False
        if len(journals) >= MAX_EVENTS:
            _deny()
        projected = advance_owned_order(order, event)
        fill = event.fill
        if fill is not None:
            if event.occurrence_ordinal != sum(item.fill_id is not None for item in journals):
                _deny()
            collision = await session.scalar(
                select(FillRow).where(
                    or_(
                        FillRow.id == fill.id,
                        (FillRow.provider == row.provider)
                        & (FillRow.external_execution_key == event.external_execution_key),
                    )
                )
            )
            if collision is not None:
                _deny()
            stored_fill = FillRow(
                id=fill.id,
                order_id=row.id,
                provider=row.provider,
                external_execution_key=event.external_execution_key,
                broker_order_id=fill.broker_order_id,
                account_id=fill.account_id,
                instrument_id=fill.instrument_id,
                side=fill.side.value,
                quantity=fill.quantity,
                price=fill.price,
                fee=fill.fee,
                occurred_at=fill.occurred_at,
                occurrence_ordinal=event.occurrence_ordinal,
                data_hash=fill.data_hash,
            )
            session.add(stored_fill)
            await session.flush((stored_fill,))
        transition_id = _hash([VERSION, "transition", event.id])
        stored_transition = OrderTransitionRow(
            id=transition_id,
            intent_id=row.intent_id,
            order_id=row.id,
            from_state=order.state.value,
            event=event.event.value,
            to_state=projected.state.value,
            actor="owned_execution",
            reason_code="owned_lifecycle_fact",
            occurred_at=event.occurred_at,
            config_hash=intent.config_hash,
            correlation_id=event.id,
            corrects_id=None,
        )
        session.add(stored_transition)
        await session.flush((stored_transition,))
        order_hash = canonical_broker_order_response_sha256(projected)
        stored_event = OwnedOrderEventRow(
            id=event.id,
            order_id=row.id,
            intent_id=row.intent_id,
            sequence=len(journals),
            payload_json=payload,
            previous_hash=head,
            order_hash=order_hash,
            event_hash=_hash([VERSION, len(journals), head, payload, order_hash]),
            transition_id=transition_id,
            fill_id=None if fill is None else fill.id,
        )
        session.add(stored_event)
        await session.flush((stored_event,))
        return True
    except (ValueError, TypeError, AttributeError, SQLAlchemyError):
        _deny()


class SqlFillReader:
    """Read exact existing fill facts; never adopts history or infers absent fees."""

    def __init__(self, session: AsyncSession, *, ensure_active: Callable[[], None]) -> None:
        self._session = session
        self._ensure_active = ensure_active

    async def get(self, fill_id: FillId) -> Fill | None:
        self._ensure_active()
        try:
            _identity(fill_id)
            row = await self._session.get(FillRow, fill_id)
            return None if row is None else _fill(row)
        except (ValueError, TypeError, AttributeError, SQLAlchemyError):
            _deny()

    async def list_for_account(self, account_id: AccountId, since: datetime) -> tuple[Fill, ...]:
        self._ensure_active()
        try:
            _identity(account_id)
            require_utc(since)
            rows = list(
                await self._session.scalars(
                    select(FillRow)
                    .where(FillRow.account_id == account_id, FillRow.occurred_at >= since)
                    .order_by(FillRow.occurred_at, FillRow.id)
                    .limit(MAX_EVENTS + 1)
                )
            )
            if len(rows) > MAX_EVENTS:
                _deny()
            return tuple(_fill(row) for row in rows)
        except (ValueError, TypeError, AttributeError, SQLAlchemyError):
            _deny()


__all__ = ["OwnedOrderJournalError", "SqlFillReader", "get_owned_order", "record_owned_event"]
