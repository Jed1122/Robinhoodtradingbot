"""Validated immutable experimental-account facts with exact decimal values."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from trading_bot.clock import require_utc

Nonnegative = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
Sleeve = Literal["long_term", "tactical"]


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Lot(Fact):
    id: str = Field(min_length=1, max_length=128)
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,14}$")
    sleeve: Sleeve
    quantity: Positive
    basis: Nonnegative
    acquired_at: datetime
    episode_id: str | None = None

    _utc = field_validator("acquired_at")(require_utc)


class Disposal(Fact):
    lots: tuple[Lot, ...]
    proceeds: Nonnegative
    disposed_basis: Nonnegative
    gain: Decimal = Field(allow_inf_nan=False)
    tax_reserve: Nonnegative | None
    short_term_gain: Decimal
    long_term_gain: Decimal


class Quote(Fact):
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,14}$")
    bid: Positive
    ask: Positive
    as_of: datetime
    tradable: StrictBool = False
    fractional: StrictBool = False
    regular_session: StrictBool = False
    halted: StrictBool = True
    average_dollar_volume: Nonnegative | None = None
    sector: str | None = None
    diversified_etf: StrictBool = False
    earnings_clear: StrictBool = False

    _utc = field_validator("as_of")(require_utc)


class PaperOrder(Fact):
    id: str = Field(min_length=1, max_length=128)
    symbol: str
    side: Literal["buy", "sell"]
    sleeve: Sleeve
    quantity: Positive
    limit_price: Positive | None = None
    risk_stop: Positive | None = None
    filled: Nonnegative = Decimal(0)
    reserved_cash: Nonnegative = Decimal(0)
    status: Literal["open", "partial", "filled", "cancelled", "rejected"] = "open"
    threshold: str | None = None
    reason: str = "experimental"
    episode_id: str | None = None


class Settlement(Fact):
    id: str
    amount: Nonnegative
    due_at: datetime

    _utc = field_validator("due_at")(require_utc)


class FillFact(Fact):
    id: str
    order_id: str
    quantity: Positive
    price: Positive
    fee: Nonnegative
    at: datetime

    _utc = field_validator("at")(require_utc)


class JobRecord(Fact):
    name: str
    status: Literal["completed", "blocked", "failed"]
    updated_at: datetime
    reason: str

    _utc = field_validator("updated_at")(require_utc)


class ReportRecord(Fact):
    name: str
    created_at: datetime
    status: Literal["experimental", "insufficient_evidence"]
    detail: str

    _utc = field_validator("created_at")(require_utc)


class ExitProgress(Fact):
    threshold: str
    symbol: str
    sleeve: Sleeve
    target: Positive
    filled: Nonnegative = Decimal(0)


class AllocationEpisode(Fact):
    id: str
    symbol: str
    sleeve: Sleeve
    original_cash: Positive
    original_quantity: Positive


class Account(Fact):
    starting_capital: Positive = Decimal(1000)
    cash: Nonnegative = Decimal(1000)
    tax_reserve: Nonnegative = Decimal(0)
    realized_gain: Decimal = Decimal(0)
    fees: Nonnegative = Decimal(0)
    lots: tuple[Lot, ...] = ()
    orders: tuple[PaperOrder, ...] = ()
    fills: tuple[FillFact, ...] = ()
    settlements: tuple[Settlement, ...] = ()
    completed_thresholds: tuple[str, ...] = ()
    high_watermark: Positive = Decimal(1000)
    daily_reference: Positive = Decimal(1000)
    weekly_reference: Positive = Decimal(1000)
    paused: StrictBool = True
    kill_switch: StrictBool = False
    jobs: tuple[JobRecord, ...] = ()
    reports: tuple[ReportRecord, ...] = ()
    research_json: str | None = Field(default=None, max_length=500000)
    comparisons_json: str | None = Field(default=None, max_length=500000)
    exit_progress: tuple[ExitProgress, ...] = ()
    marks: tuple[Quote, ...] = ()
    valuation_at: datetime | None = None
    last_equity: Positive | None = None
    daily_reference_date: date | None = None
    weekly_reference_key: str | None = None
    tactical_suspended: StrictBool = False
    weekly_review_required: StrictBool = False
    episodes: tuple[AllocationEpisode, ...] = ()

    @field_validator("valuation_at")
    @classmethod
    def valuation_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def ownership_and_reservations(self) -> Self:
        for rows in (self.lots, self.orders, self.fills, self.settlements, self.episodes):
            if len({row.id for row in rows}) != len(rows):
                raise ValueError("duplicate experimental account identity")
        if len({row.threshold for row in self.exit_progress}) != len(self.exit_progress):
            raise ValueError("duplicate exit progress")
        if self.reserved_cash > self.cash:
            raise ValueError("cash reservations exceed cash")
        for order in self.orders:
            if (
                order.filled > order.quantity
                or (order.status == "filled" and order.filled != order.quantity)
                or (order.status == "open" and order.filled != 0)
                or (order.status == "partial" and not 0 < order.filled < order.quantity)
                or (order.status in {"filled", "cancelled", "rejected"} and order.reserved_cash)
            ):
                raise ValueError("invalid order lifecycle")
        if any(row.filled > row.target for row in self.exit_progress):
            raise ValueError("invalid exit progress")
        return self

    @property
    def reserved_cash(self) -> Decimal:
        return sum((order.reserved_cash for order in self.orders), Decimal(0))

    @property
    def buying_power(self) -> Decimal:
        return max(Decimal(0), self.cash - self.reserved_cash - self.tax_reserve)
