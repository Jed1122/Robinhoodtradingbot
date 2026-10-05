"""Canonical hashes for sanitized order-review and placement evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal

from trading_bot.clock import require_utc
from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrder,
    BrokerOrderReview,
    ConfigHash,
    DataHash,
    DomainValidationError,
    InstrumentId,
    OrderIntent,
    OrderIntentId,
    OrderPurpose,
    OrderType,
    Side,
    TimeInForce,
    canonical_decimal_text,
    canonical_order_intent_sha256,
)
from trading_bot.persistence.base import PersistenceDataError
from trading_bot.persistence.models import OrderIntentRow


def order_intent_from_row(row: OrderIntentRow) -> OrderIntent:
    """Reconstruct the existing canonical intent, including all evidence fields."""

    try:
        return OrderIntent(
            id=OrderIntentId(row.id),
            account_id=AccountId(row.account_id),
            instrument_id=InstrumentId(row.instrument_id),
            asset_class=AssetClass(row.asset_class),
            side=Side(row.side),
            purpose=OrderPurpose(row.purpose),
            order_type=OrderType(row.order_type),
            time_in_force=TimeInForce(row.time_in_force),
            quantity=row.quantity,
            limit_price=row.limit_price,
            stop_price=row.stop_price,
            created_at=row.created_at,
            expires_at=row.expires_at,
            strategy_version=row.strategy_version,
            config_hash=ConfigHash(row.config_hash),
            data_hash=DataHash(row.data_hash),
            exit_policy_version=row.exit_policy_version,
        )
    except (DomainValidationError, ValueError):
        raise PersistenceDataError("stored order intent violates the domain contract") from None


def _utc_text(value: datetime) -> str:
    return require_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else canonical_decimal_text(value)


def _sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_review_response_sha256(review: BrokerOrderReview) -> str:
    """Hash the validated, non-secret review record instead of a raw provider response."""

    if type(review) is not BrokerOrderReview:
        raise DomainValidationError("review must be a BrokerOrderReview")
    return _sha256(
        {
            "broker_review_id": review.broker_review_id,
            "client_order_id": (
                None if review.client_order_id is None else str(review.client_order_id)
            ),
            "estimated_fees": canonical_decimal_text(review.estimated_fees),
            "estimated_notional": canonical_decimal_text(review.estimated_notional),
            "expires_at": _utc_text(review.expires_at),
            "normalized_intent_sha256": canonical_order_intent_sha256(review.normalized_order),
            "outbound_payload_sha256": review.outbound_payload_sha256,
            "reviewed_at": _utc_text(review.reviewed_at),
            "source": review.source,
        }
    )


def canonical_broker_order_response_sha256(order: BrokerOrder) -> str:
    """Hash a canonical broker-order response without retaining transport material."""

    if type(order) is not BrokerOrder:
        raise DomainValidationError("order must be a BrokerOrder")
    return _sha256(
        {
            "account_id": str(order.account_id),
            "broker_order_id": str(order.broker_order_id),
            "local_order_id": str(order.id),
            "client_order_id": (
                None if order.client_order_id is None else str(order.client_order_id)
            ),
            "created_at": _utc_text(order.created_at),
            "data_hash": str(order.data_hash),
            "filled_quantity": canonical_decimal_text(order.filled_quantity),
            "instrument_id": str(order.instrument_id),
            "intent_id": None if order.intent_id is None else str(order.intent_id),
            "limit_price": _decimal_text(order.limit_price),
            "order_type": order.order_type.value,
            "purpose": order.purpose.value,
            "requested_quantity": canonical_decimal_text(order.requested_quantity),
            "side": order.side.value,
            "state": order.state.value,
            "stop_price": _decimal_text(order.stop_price),
            "time_in_force": order.time_in_force.value,
            "updated_at": _utc_text(order.updated_at),
        }
    )


__all__ = [
    "canonical_broker_order_response_sha256",
    "canonical_order_intent_sha256",
    "canonical_review_response_sha256",
    "order_intent_from_row",
]
