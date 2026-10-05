"""Protected owner's safe economic receipt projection, not a broker adapter.

Sources here describe local owner boundaries. They do not attest original broker
payloads, fees, customer provenance, operational eligibility or live execution.
"""

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
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.etf_execution_receipts import EtfReceiptError

_ERRORS = (ValueError, TypeError, ArithmeticError, AttributeError, OSError, RuntimeError)


class EtfCostObserver:
    """One intent, one submission, one matched response in the same private sink."""

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
            self._check(broker_order_matches_submission(response, submission))
            self._check(response.state in (OrderState.SUBMITTED, OrderState.REJECTED))
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
        except _ERRORS:
            self._failed = True
            raise EtfReceiptError() from None
