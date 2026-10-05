"""Same-session economic/execution publication; no independent commit or live fence."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.accounting.owned_economic_codec import (
    decode_economic_event,
    encode_economic_event,
)
from trading_bot.accounting.owned_economic_models import (
    MAX_EVENTS,
    VERSION,
    Bind,
    EconomicEvent,
    EconomicState,
    Execution,
    Reserve,
    deny,
    identity,
)
from trading_bot.accounting.owned_economic_projection import project_economics_and_references
from trading_bot.domain import AccountId, CodeHash, ConfigHash
from trading_bot.domain.owned_order_lifecycle import encode_owned_event
from trading_bot.logging import contains_registered_secret
from trading_bot.persistence.evidence import (
    canonical_broker_order_response_sha256,
    order_intent_from_row,
)
from trading_bot.persistence.models import (
    AccountRow,
    OrderIntentRow,
    OrderRow,
    OwnedEconomicEventRow,
    OwnedOrderEventRow,
    SubmissionAttemptRow,
)
from trading_bot.persistence.owned_order_journal import get_owned_order, record_owned_event

_GENESIS = "0" * 64


class EconomicRepository(Protocol):
    async def append(self, event: EconomicEvent) -> bool: ...
    async def get(self, account_id: AccountId) -> EconomicState | None: ...


def _screen(value: Any) -> None:
    if isinstance(value, Enum):
        _screen(value.value)
        return
    if isinstance(value, str) and contains_registered_secret(value):
        deny()
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            _screen(getattr(value, field.name))


def _hash(row: OwnedEconomicEventRow) -> str:
    values = [
        VERSION,
        row.id,
        row.account_id,
        row.sequence,
        row.config_hash,
        row.code_hash,
        row.payload_json,
        row.previous_hash,
        row.intent_id,
        row.order_id,
        row.owned_event_id,
    ]
    return hashlib.sha256(
        json.dumps(values, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode(
            "ascii"
        )
    ).hexdigest()


class SqlEconomicRepository:
    def __init__(
        self,
        session: AsyncSession,
        *,
        code_hash: CodeHash,
        ensure_active: Callable[[], None],
        ensure_config: Callable[[ConfigHash], None],
        mark_failed: Callable[[], None],
    ) -> None:
        self._session, self._code_hash = session, code_hash
        self._ensure_active, self._ensure_config, self._mark_failed = (
            ensure_active,
            ensure_config,
            mark_failed,
        )

    async def _recover(
        self, account_id: AccountId
    ) -> tuple[EconomicState | None, tuple[EconomicEvent, ...], str]:
        identity(account_id)
        if contains_registered_secret(account_id):
            deny()
        rows = list(
            await self._session.scalars(
                select(OwnedEconomicEventRow)
                .where(OwnedEconomicEventRow.account_id == account_id)
                .order_by(OwnedEconomicEventRow.sequence)
                .limit(MAX_EVENTS + 1)
            )
        )
        if not rows:
            return None, (), _GENESIS
        if len(rows) > MAX_EVENTS:
            deny()
        events: list[EconomicEvent] = []
        head = _GENESIS
        for sequence, row in enumerate(rows):
            event = decode_economic_event(row.payload_json)
            _screen(event)
            if (
                row.sequence != sequence
                or row.id != event.id
                or row.account_id != event.account_id
                or row.config_hash != event.config_hash
                or row.previous_hash != head
                or row.event_hash != _hash(row)
            ):
                deny()
            head = row.event_hash
            events.append(event)
        frozen = tuple(events)
        state, refs = project_economics_and_references(frozen)
        bound: set[str] = set()
        expected_owned: dict[str, str] = {}
        for row, event, reference in zip(rows, frozen, refs, strict=True):
            if (row.intent_id, row.order_id, row.owned_event_id) != reference:
                deny()
            p = event.payload
            if type(p) is Reserve:
                intent = await self._session.get(OrderIntentRow, p.intent.id)
                if intent is None or order_intent_from_row(intent) != p.intent:
                    deny()
            elif type(p) is Bind:
                if await get_owned_order(self._session, p.order.id) is None:
                    deny()
                order = await self._session.get(OrderRow, p.order.id)
                if order is None:
                    deny()
                attempt = await self._session.get(SubmissionAttemptRow, order.submission_attempt_id)
                if (
                    attempt is None
                    or attempt.sanitized_response_hash
                    != canonical_broker_order_response_sha256(p.order)
                ):
                    deny()
                bound.add(p.order.id)
            elif type(p) is Execution:
                expected_owned[p.event.id] = encode_owned_event(p.event)
        if bound:
            owned = list(
                await self._session.scalars(
                    select(OwnedOrderEventRow)
                    .where(OwnedOrderEventRow.order_id.in_(bound))
                    .limit(MAX_EVENTS + 1)
                )
            )
            if len(owned) > MAX_EVENTS or {r.id for r in owned} != set(expected_owned):
                deny()
            for owned_row in owned:
                if owned_row.payload_json != expected_owned[owned_row.id]:
                    deny()
        return state, frozen, head

    async def get(self, account_id: AccountId) -> EconomicState | None:
        self._ensure_active()
        try:
            return (await self._recover(account_id))[0]
        except Exception:
            self._mark_failed()
            try:
                await self._session.rollback()
            finally:
                deny()
        except BaseException:
            self._mark_failed()
            await self._session.rollback()
            raise

    async def append(self, event: EconomicEvent) -> bool:
        self._ensure_active()
        try:
            if type(event) is not EconomicEvent:
                deny()
            event.__post_init__()
            _screen(event)
            payload = encode_economic_event(event)
            self._ensure_config(event.config_hash)
            state, events, head = await self._recover(event.account_id)
            existing = await self._session.get(OwnedEconomicEventRow, event.id)
            if existing is not None:
                if existing.account_id != event.account_id or existing.payload_json != payload:
                    deny()
                return False
            if (
                len(events) >= MAX_EVENTS
                or await self._session.get(AccountRow, event.account_id) is None
            ):
                deny()
            del state
            prospective = (*events, event)
            _, refs = project_economics_and_references(prospective)
            intent_id, order_id, owned_id = refs[-1]
            p = event.payload
            if type(p) is Reserve:
                intent = await self._session.get(OrderIntentRow, p.intent.id)
                if intent is None or order_intent_from_row(intent) != p.intent:
                    deny()
            elif type(p) is Bind:
                current = await get_owned_order(self._session, p.order.id)
                if current != p.order:
                    deny()
            elif type(p) is Execution:
                if not await record_owned_event(self._session, p.event, self._ensure_config):
                    deny()
            row = OwnedEconomicEventRow(
                id=event.id,
                account_id=event.account_id,
                sequence=len(events),
                payload_json=payload,
                config_hash=event.config_hash,
                code_hash=self._code_hash,
                previous_hash=head,
                event_hash=_GENESIS,
                intent_id=intent_id,
                order_id=order_id,
                owned_event_id=owned_id,
            )
            row.event_hash = _hash(row)
            self._session.add(row)
            await self._session.flush((row,))
            await self._recover(event.account_id)
            return True
        except Exception:
            self._mark_failed()
            try:
                await self._session.rollback()
            finally:
                deny()
        except BaseException:
            self._mark_failed()
            await self._session.rollback()
            raise
