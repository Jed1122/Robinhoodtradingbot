"""Strict fixture-only configured simulation inputs; no external capabilities."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, DecimalException, localcontext
from enum import StrEnum
from typing import Literal, NoReturn

from trading_bot.clock import require_utc
from trading_bot.config.models import CostSettings, SimulationSettings
from trading_bot.domain import AssetClass, Instrument, MarketClock, Quote, TimeInForce
from trading_bot.domain.decimal_utils import (
    _require_nonempty,
    quantize_down,
    require_bounded_decimal,
)
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle_accounting import _context
from trading_bot.simulation.lifecycle_models import (
    LifecycleErrorReason,
    LifecycleRequest,
    LifecycleValidationError,
)

SOURCE_KIND: Literal["synthetic-configured-order-v1"] = "synthetic-configured-order-v1"
GENERATED_PREFIX = "sim:"


class ConfiguredErrorReason(StrEnum):
    INPUT = "configured_input_invalid"
    IDENTITY = "configured_identity_mismatch"
    ORDERING = "configured_ordering_invalid"
    DUPLICATE = "configured_duplicate_conflict"
    UNSUPPORTED = "configured_input_unsupported"
    ARITHMETIC = "configured_arithmetic_invalid"
    HASH = "configured_hash_invalid"
    LIFECYCLE = "configured_lifecycle_denied"


class ConfiguredValidationError(ValueError):
    def __init__(
        self, reason: ConfiguredErrorReason, lifecycle_reason: LifecycleErrorReason | None = None
    ) -> None:
        self.reason = (
            reason if type(reason) is ConfiguredErrorReason else ConfiguredErrorReason.INPUT
        )
        self.lifecycle_reason = (
            lifecycle_reason if type(lifecycle_reason) is LifecycleErrorReason else None
        )
        super().__init__(self.reason.value)


def deny(reason: ConfiguredErrorReason = ConfiguredErrorReason.INPUT) -> NoReturn:
    raise ConfiguredValidationError(reason) from None


@contextmanager
def checked(reason: ConfiguredErrorReason = ConfiguredErrorReason.INPUT) -> Iterator[None]:
    try:
        with localcontext(_context(exact=True)):
            yield
    except ConfiguredValidationError:
        raise
    except LifecycleValidationError as exc:
        raise ConfiguredValidationError(ConfiguredErrorReason.LIFECYCLE, exc.reason) from None
    except (ValueError, TypeError, AttributeError, OverflowError, DecimalException):
        deny(reason)


def utc(value: datetime) -> None:
    if type(value) is not datetime:
        deny()
    require_utc(value)


def _event_header(event_id: str, cursor: EventCursor) -> None:
    _require_nonempty(event_id, "event_id")
    if event_id.startswith(GENERATED_PREFIX) or type(cursor) is not EventCursor:
        deny()
    cursor.__post_init__()


@dataclass(frozen=True, slots=True)
class SyntheticBarWindow:
    starts_at: datetime
    ends_at: datetime

    def __post_init__(self) -> None:
        with checked():
            utc(self.starts_at)
            utc(self.ends_at)
            if self.starts_at >= self.ends_at:
                deny(ConfiguredErrorReason.ORDERING)


@dataclass(frozen=True, slots=True)
class SyntheticMarketEvent:
    event_id: str
    cursor: EventCursor
    window: SyntheticBarWindow
    quote: Quote
    clock: MarketClock
    available_quantity: Decimal

    def __post_init__(self) -> None:
        with checked():
            _event_header(self.event_id, self.cursor)
            if (
                type(self.window) is not SyntheticBarWindow
                or type(self.quote) is not Quote
                or type(self.clock) is not MarketClock
            ):
                deny()
            self.window.__post_init__()
            self.quote.__post_init__()
            self.clock.__post_init__()
            require_bounded_decimal(self.available_quantity, "liquidity", nonnegative=True)
            for price in (self.quote.bid, self.quote.ask, self.quote.last):
                if price is not None:
                    require_bounded_decimal(price, "price", positive=True)
            timestamp = self.cursor.occurred_at
            utc(timestamp)
            if (
                not self.window.starts_at <= timestamp < self.window.ends_at
                or self.quote.observed_at != timestamp
                or self.clock.observed_at != timestamp
            ):
                deny(ConfiguredErrorReason.ORDERING)
            if self.quote.source != SOURCE_KIND:
                deny(ConfiguredErrorReason.UNSUPPORTED)


@dataclass(frozen=True, slots=True)
class SyntheticCancelRequest:
    event_id: str
    cursor: EventCursor

    def __post_init__(self) -> None:
        with checked():
            _event_header(self.event_id, self.cursor)
            utc(self.cursor.occurred_at)


type SyntheticInputEvent = SyntheticMarketEvent | SyntheticCancelRequest


@dataclass(frozen=True, slots=True)
class ConfiguredOrderRequest:
    initial: LifecycleRequest
    simulation: SimulationSettings
    costs: CostSettings
    seed: int
    submission_window: SyntheticBarWindow
    events: tuple[SyntheticInputEvent, ...]
    end_at: datetime
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        with checked():
            if (
                type(self.initial) is not LifecycleRequest
                or type(self.simulation) is not SimulationSettings
                or type(self.costs) is not CostSettings
                or type(self.submission_window) is not SyntheticBarWindow
                or type(self.seed) is not int
                or self.seed < 0
                or type(self.events) is not tuple
            ):
                deny()
            self.initial.__post_init__()
            self.submission_window.__post_init__()
            if self.initial.events:
                deny(ConfiguredErrorReason.UNSUPPORTED)
            for settings in (self.simulation, self.costs):
                for value in settings.model_dump().values():
                    if type(value) is Decimal:
                        require_bounded_decimal(value, "setting", nonnegative=True)
            simulation = SimulationSettings.model_validate(self.simulation.model_dump())
            costs = CostSettings.model_validate(self.costs.model_dump())
            if simulation.assumptions_validated or simulation.evidence_promotable:
                deny(ConfiguredErrorReason.UNSUPPORTED)
            object.__setattr__(self, "simulation", simulation)
            object.__setattr__(self, "costs", costs)
            submitted_at = self.initial.submitted.occurred_at
            utc(submitted_at)
            utc(self.end_at)
            if (
                not self.submission_window.starts_at
                <= submitted_at
                < self.submission_window.ends_at
                or self.end_at < submitted_at
            ):
                deny(ConfiguredErrorReason.ORDERING)
            ack_at = submitted_at + timedelta(milliseconds=simulation.latency_milliseconds)
            if self.initial.order.time_in_force is TimeInForce.GOOD_FOR_DAY:
                if self.expires_at is None:
                    deny()
                utc(self.expires_at)
                if self.expires_at <= ack_at:
                    deny(ConfiguredErrorReason.ORDERING)
            elif self.expires_at is not None:
                deny(ConfiguredErrorReason.UNSUPPORTED)
            # Local import keeps record and whole-stream responsibilities separate.
            from trading_bot.simulation.configured_validation import validate_stream

            validate_stream(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class InstrumentConfiguredOrderRequest(ConfiguredOrderRequest):
    """Explicit equity-only increment semantics; never changes the legacy request shape."""

    instrument: Instrument
    execution_version: Literal["synthetic-equity-increments-v1"] = field(
        default="synthetic-equity-increments-v1",
        init=False,
    )

    def __post_init__(self) -> None:
        ConfiguredOrderRequest.__post_init__(self)
        with checked():
            if type(self.instrument) is not Instrument:
                deny()
            self.instrument.__post_init__()
            order, position = self.initial.order, self.initial.position
            if (
                self.instrument.id != order.instrument_id
                or self.instrument.asset_class is not AssetClass.EQUITY
                or position.asset_class is not AssetClass.EQUITY
                or order.time_in_force is not TimeInForce.GOOD_FOR_DAY
                or self.instrument.observed_at > self.initial.submitted.occurred_at
            ):
                deny(ConfiguredErrorReason.IDENTITY)
            for amount in (
                self.instrument.price_increment,
                self.instrument.quantity_increment,
                self.instrument.minimum_quantity,
                self.instrument.minimum_notional,
                self.instrument.maximum_quantity,
            ):
                if amount is not None:
                    require_bounded_decimal(amount, "instrument_value", positive=True)
            quantity, price = order.requested_quantity, order.limit_price
            if (
                price is None
                or quantize_down(price, self.instrument.price_increment) != price
                or quantize_down(quantity, self.instrument.quantity_increment) != quantity
                or quantize_down(position.quantity, self.instrument.quantity_increment)
                != position.quantity
                or quantity < self.instrument.minimum_quantity
                or quantity * price < self.instrument.minimum_notional
                or (
                    self.instrument.maximum_quantity is not None
                    and quantity > self.instrument.maximum_quantity
                )
            ):
                deny(ConfiguredErrorReason.UNSUPPORTED)
