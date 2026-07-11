"""Immutable broker-neutral order, fill, and broker-health records."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_decimal,
    _require_nonempty,
    _require_sha256_hex,
    _require_tuple,
)
from trading_bot.domain.enums import (
    AssetClass,
    OrderPurpose,
    OrderState,
    OrderType,
    Side,
    TimeInForce,
)
from trading_bot.domain.identifiers import (
    AccountId,
    BrokerOrderId,
    ClientOrderId,
    ConfigHash,
    DataHash,
    FillId,
    InstrumentId,
    OrderIntentId,
    ReviewId,
    SubmissionAttemptId,
)


def _validate_order_prices(
    order_type: OrderType,
    limit_price: Decimal | None,
    stop_price: Decimal | None,
) -> None:
    if limit_price is not None:
        _require_decimal(limit_price, "limit_price", positive=True)
    if stop_price is not None:
        _require_decimal(stop_price, "stop_price", positive=True)

    valid_shape = {
        OrderType.MARKET: limit_price is None and stop_price is None,
        OrderType.LIMIT: limit_price is not None and stop_price is None,
        OrderType.STOP_LOSS: limit_price is None and stop_price is not None,
        OrderType.STOP_LIMIT: limit_price is not None and stop_price is not None,
    }
    if not valid_shape.get(order_type, False):
        raise DomainValidationError("limit and stop prices must match the order type")


@dataclass(frozen=True, slots=True)
class OrderIntent:
    id: OrderIntentId
    account_id: AccountId
    instrument_id: InstrumentId
    asset_class: AssetClass
    side: Side
    purpose: OrderPurpose
    order_type: OrderType
    time_in_force: TimeInForce
    quantity: Decimal
    limit_price: Decimal | None
    stop_price: Decimal | None
    created_at: datetime
    expires_at: datetime
    strategy_version: str
    config_hash: ConfigHash
    data_hash: DataHash
    exit_policy_version: str | None

    def __post_init__(self) -> None:
        _require_nonempty(self.id, "id")
        _require_nonempty(self.account_id, "account_id")
        _require_nonempty(self.instrument_id, "instrument_id")
        _require_decimal(self.quantity, "quantity", positive=True)
        _validate_order_prices(self.order_type, self.limit_price, self.stop_price)
        require_utc(self.created_at)
        require_utc(self.expires_at)
        if self.created_at >= self.expires_at:
            raise DomainValidationError("created_at must precede expires_at")
        _require_nonempty(self.strategy_version, "strategy_version")
        _require_sha256_hex(self.config_hash, "config_hash")
        _require_sha256_hex(self.data_hash, "data_hash")
        if self.purpose is OrderPurpose.ENTRY:
            if self.exit_policy_version is None:
                raise DomainValidationError("entry orders require an exit policy version")
            _require_nonempty(self.exit_policy_version, "exit_policy_version")
        elif self.exit_policy_version is not None:
            _require_nonempty(self.exit_policy_version, "exit_policy_version")


@dataclass(frozen=True, slots=True)
class BrokerOrderReview:
    normalized_order: OrderIntent
    source: str
    reviewed_at: datetime
    expires_at: datetime
    estimated_notional: Decimal
    estimated_fees: Decimal
    client_order_id: ClientOrderId | None
    outbound_payload_sha256: str
    broker_review_id: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.normalized_order, OrderIntent):
            raise DomainValidationError("normalized_order must be an OrderIntent")
        _require_nonempty(self.source, "source")
        require_utc(self.reviewed_at)
        require_utc(self.expires_at)
        if self.reviewed_at >= self.expires_at:
            raise DomainValidationError("reviewed_at must precede expires_at")
        if self.expires_at > self.normalized_order.expires_at:
            raise DomainValidationError("review cannot outlive the normalized order intent")
        _require_decimal(self.estimated_notional, "estimated_notional", positive=True)
        _require_decimal(self.estimated_fees, "estimated_fees", nonnegative=True)
        if self.client_order_id is not None:
            _require_nonempty(self.client_order_id, "client_order_id")
        _require_sha256_hex(self.outbound_payload_sha256, "outbound_payload_sha256")
        if self.broker_review_id is not None:
            _require_nonempty(self.broker_review_id, "broker_review_id")


@dataclass(frozen=True, slots=True)
class BrokerOrder:
    id: BrokerOrderId
    account_id: AccountId
    intent_id: OrderIntentId | None
    client_order_id: ClientOrderId | None
    instrument_id: InstrumentId
    side: Side
    purpose: OrderPurpose
    order_type: OrderType
    time_in_force: TimeInForce
    requested_quantity: Decimal
    filled_quantity: Decimal
    limit_price: Decimal | None
    stop_price: Decimal | None
    state: OrderState
    created_at: datetime
    updated_at: datetime
    data_hash: DataHash

    def __post_init__(self) -> None:
        _require_nonempty(self.id, "id")
        _require_nonempty(self.account_id, "account_id")
        if self.intent_id is not None:
            _require_nonempty(self.intent_id, "intent_id")
        if self.client_order_id is not None:
            _require_nonempty(self.client_order_id, "client_order_id")
        _require_nonempty(self.instrument_id, "instrument_id")
        _require_decimal(self.requested_quantity, "requested_quantity", positive=True)
        _require_decimal(self.filled_quantity, "filled_quantity", nonnegative=True)
        if self.filled_quantity > self.requested_quantity:
            raise DomainValidationError("filled_quantity cannot exceed requested_quantity")
        if self.state is OrderState.FILLED and self.filled_quantity != self.requested_quantity:
            raise DomainValidationError("filled orders require the full requested quantity")
        if self.state is OrderState.PARTIALLY_FILLED and not (
            0 < self.filled_quantity < self.requested_quantity
        ):
            raise DomainValidationError(
                "partially filled orders require a positive incomplete fill quantity"
            )
        _validate_order_prices(self.order_type, self.limit_price, self.stop_price)
        require_utc(self.created_at)
        require_utc(self.updated_at)
        if self.updated_at < self.created_at:
            raise DomainValidationError("updated_at cannot precede created_at")
        _require_sha256_hex(self.data_hash, "data_hash")


@dataclass(frozen=True, slots=True)
class Fill:
    id: FillId
    broker_order_id: BrokerOrderId
    account_id: AccountId
    instrument_id: InstrumentId
    side: Side
    quantity: Decimal
    price: Decimal
    fee: Decimal
    occurred_at: datetime
    data_hash: DataHash

    def __post_init__(self) -> None:
        _require_nonempty(self.id, "id")
        _require_nonempty(self.broker_order_id, "broker_order_id")
        _require_nonempty(self.account_id, "account_id")
        _require_nonempty(self.instrument_id, "instrument_id")
        _require_decimal(self.quantity, "quantity", positive=True)
        _require_decimal(self.price, "price", positive=True)
        _require_decimal(self.fee, "fee", nonnegative=True)
        require_utc(self.occurred_at)
        _require_sha256_hex(self.data_hash, "data_hash")


@dataclass(frozen=True, slots=True)
class CancelReceipt:
    broker_order_id: BrokerOrderId
    accepted: bool
    ambiguous: bool
    observed_at: datetime
    reason_code: str

    def __post_init__(self) -> None:
        _require_nonempty(self.broker_order_id, "broker_order_id")
        if self.accepted and self.ambiguous:
            raise DomainValidationError("a cancel receipt cannot be accepted and ambiguous")
        require_utc(self.observed_at)
        _require_nonempty(self.reason_code, "reason_code")


@dataclass(frozen=True, slots=True)
class BrokerHealth:
    healthy: bool
    observed_at: datetime
    latency_ms: Decimal | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        require_utc(self.observed_at)
        if self.latency_ms is not None:
            _require_decimal(self.latency_ms, "latency_ms", nonnegative=True)
        _require_tuple(self.reason_codes, "reason_codes")
        for reason_code in self.reason_codes:
            _require_nonempty(reason_code, "reason_codes item")


@dataclass(frozen=True, slots=True)
class PersistedReviewedOrder:
    review_id: ReviewId
    submission_attempt_id: SubmissionAttemptId
    review: BrokerOrderReview
    deduplication_key: str
    fencing_token: int
    live_lease_evidence_hash: str
    account_id: AccountId
    config_hash: ConfigHash

    def __post_init__(self) -> None:
        _require_nonempty(self.review_id, "review_id")
        _require_nonempty(self.submission_attempt_id, "submission_attempt_id")
        if not isinstance(self.review, BrokerOrderReview):
            raise DomainValidationError("review must be a BrokerOrderReview")
        _require_nonempty(self.deduplication_key, "deduplication_key")
        if isinstance(self.fencing_token, bool) or not isinstance(self.fencing_token, int):
            raise DomainValidationError("fencing_token must be an integer")
        if self.fencing_token < 0:
            raise DomainValidationError("fencing_token must be nonnegative")
        _require_sha256_hex(self.live_lease_evidence_hash, "live_lease_evidence_hash")
        _require_nonempty(self.account_id, "account_id")
        _require_sha256_hex(self.config_hash, "config_hash")
        normalized = self.review.normalized_order
        if self.account_id != normalized.account_id:
            raise DomainValidationError("persisted review account must match the order intent")
        if self.config_hash != normalized.config_hash:
            raise DomainValidationError("persisted review config hash must match the order intent")
