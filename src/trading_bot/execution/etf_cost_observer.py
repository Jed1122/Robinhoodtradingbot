"""Protected owner's safe economic receipt projection, not a broker adapter.

Sources here describe local owner boundaries. They do not attest original broker
payloads, fees, customer provenance, operational eligibility or live execution.
"""

from dataclasses import replace

from trading_bot.diagnostics.etf_execution_receipts import EtfExecutionReceiptRecorder
from trading_bot.domain import (
    AssetClass,
    BrokerOrder,
    OrderIntent,
    OrderState,
    PersistedReviewedOrder,
)
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.domain.order_matching import broker_order_matches_submission
from trading_bot.domain.owned_order_lifecycle import (
    MAX_EVENTS,
    OwnedOrderEvent,
    advance_owned_order,
    decode_owned_event,
    encode_owned_event,
)
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.etf_execution_receipts import EtfReceiptError

_ERRORS = (ValueError, TypeError, ArithmeticError, AttributeError, OSError, RuntimeError)


class EtfCostObserver:
    """One intent and checked local lifecycle in the same private clock session.

    The caller publishes owned facts durably before observing them. This sink
    does not authenticate those facts or commit accounting on the caller's behalf.
    """

    def __init__(self, recorder: EtfExecutionReceiptRecorder, *, decision_quote_hash: str) -> None:
        if type(recorder) is not EtfExecutionReceiptRecorder:
            raise EtfReceiptError()
        try:
            _require_sha256_hex(decision_quote_hash, "decision quote")
        except _ERRORS:
            raise EtfReceiptError() from None
        self._recorder = recorder
        self._quote_hash = decision_quote_hash
        self._intent: OrderIntent | None = None
        self._submission: PersistedReviewedOrder | None = None
        self._acknowledged = False
        self._failed = False
        self._current_order: BrokerOrder | None = None
        self._events: dict[str, str] = {}
        self._execution_keys: set[str] = set()
        self._fill_ids: set[str] = set()

    def _check(self, condition: bool) -> None:
        if self._failed or not condition:
            raise EtfReceiptError()

    @property
    def _order_hash(self) -> str:
        self._check(self._intent is not None)
        return content_hash(("etf-owner-order-v1", self._intent))

    def _source(self, schema: str, digest: str) -> str:
        return self._recorder.retain_source(
            canonical_json({"schema": schema, "observation_hash": digest}).encode()
        )

    async def decision(self, intent: OrderIntent) -> None:
        try:
            self._check(type(intent) is OrderIntent and self._intent is None)
            intent = replace(intent)
            self._check(intent.instrument_id == "SPY" and intent.asset_class is AssetClass.EQUITY)
            self._intent = intent
            terms = self._recorder.retain_source(
                canonical_json(
                    {
                        "schema": "etf-owner-economic-terms-v1",
                        "intent_hash": content_hash(intent),
                        "instrument": "SPY",
                        "side": intent.side,
                        "quantity": intent.quantity,
                        "limit_price": intent.limit_price,
                        "stop_price": intent.stop_price,
                        "order_type": intent.order_type,
                        "time_in_force": intent.time_in_force,
                        "config_hash": intent.config_hash,
                    }
                ).encode()
            )
            self._recorder.record(
                "decision",
                {
                    "order_hash": self._order_hash,
                    "side": intent.side.value,
                    "terms_hash": terms,
                    "observation_hash": self._quote_hash,
                },
            )
            # Audit retained quote bytes, causality and freshness before allowing
            # the owner to proceed to any review boundary.
            self._recorder.checkpoint()
        except _ERRORS:
            self._failed = True
            raise EtfReceiptError() from None

    async def submitting(self, submission: PersistedReviewedOrder) -> None:
        try:
            self._check(type(submission) is PersistedReviewedOrder)
            submission = replace(
                submission,
                review=replace(
                    submission.review, normalized_order=replace(submission.review.normalized_order)
                ),
            )
            self._check(self._intent is not None and self._submission is None)
            self._check(submission.review.normalized_order == self._intent)
            source = self._source("etf-owner-submission-boundary-v1", content_hash(submission))
            self._recorder.record(
                "submitted", {"order_hash": self._order_hash, "source_hash": source}
            )
            self._recorder.checkpoint()
            self._submission = submission
        except _ERRORS:
            self._failed = True
            raise EtfReceiptError() from None

    async def responded(self, submission: PersistedReviewedOrder, response: BrokerOrder) -> None:
        try:
            self._check(self._submission is not None and self._submission == submission)
            self._check(not self._acknowledged)
            self._check(type(response) is BrokerOrder)
            response = replace(response)
            self._check(broker_order_matches_submission(response, submission))
            self._check(response.state in (OrderState.SUBMITTED, OrderState.REJECTED))
            self._check(response.filled_quantity == 0)
            self._recorder.check_occurrence(response.updated_at)
            source = self._source("etf-owner-response-boundary-v1", content_hash(response))
            self._recorder.record(
                "acknowledged", {"order_hash": self._order_hash, "source_hash": source}
            )
            if response.state is OrderState.REJECTED:
                self._recorder.record(
                    "terminal",
                    {
                        "order_hash": self._order_hash,
                        "source_hash": source,
                        "state": "rejected",
                        "charged_fees": None,
                    },
                )
            self._recorder.checkpoint()
            self._acknowledged = True
            self._current_order = replace(response)
        except _ERRORS:
            self._failed = True
            raise EtfReceiptError() from None

    async def observed(self, event: OwnedOrderEvent) -> None:
        """Project a committed local fact; duplicate delivery retains its first clock.

        Failed recording latches this observer. It never rolls back a broker
        outcome, changes reservations or requests another transport attempt.
        Per-fill fee observations deliberately do not imply final order charges.
        """
        try:
            self._check(self._acknowledged and self._current_order is not None)
            encoded = encode_owned_event(event)
            # Nested domain records can be mutated by a hostile caller despite
            # frozen outer dataclasses. Callbacks must see only this checked copy.
            event = decode_owned_event(encoded)
            previous = self._events.get(event.id)
            if previous is not None:
                self._check(previous == encoded)
                return
            self._check(len(self._events) < MAX_EVENTS)
            current = self._current_order
            if current is None:
                raise EtfReceiptError()
            advanced = advance_owned_order(current, event)
            key = event.external_execution_key
            self._check(key is None or key not in self._execution_keys)
            if event.fill is not None:
                self._check(event.fill.id not in self._fill_ids)
                self._check(event.occurrence_ordinal == len(self._fill_ids))
            self._recorder.check_occurrence(event.occurred_at)
            source = self._source("etf-owner-lifecycle-boundary-v1", content_hash(event))
            if event.fill is not None:
                fill = event.fill
                self._recorder.record(
                    "fill",
                    {
                        "order_hash": self._order_hash,
                        "fill_hash": content_hash(
                            (
                                "etf-owner-execution-v1",
                                current.account_id,
                                current.broker_order_id,
                                key,
                            )
                        ),
                        "quantity": fill.quantity,
                        "price": fill.price,
                        "source_hash": source,
                    },
                )
            terminal = {
                OrderState.FILLED: "filled",
                OrderState.CANCELED: "cancelled",
                OrderState.REJECTED: "rejected",
                OrderState.EXPIRED: "expired",
            }.get(advanced.state)
            if terminal is not None:
                self._recorder.record(
                    "terminal_v2" if terminal == "expired" else "terminal",
                    {
                        "order_hash": self._order_hash,
                        "source_hash": source,
                        "state": terminal,
                        "charged_fees": None,
                    },
                )
            self._recorder.checkpoint()
            self._events[event.id] = encoded
            if key is not None:
                self._execution_keys.add(key)
            if event.fill is not None:
                self._fill_ids.add(event.fill.id)
            self._current_order = advanced
        except _ERRORS:
            self._failed = True
            raise EtfReceiptError() from None
