"""Pure Robinhood-2 declaration observations, never authenticated execution facts.

No transport, credentials, domain-order conversion, ledger or promotion authority.
Regulatory/clearing observations do not establish final or complete customer fees.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Context, Decimal, Inexact, InvalidOperation, Overflow, Rounded, localcontext
from typing import Literal, NoReturn, cast
from uuid import UUID

ORDER_DECLARATION_SHA256 = "ee8c4019da683b7bfd56ff62ad20f0cf1d3d4080f3baa5f6f785a50a218fd470"
MAX_PAGE_BYTES = 1_048_576
MAX_ROWS = 2_000
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?\Z")
_STAMP = re.compile(
    r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,9}))?(Z|\+00:00)\Z"
)
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,31}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_STATES = frozenset(
    {
        "new",
        "queued",
        "unconfirmed",
        "partially_filled",
        "filled",
        "cancelled",
        "rejected",
        "failed",
        "voided",
        "pending_cancelled",
        "partially_filled_rest_cancelled",
        "locating",
        "locate_failed",
    }
)
_FILTER_STATES = frozenset(
    {
        "new",
        "queued",
        "confirmed",
        "unconfirmed",
        "partially_filled",
        "filled",
        "cancelled",
        "rejected",
        "failed",
        "voided",
    }
)
_REQUIRED = frozenset(
    {
        "average_price",
        "created_at",
        "cumulative_quantity",
        "dollar_based_amount",
        "executions",
        "fees",
        "id",
        "instrument_id",
        "last_transaction_at",
        "market_hours",
        "placed_agent",
        "price",
        "quantity",
        "side",
        "state",
        "stop_price",
        "symbol",
        "time_in_force",
        "trigger",
        "type",
    }
)
_OPTIONAL = frozenset({"ref_id", "reject_reason"})


class EquityHistoryError(ValueError):
    def __init__(self) -> None:
        super().__init__("equity_history_invalid")


def _check(condition: bool) -> None:
    if not condition:
        raise EquityHistoryError()


def _text(value: object, maximum: int = 128, *, empty: bool = False) -> str:
    _check(type(value) is str)
    value = cast(str, value)
    _check((empty or bool(value)) and len(value) <= maximum)
    _check(all(ord(c) >= 32 and ord(c) != 127 for c in value))
    return value


def _integer(value: object) -> int:
    _check(type(value) is int and 0 <= value <= 2**63 - 1)
    return cast(int, value)


def _uuid(value: object) -> str:
    value = _text(value, 36)
    _check(str(UUID(value)) == value)
    return value


def _stamp(value: object, receipt: int, *, minimum: int = 0) -> int:
    match = _STAMP.fullmatch(_text(value, 40))
    _check(match is not None)
    assert match is not None
    try:
        instant = datetime.fromisoformat(match[1] + "+00:00")
    except ValueError:
        raise EquityHistoryError() from None
    delta = instant - _EPOCH
    result = _integer(
        (delta.days * 86400 + delta.seconds) * 10**9 + int((match[2] or "").ljust(9, "0"))
    )
    _check(minimum <= result <= receipt)
    return result


def _decimal(value: object, *, positive: bool = False) -> Decimal:
    raw = _text(value, 39)
    _check(_DECIMAL.fullmatch(raw) is not None)
    parsed = Decimal(raw)
    _check(not positive or parsed > 0)
    return parsed


def _nullable_decimal(value: object) -> Decimal | None:
    return None if value is None else _decimal(value, positive=True)


def _keys(
    value: object, required: frozenset[str], optional: frozenset[str] = frozenset()
) -> dict[str, object]:
    _check(type(value) is dict)
    result = cast(dict[str, object], value)
    _check(required <= result.keys() <= required | optional)
    return result


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        _check(key not in result)
        result[key] = value
    return result


def _reject_number(_: str) -> NoReturn:
    raise EquityHistoryError()


def _decode(body: bytes) -> dict[str, object]:
    _check(type(body) is bytes and 0 < len(body) <= MAX_PAGE_BYTES)
    quoted = escaped = False
    depth = 0
    for char in body:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (91, 123):
            depth += 1
            _check(depth <= 8)
        elif char in (93, 125):
            depth -= 1
    return _keys(
        json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_int=_reject_number,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        ),
        frozenset({"data", "guide"}),
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _cursor(value: object) -> str | None:
    return None if value is None else _text(value, 4096)


@dataclass(frozen=True, slots=True, repr=False)
class EquityHistoryRequest:
    account_fingerprint: str
    filters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _check(
            type(self.account_fingerprint) is str
            and _HASH.fullmatch(self.account_fingerprint) is not None
        )
        _check(type(self.filters) is tuple and len(self.filters) <= 5)
        previous = ""
        for pair in self.filters:
            _check(type(pair) is tuple and len(pair) == 2)
            key, value = pair
            _check(
                type(key) is str
                and key > previous
                and key in {"created_at_gte", "order_id", "placed_agent", "state", "symbol"}
            )
            _text(value, 128)
            if key == "created_at_gte":
                _stamp(
                    value + "T00:00:00Z"
                    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value)
                    else value,
                    2**63 - 1,
                )
            elif key == "order_id":
                try:
                    _uuid(value)
                except ValueError:
                    raise EquityHistoryError() from None
            elif key == "state":
                _check(value in _FILTER_STATES)
            elif key == "symbol":
                _check(_SYMBOL.fullmatch(value) is not None)
            previous = key

    @property
    def request_hash(self) -> str:
        self.__post_init__()
        return _digest(
            {
                "schema": "robinhood-2-equity-history-request-v1",
                "account": self.account_fingerprint,
                "filters": self.filters,
            }
        )


class _Unqualified:
    __slots__ = ()

    @property
    def authenticated(self) -> Literal[False]:
        return False

    @property
    def execution_eligible(self) -> Literal[False]:
        return False

    @property
    def promotable(self) -> Literal[False]:
        return False

    @property
    def fees_final(self) -> None:
        return None

    @property
    def history_complete(self) -> None:
        return None


@dataclass(frozen=True, slots=True, repr=False)
class EquityExecutionObservation(_Unqualified):
    id: str
    price: Decimal
    quantity: Decimal
    fees: Decimal
    timestamp_ns: int
    source_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class EquityOrderObservation(_Unqualified):
    id: str
    instrument_id: str
    symbol: str
    side: str
    state: str
    placed_agent: str
    market_hours: str
    time_in_force: str
    trigger: str
    type: str
    created_at_ns: int
    last_transaction_at_ns: int | None
    average_price: Decimal | None
    cumulative_quantity: Decimal
    quantity: Decimal | None
    price: Decimal | None
    stop_price: Decimal | None
    dollar_amount: Decimal | None
    fees: Decimal
    ref_id: str | None
    reject_reason: str | None
    executions: tuple[EquityExecutionObservation, ...] | None
    duplicate_executions: int
    execution_quantity: Decimal | None
    execution_fees: Decimal | None
    issues: tuple[str, ...]
    source_sha256: str

    @property
    def internally_consistent(self) -> bool:
        return not self.issues


@dataclass(frozen=True, slots=True, repr=False)
class EquityOrdersPage(_Unqualified):
    body: bytes
    body_sha256: str
    request: EquityHistoryRequest
    requested_cursor: str | None
    received_at_ns: int
    declaration_sha256: str
    orders: tuple[EquityOrderObservation, ...]
    next_cursor: str | None
    next_present: bool

    @property
    def page_hash(self) -> str:
        return _digest(
            {
                "schema": "robinhood-2-equity-orders-page-v1",
                "body": self.body_sha256,
                "request": self.request.request_hash,
                "cursor": self.requested_cursor,
                "receipt": self.received_at_ns,
                "declaration": self.declaration_sha256,
            }
        )


def _executions(
    value: object, created: int, receipt: int
) -> tuple[tuple[EquityExecutionObservation, ...] | None, int]:
    if value is None:
        return None, 0
    _check(type(value) is list and len(cast(list[object], value)) <= MAX_ROWS)
    seen: dict[str, EquityExecutionObservation] = {}
    duplicates = 0
    for item in cast(list[object], value):
        row = _keys(item, frozenset({"fees", "id", "price", "quantity", "timestamp"}))
        execution = EquityExecutionObservation(
            _uuid(row["id"]),
            _decimal(row["price"], positive=True),
            _decimal(row["quantity"], positive=True),
            _decimal(row["fees"]),
            _stamp(row["timestamp"], receipt, minimum=created),
            _digest(row),
        )
        if execution.id in seen:
            _check(seen[execution.id] == execution)
            duplicates += 1
        else:
            seen[execution.id] = execution
    return tuple(seen.values()), duplicates


def _order(value: object, receipt: int) -> EquityOrderObservation:
    row = _keys(value, _REQUIRED, _OPTIONAL)
    created = _stamp(row["created_at"], receipt)
    last = (
        None
        if row["last_transaction_at"] is None
        else _stamp(row["last_transaction_at"], receipt, minimum=created)
    )
    average, quantity, price, stop = (
        _nullable_decimal(row[key]) for key in ("average_price", "quantity", "price", "stop_price")
    )
    cumulative, fees = _decimal(row["cumulative_quantity"]), _decimal(row["fees"])
    dollar = row["dollar_based_amount"]
    dollar_amount = None
    if dollar is not None:
        money = _keys(dollar, frozenset({"amount", "currency_code"}))
        _check(money["currency_code"] == "USD")
        dollar_amount = _decimal(money["amount"], positive=True)
    source, state, symbol = (_text(row[key]) for key in ("placed_agent", "state", "symbol"))
    _check(_SYMBOL.fullmatch(symbol) is not None)
    for key, choices in (
        ("side", {"buy", "sell"}),
        ("market_hours", {"regular_hours", "extended_hours", "all_day_hours"}),
        ("time_in_force", {"gfd", "gtc"}),
        ("trigger", {"immediate", "stop"}),
        ("type", {"market", "limit"}),
    ):
        _check(type(row[key]) is str and row[key] in choices)
    ref = _text(row["ref_id"], 1024, empty=True) if "ref_id" in row else None
    reason = _text(row["reject_reason"], 8192, empty=True) if "reject_reason" in row else None
    executions, duplicates = _executions(row["executions"], created, receipt)
    execution_quantity = execution_fees = None
    issues: list[str] = []
    if executions is None:
        issues.append("executions_unknown")
    else:
        with localcontext(Context(prec=64, traps=[Inexact, InvalidOperation, Overflow, Rounded])):
            execution_quantity = sum((x.quantity for x in executions), Decimal(0))
            execution_fees = sum((x.fees for x in executions), Decimal(0))
        if execution_quantity != cumulative:
            issues.append("execution_quantity_mismatch")
        if execution_fees != fees:
            issues.append("execution_fees_mismatch")
        if executions and (last is None or last < max(x.timestamp_ns for x in executions)):
            issues.append("last_transaction_before_fill")
    if state not in _STATES:
        issues.append("state_unknown")
    if quantity is None and dollar_amount is None:
        issues.append("requested_basis_unknown")
    if quantity is not None and cumulative > quantity:
        issues.append("requested_quantity_exceeded")
    if state == "filled" and (cumulative == 0 or (quantity is not None and cumulative != quantity)):
        issues.append("filled_quantity_mismatch")
    if cumulative > 0 and average is None:
        issues.append("average_price_missing")
    if cumulative == 0 and average is not None:
        issues.append("average_price_unexpected")
    if row["type"] == "limit" and price is None:
        issues.append("limit_price_missing")
    if row["type"] == "market" and price is not None:
        issues.append("market_price_unexpected")
    if row["trigger"] == "stop" and stop is None:
        issues.append("stop_price_missing")
    if row["trigger"] == "immediate" and stop is not None:
        issues.append("stop_price_unexpected")
    if dollar_amount is not None and (row["type"] != "market" or row["trigger"] != "immediate"):
        issues.append("dollar_order_type_mismatch")
    return EquityOrderObservation(
        _uuid(row["id"]),
        _uuid(row["instrument_id"]),
        symbol,
        cast(str, row["side"]),
        state,
        source,
        cast(str, row["market_hours"]),
        cast(str, row["time_in_force"]),
        cast(str, row["trigger"]),
        cast(str, row["type"]),
        created,
        last,
        average,
        cumulative,
        quantity,
        price,
        stop,
        dollar_amount,
        fees,
        ref,
        reason,
        executions,
        duplicates,
        execution_quantity,
        execution_fees,
        tuple(issues),
        _digest(row),
    )


def parse_equity_orders_page(
    body: bytes,
    *,
    request: EquityHistoryRequest,
    requested_cursor: str | None,
    received_at_ns: int,
    declaration_sha256: str,
) -> EquityOrdersPage:
    """Decode strict supplied bytes; caller declaration identity is not authentication."""
    try:
        _check(type(request) is EquityHistoryRequest)
        request.__post_init__()
        _cursor(requested_cursor)
        receipt = _integer(received_at_ns)
        _check(type(declaration_sha256) is str and declaration_sha256 == ORDER_DECLARATION_SHA256)
        envelope = _decode(body)
        _text(envelope["guide"], 65536, empty=True)
        data = _keys(envelope["data"], frozenset({"orders"}), frozenset({"next"}))
        rows = data["orders"]
        _check(type(rows) is list and len(cast(list[object], rows)) <= MAX_ROWS)
        next_cursor = None
        if "next" in data:
            next_cursor = _text(data["next"], 4096, empty=True)
        orders = tuple(_order(row, receipt) for row in cast(list[object], rows))
        return EquityOrdersPage(
            body,
            hashlib.sha256(body).hexdigest(),
            request,
            requested_cursor,
            receipt,
            declaration_sha256,
            orders,
            next_cursor,
            "next" in data,
        )
    except (ValueError, TypeError, ArithmeticError, RecursionError, OverflowError):
        raise EquityHistoryError() from None
