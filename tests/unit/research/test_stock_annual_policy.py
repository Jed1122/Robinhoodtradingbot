"""Fictional original filings and prices; no actual data or investment qualification."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.market_data.stock_events import normalize_filing_index
from trading_bot.market_data.stock_filing_facts import normalize_filing_facts
from trading_bot.research.hybrid_policies import (
    CalendarSession,
    PolicyEvent,
    PolicyInput,
    SessionObservation,
    StrategyProposal,
    UnavailablePolicy,
    UniverseMembership,
    evaluate_policies,
)
from trading_bot.research.hybrid_sources import SourceFact
from trading_bot.research.hybrid_strategies import PriceBar
from trading_bot.research.stock_annual_quality import (
    AnnualQualityPeriods,
    AnnualQualityRequest,
    DefinedAnnualQuality,
    UnavailableAnnualQuality,
    build_annual_quality,
)

BASE = datetime(2025, 1, 1, tzinfo=UTC)
RECEIVED = datetime(2026, 10, 26, tzinfo=UTC)
ENTITY = "0000999999"
CONCEPTS = (
    "NetIncomeLoss",
    "RevenuesNetOfInterestExpense",
    "StockholdersEquity",
    "LongTermDebt",
    "ShortTermBorrowings",
)


def inputs(symbols=("AXP",), *, count=253):
    sessions = tuple(
        CalendarSession(i, BASE + timedelta(days=i, hours=14), BASE + timedelta(days=i, hours=21))
        for i in range(count + 1)
    )
    observations = tuple(
        SessionObservation(
            symbol,
            i,
            PriceBar(sessions[i].closes_at, Decimal(100 + i), Decimal(100 + i)),
            Decimal(1000),
        )
        for symbol in symbols
        for i in range(count)
    )
    return PolicyInput(
        sessions,
        observations,
        tuple(UniverseMembership(s, BASE, BASE, True, f"member-{s}") for s in symbols),
        sessions[count - 1].closes_at,
        True,
    )


def legacy_quality(symbol="AXP"):
    return tuple(
        SourceFact(
            symbol,
            metric,
            Decimal(value),
            BASE,
            BASE,
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000999999.json",
            metric,
        )
        for metric, value in (("roe", ".2"), ("revenue_growth", ".1"), ("debt_to_equity", ".5"))
    )


def annual(*, year=2023, filing_id=None, filed=None, information_at=None, omit=(), changes=None):
    """Seven fully invented native duration/instant rows from one original."""
    identity = filing_id or f"fictional-original-{year}"
    filed = filed or date(year + 1, 2, 9)
    proxy = datetime.combine(filed + timedelta(days=2), datetime.min.time(), tzinfo=UTC)
    filing = normalize_filing_index(
        {
            "data": {
                "symbol": "AXP",
                "filings": [
                    {
                        "filing_id": identity,
                        "date_filed": filed.isoformat(),
                        "form_type": "10-K",
                        "description": "Invented annual policy test",
                    }
                ],
            },
            "guide": "fictional",
        },
        received_at=RECEIVED,
        observation_sha256="a" * 64,
        requested_symbol="AXP",
    ).records[0]
    definitions = (
        ("income", "NetIncomeLoss", "20", date(year, 1, 1), date(year, 12, 31)),
        ("revenue", "RevenuesNetOfInterestExpense", "150", date(year, 1, 1), date(year, 12, 31)),
        (
            "prior",
            "RevenuesNetOfInterestExpense",
            "100",
            date(year - 1, 1, 1),
            date(year - 1, 12, 31),
        ),
        ("open_equity", "StockholdersEquity", "80", None, date(year - 1, 12, 31)),
        ("close_equity", "StockholdersEquity", "120", None, date(year, 12, 31)),
        ("long_debt", "LongTermDebt", "30", None, date(year, 12, 31)),
        ("short_debt", "ShortTermBorrowings", "10", None, date(year, 12, 31)),
    )
    rows = []
    for role, concept, value, start, end in definitions:
        if role in omit:
            continue
        row = {
            "filing_id": identity,
            "concept": concept,
            "entity": ENTITY,
            "period": f"{start}T00:00:00/{end}T00:00:00" if start else f"{end}T00:00:00",
            "axises": [],
            "char_value": "",
            "end_date": end.isoformat(),
            "unit": "iso4217:USD",
            "decimals": 0,
            "value": value,
        }
        if start is not None:
            row["start_date"] = start.isoformat()
        row.update((changes or {}).get(role, {}))
        rows.append(row)
    facts = normalize_filing_facts(
        {"data": {"facts": rows}, "guide": "fictional"},
        received_at=RECEIVED,
        observation_sha256="b" * 64,
        requested_filing_ids=tuple(sorted({row["filing_id"] for row in rows})),
        requested_concepts=CONCEPTS,
    )
    return build_annual_quality(
        AnnualQualityRequest(
            filing,
            (facts,),
            ENTITY,
            AnnualQualityPeriods(
                date(year, 1, 1), date(year, 12, 31), date(year - 1, 1, 1), date(year - 1, 12, 31)
            ),
            information_at or proxy,
        )
    )


def outcome(data, *, symbol="AXP", family="quality_momentum"):
    return next(r for r in evaluate_policies(data) if r.symbol == symbol and r.family == family)


def test_honest_duration_and_instant_bundle_is_consumed_atomically() -> None:
    bundle = annual()
    assert isinstance(bundle, DefinedAnnualQuality)
    assert bundle.roe == Decimal(".2") and bundle.revenue_growth == Decimal(".5")
    debt = next(ref.fact for ref in bundle.references if ref.role == "long_term_debt")
    assert debt.start_date is None and debt.start_date_present is False
    result = outcome(replace(inputs(), annual_quality=(bundle,)))
    assert isinstance(result, StrategyProposal) and result.decision == "enter"
    assert bundle.request.filing.receipt.received_at == RECEIVED
    assert bundle.availability_proxy_at == datetime(2024, 2, 11, tzinfo=UTC)
    assert "not_publication" in bundle.limitations[1]


@pytest.mark.parametrize(
    "omitted",
    ("income", "revenue", "prior", "open_equity", "close_equity", "long_debt", "short_debt"),
)
def test_missing_component_cannot_become_quality_entry(omitted) -> None:
    bundle = annual(omit=(omitted,))
    assert isinstance(bundle, UnavailableAnnualQuality)
    result = outcome(replace(inputs(), annual_quality=(bundle,)))
    assert isinstance(result, UnavailablePolicy) and result.code == "missing_fundamentals"


@pytest.mark.parametrize(
    ("changes", "decision"),
    (
        (
            {"income": {"value": "10"}, "revenue": {"value": "100"}, "long_debt": {"value": "110"}},
            "enter",
        ),
        ({"income": {"value": "9.999"}}, "hold"),
        ({"revenue": {"value": "99.999"}}, "hold"),
        ({"long_debt": {"value": "110.001"}}, "hold"),
        ({"long_debt": {"value": "0"}, "short_debt": {"value": "0"}}, "enter"),
    ),
)
def test_frozen_quality_thresholds_are_unchanged(changes, decision) -> None:
    result = outcome(replace(inputs(), annual_quality=(annual(changes=changes),)))
    assert isinstance(result, StrategyProposal) and result.decision == decision


def test_latest_unavailable_annual_blocks_stale_defined_fallback() -> None:
    older, latest = annual(), annual(year=2024, omit=("short_debt",))
    result = outcome(replace(inputs(), annual_quality=(latest, older)))
    assert isinstance(result, UnavailablePolicy) and result.code == "missing_fundamentals"


def test_latest_period_then_original_vintage_wins_without_ratio_mixing() -> None:
    older = annual()
    earlier = annual(year=2024, changes={"income": {"value": "1"}})
    newer = annual(year=2024, filing_id="fictional-later-original", filed=date(2025, 3, 1))
    assert outcome(replace(inputs(), annual_quality=(older, earlier, newer))).decision == "enter"
    bad_newer = annual(
        year=2024,
        filing_id="fictional-later-original",
        filed=date(2025, 3, 1),
        changes={"income": {"value": "1"}},
    )
    assert outcome(replace(inputs(), annual_quality=(older, earlier, bad_newer))).decision == "hold"


def test_separate_incomplete_originals_cannot_supply_each_others_missing_ratios() -> None:
    first = annual(omit=("income",), filing_id="fictional-one")
    second = annual(omit=("long_debt",), filing_id="fictional-two", filed=date(2024, 2, 10))
    result = outcome(replace(inputs(), annual_quality=(first, second)))
    assert isinstance(result, UnavailablePolicy)


@pytest.mark.parametrize(
    "other_changes", ({}, {"omit": ("income",)}, {"changes": {"income": {"value": "1"}}})
)
def test_same_day_distinct_originals_cannot_invent_vintage_order(other_changes) -> None:
    first = annual(filing_id="fictional-original-a")
    second = annual(filing_id="fictional-original-z", **other_changes)
    for supplied in ((first, second), (second, first)):
        with pytest.raises(ValueError, match="ambiguous same-day annual"):
            evaluate_policies(replace(inputs(), annual_quality=supplied))


def test_mixed_original_component_remains_unavailable() -> None:
    bundle = annual(changes={"long_debt": {"filing_id": "fictional-foreign-original"}})
    assert isinstance(bundle, UnavailableAnnualQuality)
    assert isinstance(outcome(replace(inputs(), annual_quality=(bundle,))), UnavailablePolicy)


@pytest.mark.parametrize(
    "bundles",
    (
        lambda: (annual(), annual(changes={"income": {"value": "21"}})),
        lambda: (annual(), annual(omit=("short_debt",))),
        lambda: (annual(), annual(information_at=datetime(2024, 2, 12, tzinfo=UTC))),
    ),
)
def test_conflicting_same_original_period_bundles_are_rejected(bundles) -> None:
    with pytest.raises(ValueError, match="conflicting annual"):
        evaluate_policies(replace(inputs(), annual_quality=bundles()))


def test_exact_duplicates_and_permutation_have_canonical_evidence() -> None:
    older, newer = annual(), annual(year=2024)
    data = replace(inputs(), annual_quality=(older, newer))
    assert evaluate_policies(data) == evaluate_policies(
        replace(data, annual_quality=(newer, annual(), older, newer))
    )
    changed = replace(
        data, annual_quality=(older, annual(year=2024, changes={"income": {"value": "21"}}))
    )
    assert outcome(data).evidence != outcome(changed).evidence


@pytest.mark.parametrize("kind", ("proxy", "period", "request_clock"))
def test_future_annual_information_is_rejected_before_any_policy(kind) -> None:
    data = inputs()
    bundle = {
        "proxy": lambda: annual(filed=date(2025, 10, 1)),
        "period": lambda: annual(year=2025, filed=date(2024, 2, 9)),
        "request_clock": lambda: annual(information_at=data.information_at + timedelta(seconds=1)),
    }[kind]()
    with pytest.raises(ValueError, match="future annual"):
        evaluate_policies(replace(data, annual_quality=(bundle,)))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("roe", Decimal("99")),
        ("qualified", True),
        ("source_qualified", True),
        ("strategy_qualified", True),
        ("live_authorized", True),
        ("availability_proxy_at", datetime(2024, 2, 10, tzinfo=UTC)),
    ),
)
def test_tampered_bundle_cannot_override_policy_boundary(field, value) -> None:
    bundle = annual()
    object.__setattr__(bundle, field, value)
    with pytest.raises(ValueError, match="stock_annual_quality_invalid"):
        evaluate_policies(replace(inputs(), annual_quality=(bundle,)))


@pytest.mark.parametrize("value", ([annual()], (object(),), (True,)))
def test_annual_input_is_an_immutable_validated_bundle_tuple(value) -> None:
    with pytest.raises(ValueError):
        evaluate_policies(replace(inputs(), annual_quality=value))


@pytest.mark.parametrize("missing", (False, True))
def test_same_symbol_legacy_quality_overlap_is_rejected(missing) -> None:
    bundle = annual(omit=("short_debt",) if missing else ())
    with pytest.raises(ValueError, match="ambiguous annual"):
        evaluate_policies(replace(inputs(), facts=legacy_quality(), annual_quality=(bundle,)))


def test_other_symbol_and_unrelated_legacy_facts_retain_their_old_path() -> None:
    data = inputs(("AXP", "BBB"))
    legacy = legacy_quality("BBB")
    raw = SourceFact(
        "AXP",
        "revenue",
        Decimal(100),
        BASE,
        BASE,
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000999999.json",
        "raw",
    )
    before = outcome(replace(data, facts=(*legacy, raw)), symbol="BBB")
    after = outcome(replace(data, facts=(*legacy, raw), annual_quality=(annual(),)), symbol="BBB")
    assert isinstance(before, StrategyProposal) and isinstance(after, StrategyProposal)
    assert before.decision == after.decision == "hold"
    assert (
        outcome(replace(data, facts=(*legacy, raw), annual_quality=(annual(),))).decision == "enter"
    )


@pytest.mark.parametrize(
    ("with_facts", "digest"),
    (
        (False, "a22cf2b1b53c5cc75f28da2940aeb15057069c8d134e281360f0c86279ab2d4d"),
        (True, "0c35209e65fc0323153a959357e19eebda75154237b34842bd8a61120e01f12e"),
    ),
)
def test_empty_annual_tuple_preserves_observed_3fc413b_legacy_hash(with_facts, digest) -> None:
    data = inputs()
    old_positional = PolicyInput(
        data.sessions,
        data.observations,
        data.universe,
        data.information_at,
        True,
        legacy_quality() if with_facts else (),
        (),
        (),
    )
    outcomes = evaluate_policies(old_positional)
    assert outcomes == evaluate_policies(replace(old_positional, annual_quality=()))
    assert all(r.evidence == (digest,) for r in outcomes if isinstance(r, StrategyProposal))
    quality = outcome(old_positional)
    assert isinstance(quality, StrategyProposal if with_facts else UnavailablePolicy)


def test_other_six_families_keep_their_decisions_and_hold_bounds() -> None:
    data = inputs()
    events = tuple(
        PolicyEvent(
            "AXP",
            kind,
            identity,
            index,
            data.sessions[index].closes_at,
            data.sessions[index].closes_at,
            Decimal(value),
        )
        for kind, identity, index, value in (
            ("earnings", "fictional-earnings", 251, ".1"),
            ("revision", "fictional-revision-1", 251, ".02"),
            ("revision", "fictional-revision-2", 250, ".02"),
        )
    )
    baseline = evaluate_policies(replace(data, events=events))
    enriched = evaluate_policies(replace(data, events=events, annual_quality=(annual(),)))
    for old, new in zip(baseline, enriched, strict=True):
        if old.family != "quality_momentum":
            assert replace(new, evidence=old.evidence) == old


def test_original_vintage_cannot_leak_across_policy_cutoff() -> None:
    data = inputs()
    known = annual(year=2024, filed=date(2025, 9, 8), changes={"income": {"value": "1"}})
    later = annual(year=2024, filing_id="fictional-later-original", filed=date(2025, 9, 9))
    assert known.availability_proxy_at <= data.information_at < later.availability_proxy_at
    assert outcome(replace(data, annual_quality=(known,))).decision == "hold"
    with pytest.raises(ValueError, match="future annual"):
        evaluate_policies(replace(data, annual_quality=(known, later)))


def test_policy_proposal_remains_immutable_unqualified_and_without_order_authority() -> None:
    result = outcome(replace(inputs(), annual_quality=(annual(),)))
    assert isinstance(result, StrategyProposal) and result.qualified is False
    assert result.execute_not_before > result.information_at
    with pytest.raises(FrozenInstanceError):
        result.qualified = True
    with pytest.raises((ValueError, TypeError)):
        replace(result, qualified=True)
    assert not hasattr(result, "quantity") and not hasattr(result, "live_authorized")
