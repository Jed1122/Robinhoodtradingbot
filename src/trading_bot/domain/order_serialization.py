"""Single canonical normalized representation for immutable order intents."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    canonical_decimal_text,
)
from trading_bot.domain.orders import OrderIntent


def _utc_text(value: datetime) -> str:
    return require_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_order_intent_payload(intent: OrderIntent) -> dict[str, object]:
    """Return every normalized intent field in one stable, JSON-safe mapping."""

    if type(intent) is not OrderIntent:
        raise DomainValidationError("intent must be an OrderIntent")
    return {
        "account_id": str(intent.account_id),
        "asset_class": intent.asset_class.value,
        "config_hash": str(intent.config_hash),
        "created_at": _utc_text(intent.created_at),
        "data_hash": str(intent.data_hash),
        "exit_policy_version": intent.exit_policy_version,
        "expires_at": _utc_text(intent.expires_at),
        "instrument_id": str(intent.instrument_id),
        "intent_id": str(intent.id),
        "limit_price": (
            None if intent.limit_price is None else canonical_decimal_text(intent.limit_price)
        ),
        "order_type": intent.order_type.value,
        "purpose": intent.purpose.value,
        "quantity": canonical_decimal_text(intent.quantity),
        "side": intent.side.value,
        "stop_price": (
            None if intent.stop_price is None else canonical_decimal_text(intent.stop_price)
        ),
        "strategy_version": intent.strategy_version,
        "time_in_force": intent.time_in_force.value,
    }


def canonical_order_intent_sha256(intent: OrderIntent) -> str:
    """Hash the one canonical normalized intent representation."""

    encoded = json.dumps(
        canonical_order_intent_payload(intent),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["canonical_order_intent_payload", "canonical_order_intent_sha256"]
