"""Offline linkage of declared execution receipts, never customer certification.

Quote prices come from reparsed exact Alpaca frames. A consistent hash chain and
declared clock session are not provider authentication or hardware attestation.
No credential, broker, risk decision or network capability exists here.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import cast

from trading_bot.market_data.alpaca_native import parse_timestamp_ns
from trading_bot.market_data.alpaca_observations import (
    AlpacaStreamObservation,
    parse_alpaca_observation_frame,
)
from trading_bot.market_data.bundle_codec import (
    _decimal,
    _digest,
    _json,
    _mapping,
    _string,
    _time,
)
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.recording import canonical_json
from trading_bot.research.etf_cost_calibration import measure_etf_cost_observations
from trading_bot.research.etf_costs import _fee_context

MAX_BODY_BYTES = 1_048_576
MAX_SOURCE_BYTES = 8_388_608
MAX_EVENTS = 10_000
_LIMITS = BundleLimits(MAX_BODY_BYTES, MAX_BODY_BYTES, MAX_SOURCE_BYTES, MAX_EVENTS, 32)
_PAYLOAD_KEYS = {
    "alpaca_frame": {"frame_index", "body_sha256"},
    "decision": {"order_hash", "side", "terms_hash", "observation_hash"},
    "submitted": {"order_hash", "source_hash"},
    "acknowledged": {"order_hash", "source_hash"},
    "fill": {"order_hash", "fill_hash", "quantity", "price", "source_hash"},
    "terminal": {"order_hash", "source_hash", "state", "charged_fees"},
    "final_fees": {"order_hash", "terminal_hash", "source_hash", "charged_fees"},
}


class EtfReceiptError(ValueError):
    def __init__(self) -> None:
        super().__init__("etf_execution_receipt_invalid")


def _check(condition: bool) -> None:
    if not condition:
        raise EtfReceiptError()


def _integer(value: object, *, positive: bool = False) -> int:
    _check(type(value) is int and (1 if positive else 0) <= value <= 2**63 - 1)
    return cast(int, value)


def _decode(body: bytes) -> object:
    _check(type(body) is bytes and 0 < len(body) <= MAX_BODY_BYTES)
    return _json(body, max_bytes=MAX_BODY_BYTES, limits=_LIMITS)


def source_digest(body: bytes) -> str:
    _check(type(body) is bytes and 0 < len(body) <= MAX_BODY_BYTES)
    return hashlib.sha256(body).hexdigest()


def _fees(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    names = ("commission", "sec", "taf", "cat", "other")
    row = _mapping(value, {*names, "total", "source_hash"})
    _digest(row["source_hash"])
    amounts = {name: _decimal(row[name]) for name in (*names, "total")}
    _check(all(amount >= 0 for amount in amounts.values()))
    with localcontext(_fee_context()):
        _check(sum((amounts[name] for name in names), Decimal(0)) == amounts["total"])
    return row


def validate_receipt_payload(kind: str, value: object) -> dict[str, object]:
    """Strict safe receipt projection; never accepts account/order identifiers."""
    _check(type(kind) is str and kind in _PAYLOAD_KEYS)
    row = _mapping(value, _PAYLOAD_KEYS[kind])
    for key in (
        "order_hash",
        "source_hash",
        "terms_hash",
        "observation_hash",
        "fill_hash",
        "body_sha256",
        "terminal_hash",
    ):
        if key in row:
            _digest(row[key])
    if kind == "alpaca_frame":
        _integer(row["frame_index"])
    elif kind == "decision":
        _check(row["side"] in ("buy", "sell"))
    elif kind == "fill":
        _check(_decimal(row["quantity"]) > 0 and _decimal(row["price"]) > 0)
    elif kind == "terminal":
        _check(row["state"] in ("filled", "cancelled", "rejected", "failed"))
        _fees(row["charged_fees"])
    elif kind == "final_fees":
        _check(_fees(row["charged_fees"]) is not None)
    return row


def validate_clock_session(body: bytes) -> dict[str, object]:
    row = _mapping(
        _decode(body),
        {
            "schema",
            "nonce",
            "provenance",
            "code_revision",
            "started_at",
            "started_monotonic_ns",
            "maximum_quote_age_ns",
            "evidence_promotable",
        },
    )
    _check(row["schema"] == "etf-execution-clock-session-v1")
    _digest(row["nonce"])
    _check(row["provenance"] in ("paper", "synthetic", "customer"))
    revision = _string(row["code_revision"])
    _check(len(revision) == 40 and all(c in "0123456789abcdef" for c in revision))
    _time(row["started_at"])
    _integer(row["started_monotonic_ns"])
    _integer(row["maximum_quote_age_ns"], positive=True)
    _check(row["evidence_promotable"] is False)
    return row


@dataclass
class _Quote:
    observation: AlpacaStreamObservation
    monotonic_ns: int
    receipt_ns: int

    def usable(self, at_utc: int, at_mono: int, age: int) -> bool:
        q = self.observation.quote
        return bool(
            q is not None
            and 0 < q.bid < q.ask
            and self.observation.timestamp_ns <= self.receipt_ns <= at_utc
            and 0 <= at_utc - self.observation.timestamp_ns <= age
            and 0 <= at_mono - self.monotonic_ns <= age
        )

    def wire(self) -> dict[str, object]:
        q = self.observation.quote
        if q is None:
            raise EtfReceiptError()
        seconds, remainder = divmod(self.observation.timestamp_ns, 1_000_000_000)
        observed = datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=remainder // 1000)
        return {
            "bid": q.bid,
            "ask": q.ask,
            "source_hash": self.observation.body_sha256,
            "observed_at": observed,
            "received_monotonic_ns": self.monotonic_ns,
        }


@dataclass
class _Order:
    decision: dict[str, object]
    quote: _Quote
    submitted: dict[str, object] | None = None
    arrival: _Quote | None = None
    ack: int | None = None
    fills: list[dict[str, object]] = field(default_factory=list)
    terminal: dict[str, object] | None = None
    terminal_hash: str | None = None
    final_fees: dict[str, object] | None = None


def _link(
    session: bytes, receipts: tuple[bytes, ...], sources: dict[str, bytes]
) -> dict[str, object]:
    clock = validate_clock_session(session)
    _check(type(receipts) is tuple and len(receipts) <= MAX_EVENTS)
    _check(type(sources) is dict and len(sources) <= MAX_EVENTS)
    total = 0
    for key, body in sources.items():
        _digest(key)
        _check(source_digest(body) == key)
        total += len(body)
        _check(total <= MAX_SOURCE_BYTES)
    session_hash = source_digest(session)
    previous = None
    previous_utc = parse_timestamp_ns(_string(clock["started_at"]))
    previous_mono = _integer(clock["started_monotonic_ns"])
    age = _integer(clock["maximum_quote_age_ns"], positive=True)
    quotes: dict[str, _Quote] = {}
    orders: dict[str, _Order] = {}
    fills: dict[str, dict[str, object]] = {}
    frame_index = 0
    references: set[str] = set()
    receipt_bytes = 0
    for sequence, body in enumerate(receipts):
        _check(type(body) is bytes)
        receipt_bytes += len(body)
        _check(receipt_bytes <= MAX_SOURCE_BYTES)
        row = _mapping(
            _decode(body),
            {
                "schema",
                "session_hash",
                "sequence",
                "previous_hash",
                "kind",
                "received_at",
                "received_monotonic_ns",
                "payload",
            },
        )
        _check(row["schema"] in ("etf-execution-receipt-v1", "etf-execution-receipt-v2"))
        _check(row["session_hash"] == session_hash)
        _check(_integer(row["sequence"]) == sequence and row["previous_hash"] == previous)
        _time(row["received_at"])
        utc = parse_timestamp_ns(_string(row["received_at"]))
        mono = _integer(row["received_monotonic_ns"])
        _check(previous_utc <= utc and previous_mono <= mono)
        previous_utc, previous_mono, previous = utc, mono, source_digest(body)
        kind = _string(row["kind"])
        payload = validate_receipt_payload(kind, row["payload"])
        _check(kind != "final_fees" or row["schema"] == "etf-execution-receipt-v2")
        for key in ("source_hash", "terms_hash", "body_sha256"):
            if key in payload:
                reference = _string(payload[key])
                _check(reference in sources)
                references.add(reference)
        if kind == "alpaca_frame":
            _check(payload["frame_index"] == frame_index)
            observations = parse_alpaca_observation_frame(
                sources[_string(payload["body_sha256"])],
                frame_index=frame_index,
                received_at_ns=utc,
            )
            frame_index += 1
            for observation in observations:
                if observation.quote is None:
                    continue
                quote = _Quote(observation, mono, utc)
                quotes[observation.observation_hash] = quote
                for order in orders.values():
                    if (
                        order.submitted is not None
                        and order.arrival is None
                        and not order.fills
                        and order.terminal is None
                    ):
                        submitted_utc = parse_timestamp_ns(_string(order.submitted["received_at"]))
                        if submitted_utc <= observation.timestamp_ns and quote.usable(
                            utc, mono, age
                        ):
                            order.arrival = quote
            continue
        order_hash = _string(payload["order_hash"])
        if kind == "decision":
            _check(order_hash not in orders and len(orders) < 1000)
            selected_quote = quotes.get(_string(payload["observation_hash"]))
            if selected_quote is None or not selected_quote.usable(utc, mono, age):
                raise EtfReceiptError()
            orders[order_hash] = _Order(payload, selected_quote)
            continue
        _check(order_hash in orders)
        order = orders[order_hash]
        if kind == "submitted":
            _check(
                order.submitted is None
                and order.terminal is None
                and order.quote.usable(utc, mono, age)
            )
            order.submitted = row
            continue
        _check(order.submitted is not None)
        if kind == "fill" and _string(payload["fill_hash"]) in fills:
            _check(fills[_string(payload["fill_hash"])] == payload)
            continue
        if kind == "final_fees":
            _check(order.terminal is not None and order.terminal_hash == payload["terminal_hash"])
            if order.terminal is None:
                raise EtfReceiptError()
            terminal_payload = cast(dict[str, object], order.terminal["payload"])
            _check(terminal_payload["charged_fees"] is None)
            fees = _fees(payload["charged_fees"])
            _check(fees is not None and fees["source_hash"] == payload["source_hash"])
            if order.final_fees is not None:
                _check(order.final_fees == payload)
            else:
                order.final_fees = payload
            continue
        _check(order.terminal is None)
        if kind == "acknowledged":
            _check(order.ack is None and not order.fills)
            order.ack = mono
        elif kind == "fill":
            _check(order.arrival is not None)
            if not order.fills:
                _check(order.arrival is not None and order.arrival.usable(utc, mono, age))
            fills[_string(payload["fill_hash"])] = payload
            order.fills.append(
                {
                    "fill_hash": payload["fill_hash"],
                    "quantity": payload["quantity"],
                    "price": payload["price"],
                    "received_monotonic_ns": mono,
                }
            )
        elif kind == "terminal":
            _check(payload["state"] != "filled" or bool(order.fills))
            _check(payload["state"] not in ("rejected", "failed") or not order.fills)
            fees = _fees(payload["charged_fees"])
            if fees is not None:
                _check(fees["source_hash"] == payload["source_hash"])
            order.terminal = row
            order.terminal_hash = source_digest(body)
    completed: list[dict[str, object]] = []
    unfilled_outcomes: list[dict[str, object]] = []
    incomplete = unfilled = missing_fees = 0
    for order_hash, order in orders.items():
        if order.terminal is None:
            incomplete += 1
            continue
        if not order.fills:
            unfilled += 1
            outcome = cast(dict[str, object], order.terminal["payload"])
            unfilled_outcomes.append(
                {
                    "order_hash": order_hash,
                    "state": outcome["state"],
                    "charged_fees": (
                        outcome["charged_fees"]
                        if order.final_fees is None
                        else order.final_fees["charged_fees"]
                    ),
                }
            )
            continue
        if order.submitted is None or order.arrival is None:
            raise EtfReceiptError()
        terminal_payload = cast(dict[str, object], order.terminal["payload"])
        submitted_payload = cast(dict[str, object], order.submitted["payload"])
        fee = (
            terminal_payload["charged_fees"]
            if order.final_fees is None
            else order.final_fees["charged_fees"]
        )
        missing_fees += fee is None
        completed.append(
            {
                "order_hash": order_hash,
                "source_hash": submitted_payload["source_hash"],
                "terms_hash": order.decision["terms_hash"],
                "side": order.decision["side"],
                "submitted_at": order.submitted["received_at"],
                "submitted_monotonic_ns": order.submitted["received_monotonic_ns"],
                "acknowledged_monotonic_ns": order.ack,
                "clock_session_hash": session_hash,
                "terminal_monotonic_ns": order.terminal["received_monotonic_ns"],
                "decision_quote": order.quote.wire(),
                "arrival_quote": order.arrival.wire(),
                "fills": order.fills,
                "charged_fees": fee,
                "fee_grouping": "terminal-order-total",
            }
        )
    cost_input = {
        "schema": "etf-cost-observations-v1",
        "provenance": clock["provenance"],
        "execution_broker": "robinhood",
        "market_data_source": "alpaca-sip",
        "orders": completed,
    }
    # Canonicalize Decimal/UTC objects to the unchanged wire schema before return.
    input_bytes = canonical_json(cost_input).encode()
    measure_etf_cost_observations(input_bytes)
    return {
        "cost_input": _decode(input_bytes),
        "completed_order_count": len(completed),
        "incomplete_order_count": incomplete,
        "unfilled_order_count": unfilled,
        "unfilled_outcomes": unfilled_outcomes,
        "missing_fee_order_count": missing_fees,
        "reference_hashes": sorted(references),
        "quote_receipt_bytes_linked": True,
        "clock_session_attested": False,
        "customer_authenticated": False,
        "calibration_verified": False,
        "evidence_promotable": False,
        "execution_enabled": False,
    }


def link_execution_receipts(
    session: bytes, receipts: tuple[bytes, ...], sources: dict[str, bytes]
) -> dict[str, object]:
    try:
        return _link(session, receipts, sources)
    except (ValueError, TypeError, ArithmeticError, AttributeError, RecursionError, KeyError):
        raise EtfReceiptError() from None
