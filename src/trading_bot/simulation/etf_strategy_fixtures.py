"""Explicitly fictional acknowledgements/settlements for operator demonstrations."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_bot.domain import (
    AssetClass,
    Bar,
    BarInterval,
    InstrumentId,
    MarketClock,
    OrderEvent,
    Quote,
    TimestampSource,
)
from trading_bot.market_data.etf_source import (
    EtfObservedBar,
    EtfObservedQuote,
    EtfSessionEvent,
    _ceil_time,
    _ns,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_study import EtfStudy
from trading_bot.simulation.etf_account import EtfAccountEvent
from trading_bot.simulation.etf_fixture_execution import EtfFixtureAccountObservation
from trading_bot.simulation.etf_fixtures import synthetic_etf_quote_request
from trading_bot.simulation.etf_history import EtfFixturePrefixRequest
from trading_bot.simulation.etf_strategy import (
    EtfFixtureStrategyRequest,
    EtfFixtureStrategyResult,
    run_etf_fixture_strategy,
)

_START = datetime(2016, 1, 1, tzinfo=UTC)
_OPEN = _START + timedelta(days=751, hours=14, minutes=30)
_AT = _ns(_OPEN)
_SPY = InstrumentId("SPY")


def synthetic_etf_strategy_request(
    study: EtfStudy,
    cash: Decimal,
    scenario: str = "completed_stop",
) -> EtfFixtureStrategyRequest:
    if scenario not in ("completed_stop", "open", "partial_cancel"):
        raise ValueError("etf_strategy_fixture_invalid")
    seed = synthetic_etf_quote_request(study, cash)
    instrument = seed.account.events[0].instrument
    if instrument is None:
        raise ValueError("etf_strategy_fixture_invalid")
    instrument = replace(instrument, observed_at=_OPEN)
    costs = replace(
        seed.costs,
        intervals=tuple(
            replace(
                i,
                starts_at=_OPEN - timedelta(days=1),
                ends_at=_OPEN + timedelta(days=400),
                known_at=_OPEN - timedelta(days=2),
            )
            for i in seed.costs.intervals
        ),
    )
    events: list[EtfObservedBar | EtfSessionEvent | EtfObservedQuote] = []
    for i in range(750):
        end = _START + timedelta(days=i, hours=21)
        price = Decimal("100") + Decimal(i) / 100
        digest = content_hash(("etf-strategy-fictional-bar-v1", i, price))
        events.append(
            EtfObservedBar(
                digest,
                i,
                _ns(end),
                _ns(end) + 1,
                _SPY,
                None,
                Bar(
                    _SPY,
                    BarInterval.ONE_DAY,
                    end - timedelta(hours=7),
                    end,
                    price,
                    price + Decimal(".5"),
                    price - Decimal(".5"),
                    price,
                    Decimal("10000"),
                    "synthetic",
                    digest,
                ),
            )
        )
    digest = content_hash("etf-strategy-fictional-session-v1")
    events.append(
        EtfSessionEvent(
            digest,
            750,
            _AT,
            _AT,
            _SPY,
            None,
            MarketClock(
                AssetClass.EQUITY,
                "XNYS",
                _OPEN,
                True,
                False,
                False,
                False,
                _OPEN + timedelta(days=1),
                _OPEN + timedelta(hours=6, minutes=30),
            ),
        )
    )

    def quote(ordinal: int, millis: int, bid: str, ask: str, size: str) -> EtfObservedQuote:
        at = _AT + millis * 1_000_000
        digest = content_hash(("etf-strategy-fictional-quote-v1", ordinal, at, bid, ask, size))
        return EtfObservedQuote(
            digest,
            ordinal,
            at,
            at,
            _SPY,
            None,
            Quote(
                _SPY,
                _ceil_time(at),
                Decimal(bid),
                Decimal(ask),
                None,
                "synthetic",
                digest,
                False,
                TimestampSource.SIMULATED,
            ),
            Decimal(size),
            Decimal(size),
        )

    events.append(quote(751, 20, "99.99", "100", "1"))
    prefix = EtfFixturePrefixRequest(study, tuple(events), cash)
    request = EtfFixtureStrategyRequest(prefix, instrument, costs, (), Decimal(".1"))
    pending = run_etf_fixture_strategy(request)

    def ack(
        state: EtfFixtureStrategyResult, source: int, millis: int
    ) -> EtfFixtureAccountObservation:
        record = state.account.orders[-1]
        return EtfFixtureAccountObservation(
            source,
            EtfAccountEvent(
                content_hash(("fictional-strategy-ack-v1", source, record.intent.id)),
                (state.account.last_ordinal or 0) + 1,
                _AT + millis * 1_000_000,
                "order_status",
                order_id=record.intent.id,
                order_event=OrderEvent.BROKER_ACCEPTED,
            ),
        )

    accepted = ack(pending, 752, 21)
    entry = quote(753, 40, "99.99", "100", ".04" if scenario == "partial_cancel" else "1")
    request = replace(
        request, prefix=replace(prefix, events=(*prefix.events, entry)), notices=(accepted,)
    )
    if scenario == "open":
        return request
    stop = quote(754, 50, "97.99", "98", "1")
    request = replace(
        request, prefix=replace(request.prefix, events=(*request.prefix.events, stop))
    )
    if scenario == "partial_cancel":
        return request
    closing = run_etf_fixture_strategy(request)
    exit_ack = ack(closing, 755, 51)
    request = replace(
        request,
        prefix=replace(
            request.prefix, events=(*request.prefix.events, quote(756, 70, "97.99", "98", "1"))
        ),
        notices=(*request.notices, exit_ack),
    )
    closed = run_etf_fixture_strategy(request)
    settled = EtfFixtureAccountObservation(
        757,
        EtfAccountEvent(
            content_hash(("fictional-strategy-settlement-v1", closed.account.state_hash)),
            (closed.account.last_ordinal or 0) + 1,
            _AT + 80_000_000,
            "settlement",
            fill_ids=tuple(item[0] for item in closed.account.unsettled),
        ),
    )
    return replace(request, notices=(*request.notices, settled))
