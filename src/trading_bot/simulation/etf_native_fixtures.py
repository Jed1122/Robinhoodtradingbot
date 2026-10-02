"""Pure fictional market-input assembly; never evaluates a strategy or account.

All six cash/scenario combinations share one source, instrument and full-window
cost identity. The operator command preregisters them before running the engine.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

from trading_bot.domain import AssetClass, Bar, BarInterval, Instrument, InstrumentId, MarketClock
from trading_bot.market_data.etf_source import _ns
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_costs import EtfCostEvidence, EtfCostInterval, _fee_context
from trading_bot.research.etf_study import EtfStudy
from trading_bot.simulation.etf_native_models import (
    EtfHistoryRequest,
    EtfReplayDataset,
    EtfReplayEvent,
)


def synthetic_etf_history_request(
    study: EtfStudy, cash: Decimal, scenario: str = "base"
) -> EtfHistoryRequest:
    start = datetime(2016, 1, 1, tzinfo=UTC)
    opening = start + timedelta(days=751, hours=14, minutes=30)
    instrument = Instrument(
        InstrumentId("SPY"),
        "SPY",
        AssetClass.EQUITY,
        "synthetic",
        True,
        True,
        Decimal("0.01"),
        Decimal("0.001"),
        Decimal("0.001"),
        Decimal("1"),
        None,
        "US-equity",
        opening,
        content_hash("etf-fictional-native-instrument-v1"),
    )
    costs = EtfCostEvidence(
        tuple(
            EtfCostInterval(
                role,
                unit,
                Decimal(value),
                "USD",
                study.requested_start,
                study.requested_end,
                study.requested_start - timedelta(days=1),
                content_hash(("etf-fictional-native-cost-v1", role)),
            )
            for role, unit, value in (
                ("commission_per_share", "USD/share", "0.02"),
                ("minimum_commission", "USD/order", "0.03"),
                ("regulatory_per_notional", "USD/USD", "0.0001"),
                ("extra_slippage", "bps", "0"),
                ("latency", "seconds", "0.01"),
                ("cash_rate", "whole_percent/year", "0"),
                ("operating_cost", "USD/day", "0.25"),
            )
        ),
        "synthetic",
        (),
    )
    events: list[EtfReplayEvent] = []
    with localcontext(_fee_context()):
        for index in range(750):
            ended = start + timedelta(days=index, hours=21)
            price = Decimal("100") + Decimal(index) / 100
            source_hash = content_hash(("etf-fictional-native-bar-v1", index, price))
            events.append(
                EtfReplayEvent(
                    index,
                    _ns(ended),
                    _ns(ended) + 1,
                    source_hash,
                    "bar",
                    bar=Bar(
                        InstrumentId("SPY"),
                        BarInterval.ONE_DAY,
                        ended - timedelta(hours=6),
                        ended,
                        price,
                        price + Decimal("0.5"),
                        price - Decimal("0.5"),
                        price,
                        Decimal("1000000"),
                        "synthetic",
                        source_hash,
                    ),
                )
            )

    def session(at: datetime) -> EtfReplayEvent:
        return EtfReplayEvent(
            len(events),
            _ns(at),
            _ns(at),
            content_hash(("etf-fictional-native-session-v1", at)),
            "session",
            clock=MarketClock(
                AssetClass.EQUITY,
                "XNYS",
                at,
                True,
                False,
                False,
                False,
                at + timedelta(days=1),
                at + timedelta(hours=6, minutes=30),
            ),
        )

    events.append(session(opening))
    for millis, bid, ask in (
        (20, "99.99", "100"),
        (40, "99.99", "100"),
        (50, "97.99", "98"),
        (70, "97.99", "98"),
        (90, "97.99", "98"),
    ):
        at = _ns(opening) + millis * 1_000_000
        events.append(
            EtfReplayEvent(
                len(events),
                at,
                at,
                content_hash(("etf-fictional-native-quote-v1", millis, bid, ask)),
                "quote",
                bid=Decimal(bid),
                ask=Decimal(ask),
                bid_size=Decimal("1"),
                ask_size=Decimal("1"),
            )
        )
    events.append(session(opening + timedelta(days=1)))
    events.append(session(opening + timedelta(days=2)))
    return EtfHistoryRequest(
        study,
        EtfReplayDataset(
            tuple(events),
            content_hash("etf-fictional-native-inputs-v1"),
            "synthetic",
            ("synthetic_inputs_only",),
        ),
        costs,
        cash,
        scenario,
        instrument,
    )
