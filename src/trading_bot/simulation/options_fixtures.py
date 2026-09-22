"""Explicitly fabricated prices/calendars/fees, never historical market evidence."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from trading_bot.config import LoadedConfig
from trading_bot.domain import Bar, BarInterval, DataHash, InstrumentId
from trading_bot.domain.options import (
    ExerciseStyle,
    OptionContract,
    OptionKind,
    OptionQuote,
    OptionSession,
    SettlementKind,
    SettlementTiming,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.risk.options_economics import TrialLossState
from trading_bot.simulation.options_replay_models import (
    SOURCE,
    OptionsReplayEvent,
    OptionsReplayRequest,
)
from trading_bot.strategies.protocol import HistoricalSlice

SCENARIOS = (
    "completed",
    "loss",
    "open",
    "unfilled",
    "unknown",
    "unsettled",
    "cancel_race",
    "canceled",
    "rejected",
)


def synthetic_options_request(
    loaded: LoadedConfig,
    capital: Decimal,
    scenario: str = "completed",
    *,
    option_kind: OptionKind = OptionKind.CALL,
) -> OptionsReplayRequest:
    if scenario not in SCENARIOS:
        raise ValueError("unsupported synthetic options scenario")
    if type(option_kind) is not OptionKind:
        raise ValueError("exact option kind required")
    is_call = option_kind is OptionKind.CALL
    at = datetime(2026, 9, 18, 15, tzinfo=UTC)
    contract = OptionContract(
        f"synthetic-{option_kind.value}-100",
        "SYN261016C00100000" if is_call else "SYN261016P00100000",
        "SYN",
        option_kind,
        Decimal(100),
        date(2026, 10, 16),
        datetime(2026, 10, 16, 20, tzinfo=UTC),
        datetime(2026, 10, 19, 20, tzinfo=UTC),
        ExerciseStyle.AMERICAN,
        SettlementKind.SHARES,
        SettlementTiming.PM,
        Decimal(100),
        Decimal(100),
        "SYN",
        False,
        Decimal("0.01"),
        (
            OptionSession(
                "synthetic-session-2026-09-18",
                at,
                at + timedelta(hours=5),
                date(2026, 9, 18),
                "America/New_York",
            ),
        ),
        at - timedelta(days=1),
        content_hash({"synthetic-contract": 1} if is_call else {"synthetic-put-contract": 1}),
        "USD",
    )
    bars = []
    count = loaded.config.research.minimum_history_bars
    for index in range(count):
        end = at - timedelta(days=count - index)
        price = (
            Decimal(90) + Decimal(index) / Decimal(100)
            if is_call
            else Decimal(110) - Decimal(index) / Decimal(100)
        )
        bars.append(
            Bar(
                InstrumentId("SYN"),
                BarInterval.ONE_DAY,
                end - timedelta(days=1),
                end,
                price,
                price + 1,
                price - 1,
                price,
                Decimal(1000),
                SOURCE,
                content_hash({"synthetic-bar": index} if is_call else {"synthetic-put-bar": index}),
            )
        )
    history = HistoricalSlice(InstrumentId("SYN"), tuple(bars), None, content_hash(tuple(bars)))

    def quote(second: int, bid: str, ask: str) -> OptionQuote:
        when = at + timedelta(seconds=second)
        return OptionQuote(
            contract.contract_id,
            Decimal(bid),
            Decimal(ask),
            1,
            1,
            when,
            when,
            when,
            SOURCE,
            DataHash(content_hash((second, bid, ask))),
            (),
            "SYN",
        )

    def event(second: int, action: str, bid: str = "0.09", ask: str = "0.10") -> OptionsReplayEvent:
        return OptionsReplayEvent(
            f"synthetic-{second}-{action}",
            at + timedelta(seconds=second),
            action,
            quote(second, bid, ask) if action == "market" else None,
        )

    events = [event(1, "accept_entry"), event(2, "market")]
    if scenario == "unknown":
        events = [event(1, "unknown_entry")]
    elif scenario == "rejected":
        events = [event(1, "reject_entry")]
    elif scenario == "unfilled":
        events = [event(1, "accept_entry"), event(2, "market", "0.10", "0.11")]
    elif scenario in ("canceled", "cancel_race"):
        events = [
            event(1, "accept_entry"),
            event(2, "cancel_entry"),
            event(3, "market" if scenario == "cancel_race" else "confirm_cancel"),
        ]
    elif scenario != "open":
        bid, ask = ("0.05", "0.06") if scenario == "loss" else ("0.15", "0.16")
        events.extend((event(3, "request_close"), event(4, "market", bid, ask)))
        if scenario != "unsettled":
            events.append(event(5, "settle"))
    return OptionsReplayRequest(
        loaded,
        capital,
        at,
        history,
        contract,
        quote(0, "0.09", "0.10"),
        Decimal("0.50"),
        Decimal("0.50"),
        Decimal("0.05") if scenario == "loss" else Decimal("0.15"),
        tuple(events),
        TrialLossState(()),
    )
