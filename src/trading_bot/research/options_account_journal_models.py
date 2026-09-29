"""Closed research accounting facts, not broker observations or risk authorizations."""

from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from trading_bot.domain import DataHash
from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.domain.enums import OrderEvent
from trading_bot.domain.options import OptionsOrderIntent
from trading_bot.market_data.options_source_models import check, hashes, identity, instant
from trading_bot.market_data.recording import content_hash


@dataclass(frozen=True, slots=True)
class JournalIntent:
    episode_id: str
    session_id: str
    intent: OptionsOrderIntent

    def __post_init__(self) -> None:
        identity(self.episode_id)
        identity(self.session_id)
        check(type(self.intent) is OptionsOrderIntent)


@dataclass(frozen=True, slots=True)
class JournalOrderUpdate:
    order_id: str
    event: OrderEvent
    fill_units: int = 0
    price: Decimal | None = None
    fee: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        identity(self.order_id)
        check(type(self.event) is OrderEvent)
        check(type(self.fill_units) is int and self.fill_units >= 0)
        require_bounded_decimal(self.fee, "fee", nonnegative=True)
        if self.event in (OrderEvent.FILL, OrderEvent.PARTIAL_FILL):
            check(self.fill_units > 0 and self.price is not None)
            require_bounded_decimal(cast(Decimal, self.price), "fill price", positive=True)
        else:
            check(self.fill_units == 0 and self.price is None and self.fee == 0)


@dataclass(frozen=True, slots=True)
class JournalSettlement:
    event_id: str

    def __post_init__(self) -> None:
        identity(self.event_id)


@dataclass(frozen=True, slots=True)
class JournalComplete:
    episode_id: str

    def __post_init__(self) -> None:
        identity(self.episode_id)


@dataclass(frozen=True, slots=True)
class JournalExternalFlow:
    amount: Decimal

    def __post_init__(self) -> None:
        require_bounded_decimal(self.amount, "external flow")
        check(self.amount != 0)


@dataclass(frozen=True, slots=True)
class JournalIncident:
    reason: str

    def __post_init__(self) -> None:
        identity(self.reason)


@dataclass(frozen=True, slots=True)
class JournalMark:
    episode_id: str
    price: Decimal | None

    def __post_init__(self) -> None:
        identity(self.episode_id)
        if self.price is not None:
            require_bounded_decimal(self.price, "liquidation mark", nonnegative=True)


type AccountFact = (
    JournalIntent
    | JournalOrderUpdate
    | JournalSettlement
    | JournalComplete
    | JournalExternalFlow
    | JournalIncident
    | JournalMark
)


@dataclass(frozen=True, slots=True)
class AccountJournalEntry:
    event_id: str
    available_ns: int
    previous_hash: DataHash
    fact: AccountFact

    def __post_init__(self) -> None:
        identity(self.event_id)
        instant(self.available_ns)
        hashes((self.previous_hash,))
        check(
            type(self.fact)
            in (
                JournalIntent,
                JournalOrderUpdate,
                JournalSettlement,
                JournalComplete,
                JournalExternalFlow,
                JournalIncident,
                JournalMark,
            )
        )

    @property
    def entry_hash(self) -> DataHash:
        return content_hash({"schema": "options-account-journal-entry-v1", "entry": self})
