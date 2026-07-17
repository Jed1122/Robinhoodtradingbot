"""Deterministic execution-test records without provider or network dependencies."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrderReview,
    ClientOrderId,
    ConfigHash,
    DataHash,
    InstrumentId,
    OrderIntent,
    OrderIntentId,
    OrderPurpose,
    OrderType,
    Side,
    TimeInForce,
)
from trading_bot.risk import canonical_review_payload_sha256

NOW = datetime(2026, 7, 16, 18, 0, tzinfo=UTC)
CONFIG_HASH = ConfigHash("a" * 64)
DATA_HASH = DataHash("b" * 64)


def make_intent(**overrides: object) -> OrderIntent:
    values: dict[str, object] = {
        "id": OrderIntentId("00000000-0000-4000-8000-000000000008"),
        "account_id": AccountId("paper-account"),
        "instrument_id": InstrumentId("paper-btc-usd"),
        "asset_class": AssetClass.CRYPTO,
        "side": Side.BUY,
        "purpose": OrderPurpose.ENTRY,
        "order_type": OrderType.LIMIT,
        "time_in_force": TimeInForce.GOOD_TIL_CANCELED,
        "quantity": Decimal("0.01"),
        "limit_price": Decimal("100"),
        "stop_price": None,
        "created_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(minutes=5),
        "strategy_version": "paper-strategy-v1",
        "config_hash": CONFIG_HASH,
        "data_hash": DATA_HASH,
        "exit_policy_version": "protective-v1",
    }
    values.update(overrides)
    return OrderIntent(**values)  # type: ignore[arg-type]


def make_review(intent: OrderIntent, **overrides: object) -> BrokerOrderReview:
    client_order_id = ClientOrderId(str(intent.id))
    values: dict[str, object] = {
        "normalized_order": intent,
        "source": "paper",
        "reviewed_at": NOW,
        "expires_at": NOW + timedelta(seconds=30),
        "estimated_notional": Decimal("1"),
        "estimated_fees": Decimal("0"),
        "client_order_id": client_order_id,
        "outbound_payload_sha256": canonical_review_payload_sha256(
            intent,
            client_order_id=client_order_id,
        ),
        "broker_review_id": "paper-review-1",
    }
    values.update(overrides)
    return BrokerOrderReview(**values)  # type: ignore[arg-type]
