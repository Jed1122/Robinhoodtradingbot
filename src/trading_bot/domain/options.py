"""Broker-neutral options identities. These records confer no execution capability."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_exact_bool,
    _require_exact_enum,
    _require_nonempty,
    _require_nonnegative_int,
    _require_sha256_hex,
    _require_tuple,
    quantize_down,
    require_bounded_decimal,
)
from trading_bot.domain.enums import Side


class OptionKind(StrEnum):
    CALL = "call"
    PUT = "put"


class ExerciseStyle(StrEnum):
    AMERICAN = "american"
    EUROPEAN = "european"


class SettlementKind(StrEnum):
    SHARES = "shares"
    CASH = "cash"


class SettlementTiming(StrEnum):
    AM = "am"
    PM = "pm"


class PositionEffect(StrEnum):
    OPEN = "open"
    CLOSE = "close"


class StructureKind(StrEnum):
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    DEBIT_VERTICAL = "debit_vertical"
    CREDIT_VERTICAL = "credit_vertical"
    IRON_CONDOR = "iron_condor"


def _positive_integer(value: int, name: str) -> None:
    _require_nonnegative_int(value, name)
    if value == 0:
        raise DomainValidationError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class OptionSession:
    """Explicit contract-eligible UTC interval, supplied by a verified calendar."""

    session_id: str
    opens_at: datetime
    closes_at: datetime
    trading_date: date
    exchange_timezone: str

    def __post_init__(self) -> None:
        _require_nonempty(self.session_id, "session_id")
        require_utc(self.opens_at)
        require_utc(self.closes_at)
        if self.opens_at >= self.closes_at:
            raise DomainValidationError("session must open before closing")
        if type(self.trading_date) is not date:
            raise DomainValidationError("session trading_date must be a date")
        _require_nonempty(self.exchange_timezone, "exchange_timezone")
        try:
            zone = ZoneInfo(self.exchange_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise DomainValidationError("unknown exchange timezone") from exc
        if (
            not self.opens_at.astimezone(zone).date()
            <= self.trading_date
            <= (self.closes_at.astimezone(zone).date())
        ):
            raise DomainValidationError("session trading date conflicts with its interval")


@dataclass(frozen=True, slots=True)
class OptionContract:
    contract_id: str
    standardized_id: str
    underlying: str
    kind: OptionKind
    strike: Decimal
    expiration: date
    last_trading_at: datetime
    settlement_at: datetime
    exercise_style: ExerciseStyle
    settlement_kind: SettlementKind
    settlement_timing: SettlementTiming
    premium_multiplier: Decimal
    deliverable_units: Decimal
    deliverable_symbol: str
    adjusted: bool
    tick_size: Decimal
    eligible_sessions: tuple[OptionSession, ...]
    available_at: datetime
    data_hash: str
    currency: Literal["USD"]

    def __post_init__(self) -> None:
        if type(self.currency) is not str or self.currency != "USD":
            raise DomainValidationError("only explicit USD contracts are supported")
        for name in ("contract_id", "standardized_id", "underlying", "deliverable_symbol"):
            _require_nonempty(getattr(self, name), name)
        for name, enum in (
            ("kind", OptionKind),
            ("exercise_style", ExerciseStyle),
            ("settlement_kind", SettlementKind),
            ("settlement_timing", SettlementTiming),
        ):
            _require_exact_enum(getattr(self, name), enum, name)
        for name in ("strike", "premium_multiplier", "tick_size"):
            require_bounded_decimal(getattr(self, name), name, positive=True)
        require_bounded_decimal(self.deliverable_units, "deliverable_units", nonnegative=True)
        _require_exact_bool(self.adjusted, "adjusted")
        if self.adjusted:
            raise DomainValidationError("adjusted deliverables are unsupported")
        if self.settlement_kind is SettlementKind.SHARES and (
            self.deliverable_units != self.premium_multiplier
            or self.deliverable_symbol != self.underlying
        ):
            raise DomainValidationError("inconsistent standard share deliverable")
        if self.settlement_kind is SettlementKind.CASH and self.deliverable_units != 0:
            raise DomainValidationError("cash settlement cannot deliver shares")
        if type(self.expiration) is not date:
            raise DomainValidationError("expiration must be a date, not a timestamp")
        for value in (self.last_trading_at, self.settlement_at, self.available_at):
            require_utc(value)
        if not self.available_at < self.last_trading_at <= self.settlement_at:
            raise DomainValidationError("contract availability/trading/settlement is inconsistent")
        _require_tuple(self.eligible_sessions, "eligible_sessions")
        if not self.eligible_sessions:
            raise DomainValidationError("contract needs explicit eligible sessions")
        previous: OptionSession | None = None
        identifiers: set[str] = set()
        for session in self.eligible_sessions:
            if type(session) is not OptionSession:
                raise DomainValidationError("invalid contract session")
            if (
                session.session_id in identifiers
                or session.trading_date > self.expiration
                or session.closes_at > self.last_trading_at
                or (previous is not None and session.opens_at < previous.closes_at)
            ):
                raise DomainValidationError("contract sessions overlap or exceed last trading")
            identifiers.add(session.session_id)
            previous = session
        _require_sha256_hex(self.data_hash, "data_hash")


@dataclass(frozen=True, slots=True)
class OptionQuote:
    """An observation, not a guarantee of a fill or a trading-ready quote."""

    contract_id: str
    bid: Decimal
    ask: Decimal
    bid_size: int | None
    ask_size: int | None
    event_at: datetime
    received_at: datetime
    underlying_event_at: datetime
    source: str
    data_hash: str
    quality_flags: tuple[str, ...]
    underlying: str

    def __post_init__(self) -> None:
        _require_nonempty(self.contract_id, "contract_id")
        _require_nonempty(self.underlying, "underlying")
        _require_nonempty(self.source, "source")
        require_bounded_decimal(self.bid, "bid", nonnegative=True)
        require_bounded_decimal(self.ask, "ask", positive=True)
        if self.bid > self.ask:
            raise DomainValidationError("crossed option quote")
        for name in ("bid_size", "ask_size"):
            value = getattr(self, name)
            if value is not None:
                _require_nonnegative_int(value, name)
        for value in (self.event_at, self.received_at, self.underlying_event_at):
            require_utc(value)
        if self.received_at < self.event_at:
            raise DomainValidationError("receipt cannot precede event")
        _require_sha256_hex(self.data_hash, "data_hash")
        _require_tuple(self.quality_flags, "quality_flags")
        for flag in self.quality_flags:
            _require_nonempty(flag, "quality_flag")


def executable_quote_reasons(
    contract: OptionContract,
    quote: OptionQuote,
    *,
    as_of: datetime,
    max_age_seconds: Decimal,
    max_underlying_skew_seconds: Decimal,
    allow_locked: bool,
) -> tuple[str, ...]:
    """Strict entry-quality checks. Session half-open intervals avoid close-time entries."""
    if type(contract) is not OptionContract or type(quote) is not OptionQuote:
        raise DomainValidationError("exact contract and quote records required")
    require_utc(as_of)
    require_bounded_decimal(max_age_seconds, "max_age_seconds", positive=True)
    require_bounded_decimal(max_underlying_skew_seconds, "max_skew", nonnegative=True)
    _require_exact_bool(allow_locked, "allow_locked")
    reasons: list[str] = []
    if quote.contract_id != contract.contract_id:
        reasons.append("contract_mismatch")
    if quote.underlying != contract.underlying:
        reasons.append("underlying_mismatch")
    if (
        max(quote.event_at, quote.received_at, quote.underlying_event_at, contract.available_at)
        > as_of
    ):
        reasons.append("future_observation")
    if Decimal(str((as_of - quote.event_at).total_seconds())) > max_age_seconds:
        reasons.append("stale_quote")
    if Decimal(str(abs((quote.event_at - quote.underlying_event_at).total_seconds()))) > (
        max_underlying_skew_seconds
    ):
        reasons.append("underlying_skew")
    if quote.bid == 0:
        reasons.append("zero_bid")
    if quote.bid == quote.ask and not allow_locked:
        reasons.append("locked_quote")
    if quote.bid_size is None or quote.ask_size is None:
        reasons.append("missing_depth")
    elif quote.bid_size == 0 or quote.ask_size == 0:
        reasons.append("empty_depth")
    if (
        quantize_down(quote.bid, contract.tick_size) != quote.bid
        or quantize_down(quote.ask, contract.tick_size) != quote.ask
    ):
        reasons.append("off_tick")
    if quote.quality_flags:
        reasons.append("quality_flags")
    if not any(s.opens_at <= as_of < s.closes_at for s in contract.eligible_sessions):
        reasons.append("outside_contract_session")
    return tuple(reasons)


@dataclass(frozen=True, slots=True)
class OptionLeg:
    contract: OptionContract
    side: Side
    effect: PositionEffect
    ratio: int

    def __post_init__(self) -> None:
        if type(self.contract) is not OptionContract:
            raise DomainValidationError("leg requires an exact OptionContract")
        _require_exact_enum(self.side, Side, "side")
        _require_exact_enum(self.effect, PositionEffect, "effect")
        _positive_integer(self.ratio, "ratio")

    @property
    def opening_side(self) -> Side:
        if self.effect is PositionEffect.OPEN:
            return self.side
        return Side.SELL if self.side is Side.BUY else Side.BUY


@dataclass(frozen=True, slots=True)
class OptionStructure:
    kind: StructureKind
    legs: tuple[OptionLeg, ...]

    def __post_init__(self) -> None:
        _require_exact_enum(self.kind, StructureKind, "structure kind")
        _require_tuple(self.legs, "legs")
        count = {
            StructureKind.LONG_CALL: 1,
            StructureKind.LONG_PUT: 1,
            StructureKind.DEBIT_VERTICAL: 2,
            StructureKind.CREDIT_VERTICAL: 2,
            StructureKind.IRON_CONDOR: 4,
        }[self.kind]
        if len(self.legs) != count or any(type(x) is not OptionLeg for x in self.legs):
            raise DomainValidationError("invalid number or type of structure legs")
        if any(x.ratio != 1 for x in self.legs):
            raise DomainValidationError("only matched 1:1 ratios supported")
        if len({x.contract.contract_id for x in self.legs}) != count:
            raise DomainValidationError("duplicate contract leg")
        first = self.legs[0]
        identity = (
            "underlying",
            "expiration",
            "last_trading_at",
            "settlement_at",
            "exercise_style",
            "settlement_kind",
            "settlement_timing",
            "premium_multiplier",
            "deliverable_units",
            "deliverable_symbol",
            "eligible_sessions",
            "currency",
        )
        for leg in self.legs[1:]:
            if leg.effect is not first.effect or any(
                getattr(leg.contract, name) != getattr(first.contract, name) for name in identity
            ):
                raise DomainValidationError("incompatible structure identity or effect")
        if count == 1:
            kind = OptionKind.CALL if self.kind is StructureKind.LONG_CALL else OptionKind.PUT
            if first.contract.kind is not kind or first.opening_side is not Side.BUY:
                raise DomainValidationError("single leg must be a fully paid long option")
        elif count == 2:
            low, high = sorted(self.legs, key=lambda x: x.contract.strike)
            if low.contract.kind is not high.contract.kind or low.contract.strike == (
                high.contract.strike
            ):
                raise DomainValidationError("vertical requires distinct same-kind strikes")
            debit = self.kind is StructureKind.DEBIT_VERTICAL
            low_long = debit == (low.contract.kind is OptionKind.CALL)
            expected = (Side.BUY, Side.SELL) if low_long else (Side.SELL, Side.BUY)
            if (low.opening_side, high.opening_side) != expected:
                raise DomainValidationError("vertical direction does not match its kind")
        else:
            ordered = sorted(self.legs, key=lambda x: x.contract.strike)
            if len({x.contract.strike for x in ordered}) != 4 or tuple(
                (x.contract.kind, x.opening_side) for x in ordered
            ) != (
                (OptionKind.PUT, Side.BUY),
                (OptionKind.PUT, Side.SELL),
                (OptionKind.CALL, Side.SELL),
                (OptionKind.CALL, Side.BUY),
            ):
                raise DomainValidationError("condor requires ordered protective outer wings")


@dataclass(frozen=True, slots=True)
class OptionsOrderIntent:
    intent_id: str
    account_scope: str
    structure: OptionStructure
    quantity: int
    limit_price: Decimal
    net_effect: Literal["debit", "credit"]
    created_at: datetime
    expires_at: datetime
    strategy_version: str
    config_hash: str
    data_hash: str
    exit_policy_version: str
    order_type: Literal["limit"]
    time_in_force: Literal["day"]

    def __post_init__(self) -> None:
        if type(self.order_type) is not str or self.order_type != "limit":
            raise DomainValidationError("only limit option intents are supported")
        if type(self.time_in_force) is not str or self.time_in_force != "day":
            raise DomainValidationError("only day option intents are supported")
        for name in ("intent_id", "account_scope", "strategy_version", "exit_policy_version"):
            _require_nonempty(getattr(self, name), name)
        for name in ("config_hash", "data_hash"):
            _require_sha256_hex(getattr(self, name), name)
        if type(self.structure) is not OptionStructure:
            raise DomainValidationError("intent needs exact OptionStructure")
        _positive_integer(self.quantity, "quantity")
        require_bounded_decimal(self.limit_price, "limit_price", positive=True)
        require_utc(self.created_at)
        require_utc(self.expires_at)
        if self.created_at >= self.expires_at:
            raise DomainValidationError("intent timestamps are inconsistent")
        debit_open = self.structure.kind in (
            StructureKind.LONG_CALL,
            StructureKind.LONG_PUT,
            StructureKind.DEBIT_VERTICAL,
        )
        opening = self.structure.legs[0].effect is PositionEffect.OPEN
        expected = "debit" if debit_open == opening else "credit"
        if type(self.net_effect) is not str or self.net_effect != expected:
            raise DomainValidationError("net effect conflicts with structure direction")
        for leg in self.structure.legs:
            c = leg.contract
            if quantize_down(self.limit_price, c.tick_size) != self.limit_price:
                raise DomainValidationError("limit_price violates contract tick")
            if c.available_at > self.created_at or self.expires_at > c.last_trading_at:
                raise DomainValidationError("intent outside known contract lifetime")
            if not any(
                s.opens_at <= self.created_at < self.expires_at <= s.closes_at
                for s in c.eligible_sessions
            ):
                raise DomainValidationError("day intent must remain inside one eligible session")
