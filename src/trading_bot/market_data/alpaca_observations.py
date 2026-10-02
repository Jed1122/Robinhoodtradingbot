"""Pure SPY SIP quote/status/LULD syntax for forward observations.

The wire keys follow Alpaca's official stock-stream mappings in ``alpaca-py``
(``alpaca/data/mappings.py``) and ``alpaca-trade-api-python``
(``alpaca_trade_api/entity_v2.py`` and ``stream.py``). Codes and messages are
retained without inventing trading eligibility. No credential, transport, broker,
or qualified-evidence capability is present here.

Provider event time and an injected local receipt time are separate observations;
their difference does not establish latency. Stream identity is observation_hash,
which binds frame and row position as well as exact-body identity. An embedded
AlpacaQuoteRecord uses page_index=0 for native-record compatibility, so its
record_hash alone is not a stream event identity.
"""

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, cast

from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.alpaca_native import AlpacaQuoteRecord, parse_timestamp_ns
from trading_bot.market_data.bundle_codec import _object, _reject_number
from trading_bot.market_data.recording import content_hash

MAX_FRAME_BYTES = 1_048_576
MAX_FRAME_ROWS = 1000
MAX_NUMBER_CHARACTERS = 512
MAX_RAW_STRING_CHARACTERS = 4096
_MAX_INTEGER = 2**63 - 1
_COMMON_KEYS = {"T", "S", "t", "z"}
_QUOTE_KEYS = _COMMON_KEYS | {"bp", "ap", "bs", "as", "bx", "ax", "c"}
_STATUS_KEYS = _COMMON_KEYS | {"sc", "sm", "rc", "rm"}
_LULD_KEYS = _COMMON_KEYS | {"u", "d", "i"}


class AlpacaObservationError(ValueError):
    """Opaque syntax/identity failure; never includes provider payload values."""

    def __init__(self) -> None:
        super().__init__("alpaca_observation_invalid")


def _check(value: bool) -> None:
    if not value:
        raise AlpacaObservationError()


def _integer(value: object, maximum: int = _MAX_INTEGER) -> int:
    _check(type(value) is int and 0 <= value <= maximum)
    return cast(int, value)


def _raw_string(value: object) -> str:
    # Empty/space strings are wire information, not missing status semantics.
    _check(type(value) is str and len(value) <= MAX_RAW_STRING_CHARACTERS)
    return cast(str, value)


def _decimal(value: Decimal) -> Decimal:
    result = require_bounded_decimal(value, "observation price", nonnegative=True)
    # The shared domain helper permits arbitrary zero exponents. Bound the wire
    # representation too, including zero, before content addressing/arithmetic.
    exponent = result.as_tuple().exponent
    _check(type(exponent) is int and abs(exponent) <= MAX_NUMBER_CHARACTERS)
    _check(len(result.as_tuple().digits) <= MAX_NUMBER_CHARACTERS)
    return result


def _price(value: object) -> Decimal:
    _check(type(value) in (int, Decimal))
    return _decimal(Decimal(cast(int | Decimal, value)))


def _parse_integer(value: str) -> int:
    _check(value != "-0" and len(value) <= MAX_NUMBER_CHARACTERS)
    return int(value)


def _parse_decimal(value: str) -> Decimal:
    _check(len(value) <= MAX_NUMBER_CHARACTERS)
    return _decimal(Decimal(value))


def _frame_json(body: bytes) -> list[object]:
    _check(type(body) is bytes and 0 < len(body) <= MAX_FRAME_BYTES)
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
            _check(depth <= 3)
        elif char in (93, 125):
            depth -= 1
    result = json.loads(
        body.decode("utf-8"),
        object_pairs_hook=_object,
        parse_int=_parse_integer,
        parse_float=_parse_decimal,
        parse_constant=_reject_number,
    )
    _check(type(result) is list and len(result) <= MAX_FRAME_ROWS)
    return cast(list[object], result)


@dataclass(frozen=True, slots=True, repr=False)
class AlpacaStreamObservation:
    kind: Literal["quote", "status", "luld"]
    frame_index: int
    row_index: int
    timestamp_ns: int
    received_at_ns: int
    body_sha256: str
    quote: AlpacaQuoteRecord | None
    tape: str
    status_code: str | None = None
    status_message: str | None = None
    reason_code: str | None = None
    reason_message: str | None = None
    upper_band: Decimal | None = None
    lower_band: Decimal | None = None
    indicator: str | None = None
    source_qualified: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        try:
            _check(type(self.kind) is str and self.kind in ("quote", "status", "luld"))
            _integer(self.frame_index)
            _integer(self.row_index, MAX_FRAME_ROWS - 1)
            _integer(self.timestamp_ns)
            _integer(self.received_at_ns)
            _require_sha256_hex(self.body_sha256, "body")
            _check(type(self.tape) is str and self.tape in ("A", "B", "C"))
            statuses = (
                self.status_code,
                self.status_message,
                self.reason_code,
                self.reason_message,
            )
            if self.kind == "quote":
                _check(type(self.quote) is AlpacaQuoteRecord)
                if self.quote is None:
                    raise AlpacaObservationError()
                self.quote.__post_init__()
                _decimal(self.quote.bid)
                _decimal(self.quote.ask)
                _check(
                    self.quote.page_index == 0
                    and self.quote.row_index == self.row_index
                    and self.quote.timestamp_ns == self.timestamp_ns
                    and self.quote.body_sha256 == self.body_sha256
                    and self.quote.tape == self.tape
                )
            else:
                _check(self.quote is None)
            if self.kind == "status":
                for value in statuses:
                    _raw_string(value)
            else:
                _check(all(value is None for value in statuses))
            if self.kind == "luld":
                _check(type(self.upper_band) is Decimal and type(self.lower_band) is Decimal)
                _decimal(cast(Decimal, self.upper_band))
                _decimal(cast(Decimal, self.lower_band))
                _raw_string(self.indicator)
            else:
                _check(
                    self.upper_band is None and self.lower_band is None and self.indicator is None
                )
            _check(
                self.source_qualified is False
                and self.evidence_promotable is False
                and self.execution_enabled is False
            )
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise AlpacaObservationError() from None

    @property
    def observation_hash(self) -> str:
        self.__post_init__()
        return content_hash({"schema": "alpaca-spy-stream-observation-v1", "observation": self})

    @property
    def observation_reasons(self) -> tuple[str, ...]:
        self.__post_init__()
        reasons = ["stream_source_qualification_unverified", "execution_eligibility_unverified"]
        if self.received_at_ns < self.timestamp_ns:
            reasons.append("receipt_clock_precedes_provider_timestamp")
        if self.quote is not None:
            if self.quote.bid == 0:
                reasons.append("inactive_bid")
            if self.quote.ask == 0:
                reasons.append("inactive_ask")
            if self.quote.bid > 0 and self.quote.ask > 0:
                if self.quote.bid > self.quote.ask:
                    reasons.append("crossed_quote")
                elif self.quote.bid == self.quote.ask:
                    reasons.append("locked_quote")
        return tuple(reasons)


def parse_alpaca_observation_frame(
    body: bytes, *, frame_index: int, received_at_ns: int
) -> tuple[AlpacaStreamObservation, ...]:
    """Parse only SPY q/s/l rows atomically; control/error frames belong to transport.

    No sort or timestamp deduplication occurs: repeated and out-of-order provider
    timestamps remain distinct frame/row observations. Empty arrays carry no
    observations or completeness evidence.
    """
    try:
        _integer(frame_index)
        _integer(received_at_ns)
        rows = _frame_json(body)
        digest = hashlib.sha256(body).hexdigest()
        result: list[AlpacaStreamObservation] = []
        for index, entry in enumerate(rows):
            _check(type(entry) is dict)
            row = cast(dict[str, object], entry)
            wire_kind = row.get("T")
            _check(type(wire_kind) is str and wire_kind in ("q", "s", "l"))
            keys = {"q": _QUOTE_KEYS, "s": _STATUS_KEYS, "l": _LULD_KEYS}[cast(str, wire_kind)]
            _check(set(row) == keys and row["S"] == "SPY")
            stamp = parse_timestamp_ns(cast(str, row["t"]))
            tape = cast(str, row["z"])
            if wire_kind == "q":
                _check(type(row["c"]) is list)
                quote = AlpacaQuoteRecord(
                    digest,
                    0,
                    index,
                    stamp,
                    _price(row["bp"]),
                    _price(row["ap"]),
                    _integer(row["bs"], 2**32 - 1),
                    _integer(row["as"], 2**32 - 1),
                    cast(str, row["bx"]),
                    cast(str, row["ax"]),
                    tuple(cast(list[str], row["c"])),
                    tape,
                )
                result.append(
                    AlpacaStreamObservation(
                        "quote", frame_index, index, stamp, received_at_ns, digest, quote, tape
                    )
                )
            elif wire_kind == "s":
                result.append(
                    AlpacaStreamObservation(
                        "status",
                        frame_index,
                        index,
                        stamp,
                        received_at_ns,
                        digest,
                        None,
                        tape,
                        status_code=_raw_string(row["sc"]),
                        status_message=_raw_string(row["sm"]),
                        reason_code=_raw_string(row["rc"]),
                        reason_message=_raw_string(row["rm"]),
                    )
                )
            else:
                result.append(
                    AlpacaStreamObservation(
                        "luld",
                        frame_index,
                        index,
                        stamp,
                        received_at_ns,
                        digest,
                        None,
                        tape,
                        upper_band=_price(row["u"]),
                        lower_band=_price(row["d"]),
                        indicator=_raw_string(row["i"]),
                    )
                )
        return tuple(result)
    except (ValueError, TypeError, ArithmeticError, RecursionError, AttributeError, KeyError):
        raise AlpacaObservationError() from None
