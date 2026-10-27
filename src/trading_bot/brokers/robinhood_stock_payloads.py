"""Pure arguments for a narrow official Robinhood stock-order subset.

The 2026-10-26 declared review/place inputs support these regular-hours GFD
share orders. Omitting tax_lots requests documented default FIFO; it does not
verify an account's actual cost basis. No transport, response, approval, risk,
position, eligibility or live authority exists here. Callers persist the UUID
and account/reference-to-terms binding before any separately authorized call.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal
from uuid import RFC_4122, UUID

from trading_bot.domain.decimal_utils import canonical_decimal_text, require_bounded_decimal


class StockOrderPayloadError(ValueError):
    """Fixed sanitized validation failure; never contains supplied account data."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise StockOrderPayloadError(reason)


def _decimal_text(value: Decimal, reason: str) -> str:
    try:
        require_bounded_decimal(value, "stock_value", positive=True)
        return canonical_decimal_text(value)
    except ValueError:
        raise StockOrderPayloadError(reason) from None


def _canonical_hash(value: dict[str, str]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_ref_id(value: str) -> None:
    _require(type(value) is str and len(value) == 36, "stock_ref_id_invalid")
    try:
        parsed = UUID(value)
    except ValueError:
        raise StockOrderPayloadError("stock_ref_id_invalid") from None
    _require(str(parsed) == value and parsed.variant == RFC_4122, "stock_ref_id_invalid")


@dataclass(frozen=True, slots=True, repr=False)
class StockOrderTerms:
    account_number: str
    symbol: str
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"]
    quantity: Decimal
    limit_price: Decimal | None = None
    market_hours: Literal["regular_hours"] = "regular_hours"
    time_in_force: Literal["gfd"] = "gfd"

    def __post_init__(self) -> None:
        _require(
            type(self.account_number) is str
            and 0 < len(self.account_number) <= 128
            and self.account_number.isascii()
            and self.account_number.isprintable()
            and not any(c.isspace() for c in self.account_number),
            "stock_account_invalid",
        )
        _require(
            type(self.symbol) is str
            and 0 < len(self.symbol) <= 128
            and self.symbol[0].isascii()
            and self.symbol[0].isalpha()
            and self.symbol == self.symbol.upper()
            and all(c.isascii() and (c.isalnum() or c in ".-/") for c in self.symbol),
            "stock_symbol_invalid",
        )
        _require(type(self.side) is str and self.side in ("buy", "sell"), "stock_side_unsupported")
        _require(
            type(self.order_type) is str and self.order_type in ("market", "limit"),
            "stock_order_type_unsupported",
        )
        _require(
            type(self.market_hours) is str and self.market_hours == "regular_hours",
            "stock_market_hours_unsupported",
        )
        _require(
            type(self.time_in_force) is str and self.time_in_force == "gfd",
            "stock_time_in_force_unsupported",
        )
        quantity = _decimal_text(self.quantity, "stock_quantity_invalid")
        _require(len(quantity.partition(".")[2]) <= 6, "stock_quantity_invalid")
        if self.order_type == "market":
            _require(self.limit_price is None, "stock_market_limit_price_forbidden")
        else:
            _require("." not in quantity, "stock_limit_quantity_must_be_whole")
            _require(self.limit_price is not None, "stock_limit_price_invalid")
            if self.limit_price is not None:
                _decimal_text(self.limit_price, "stock_limit_price_invalid")


def _review_arguments(terms: StockOrderTerms) -> dict[str, str]:
    _require(type(terms) is StockOrderTerms, "typed_stock_order_terms_required")
    terms.__post_init__()
    arguments = {
        "account_number": terms.account_number,
        "symbol": terms.symbol,
        "side": terms.side,
        "type": terms.order_type,
        "quantity": _decimal_text(terms.quantity, "stock_quantity_invalid"),
        "market_hours": terms.market_hours,
        "time_in_force": terms.time_in_force,
    }
    if terms.limit_price is not None:
        arguments["limit_price"] = _decimal_text(terms.limit_price, "stock_limit_price_invalid")
    return arguments


def _order_binding_hash(terms_hash: str, ref_id: str) -> str:
    return _canonical_hash(
        {"policy": "robinhood-stock-arguments-v1", "terms_hash": terms_hash, "ref_id": ref_id}
    )


@dataclass(frozen=True, slots=True, repr=False)
class PreparedStockOrderPayloads:
    """One immutable logical-order binding; returned dictionaries are fresh copies.

    Hashes bind arguments; they do not authenticate a broker review or authorize
    submission. Independent objects can reuse a reference, so the later durable
    owner must reject account/ref_id rebinding to different terms.
    """

    terms: StockOrderTerms
    ref_id: str
    terms_hash: str = field(init=False)
    order_binding_hash: str = field(init=False)

    def __post_init__(self) -> None:
        arguments = _review_arguments(self.terms)
        _require_ref_id(self.ref_id)
        terms_hash = _canonical_hash(arguments)
        object.__setattr__(self, "terms_hash", terms_hash)
        object.__setattr__(self, "order_binding_hash", _order_binding_hash(terms_hash, self.ref_id))

    def _checked_arguments(self) -> dict[str, str]:
        arguments = _review_arguments(self.terms)
        _require_ref_id(self.ref_id)
        _require(
            _canonical_hash(arguments) == self.terms_hash
            and _order_binding_hash(self.terms_hash, self.ref_id) == self.order_binding_hash,
            "stock_order_binding_changed",
        )
        return arguments

    @property
    def review_arguments(self) -> dict[str, str]:
        return self._checked_arguments()

    @property
    def place_arguments(self) -> dict[str, str]:
        return self._checked_arguments() | {"ref_id": self.ref_id}


def prepare_stock_order_payloads(
    terms: StockOrderTerms, *, ref_id: str
) -> PreparedStockOrderPayloads:
    """Prepare only; caller supplies and persists one UUID for the logical order."""
    return PreparedStockOrderPayloads(terms, ref_id)
