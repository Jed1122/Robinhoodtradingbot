"""Exact versioned local-fact codec, not a provider/source admission parser."""

import json
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal, DecimalException
from enum import Enum
from typing import Any

from trading_bot.accounting.owned_economic_models import (
    MAX_BYTES,
    VERSION,
    Bind,
    Complete,
    EconomicEvent,
    Execution,
    FinalFees,
    Funding,
    Opening,
    Release,
    Reserve,
    Settlement,
    deny,
)
from trading_bot.domain import (
    AccountId,
    AssetClass,
    BrokerOrder,
    ConfigHash,
    DataHash,
    InstrumentId,
    OrderId,
    OrderIntent,
    OrderPurpose,
    OrderState,
    OrderType,
    Side,
    TimeInForce,
)
from trading_bot.domain.decimal_utils import canonical_decimal_text
from trading_bot.domain.owned_order_lifecycle import decode_owned_event, encode_owned_event


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    return value


def encode_economic_event(event: EconomicEvent) -> str:
    try:
        if type(event) is not EconomicEvent:
            deny()
        event.__post_init__()
        data = _plain(event)
        data["version"] = VERSION
        data["kind"] = type(event.payload).__name__
        if type(event.payload) is Execution:
            data["payload"] = {"event": encode_owned_event(event.payload.event)}
        text = json.dumps(
            data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
        if len(text.encode("ascii")) > MAX_BYTES:
            deny()
        return text
    except (ValueError, TypeError, AttributeError, DecimalException, RecursionError):
        deny()


def _decimal(raw: Any) -> Decimal:
    if type(raw) is not str:
        deny()
    return Decimal(raw)


def _intent(raw: dict[str, Any]) -> OrderIntent:
    data = dict(raw)
    for name in ("quantity", "limit_price", "stop_price"):
        if data[name] is not None:
            data[name] = _decimal(data[name])
    for name in ("created_at", "expires_at"):
        data[name] = datetime.fromisoformat(data[name])
    for name, enum in (
        ("asset_class", AssetClass),
        ("side", Side),
        ("purpose", OrderPurpose),
        ("order_type", OrderType),
        ("time_in_force", TimeInForce),
    ):
        data[name] = enum(data[name])
    return OrderIntent(**data)


def _order(raw: dict[str, Any]) -> BrokerOrder:
    data = dict(raw)
    for name in ("requested_quantity", "filled_quantity", "limit_price", "stop_price"):
        if data[name] is not None:
            data[name] = _decimal(data[name])
    for name in ("created_at", "updated_at"):
        data[name] = datetime.fromisoformat(data[name])
    for name, enum in (
        ("side", Side),
        ("purpose", OrderPurpose),
        ("order_type", OrderType),
        ("time_in_force", TimeInForce),
        ("state", OrderState),
    ):
        data[name] = enum(data[name])
    return BrokerOrder(**data)


def decode_economic_event(text: str) -> EconomicEvent:
    try:
        if type(text) is not str or len(text) > MAX_BYTES:
            deny()
        root = json.loads(text)
        if type(root) is not dict or root["version"] != VERSION:
            deny()
        raw, kind = root["payload"], root["kind"]
        if type(raw) is not dict:
            deny()
        p: Any
        if kind == "Opening":
            p = Opening(InstrumentId(raw["instrument_id"]), _decimal(raw["cash"]))
        elif kind == "Reserve":
            p = Reserve(
                _intent(raw["intent"]),
                raw["episode_id"],
                _decimal(raw["fee_bound"]),
                _decimal(raw["reserved_risk"]),
            )
        elif kind == "Bind":
            p = Bind(_order(raw["order"]))
        elif kind == "Execution":
            p = Execution(decode_owned_event(raw["event"]))
        elif kind == "FinalFees":
            p = FinalFees(OrderId(raw["order_id"]), _decimal(raw["total"]))
        elif kind == "Settlement":
            p = Settlement(raw["obligation_id"], _decimal(raw["amount"]))
        elif kind == "Release":
            p = Release(OrderId(raw["order_id"]))
        elif kind == "Complete":
            p = Complete(raw["episode_id"])
        elif kind == "Funding":
            p = Funding(_decimal(raw["amount"]))
        else:
            deny()
        event = EconomicEvent(
            root["id"],
            AccountId(root["account_id"]),
            datetime.fromisoformat(root["occurred_at"]),
            DataHash(root["source_hash"]),
            ConfigHash(root["config_hash"]),
            p,
        )
        if encode_economic_event(event) != text:
            deny()
        return event
    except (ValueError, TypeError, KeyError, AttributeError, DecimalException, RecursionError):
        deny()
