"""Fabricated shortlist inputs; never historical data or source authentication."""

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from trading_bot.config import LoadedConfig, load_config
from trading_bot.domain import Bar, BarInterval, DataHash, InstrumentId
from trading_bot.domain.options import (
    ExerciseStyle,
    OptionContract,
    OptionKind,
    OptionSession,
    SettlementKind,
    SettlementTiming,
)
from trading_bot.market_data.options_records import ChainSnapshot, OptionsDataRecord
from trading_bot.market_data.recording import content_hash

SOURCE = "synthetic-shortlist"
D = Decimal


def load_shortlist() -> LoadedConfig:
    root = Path("configs")
    return load_config(
        root / "base.yaml",
        root / "options/shortlist/simulation.yaml",
        root / "safety-envelope.yaml",
        {},
    )


def fixture_session(day: date, close: time = time(16)) -> OptionSession:
    zone = ZoneInfo("America/New_York")
    return OptionSession(
        f"synthetic-regular-{day.isoformat()}",
        datetime.combine(day, time(9, 30), zone).astimezone(UTC),
        datetime.combine(day, close, zone).astimezone(UTC),
        day,
        "America/New_York",
    )


def make_case(*, dtes=(30,), current=None, prior=None):
    from trading_bot.research.options_shortlist_models import (
        ShortlistCalendar,
        ShortlistCalendarDay,
        ShortlistClose,
        ShortlistEvidence,
        ShortlistSessionInput,
    )

    current = current or fixture_session(date(2024, 1, 2))
    prior = prior or fixture_session(date(2023, 12, 29))
    known = prior.opens_at - timedelta(days=1)
    digest = content_hash("fabricated-shortlist-input")
    evidence = ShortlistEvidence(
        SOURCE,
        "synthetic",
        digest,
        known,
        prior.opens_at,
        current.closes_at,
        "synthetic-shortlist-v1",
    )
    days = tuple(
        ShortlistCalendarDay(
            day,
            prior
            if day == prior.trading_date
            else (current if day == current.trading_date else None),
        )
        for offset in range((current.trading_date - prior.trading_date).days + 1)
        for day in (prior.trading_date + timedelta(days=offset),)
    )
    bar = Bar(
        InstrumentId("SPY"),
        BarInterval.ONE_DAY,
        prior.opens_at,
        prior.closes_at,
        D("100"),
        D("101"),
        D("99"),
        D("100"),
        D("1000"),
        SOURCE,
        digest,
    )
    contracts = []
    for dte in dtes:
        expiry = current.trading_date + timedelta(days=dte)
        last = fixture_session(expiry).closes_at
        for kind in (OptionKind.CALL, OptionKind.PUT):
            for strike in (D("99"), D("101")):
                ident = f"synthetic-{expiry}-{kind.value}-{strike}"
                symbol = f"SPY   {expiry:%y%m%d}{kind.value[0].upper()}{int(strike * 1000):08d}"
                contracts.append(
                    OptionContract(
                        ident,
                        symbol,
                        "SPY",
                        kind,
                        strike,
                        expiry,
                        last,
                        last + timedelta(days=1),
                        ExerciseStyle.AMERICAN,
                        SettlementKind.SHARES,
                        SettlementTiming.PM,
                        D("100"),
                        D("100"),
                        "SPY",
                        False,
                        D("0.01"),
                        (current,),
                        known,
                        str(content_hash(ident)),
                        "USD",
                    )
                )
    records = tuple(
        OptionsDataRecord(SOURCE, "synthetic", digest, known, known, item) for item in contracts
    )
    chain = OptionsDataRecord(
        SOURCE,
        "synthetic",
        digest,
        known,
        known,
        ChainSnapshot("SPY", tuple(c.contract_id for c in contracts)),
    )
    return ShortlistSessionInput(
        current,
        prior,
        ShortlistCalendar(evidence, days),
        (
            ShortlistClose(
                bar,
                prior.closes_at + timedelta(minutes=1),
                "unadjusted",
                "source_last_trade",
                evidence,
            ),
        ),
        evidence,
        (),
        SOURCE,
        evidence,
        (*records, chain),
        "synthetic",
    )


def imported_case():
    case = make_case()

    def imported(evidence):
        return replace(evidence, source_kind="imported", semantics="unverified-import-v1")

    return replace(
        case,
        source_kind="imported",
        calendar=replace(case.calendar, evidence=imported(case.calendar.evidence)),
        closes=tuple(replace(c, evidence=imported(c.evidence)) for c in case.closes),
        action_evidence=imported(case.action_evidence),
        chain_evidence=imported(case.chain_evidence),
        records=tuple(replace(r, source_kind="imported") for r in case.records),
    )


def selected_result():
    from trading_bot.research.options_shortlist_models import (
        OptionsShortlistCandidate,
        OptionsShortlistResult,
    )

    case = make_case()
    candidates = tuple(
        OptionsShortlistCandidate(
            case.current_session.session_id,
            case.current_session.opens_at,
            kind,
            f"synthetic-{kind}",
            f"SPY   240201{kind.value[0].upper()}00099000",
            date(2024, 2, 1),
            D("99"),
            DataHash("a" * 64),
            (("prior_close", DataHash("a" * 64)),),
        )
        for kind in (OptionKind.CALL, OptionKind.PUT)
    )
    return OptionsShortlistResult(
        "spy-prior-close-atm-30d-v1",
        case.current_session.session_id,
        case.current_session.opens_at,
        "synthetic",
        DataHash("b" * 64),
        DataHash("c" * 64),
        DataHash("d" * 64),
        DataHash("e" * 64),
        "selected",
        (),
        candidates,
        11,
    )
