"""Durable once-only fictional current-stock execution; no broker capability.

The owner commits an actual paper cash/share reservation before exposing a
simulation ticket. No SDK, account discovery, credential or live transport exists.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Context, Decimal, localcontext
from enum import Enum
from fractions import Fraction
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import (
    BaseModel,
    Field,
    ModelWrapValidatorHandler,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from trading_bot.clock import Clock, require_utc
from trading_bot.config.hybrid import HybridSettings
from trading_bot.domain import (
    BrokerOrder,
    BrokerOrderReview,
    CancelReceipt,
    ExecutionMode,
    Fill,
    OrderState,
    PersistedReviewedOrder,
    ReviewId,
    SubmissionAttemptId,
)
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.domain.order_matching import broker_order_matches_submission, review_matches_intent
from trading_bot.execution.idempotency import derive_deduplication_key
from trading_bot.execution.review import review_is_fresh
from trading_bot.execution.stock_intents import (
    PreparedStockExecution,
    StockExecutionContext,
    StockExecutionSelection,
    StockSimulationGrant,
    prepare_stock_execution,
    stock_simulation_account_hash,
)
from trading_bot.hybrid.execution import (
    cancel_order,
    fill_order,
    mark_account,
    reserve_order,
    settle,
)
from trading_bot.hybrid.models import Account, Fact, FillFact, Quote
from trading_bot.market_data.recording import content_hash
from trading_bot.persistence.hybrid_journal import HybridJournal, HybridJournalFactory
from trading_bot.risk import canonical_review_payload_sha256

_PROFILE: Literal["current-stock-simulation-account-v1"] = "current-stock-simulation-account-v1"
_CONTEXT = Context(prec=50, capitals=1)
_BASE_FIELDS = set(Account.model_fields)
Phase = Literal[
    "reserved", "submitting", "ambiguous", "submitted", "partial", "cancel_pending", "terminal"
]
Diagnostic = Literal["none", "transport_ambiguous", "cancel_ambiguous", "unreconciled_order_state"]


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("stock_simulation_unavailable")


def _record(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _record(value.model_dump())
    if is_dataclass(value) and not isinstance(value, type):
        return _record(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if type(value) is Decimal:
        with localcontext(_CONTEXT):
            return str(value)
    if isinstance(value, dict):
        return {key: _record(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_record(item) for item in value]
    _check(value is None or type(value) in (str, int, bool))
    return value


def _hash(value: object) -> str:
    return str(content_hash(_record(value)))


def _base(state: Account) -> Account:
    return Account.model_validate(state.model_dump(include=_BASE_FIELDS))


class StockSimulationAttempt(Fact):
    prepared: PreparedStockExecution
    grant: StockSimulationGrant
    selection: StockExecutionSelection
    prepared_hash: str
    reserved_account_hash: str
    reserved_at: datetime
    phase: Phase = "reserved"
    last_observed_at: datetime
    submitted_at: datetime | None = None
    submission: PersistedReviewedOrder | None = None
    broker_order: BrokerOrder | None = None
    cancel_receipt: CancelReceipt | None = None
    diagnostic: Diagnostic = "none"
    terminal_state: OrderState | None = None
    fill_facts: tuple[Fill, ...] = Field(default=(), max_length=10000)

    @field_serializer("prepared")
    def _write_prepared(self, value: PreparedStockExecution) -> dict[str, Any]:
        return value.to_record()

    @field_validator("prepared", mode="before")
    @classmethod
    def _stored_prepared(cls, value: Any) -> PreparedStockExecution:
        if type(value) is PreparedStockExecution:
            return value
        _check(
            type(value) is dict and set(value) == {f.name for f in fields(PreparedStockExecution)}
        )
        data = dict(value)
        _check(data.pop("mode") == ExecutionMode.SIMULATION.value)
        for flag in ("live_authorized", "broker_transport_allowed", "reservations_created"):
            _check(data.pop(flag) is False)
        payload = dict(data["payloads"])
        terms_hash = payload.pop("terms_hash")
        binding_hash = payload.pop("order_binding_hash")
        data["payloads"] = payload
        restored = TypeAdapter(PreparedStockExecution).validate_python(data)
        _check(restored.payloads.terms_hash == terms_hash)
        _check(restored.payloads.order_binding_hash == binding_hash)
        return restored

    @field_validator("reserved_at", "last_observed_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def _bindings(self) -> StockSimulationAttempt:
        p, g = self.prepared, self.grant
        _require_sha256_hex(self.reserved_account_hash, "simulation_reserved_account")
        _check(p.evidence_hash == self.prepared_hash and p.approval_hash == g.evidence_hash)
        _check(p.selection_hash == self.selection.evidence_hash == g.selection_hash)
        _check(p.intent.id == p.paper_order.id == p.payloads.ref_id)
        _check(p.intent.account_id == g.simulation_account_id)
        _check(p.paper_order.symbol == self.selection.symbol == p.quote.symbol)
        _check(p.paper_order.sleeve == self.selection.sleeve == g.sleeve)
        _check(p.paper_order.quantity == p.intent.quantity == p.payloads.terms.quantity)
        _check(p.intent.account_id == p.payloads.terms.account_number)
        _check(p.intent.limit_price == p.paper_order.limit_price == p.payloads.terms.limit_price)
        _check(p.payloads.terms.symbol == p.paper_order.symbol)
        _check(p.payloads.terms.side == p.paper_order.side == p.intent.side.value)
        _ = p.payloads.review_arguments
        _ = p.payloads.place_arguments
        _check(
            p.paper_order.filled == 0
            and p.paper_order.reserved_cash == 0
            and p.paper_order.status == "open"
        )
        _check(g.approved_at <= p.created_at <= self.reserved_at < p.expires_at <= g.expires_at)
        _check(self.reserved_at <= self.last_observed_at)
        _check(
            (
                p.context_hash,
                p.plan_hash,
                p.policy_hash,
                p.source_config_hash,
                p.analysis_code_hash,
                p.execution_config_hash,
                p.source_report_body_sha256,
                p.before_account_hash,
            )
            == (
                g.context_hash,
                g.plan_hash,
                g.policy_hash,
                g.source_config_hash,
                g.analysis_code_hash,
                g.execution_config_hash,
                g.source_report_body_sha256,
                g.before_account_hash,
            )
        )
        if self.submission is not None:
            s = self.submission
            _check(s.execution_mode is ExecutionMode.SIMULATION and s.fencing_token == 0)
            _check(s.live_lease_id is s.live_lease_evidence_hash is None)
            _check(s.account_id == p.intent.account_id and s.config_hash == p.intent.config_hash)
            _check(s.review.normalized_order == p.intent)
            _check(s.deduplication_key == derive_deduplication_key(p.intent))
            _check(self.submitted_at is not None)
            if self.submitted_at is not None:
                require_utc(self.submitted_at)
                _check(
                    self.reserved_at <= self.submitted_at < min(p.expires_at, s.review.expires_at)
                )
        else:
            _check(self.submitted_at is None and self.phase == "reserved")
        if self.broker_order is not None:
            _check(self.submission is not None)
            if self.submission is not None:
                _check(broker_order_matches_submission(self.broker_order, self.submission))
        for fact in self.fill_facts:
            fact.__post_init__()
            _check(self.broker_order is not None and self.submitted_at is not None)
            if self.broker_order is not None and self.submitted_at is not None:
                _check(fact.broker_order_id == self.broker_order.broker_order_id)
                _check(
                    (fact.account_id, fact.instrument_id, fact.side)
                    == (p.intent.account_id, p.intent.instrument_id, p.intent.side)
                )
                _check(self.submitted_at <= fact.occurred_at <= self.last_observed_at)
        if self.phase in ("submitted", "partial", "cancel_pending", "terminal"):
            _check(self.broker_order is not None)
        if self.phase == "terminal":
            _check(
                self.terminal_state
                in (OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED, OrderState.EXPIRED)
            )
        else:
            _check(self.terminal_state is None)
        return self


class StockSimulationAccount(Account):
    simulation_profile: Literal["current-stock-simulation-account-v1"]
    simulation_account_id: str = Field(pattern=r"^sim-[A-Za-z0-9:_.-]{1,120}$")
    execution_config_hash: str
    execution_policy: HybridSettings
    attempts: tuple[StockSimulationAttempt, ...] = Field(default=(), max_length=1000)
    live_authorized: Literal[False] = False
    broker_transport_allowed: Literal[False] = False
    source_authenticated: Literal[False] = False
    broker_account_verified: Literal[False] = False

    @model_validator(mode="wrap")
    @classmethod
    def _validation_context(
        cls, value: Any, handler: ModelWrapValidatorHandler[StockSimulationAccount]
    ) -> StockSimulationAccount:
        with localcontext(_CONTEXT):
            return handler(value)

    @model_serializer(mode="wrap")
    def _serialization_context(self, handler: SerializerFunctionWrapHandler) -> Any:
        with localcontext(_CONTEXT):
            return handler(self)

    @field_validator(
        "live_authorized",
        "broker_transport_allowed",
        "source_authenticated",
        "broker_account_verified",
        mode="before",
    )
    @classmethod
    def _false_authority(cls, value: Any) -> Literal[False]:
        _check(value is False)
        return False

    @field_validator("execution_policy", mode="before")
    @classmethod
    def _stored_policy(cls, value: Any) -> HybridSettings:
        # Canonical local JSON stores Decimal as text; the config input model
        # intentionally rejects text. Restore only this closed storage schema.
        if type(value) is HybridSettings:
            return value
        _check(type(value) is dict and set(value) == set(HybridSettings.model_fields))
        restored = dict(value)
        for name in (
            "starting_capital_usd",
            "long_term_pct",
            "tactical_pct",
            "reserve_pct",
            "tactical_position_pct",
            "company_pct",
            "sector_pct",
            "monthly_operating_usd",
            "additional_monthly_budget_usd",
            "tax_rate",
            "principal_trigger_pct",
            "trailing_pct",
            "simulation_slippage_bps",
            "simulation_fee_usd",
        ):
            item = restored[name]
            if type(item) is str:
                _check(0 < len(item) <= 100)
                number = Decimal(item)
                _check(number.is_finite() and len(number.as_tuple().digits) <= 50)
                exponent = number.as_tuple().exponent
                _check(type(exponent) is int and -30 <= exponent <= 30)
                _check(number.copy_abs() <= Decimal("1e30"))
                _check(_record(number) == item)
                restored[name] = number
        return HybridSettings.model_validate(restored)

    @model_validator(mode="after")
    def _attempts(self) -> StockSimulationAccount:
        _check(
            self.live_authorized
            is self.broker_transport_allowed
            is self.source_authenticated
            is self.broker_account_verified
            is False
        )
        _require_sha256_hex(self.execution_config_hash, "simulation_execution_config")
        _check(self.execution_policy.live_enabled is False)
        orders = {x.id: x for x in self.orders}
        seen = set()
        seen_fills: set[str] = set()
        recorded_fills = {x.id: x for x in self.fills}
        for attempt in self.attempts:
            p = attempt.prepared
            _check(p.intent.id not in seen and p.intent.id in orders)
            seen.add(p.intent.id)
            _check(p.intent.account_id == self.simulation_account_id)
            _check(p.execution_config_hash == self.execution_config_hash)
            order = orders[p.intent.id]
            original = p.paper_order
            _check(
                (
                    order.id,
                    order.symbol,
                    order.side,
                    order.sleeve,
                    order.quantity,
                    order.limit_price,
                    order.risk_stop,
                    order.threshold,
                    order.reason,
                    order.episode_id,
                )
                == (
                    original.id,
                    original.symbol,
                    original.side,
                    original.sleeve,
                    original.quantity,
                    original.limit_price,
                    original.risk_stop,
                    original.threshold,
                    original.reason,
                    original.episode_id,
                )
            )
            for fact in attempt.fill_facts:
                _check(fact.id not in seen_fills and fact.id in recorded_fills)
                seen_fills.add(fact.id)
                actual = recorded_fills[fact.id]
                _check(
                    (actual.order_id, actual.quantity, actual.price, actual.fee, actual.at)
                    == (p.intent.id, fact.quantity, fact.price, fact.fee, fact.occurred_at)
                )
            _check(
                sum((Fraction(x.quantity) for x in attempt.fill_facts), Fraction(0))
                == Fraction(order.filled)
            )
            _check(
                (attempt.phase == "terminal")
                == (order.status in ("filled", "cancelled", "rejected"))
            )
            if attempt.phase == "partial":
                _check(order.status == "partial")
            if attempt.phase == "cancel_pending":
                _check(attempt.cancel_receipt is not None and attempt.cancel_receipt.accepted)
            if attempt.terminal_state is OrderState.REJECTED:
                _check(order.status == "rejected" and order.filled == 0)
        return self


@dataclass(frozen=True, slots=True, repr=False)
class StockSimulationReservation:
    prepared: PreparedStockExecution
    created: bool


@dataclass(frozen=True, slots=True, repr=False)
class StockSimulationTicket:
    prepared: PreparedStockExecution
    submission: PersistedReviewedOrder
    attempted_at: datetime


class StockSimulationJournal(HybridJournal):
    def __init__(
        self,
        factory: HybridJournalFactory,
        config_hash: str,
        *,
        simulation_account_id: str,
        policy: HybridSettings,
        clock: Clock,
    ) -> None:
        _check(type(simulation_account_id) is str and simulation_account_id.startswith("sim-"))
        _require_sha256_hex(config_hash, "simulation_execution_config")
        _check(type(policy) is HybridSettings and isinstance(clock, Clock))
        with localcontext(_CONTEXT):
            self._policy = HybridSettings.model_validate(policy.model_dump())
        self._simulation_id, self._execution_hash, self._clock = (
            simulation_account_id,
            config_hash,
            clock,
        )
        self._fresh: set[str] = set()
        super().__init__(
            factory, _hash((_PROFILE, config_hash, simulation_account_id, self._policy))
        )

    def _decode_account(self, raw: str) -> Account:
        state = StockSimulationAccount.model_validate_json(raw)
        _check(state.model_dump_json() == raw)
        _check(state.simulation_account_id == self._simulation_id)
        _check(
            state.execution_config_hash == self._execution_hash
            and state.execution_policy == self._policy
        )
        return state

    def _now(self) -> datetime:
        return require_utc(self._clock.now())

    @staticmethod
    def _state(value: Account) -> StockSimulationAccount:
        _check(type(value) is StockSimulationAccount)
        if not isinstance(value, StockSimulationAccount):
            raise ValueError("stock_simulation_unavailable")
        return value

    @staticmethod
    def _find(state: StockSimulationAccount, ref: str) -> StockSimulationAttempt:
        values = tuple(x for x in state.attempts if x.prepared.intent.id == ref)
        _check(len(values) == 1)
        return values[0]

    @staticmethod
    def _merge(
        state: StockSimulationAccount, base: Account, attempt: StockSimulationAttempt | None = None
    ) -> StockSimulationAccount:
        meta = state.model_dump(exclude=_BASE_FIELDS)
        if attempt is not None:
            ref = attempt.prepared.intent.id
            meta["attempts"] = tuple(
                attempt if x.prepared.intent.id == ref else x for x in state.attempts
            )
        return StockSimulationAccount.model_validate(base.model_dump() | meta)

    async def read_state(self) -> StockSimulationAccount:
        try:
            return self._state(await super().read())
        except Exception:
            raise ValueError("stock_simulation_unavailable") from None

    @staticmethod
    def _updated(attempt: StockSimulationAttempt, **changes: Any) -> StockSimulationAttempt:
        return StockSimulationAttempt.model_validate(attempt.model_dump() | changes)

    async def _mutate(
        self,
        ref: str,
        action: str,
        fact: object,
        operation: Callable[
            [StockSimulationAccount, StockSimulationAttempt, datetime],
            tuple[Account, StockSimulationAttempt],
        ],
    ) -> StockSimulationAttempt:
        request = {"ref": ref, "action": action, "fact": _record(fact)}
        event = "simulation:" + action + ":" + _hash(request)

        def transition(value: Account) -> Account:
            state = self._state(value)
            attempt = self._find(state, ref)
            now = self._now()
            _check(now >= attempt.last_observed_at)
            with localcontext(_CONTEXT):
                base, updated = operation(state, attempt, now)
                return self._merge(state, base, updated)

        state = self._state(
            await self.change(event, "fill" if action == "fill" else "order", request, transition)
        )
        return self._find(state, ref)

    async def claim_submission(
        self, intent_id: str, review: BrokerOrderReview
    ) -> StockSimulationTicket | None:
        if intent_id not in self._fresh:
            return None
        # Consumed before awaiting: racing callers cannot both acquire this local right.
        self._fresh.remove(intent_id)
        ticket: StockSimulationTicket | None = None
        try:
            _check(type(review) is BrokerOrderReview)

            def operation(
                state: StockSimulationAccount, a: StockSimulationAttempt, now: datetime
            ) -> tuple[Account, StockSimulationAttempt]:
                nonlocal ticket
                p = a.prepared
                _check(a.phase == "reserved" and a.submission is None)
                _check(not state.paused and not state.kill_switch)
                _check(a.reserved_account_hash == stock_simulation_account_hash(_base(state)))
                owned_order = next(x for x in state.orders if x.id == intent_id)
                _check(owned_order.status == "open" and owned_order.filled == 0)
                if owned_order.side == "buy":
                    _check(owned_order.sleeve != "tactical" or not state.tactical_suspended)
                    other_holds = state.reserved_cash - owned_order.reserved_cash
                    _check(
                        owned_order.reserved_cash <= state.cash - state.tax_reserve - other_holds
                    )
                else:
                    shares = sum(
                        (
                            x.quantity
                            for x in state.lots
                            if x.symbol == owned_order.symbol
                            and x.sleeve == owned_order.sleeve
                            and (
                                owned_order.episode_id is None
                                or x.episode_id == owned_order.episode_id
                            )
                        ),
                        Decimal(0),
                    )
                    _check(shares >= owned_order.quantity)
                _check(
                    a.reserved_at <= now < min(p.expires_at, a.grant.expires_at, review.expires_at)
                )
                review.__post_init__()
                _check(review_matches_intent(review, p.intent) and review_is_fresh(review, now))
                _check(a.reserved_at <= review.reviewed_at <= now)
                _check(review.source == "fake")
                _check(
                    review.client_order_id is None
                    or str(review.client_order_id) == str(p.intent.id)
                )
                _check(
                    review.outbound_payload_sha256
                    == canonical_review_payload_sha256(
                        p.intent, client_order_id=review.client_order_id
                    )
                )
                _check(review.estimated_fees <= self._policy.simulation_fee_usd)
                quote_price = p.quote.ask if p.intent.side.value == "buy" else p.quote.bid
                _check(
                    review.estimated_notional
                    == p.intent.quantity * (p.intent.limit_price or quote_price)
                )
                submission = PersistedReviewedOrder(
                    review_id=ReviewId(str(uuid5(NAMESPACE_URL, "simulation:review:" + intent_id))),
                    submission_attempt_id=SubmissionAttemptId(
                        str(uuid5(NAMESPACE_URL, "simulation:attempt:" + intent_id))
                    ),
                    review=review,
                    deduplication_key=derive_deduplication_key(p.intent),
                    fencing_token=0,
                    execution_mode=ExecutionMode.SIMULATION,
                    live_lease_id=None,
                    live_lease_evidence_hash=None,
                    account_id=p.intent.account_id,
                    config_hash=p.intent.config_hash,
                )
                updated = self._updated(
                    a,
                    phase="submitting",
                    submitted_at=now,
                    submission=submission,
                    last_observed_at=now,
                )
                ticket = StockSimulationTicket(p, submission, now)
                return _base(state), updated

            await self._mutate(intent_id, "submit", review, operation)
            return ticket
        except Exception:
            raise ValueError("stock_simulation_unavailable") from None

    @staticmethod
    def _matching_order(a: StockSimulationAttempt, response: BrokerOrder, now: datetime) -> None:
        _check(
            type(response) is BrokerOrder
            and a.submission is not None
            and a.submitted_at is not None
        )
        response.__post_init__()
        if a.submission is None or a.submitted_at is None:
            raise ValueError("stock_simulation_unavailable")
        _check(broker_order_matches_submission(response, a.submission))
        _check(a.submitted_at <= response.created_at <= response.updated_at <= now)
        _check(
            Fraction(response.filled_quantity)
            >= sum((Fraction(x.quantity) for x in a.fill_facts), Fraction(0))
        )
        if a.broker_order is not None:
            _check(
                (response.id, response.broker_order_id, response.created_at)
                == (a.broker_order.id, a.broker_order.broker_order_id, a.broker_order.created_at)
            )
            _check(response.updated_at >= a.broker_order.updated_at)
            _check(response.filled_quantity >= a.broker_order.filled_quantity)

    def _terminal(
        self,
        state: StockSimulationAccount,
        a: StockSimulationAttempt,
        response: BrokerOrder,
        now: datetime,
    ) -> tuple[Account, StockSimulationAttempt]:
        self._matching_order(a, response, now)
        base = _base(state)
        order = next(x for x in base.orders if x.id == a.prepared.intent.id)
        _check(
            response.state
            in (OrderState.FILLED, OrderState.CANCELED, OrderState.EXPIRED, OrderState.REJECTED)
        )
        _check(response.filled_quantity == order.filled)
        submitted = a.submitted_at
        if submitted is None:
            raise ValueError("stock_simulation_unavailable")
        _check(response.updated_at >= max((x.occurred_at for x in a.fill_facts), default=submitted))
        if response.state is OrderState.REJECTED:
            _check(order.filled == 0 and order.status not in ("filled", "cancelled"))
            rejected = order.model_copy(update={"status": "rejected", "reserved_cash": Decimal(0)})
            base = Account.model_validate(
                base.model_dump()
                | {"orders": tuple(rejected if x.id == order.id else x for x in base.orders)}
            )
        elif response.state is OrderState.FILLED:
            _check(order.status == "filled" and order.filled == order.quantity)
        else:
            _check(order.status in ("open", "partial", "cancelled"))
            base = cancel_order(base, order.id)
        return base, self._updated(
            a,
            phase="terminal",
            broker_order=response,
            terminal_state=response.state,
            diagnostic="none",
            last_observed_at=now,
        )

    @staticmethod
    def _active_phase(
        a: StockSimulationAttempt, filled: Decimal, reported: Decimal
    ) -> tuple[Phase, Diagnostic]:
        if a.cancel_receipt is not None and a.cancel_receipt.ambiguous:
            return "ambiguous", "cancel_ambiguous"
        if reported > filled:
            return "ambiguous", "unreconciled_order_state"
        if a.cancel_receipt is not None and a.cancel_receipt.accepted:
            return "cancel_pending", "none"
        return ("partial" if filled else "submitted"), "none"

    async def record_order(self, intent_id: str, response: BrokerOrder) -> StockSimulationAttempt:
        try:
            _check(type(response) is BrokerOrder)

            def operation(
                state: StockSimulationAccount, a: StockSimulationAttempt, now: datetime
            ) -> tuple[Account, StockSimulationAttempt]:
                self._matching_order(a, response, now)
                _check(a.phase != "reserved")
                order = next(x for x in state.orders if x.id == intent_id)
                if response.state is OrderState.REJECTED:
                    return self._terminal(state, a, response, now)
                if response.state in (OrderState.CANCELED, OrderState.EXPIRED, OrderState.FILLED):
                    if response.filled_quantity == order.filled:
                        return self._terminal(state, a, response, now)
                elif (
                    response.state in (OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED)
                    and response.filled_quantity == order.filled
                ):
                    _check(a.phase != "terminal")
                    phase, diagnostic = self._active_phase(
                        a, order.filled, response.filled_quantity
                    )
                    return _base(state), self._updated(
                        a,
                        phase=phase,
                        broker_order=response,
                        diagnostic=diagnostic,
                        last_observed_at=now,
                    )
                _check(a.phase != "terminal")
                base = Account.model_validate(_base(state).model_dump() | {"paused": True})
                return base, self._updated(
                    a,
                    phase="ambiguous",
                    broker_order=response,
                    diagnostic="unreconciled_order_state",
                    last_observed_at=now,
                )

            return await self._mutate(intent_id, "response", response, operation)
        except Exception:
            raise ValueError("stock_simulation_unavailable") from None

    async def record_ambiguous(
        self, intent_id: str, *, reason: Diagnostic = "transport_ambiguous"
    ) -> StockSimulationAttempt:
        try:
            _check(
                reason in ("transport_ambiguous", "cancel_ambiguous", "unreconciled_order_state")
            )

            def operation(
                state: StockSimulationAccount, a: StockSimulationAttempt, now: datetime
            ) -> tuple[Account, StockSimulationAttempt]:
                _check(a.submission is not None and a.phase != "terminal")
                base = Account.model_validate(_base(state).model_dump() | {"paused": True})
                return base, self._updated(
                    a, phase="ambiguous", diagnostic=reason, last_observed_at=now
                )

            return await self._mutate(intent_id, "ambiguous", reason, operation)
        except Exception:
            raise ValueError("stock_simulation_unavailable") from None

    async def record_fill(
        self, intent_id: str, fill: Fill, *, settlement_at: datetime | None = None
    ) -> StockSimulationAttempt:
        try:
            _check(type(fill) is Fill)
            fill.__post_init__()

            def operation(
                state: StockSimulationAccount, a: StockSimulationAttempt, now: datetime
            ) -> tuple[Account, StockSimulationAttempt]:
                _check(
                    a.broker_order is not None
                    and a.submitted_at is not None
                    and a.phase != "terminal"
                )
                if a.broker_order is None or a.submitted_at is None:
                    raise ValueError("stock_simulation_unavailable")
                p = a.prepared
                _check(
                    (fill.account_id, fill.instrument_id, fill.side, fill.broker_order_id)
                    == (
                        p.intent.account_id,
                        p.intent.instrument_id,
                        p.intent.side,
                        a.broker_order.broker_order_id,
                    )
                )
                _check(a.submitted_at <= fill.occurred_at <= now)
                previous = tuple(x for x in a.fill_facts if x.id == fill.id)
                if previous:
                    _check(previous == (fill,))
                    return _base(state), a
                base = fill_order(
                    _base(state),
                    FillFact(
                        id=str(fill.id),
                        order_id=intent_id,
                        quantity=fill.quantity,
                        price=fill.price,
                        fee=fill.fee,
                        at=fill.occurred_at,
                    ),
                    self._policy,
                    settlement_at=settlement_at,
                )
                actual = next(x for x in base.orders if x.id == intent_id)
                full = actual.status == "filled"
                phase, diagnostic = self._active_phase(
                    a, actual.filled, a.broker_order.filled_quantity
                )
                return base, self._updated(
                    a,
                    fill_facts=(*a.fill_facts, fill),
                    phase="terminal" if full else phase,
                    diagnostic="none" if full else diagnostic,
                    terminal_state=OrderState.FILLED if full else None,
                    last_observed_at=now,
                )

            return await self._mutate(
                intent_id, "fill", {"fill": fill, "settlement_at": settlement_at}, operation
            )
        except Exception:
            raise ValueError("stock_simulation_unavailable") from None

    async def record_cancel_ack(
        self, intent_id: str, receipt: CancelReceipt
    ) -> StockSimulationAttempt:
        try:
            _check(type(receipt) is CancelReceipt)
            receipt.__post_init__()

            def operation(
                state: StockSimulationAccount, a: StockSimulationAttempt, now: datetime
            ) -> tuple[Account, StockSimulationAttempt]:
                _check(
                    a.broker_order is not None
                    and a.submitted_at is not None
                    and a.phase != "terminal"
                )
                if a.broker_order is None or a.submitted_at is None:
                    raise ValueError("stock_simulation_unavailable")
                _check(receipt.broker_order_id == a.broker_order.broker_order_id)
                _check(a.submitted_at <= receipt.observed_at <= now)
                base = _base(state)
                changes: dict[str, Any] = {"cancel_receipt": receipt, "last_observed_at": now}
                if receipt.ambiguous:
                    base = Account.model_validate(base.model_dump() | {"paused": True})
                    changes.update(phase="ambiguous", diagnostic="cancel_ambiguous")
                elif receipt.accepted:
                    changes.update(phase="cancel_pending")
                return base, self._updated(a, **changes)

            return await self._mutate(intent_id, "cancel-ack", receipt, operation)
        except Exception:
            raise ValueError("stock_simulation_unavailable") from None

    async def confirm_terminal(
        self, intent_id: str, response: BrokerOrder
    ) -> StockSimulationAttempt:
        try:
            _check(type(response) is BrokerOrder)
            return await self._mutate(
                intent_id,
                "terminal",
                response,
                lambda state, attempt, now: self._terminal(state, attempt, response, now),
            )
        except Exception:
            raise ValueError("stock_simulation_unavailable") from None

    async def initialize(self, initial: Account, *, event_id: str) -> StockSimulationAccount:
        try:
            _check(type(initial) is Account)

            def transition(_: Account) -> Account:
                return StockSimulationAccount(
                    **initial.model_dump(),
                    simulation_profile=_PROFILE,
                    simulation_account_id=self._simulation_id,
                    execution_config_hash=self._execution_hash,
                    execution_policy=self._policy,
                )

            return self._state(
                await self.change(event_id, "initialize", {"initial": _record(initial)}, transition)
            )
        except Exception:
            raise ValueError("stock_simulation_unavailable") from None

    async def reserve(
        self,
        context: StockExecutionContext,
        *,
        grant: StockSimulationGrant,
        selection: StockExecutionSelection,
    ) -> StockSimulationReservation:
        try:
            _check(type(context) is StockExecutionContext and type(grant) is StockSimulationGrant)
            _check(type(selection) is StockExecutionSelection)
            request = {
                "context_hash": context.evidence_hash,
                "grant": _record(grant),
                "selection": _record(selection),
            }
            event_id = "simulation:reserve:" + _hash(request)
            created = False
            ref = ""

            def transition(value: Account) -> Account:
                nonlocal created, ref
                state = self._state(value)
                _check(
                    state.execution_config_hash
                    == context.execution_config_hash
                    == self._execution_hash
                )
                _check(context.execution_policy == self._policy)
                now, base = self._now(), _base(state)
                with localcontext(_CONTEXT):
                    p = prepare_stock_execution(
                        context,
                        account=base,
                        simulation_account_id=state.simulation_account_id,
                        grant=grant,
                        selection=selection,
                        now=now,
                    )
                    _check(p.intent.id not in {x.prepared.intent.id for x in state.attempts})
                    reserved = reserve_order(
                        base,
                        p.paper_order,
                        p.quote,
                        now,
                        self._policy,
                        exposure_quotes={q.symbol: q for q in p.exposure_quotes},
                    )
                attempt = StockSimulationAttempt(
                    prepared=p,
                    grant=grant,
                    selection=selection,
                    prepared_hash=p.evidence_hash,
                    reserved_account_hash=stock_simulation_account_hash(reserved),
                    reserved_at=now,
                    last_observed_at=now,
                )
                meta = state.model_dump(exclude=_BASE_FIELDS)
                meta["attempts"] = (*state.attempts, attempt)
                result = StockSimulationAccount.model_validate(reserved.model_dump() | meta)
                created, ref = True, str(p.intent.id)
                return result

            state = self._state(await self.change(event_id, "order", request, transition))
            matches = tuple(
                x
                for x in state.attempts
                if x.prepared.approval_hash == grant.evidence_hash
                and x.prepared.selection_hash == selection.evidence_hash
            )
            _check(len(matches) == 1)
            if created:
                self._fresh.add(ref)
            return StockSimulationReservation(matches[0].prepared, created)
        except Exception:
            raise ValueError("stock_simulation_unavailable") from None

    async def settle_due(self) -> StockSimulationAccount:
        """Credit only retained explicit obligations due at this observed clock."""
        try:
            observed_at = self._now()
            request: dict[str, object] = {"observed_at": observed_at.isoformat()}

            def transition(value: Account) -> Account:
                state = self._state(value)
                _check(self._now() >= observed_at)
                _check(all(x.last_observed_at <= observed_at for x in state.attempts))
                with localcontext(_CONTEXT):
                    return self._merge(state, settle(_base(state), observed_at))

            result = await self.change(
                "simulation:settle:" + _hash(request), "settle", request, transition
            )
            return self._state(result)
        except Exception:
            raise ValueError("stock_simulation_unavailable") from None

    async def mark_market(self, quotes: tuple[Quote, ...]) -> StockSimulationAccount:
        """Persist complete supplied fictional marks and existing loss controls."""
        try:
            _check(type(quotes) is tuple and len(quotes) <= 1000)
            _check(all(type(q) is Quote for q in quotes))
            with localcontext(_CONTEXT):
                validated = tuple(Quote.model_validate(q.model_dump()) for q in quotes)
                _check(len({q.symbol for q in validated}) == len(validated))
                _check(all(q.bid <= q.ask for q in validated))
                ordered = tuple(sorted(validated, key=lambda q: q.symbol))
                observed_at = self._now()
                request = {"observed_at": observed_at.isoformat(), "quotes": _record(ordered)}

            def transition(value: Account) -> Account:
                state = self._state(value)
                _check(self._now() >= observed_at)
                _check(all(x.last_observed_at <= observed_at for x in state.attempts))
                _check(all(x.acquired_at <= observed_at for x in state.lots))
                _check(all(x.at <= observed_at for x in state.fills))
                with localcontext(_CONTEXT):
                    base = mark_account(_base(state), {q.symbol: q for q in ordered}, observed_at)
                    return self._merge(state, base)

            result = await self.change(
                "simulation:mark:" + _hash(request), "mark", request, transition
            )
            return self._state(result)
        except Exception:
            raise ValueError("stock_simulation_unavailable") from None
