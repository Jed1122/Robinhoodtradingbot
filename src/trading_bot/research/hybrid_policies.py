"""Frozen v1 research policies. Proposals cannot authorize or submit an order."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from itertools import pairwise
from types import MappingProxyType
from typing import Literal

from trading_bot.market_data.recording import content_hash
from trading_bot.research.hybrid_sources import SourceFact, identifier, utc, visible_facts
from trading_bot.research.hybrid_strategies import FAMILIES, PriceBar
from trading_bot.research.stock_annual_quality import (
    DefinedAnnualQuality,
    UnavailableAnnualQuality,
    revalidate_annual_quality,
)

Decision = Literal["enter", "hold", "exit"]
EventKind = Literal["earnings", "revision"]
AnnualQuality = DefinedAnnualQuality | UnavailableAnnualQuality


@dataclass(frozen=True)
class CalendarSession:
    index: int
    opens_at: datetime
    closes_at: datetime

    def __post_init__(self) -> None:
        if (
            type(self.index) is not int
            or self.index < 0
            or utc(self.opens_at) >= utc(self.closes_at)
        ):
            raise ValueError("invalid calendar session")


@dataclass(frozen=True)
class SessionObservation:
    symbol: str
    session_index: int
    bar: PriceBar
    volume: Decimal | None

    def __post_init__(self) -> None:
        identifier(self.symbol)
        if type(self.session_index) is not int or self.session_index < 0:
            raise ValueError("invalid observation session identity")
        if self.volume is not None and (
            not isinstance(self.volume, Decimal)
            or not self.volume.is_finite()
            or not 0 <= self.volume <= Decimal("1e30")
        ):
            raise ValueError("invalid observed volume")


@dataclass(frozen=True)
class UniverseMembership:
    symbol: str
    effective_at: datetime
    available_at: datetime
    included: bool
    event_id: str

    def __post_init__(self) -> None:
        identifier(self.symbol)
        identifier(self.event_id)
        utc(self.effective_at)
        utc(self.available_at)
        if type(self.included) is not bool:
            raise ValueError("exact membership boolean required")


@dataclass(frozen=True)
class PolicyEvent:
    symbol: str
    kind: EventKind
    event_id: str
    session_index: int
    occurred_at: datetime
    available_at: datetime
    value: Decimal

    def __post_init__(self) -> None:
        identifier(self.symbol)
        identifier(self.event_id)
        if type(self.session_index) is not int or self.session_index < 0:
            raise ValueError("invalid event session identity")
        if self.kind not in ("earnings", "revision"):
            raise ValueError("unsupported structured event kind")
        if utc(self.available_at) < utc(self.occurred_at):
            raise ValueError("event availability precedes occurrence")
        if (
            not isinstance(self.value, Decimal)
            or not self.value.is_finite()
            or abs(self.value) > 100
        ):
            raise ValueError("bounded fractional event change required")


@dataclass(frozen=True)
class PolicyInput:
    sessions: tuple[CalendarSession, ...]
    observations: tuple[SessionObservation, ...]
    universe: tuple[UniverseMembership, ...]
    information_at: datetime
    calendar_verified: bool
    facts: tuple[SourceFact, ...] = ()
    events: tuple[PolicyEvent, ...] = ()
    held_positions: tuple[tuple[str, str], ...] = ()
    annual_quality: tuple[AnnualQuality, ...] = ()

    def __post_init__(self) -> None:
        utc(self.information_at)
        if type(self.calendar_verified) is not bool:
            raise ValueError("exact calendar verification boolean required")
        if any(
            not isinstance(value, tuple)
            for value in (
                self.sessions,
                self.observations,
                self.universe,
                self.facts,
                self.events,
                self.held_positions,
                self.annual_quality,
            )
        ):
            raise ValueError("immutable observation tuples required")
        for position in self.held_positions:
            if not isinstance(position, tuple) or len(position) != 2:
                raise ValueError("immutable symbol/family position pair required")
            identifier(position[0])
            if position[1] not in FAMILIES:
                raise ValueError("unknown held policy family")
        if len(set(self.held_positions)) != len(self.held_positions):
            raise ValueError("duplicate held position")


@dataclass(frozen=True)
class StrategyProposal:
    symbol: str
    family: str
    information_at: datetime
    execute_not_before: datetime
    decision: Decision
    reason: str
    minimum_holding_sessions: int
    maximum_holding_sessions: int
    evidence: tuple[str, ...]
    version: Literal["hybrid-policy-v1"] = field(default="hybrid-policy-v1", init=False)
    qualified: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        identifier(self.symbol)
        if self.family not in FAMILIES or self.decision not in ("enter", "hold", "exit"):
            raise ValueError("invalid policy proposal")
        if utc(self.execute_not_before) <= utc(self.information_at):
            raise ValueError("proposal must wait for a future session")
        if not 1 <= self.minimum_holding_sessions <= self.maximum_holding_sessions:
            raise ValueError("invalid holding session bounds")
        if not isinstance(self.evidence, tuple) or not self.evidence:
            raise ValueError("immutable evidence references required")


@dataclass(frozen=True)
class UnavailablePolicy:
    symbol: str
    family: str
    information_at: datetime
    reason: str
    code: str
    qualified: Literal[False] = field(default=False, init=False)


PolicyOutcome = StrategyProposal | UnavailablePolicy
BOUNDS = MappingProxyType(
    {
        "momentum": (20, 252),
        "trend": (1, 252),
        "breakout": (1, 20),
        "quality_momentum": (20, 252),
        "mean_reversion": (1, 5),
        "pead": (1, 20),
        "revision_momentum": (1, 30),
    }
)


def _validate(
    data: PolicyInput,
) -> tuple[
    dict[int, CalendarSession],
    dict[tuple[str, int], SessionObservation],
    tuple[PolicyEvent, ...],
    tuple[AnnualQuality, ...],
]:
    annual_quality = _validate_annual_quality(data)
    sessions: dict[int, CalendarSession] = {}
    for session in data.sessions:
        if session.index in sessions:
            raise ValueError("duplicate calendar session")
        sessions[session.index] = session
    ordered = sorted(sessions.values(), key=lambda s: s.index)
    for previous, current in pairwise(ordered):
        if current.index != previous.index + 1 or previous.closes_at >= current.opens_at:
            raise ValueError("calendar sessions must be consecutive and nonoverlapping")
    observations: dict[tuple[str, int], SessionObservation] = {}
    for row in data.observations:
        row_session = sessions.get(row.session_index)
        if row.bar.completed_at > data.information_at:
            raise ValueError("future observation")
        if row_session is None or row_session.closes_at != row.bar.completed_at:
            raise ValueError("observation calendar mismatch")
        key = (row.symbol, row.session_index)
        if key in observations and observations[key] != row:
            raise ValueError("conflicting observation")
        observations[key] = row
    for fact in data.facts:
        if fact.available_at > data.information_at or fact.period_end > data.information_at:
            raise ValueError("future financial fact")
    visible_facts(data.facts, data.information_at)
    events: dict[tuple[str, str], PolicyEvent] = {}
    for event in data.events:
        if event.available_at > data.information_at or event.occurred_at > data.information_at:
            raise ValueError("future event")
        event_session = sessions.get(event.session_index)
        next_session = sessions.get(event.session_index + 1)
        if (
            event_session is None
            or next_session is None
            or not event_session.opens_at <= event.occurred_at < next_session.opens_at
        ):
            raise ValueError("event occurrence/calendar mismatch")
        event_key = (event.symbol, event.event_id)
        if event_key in events and events[event_key] != event:
            raise ValueError("conflicting event")
        events[event_key] = event
    membership: dict[tuple[str, datetime, datetime], UniverseMembership] = {}
    for record in data.universe:
        member_key = (record.symbol, record.effective_at, record.available_at)
        if member_key in membership and membership[member_key].included != record.included:
            raise ValueError("conflicting universe membership")
        membership[member_key] = record
    return (
        sessions,
        observations,
        tuple(sorted(events.values(), key=lambda e: (e.symbol, e.event_id))),
        annual_quality,
    )


def _validate_annual_quality(data: PolicyInput) -> tuple[AnnualQuality, ...]:
    if not isinstance(data.annual_quality, tuple):
        raise ValueError("immutable annual quality tuple required")
    records = []
    for supplied in data.annual_quality:
        bundle = revalidate_annual_quality(supplied)
        records.append((bundle, bundle.evidence_hash))
    return _annual_records(data, tuple(records))


def _annual_records(
    data: PolicyInput, records: tuple[tuple[AnnualQuality, str], ...]
) -> tuple[AnnualQuality, ...]:
    originals: dict[tuple[str, str, date], str] = {}
    vintages: dict[tuple[str, date, date, datetime], str] = {}
    unique: dict[str, AnnualQuality] = {}
    for bundle, digest in records:
        request, periods = bundle.request, bundle.request.periods
        if (
            bundle.availability_proxy_at > data.information_at
            or request.information_at > data.information_at
            or request.filing.date_filed > data.information_at.date()
            or any(
                day > data.information_at.date()
                for day in (
                    periods.current_start,
                    periods.current_end,
                    periods.prior_start,
                    periods.prior_end,
                )
            )
        ):
            raise ValueError("future annual quality information")
        key = (request.filing.symbol, request.filing.filing_id, periods.current_end)
        if key in originals and originals[key] != digest:
            raise ValueError("conflicting annual quality original/period")
        originals[key] = digest
        vintage = (
            request.filing.symbol,
            periods.current_end,
            request.filing.date_filed,
            bundle.availability_proxy_at,
        )
        if vintage in vintages and vintages[vintage] != request.filing.filing_id:
            raise ValueError("ambiguous same-day annual originals")
        vintages[vintage] = request.filing.filing_id
        unique[digest] = bundle
    symbols = {bundle.request.filing.symbol for bundle in unique.values()}
    if any(
        fact.symbol in symbols and fact.metric in {"roe", "revenue_growth", "debt_to_equity"}
        for fact in data.facts
    ):
        raise ValueError("ambiguous annual and legacy quality evidence")
    return tuple(unique[digest] for digest in sorted(unique))


def _members(data: PolicyInput) -> tuple[str, ...]:
    latest: dict[str, UniverseMembership] = {}
    for record in data.universe:
        if record.effective_at > data.information_at or record.available_at > data.information_at:
            continue
        old = latest.get(record.symbol)
        if old is None or (record.effective_at, record.available_at) > (
            old.effective_at,
            old.available_at,
        ):
            latest[record.symbol] = record
    return tuple(sorted(s for s, record in latest.items() if record.included))


def _window(
    symbol: str, current: int, count: int, observations: dict[tuple[str, int], SessionObservation]
) -> tuple[SessionObservation, ...]:
    keys = tuple((symbol, i) for i in range(current - count + 1, current + 1))
    return tuple(observations[key] for key in keys) if all(k in observations for k in keys) else ()


def _financial_quality(
    data: PolicyInput, symbol: str, annual_quality: tuple[AnnualQuality, ...]
) -> bool | None:
    supplied = [bundle for bundle in annual_quality if bundle.request.filing.symbol == symbol]
    if supplied:
        selected = max(
            supplied,
            key=lambda bundle: (
                bundle.request.periods.current_end,
                bundle.request.filing.date_filed,
                bundle.availability_proxy_at,
            ),
        )
        if isinstance(selected, UnavailableAnnualQuality):
            return None
        return (
            selected.roe >= Decimal(".10")
            and selected.revenue_growth >= 0
            and 0 <= selected.debt_to_equity <= 1
        )
    latest: dict[str, SourceFact] = {}
    required = {"roe", "revenue_growth", "debt_to_equity"}
    for fact in visible_facts(data.facts, data.information_at):
        if fact.symbol == symbol and fact.metric in required:
            old = latest.get(fact.metric)
            if old is None or (fact.period_end, fact.available_at, fact.event_id) > (
                old.period_end,
                old.available_at,
                old.event_id,
            ):
                latest[fact.metric] = fact
    if (
        latest.keys() != required
        or len({(f.period_start, f.period_end) for f in latest.values()}) != 1
    ):
        return None
    return (
        latest["roe"].value >= Decimal(".10")
        and latest["revenue_growth"].value >= 0
        and 0 <= latest["debt_to_equity"].value <= 1
    )


def evaluate_policies(data: PolicyInput) -> tuple[PolicyOutcome, ...]:
    """Validate all supplied observations, then evaluate frozen, independent hypotheses.

    The calendar verification boolean is a caller declaration, not source attestation.
    Optional atomic annual measurements retain their retrospective availability
    proxy and original receipt clocks; neither is promoted to native publication.
    Missing data produces no proposal. A proposal has no quantity, broker identity,
    risk approval, or order authority. Holding ranges are research horizon bounds.
    """
    sessions, observations, events, annual_quality = _validate(data)
    return _evaluate_validated_policies(data, sessions, observations, events, annual_quality)


def _evaluate_validated_policies(
    data: PolicyInput,
    sessions: dict[int, CalendarSession],
    observations: dict[tuple[str, int], SessionObservation],
    events: tuple[PolicyEvent, ...],
    annual_quality: tuple[AnnualQuality, ...],
    annual_hashes: tuple[str, ...] | None = None,
) -> tuple[PolicyOutcome, ...]:
    symbols = sorted(
        {r.symbol for r in data.universe}
        | {r.symbol for r in data.observations}
        | {s for s, _ in data.held_positions}
    )
    completed = [s for s in sessions.values() if s.closes_at <= data.information_at]
    current = max((s.index for s in completed), default=-1)
    following = sessions.get(current + 1)
    if following is not None and following.opens_at <= data.information_at:
        raise ValueError("next-session proposal window already passed")
    members = _members(data)
    momentum: dict[str, Decimal] = {}
    complete_cross_section = bool(members)
    for symbol in members:
        window = _window(symbol, current, 253, observations)
        if not window:
            complete_cross_section = False
        else:
            momentum[symbol] = window[-22].bar.close / window[0].bar.close - 1
    leaders = set(
        sorted(momentum, key=lambda s: (-momentum[s], s))[: max(1, math.ceil(len(members) * 0.2))]
    )
    # Bind the entire declared cross-section and calendar: input permutation cannot change evidence.
    evidence_body = {
        "information_at": data.information_at.isoformat(),
        "held_positions": sorted(data.held_positions),
        "sessions": [
            (s.index, s.opens_at.isoformat(), s.closes_at.isoformat())
            for s in sorted(sessions.values(), key=lambda s: s.index)
        ],
        "observations": [
            (s, i, str(r.bar.open), str(r.bar.close), str(r.volume))
            for (s, i), r in sorted(observations.items())
        ],
        "membership": sorted(
            (
                r.symbol,
                r.effective_at.isoformat(),
                r.available_at.isoformat(),
                r.included,
                r.event_id,
            )
            for r in data.universe
            if r.effective_at <= data.information_at and r.available_at <= data.information_at
        ),
        "facts": sorted(
            (
                f.symbol,
                f.metric,
                str(f.value),
                f.period_end.isoformat(),
                "" if f.period_start is None else f.period_start.isoformat(),
                f.source_url,
                f.available_at.isoformat(),
                f.event_id,
            )
            for f in data.facts
        ),
        "events": [
            (
                e.symbol,
                e.kind,
                e.event_id,
                e.session_index,
                str(e.value),
                e.occurred_at.isoformat(),
                e.available_at.isoformat(),
            )
            for e in events
        ],
    }
    # Absence preserves the complete legacy evidence body and its existing hashes.
    if annual_quality:
        evidence_body["annual_quality"] = (
            [bundle.evidence_hash for bundle in annual_quality]
            if annual_hashes is None
            else list(annual_hashes)
        )
    digest = hashlib.sha256(json.dumps(evidence_body, sort_keys=True).encode()).hexdigest()
    results: list[PolicyOutcome] = []
    for symbol in symbols:
        for family in FAMILIES:
            missing: str | None = None
            qualifies = False
            reason = "v1 hypothesis conditions not met"
            if not data.calendar_verified or following is None or current < 0:
                missing = "missing_calendar"
            elif symbol not in members:
                missing = "not_member"
            elif family in ("momentum", "quality_momentum"):
                if not complete_cross_section:
                    missing = "missing_history"
                else:
                    qualifies = symbol in leaders and momentum[symbol] > 0
                    if family == "quality_momentum":
                        quality = _financial_quality(data, symbol, annual_quality)
                        if quality is None:
                            missing = "missing_fundamentals"
                        else:
                            qualifies = qualifies and quality
            elif family in ("trend", "mean_reversion"):
                window = _window(symbol, current, 200, observations)
                if not window:
                    missing = "missing_history"
                else:
                    closes = [r.bar.close for r in window]
                    mean200 = sum(closes) / 200
                    positive_trend = closes[-1] > mean200
                    if family == "trend":
                        qualifies = positive_trend and sum(closes[-50:]) / 50 > mean200
                    else:
                        qualifies = positive_trend and closes[-1] / closes[-6] - 1 <= Decimal(
                            "-.05"
                        )
            elif family == "breakout":
                window = _window(symbol, current, 21, observations)
                if not window:
                    missing = "missing_history"
                elif any(r.volume is None for r in window):
                    missing = "missing_volume"
                else:
                    baseline = (
                        sum((r.volume for r in window[:-1] if r.volume is not None), Decimal(0))
                        / 20
                    )
                    volume = window[-1].volume
                    qualifies = (
                        baseline > 0
                        and volume is not None
                        and volume >= baseline * Decimal("1.5")
                        and window[-1].bar.close > max(r.bar.close for r in window[:-1])
                    )
            else:
                kind = "earnings" if family == "pead" else "revision"
                supplied = [e for e in events if e.symbol == symbol and e.kind == kind]
                if not supplied:
                    missing = "missing_event"
                elif family == "pead":
                    recent = max(supplied, key=lambda e: (e.occurred_at, e.event_id))
                    window = _window(symbol, current, 2, observations)
                    if not window:
                        missing = "missing_history"
                    else:
                        qualifies = (
                            1 <= current - recent.session_index <= 3
                            and recent.value >= Decimal(".05")
                            and window[-1].bar.close > window[-2].bar.close
                        )
                else:
                    recent_revisions = [e for e in supplied if 0 <= current - e.session_index < 30]
                    if len(recent_revisions) < 2:
                        missing = "missing_event"
                    else:
                        qualifies = sum((e.value for e in recent_revisions), Decimal(0)) >= Decimal(
                            ".02"
                        )
            if missing is not None:
                results.append(
                    UnavailablePolicy(
                        symbol,
                        family,
                        data.information_at,
                        "required point-in-time observations unavailable",
                        missing,
                    )
                )
                continue
            held = (symbol, family) in data.held_positions
            decision: Decision = "hold" if held == qualifies else ("enter" if qualifies else "exit")
            if qualifies:
                reason = (
                    "frozen v1 entry hypothesis met"
                    if not held
                    else "frozen v1 holding hypothesis met"
                )
            elif held:
                reason = "frozen v1 hypothesis no longer met"
            minimum, maximum = BOUNDS[family]
            if following is None:
                raise ValueError("missing next calendar session")
            results.append(
                StrategyProposal(
                    symbol,
                    family,
                    data.information_at,
                    following.opens_at,
                    decision,
                    reason,
                    minimum,
                    maximum,
                    (digest,),
                )
            )
    return tuple(results)


@dataclass(frozen=True, slots=True)
class _CompiledAnnualPolicyInventory:
    records: tuple[tuple[AnnualQuality, str, str], ...]
    root: str


def _annual_compact(bundle: AnnualQuality) -> str:
    request = bundle.request
    filing = request.filing
    return str(
        content_hash(
            (
                "owned-annual-policy-leaf-v1",
                type(bundle).__qualname__,
                bundle.method_id,
                filing.symbol,
                filing.filing_id,
                filing.date_filed,
                filing.receipt.observation_sha256,
                filing.receipt.received_at,
                request.entity,
                request.periods,
                request.information_at,
                bundle.availability_proxy_at,
                bundle.debt_measurement_at,
                bundle.status,
                bundle.reason_codes,
                tuple(
                    (
                        type(n).__qualname__,
                        None
                        if n is None
                        else (n.as_tuple().sign, n.as_tuple().digits, n.as_tuple().exponent),
                    )
                    for n in (bundle.roe, bundle.revenue_growth, bundle.debt_to_equity)
                ),
                tuple(
                    (r.role, r.source_collection_index, r.fact.row_index) for r in bundle.references
                ),
                tuple(
                    (
                        source.receipt.observation_sha256,
                        source.receipt.received_at,
                        source.requested_filing_ids,
                        source.requested_concepts,
                        len(source.records),
                        source.facts_missing,
                        source.null_row_indices,
                    )
                    for source in request.facts
                ),
                (
                    bundle.qualified,
                    bundle.source_qualified,
                    bundle.strategy_qualified,
                    bundle.investment_eligible,
                    bundle.trading_enabled,
                    bundle.live_authorized,
                ),
            )
        )
    )


def _compile_annual_policy_inventory(
    supplied: tuple[AnnualQuality, ...],
) -> _CompiledAnnualPolicyInventory:
    if type(supplied) is not tuple or len(supplied) > 64:
        raise ValueError("bounded annual inventory required")
    unique = {}
    for item in supplied:
        bundle = revalidate_annual_quality(item)
        digest = bundle.evidence_hash
        unique[digest] = (bundle, digest, _annual_compact(bundle))
    records = tuple(unique[d] for d in sorted(unique))
    if records:
        at = max(max(b.availability_proxy_at, b.request.information_at) for b, _, _ in records)
        _annual_records(PolicyInput((), (), (), at, True), tuple((b, d) for b, d, _ in records))
    root = str(
        content_hash(
            ("owned-annual-policy-inventory-v1", tuple((d, leaf) for _, d, leaf in records))
        )
    )
    return _CompiledAnnualPolicyInventory(records, root)


def _evaluate_owned_policies(
    data: PolicyInput,
    inventory: _CompiledAnnualPolicyInventory,
) -> tuple[PolicyOutcome, ...]:
    """Private compiled route; owning source boundaries must rebuild the inventory."""
    if type(inventory) is not _CompiledAnnualPolicyInventory or data.annual_quality:
        raise ValueError("owned annual context and empty public annual input required")
    for bundle, _, leaf in inventory.records:
        if _annual_compact(bundle) != leaf:
            raise ValueError("owned annual source leaf changed")
    root = str(
        content_hash(
            (
                "owned-annual-policy-inventory-v1",
                tuple((d, leaf) for _, d, leaf in inventory.records),
            )
        )
    )
    if root != inventory.root:
        raise ValueError("owned annual context changed")
    sessions, observations, events, _ = _validate(data)
    visible = tuple(
        (b, digest)
        for b, digest, _ in inventory.records
        if b.availability_proxy_at <= data.information_at
        and b.request.information_at <= data.information_at
    )
    annual = _annual_records(data, visible)
    return _evaluate_validated_policies(
        data, sessions, observations, events, annual, tuple(d for _, d in visible)
    )
