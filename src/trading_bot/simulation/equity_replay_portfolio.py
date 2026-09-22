"""Single-owner, in-memory synthetic allocations; no broker or risk authority."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from trading_bot.domain import (
    AssetClass,
    BrokerOrder,
    BrokerOrderId,
    DataHash,
    InstrumentId,
    OrderId,
    OrderIntent,
    OrderState,
    PortfolioSnapshot,
    Position,
    Quote,
    Side,
    TimestampSource,
)
from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.configured_results import ConfiguredOrderResult
from trading_bot.simulation.equity_replay_codec import ReplayIdentity, replay_identity
from trading_bot.simulation.equity_replay_models import (
    SOURCE_KIND,
    EquityStrategyReplayRequest,
    ReplayOrderOutcome,
    ReplayValidationError,
    checked,
    deny,
    label,
    utc,
)
from trading_bot.simulation.equity_replay_portfolio_checks import intent_slots, validate_result
from trading_bot.simulation.events import EventCursor
from trading_bot.simulation.lifecycle import replay_order_lifecycle
from trading_bot.simulation.lifecycle_models import LifecycleRequest, LifecycleResult

ZERO = Decimal(0)


def _hash(kind: str, value: object) -> DataHash:
    return content_hash({"domain": SOURCE_KIND, "kind": kind, "value": value})


@dataclass(frozen=True, slots=True)
class ReplayOrderRecord:
    intent: OrderIntent
    initial: LifecycleRequest
    opportunity_times: tuple[datetime, ...]
    lifecycle: LifecycleResult
    result: ConfiguredOrderResult | None = None


class ReplayPortfolio:
    """Reserve transfers allocation; only lifecycle replay debits cash or changes shares.

    Funding acceptance is not a risk approval. Failed structural/accounting operations latch
    the book invalid; the last published monetary state remains inspectable for diagnostics.
    """

    def __init__(self, request: EquityStrategyReplayRequest) -> None:
        with checked():
            if type(request) is not EquityStrategyReplayRequest:
                deny()
            self._request = replace(request)
            self._identity = replay_identity(self._request)
            self._run_key = self._identity.run_key
            self._cash = self._request.initial_cash
            self._orders: dict[str, ReplayOrderRecord] = {}
            self._intents: dict[str, tuple[OrderIntent, int, ReplayOrderOutcome]] = {}
            self._positions: dict[InstrumentId, Position] = {}
            self._flows: dict[InstrumentId, Decimal] = {}
            self._realized = ZERO
            self._through = self._request.starts_at
            self._invalid = False

    @contextmanager
    def _operation(self) -> Iterator[None]:
        try:
            with checked():
                if self._invalid:
                    deny("replay_portfolio_invalid")
                yield
        except ReplayValidationError:
            self._invalid = True
            raise

    @property
    def request_identity(self) -> ReplayIdentity:
        return self._identity

    @property
    def valid(self) -> bool:
        return not self._invalid

    @property
    def orders(self) -> tuple[ReplayOrderRecord, ...]:
        return tuple(self._orders.values())

    @property
    def outcomes(self) -> tuple[ReplayOrderOutcome, ...]:
        return tuple(item[2] for item in self._intents.values())

    @property
    def orders_terminal(self) -> bool:
        return all(o.lifecycle.order_terminal for o in self.orders)

    @property
    def positions_flat(self) -> bool:
        return all(p.quantity == 0 for p in self._positions.values())

    @property
    def allocatable_cash(self) -> Decimal:
        return self._cash

    @property
    def reserved_cash(self) -> Decimal:
        with checked():
            return sum(
                (o.lifecycle.snapshot.cash for o in self.orders if not o.lifecycle.order_terminal),
                ZERO,
            )

    @property
    def cash(self) -> Decimal:
        with checked():
            return self._cash + self.reserved_cash

    @property
    def fees(self) -> Decimal:
        with checked():
            return sum((o.lifecycle.snapshot.fees for o in self.orders), ZERO)

    @property
    def reserved_shares(self) -> tuple[tuple[InstrumentId, Decimal], ...]:
        return tuple(
            sorted(
                (o.intent.instrument_id, o.lifecycle.snapshot.remaining_quantity)
                for o in self.orders
                if o.intent.side is Side.SELL and not o.lifecycle.order_terminal
            )
        )

    def initial_order(self, order_id: str) -> LifecycleRequest:
        with self._operation():
            label(order_id)
            if order_id not in self._orders:
                deny("replay_order_unknown")
            return self._orders[order_id].initial

    def reserve(self, intent: OrderIntent, fee_opportunities: int) -> ReplayOrderOutcome:
        with self._operation():
            _, slots = intent_slots(self._request, intent, fee_opportunities)
            previous = self._intents.get(intent.id)
            if previous is not None:
                if previous[:2] != (intent, fee_opportunities):
                    deny("replay_duplicate_conflict")
                return previous[2]
            if intent.created_at < self._through:
                deny("replay_ordering_invalid")
            position = self._positions.get(intent.instrument_id)
            reason: str | None = None
            if any(
                o.intent.instrument_id == intent.instrument_id and not o.lifecycle.order_terminal
                for o in self.orders
            ):
                reason = "replay_instrument_busy"
            elif intent.side is Side.BUY and position is not None and position.quantity > 0:
                reason = "replay_position_already_open"
            elif intent.side is Side.SELL and (
                position is None or position.quantity < intent.quantity
            ):
                reason = "replay_insufficient_shares"
            if intent.limit_price is None:
                deny()
            allocation = (
                intent.quantity * intent.limit_price
                + self._request.loaded.config.costs.equity_commission_usd * len(slots)
                if intent.side is Side.BUY
                else ZERO
            )
            require_bounded_decimal(allocation, "allocation", nonnegative=True)
            if reason is None and allocation > self._cash:
                reason = "replay_insufficient_cash"
            if reason is not None:
                outcome = ReplayOrderOutcome(intent.id, False, (reason,), None)
                self._intents[intent.id] = (intent, fee_opportunities, outcome)
                self._through = intent.created_at
                return outcome
            identifier = "replay:" + _hash("order", {"run": self._run_key, "intent": intent})
            if position is None:
                position = Position(
                    self._request.account_id,
                    intent.instrument_id,
                    AssetClass.EQUITY,
                    ZERO,
                    None,
                    ZERO,
                    intent.created_at,
                    _hash("flat", intent.instrument_id),
                )
            order = BrokerOrder(
                OrderId(identifier),
                BrokerOrderId(identifier),
                intent.account_id,
                intent.id,
                None,
                intent.instrument_id,
                intent.side,
                intent.purpose,
                intent.order_type,
                intent.time_in_force,
                intent.quantity,
                ZERO,
                intent.limit_price,
                None,
                OrderState.SUBMISSION_PENDING,
                intent.created_at,
                intent.created_at,
                _hash("order_input", intent),
            )
            initial = LifecycleRequest(
                order, position, allocation, EventCursor(0, intent.created_at), ()
            )
            record = ReplayOrderRecord(intent, initial, slots, replay_order_lifecycle(initial))
            orders = {**self._orders, identifier: record}
            unallocated = self._cash - allocation
            self._conservation(unallocated, orders)
            outcome = ReplayOrderOutcome(intent.id, True, ("replay_funding_reserved",), identifier)
            self._orders, self._cash = orders, unallocated
            self._intents[intent.id] = (intent, fee_opportunities, outcome)
            self._through = intent.created_at
            return outcome

    def _conservation(self, unallocated: Decimal, orders: dict[str, ReplayOrderRecord]) -> None:
        allocated = sum(
            (o.lifecycle.snapshot.cash for o in orders.values() if not o.lifecycle.order_terminal),
            ZERO,
        )
        traced = self._request.initial_cash + sum(
            (o.lifecycle.snapshot.cash - o.initial.cash for o in orders.values()), ZERO
        )
        for value in (unallocated, allocated, traced, unallocated + allocated):
            require_bounded_decimal(value, "cash", nonnegative=True)
        if unallocated + allocated != traced:
            deny("replay_cash_conservation_invalid")

    def apply(self, order_id: str, configured_result: ConfiguredOrderResult) -> None:
        with self._operation():
            label(order_id)
            if order_id not in self._orders:
                deny("replay_order_unknown")
            record = self._orders[order_id]
            if type(configured_result) is not ConfiguredOrderResult:
                deny()
            if configured_result == record.result:
                return
            instrument = next(
                i for i in self._request.instruments if i.id == record.intent.instrument_id
            )
            validate_result(
                self._request,
                record.initial,
                instrument,
                record.opportunity_times,
                configured_result,
                record.result,
                self._through,
            )
            candidate = replace(
                record, lifecycle=configured_result.lifecycle, result=configured_result
            )
            orders = {**self._orders, order_id: candidate}
            unallocated = self._cash
            positions, flows = dict(self._positions), dict(self._flows)
            realized = self._realized
            if not record.lifecycle.order_terminal:
                if candidate.lifecycle.order_terminal:
                    unallocated += candidate.lifecycle.snapshot.cash
                symbol = record.intent.instrument_id
                positions[symbol] = candidate.lifecycle.snapshot.position
                flows[symbol] = flows.get(symbol, ZERO) + (
                    candidate.lifecycle.snapshot.cash - record.lifecycle.snapshot.cash
                )
                if candidate.lifecycle.order_terminal and positions[symbol].quantity == 0:
                    # Recognize cash-flow results only after the entire synthetic round trip.
                    # Partial exits stay in the open-flow mark, not broker/tax-lot realized PnL.
                    realized += flows.pop(symbol)
            self._conservation(unallocated, orders)
            require_bounded_decimal(realized, "realized")
            through = max(
                (d.occurred_at for d in configured_result.decisions), default=self._through
            )
            self._orders, self._cash = orders, unallocated
            self._positions, self._flows, self._realized = positions, flows, realized
            self._through = max(self._through, through)

    def snapshot(self, as_of: datetime, quotes: tuple[Quote, ...]) -> PortfolioSnapshot:
        with self._operation():
            utc(as_of)
            if not self._through <= as_of <= self._request.end_at or type(quotes) is not tuple:
                deny("replay_ordering_invalid")
            visible: dict[InstrumentId, Quote] = {}
            for quote in quotes:
                if type(quote) is not Quote:
                    deny()
                quote.__post_init__()
                if (
                    quote.instrument_id in visible
                    or not quote.freshness_verified
                    or quote.source != "synthetic-configured-order-v1"
                    or quote.timestamp_source is not TimestampSource.SIMULATED
                    or quote.observed_at > as_of
                    or not any(e.quote == quote for e in self._request.markets)
                ):
                    deny("replay_mark_invalid")
                age = as_of - quote.observed_at
                seconds = (
                    Decimal(age.days * 86400 + age.seconds) + Decimal(age.microseconds) / 1000000
                )
                if seconds > self._request.loaded.config.freshness.max_executable_quote_age_seconds:
                    deny("replay_mark_stale")
                visible[quote.instrument_id] = quote
            positions = []
            for symbol, position in sorted(self._positions.items()):
                if position.quantity == 0:
                    continue
                if symbol not in visible:
                    deny("replay_mark_missing")
                quote = visible[symbol]
                mark = position.quantity * quote.bid
                require_bounded_decimal(mark, "mark", nonnegative=True)
                positions.append(
                    replace(
                        position,
                        market_value=mark,
                        observed_at=as_of,
                        data_hash=_hash("mark", (position, quote, as_of)),
                    )
                )
            exposure = sum((p.market_value for p in positions), ZERO)
            equity = self.cash + exposure
            unrealized = sum(self._flows.values(), ZERO) + exposure
            if equity - self._request.initial_cash != self._realized + unrealized:
                deny("replay_cash_conservation_invalid")
            require_bounded_decimal(equity, "equity", nonnegative=True)
            digest = _hash(
                "portfolio",
                (
                    self._run_key,
                    as_of,
                    tuple(positions),
                    self.cash,
                    self._cash,
                    # Configured result/input hashes bind future deliveries. A decision's
                    # current portfolio identity must bind only the applied lifecycle prefix.
                    tuple(
                        (o.intent, o.initial, o.opportunity_times, o.lifecycle) for o in self.orders
                    ),
                    self._realized,
                    unrealized,
                ),
            )
            return PortfolioSnapshot(
                self._request.account_id,
                tuple(positions),
                self.cash,
                equity,
                exposure,
                exposure,
                ZERO,
                self._realized,
                unrealized,
                as_of,
                digest,
            )
