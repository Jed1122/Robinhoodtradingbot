"""Finite conditional calendar transcription, without prices or broker authority.

Packets retain complete source bytes and exact reviewed byte spans. Their hashes,
URLs and clocks are caller-declared bindings, never source authentication or an
NLP verification of the transcription. Normal weekdays and padded regular hours
are explicit research assumptions. CNS and dividend funding are separate axes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, is_dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.recording import content_hash
from trading_bot.market_data.stock_daily_series import (
    StockDailyCalendar,
    parse_stock_daily_calendar,
)
from trading_bot.research.hybrid_policies import CalendarSession

Axis = Literal["market", "cns", "dividend_funding"]
Representation = Literal["original_body", "indexed_primary_receipt", "rendered_primary_receipt"]
_NY = ZoneInfo("America/New_York")
_FIRST = date(2024, 1, 2)
_LAST_PRICE = date(2026, 10, 23)
_END = date(2026, 11, 12)
_KINDS = {
    "exchange_calendar": ("market", 1),
    "market_notice": ("market", 2),
    "ordinary_cns_calendar": ("cns", 1),
    "ordinary_cns_notice": ("cns", 2),
    "dividend_funding_schedule": ("dividend_funding", 1),
    "dividend_funding_notice": ("dividend_funding", 2),
}
_STATUSES = {
    "market": ("open", "closed", "unknown"),
    "cns": ("ordinary_supported", "closed", "limited", "unknown"),
    "dividend_funding": ("supported", "unavailable", "unknown"),
}
_BASELINES = {
    "market_regular_weekdays_v1": ("market", "open", "closed"),
    "ordinary_cns_weekdays_v1": ("cns", "ordinary_supported", "closed"),
    "dividend_funding_weekdays_v1": ("dividend_funding", "supported", "unavailable"),
}
_LIMITATIONS = (
    "source_bindings_and_reviewed_transcriptions_are_caller_declared_not_authenticated",
    "indexed_and_rendered_receipts_are_not_original_document_bytes",
    "normal_weekdays_are_source_scoped_model_assumptions_not_observed_service",
    "padded_0930_1600_new_york_sessions_are_modeled_schedule_only",
    "anticipated_tables_do_not_establish_complete_service_amendment_coverage",
    "cns_and_dividend_funding_are_independent",
    "cash_availability_is_conservative_modeled_timing_not_broker_posting",
)


class ReplayScheduleError(ValueError):
    def __init__(self, reason: str = "stock_replay_schedule_invalid") -> None:
        super().__init__(reason)


def _check(condition: bool, reason: str = "stock_replay_schedule_invalid") -> None:
    if not condition:
        raise ReplayScheduleError(reason)


def _hash(value: object) -> str:
    return str(content_hash(value))


def _same(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if is_dataclass(left) and not isinstance(left, type):
        return _same(object.__getstate__(left), object.__getstate__(right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same(v, right[k]) for k, v in left.items())
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(
            _same(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


def _day(value: object) -> None:
    _check(type(value) is date, "exact_calendar_date_required")


@dataclass(frozen=True, slots=True)
class ReplaySourceSpan:
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ReplayScheduleDayFact:
    day: date
    status: str
    span: ReplaySourceSpan


@dataclass(frozen=True, slots=True)
class ReplayWeekdayBaseline:
    name: str
    span: ReplaySourceSpan


@dataclass(frozen=True, slots=True)
class ReplayScheduleSourcePacket:
    notice_id: str
    axis: Axis
    kind: str
    representation: Representation
    source_url: str
    original_bytes: bytes
    original_sha256: str
    requested_at: datetime | None
    received_at: datetime | None
    coverage_start: date
    coverage_end: date
    facts: tuple[ReplayScheduleDayFact, ...] = ()
    weekday_baseline: ReplayWeekdayBaseline | None = None
    http_status: int | None = None
    retained_receipt_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class RetrospectiveScheduleRule:
    version: Literal["finite_stock_schedule_v1"] = field(
        default="finite_stock_schedule_v1", init=False
    )
    first_price_date: date = field(default=_FIRST, init=False)
    last_price_date: date = field(default=_LAST_PRICE, init=False)
    padding_through: date = field(default=_END, init=False)
    native_session_count: Literal[706] = field(default=706, init=False)
    first_execution_session: Literal[200] = field(default=200, init=False)
    settlement_lag: Literal[1] = field(default=1, init=False)
    settlement_transition: date = field(default=date(2024, 5, 28), init=False)
    modeled_cash_phase: str = field(
        default="first_market_open_strictly_after_due_date_v1", init=False
    )
    padded_hours: str = field(default="0930_1600_America_New_York_v1", init=False)


@dataclass(frozen=True, slots=True)
class ReplayPacketBinding:
    packet_sha256: str
    notice_id: str
    axis: Axis
    kind: str
    representation: Representation
    original_sha256: str
    retained_receipt_sha256: str | None
    source_url: str
    requested_at: datetime | None
    received_at: datetime | None
    coverage_start: date
    coverage_end: date


@dataclass(frozen=True, slots=True)
class ReplayScheduleDay:
    day: date
    status: str
    basis: Literal[
        "native_calendar", "source_transcription", "modeled_weekday", "unknown", "conflict"
    ]
    packet_hashes: tuple[str, ...]
    overridden_packet_hashes: tuple[str, ...] = ()
    opens_at: datetime | None = None
    closes_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReplaySettlementAvailability:
    trade_session_index: int
    settlement_date: date | None
    available_at: datetime | None
    reason: str | None
    modeled_not_broker_posting: Literal[True] = field(default=True, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class RetrospectiveReplaySchedule:
    native_calendar: StockDailyCalendar
    source_packets: tuple[ReplayScheduleSourcePacket, ...]
    rule: RetrospectiveScheduleRule
    market_sessions: tuple[CalendarSession, ...] = field(init=False)
    market_days: tuple[ReplayScheduleDay, ...] = field(init=False)
    cns_days: tuple[ReplayScheduleDay, ...] = field(init=False)
    dividend_funding_days: tuple[ReplayScheduleDay, ...] = field(init=False)
    packet_bindings: tuple[ReplayPacketBinding, ...] = field(init=False)
    source_graph_sha256: str = field(init=False)
    status: Literal["conditionally_prepared", "unavailable"] = field(init=False)
    reason_codes: tuple[str, ...] = field(init=False)
    limitations: tuple[str, ...] = field(init=False)
    source_profile: Literal["conditional_retrospective_schedule_v1"] = field(
        default="conditional_retrospective_schedule_v1", init=False
    )
    price_session_count: Literal[706] = field(default=706, init=False)
    padding_has_prices: Literal[False] = field(default=False, init=False)
    complete_service_coverage: Literal[False] = field(default=False, init=False)
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    full_task5_complete: Literal[False] = field(default=False, init=False)
    authenticated: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    _evidence_hash: str = field(init=False, repr=False)
    _query_proofs: tuple[tuple[str, ...], ...] = field(init=False, repr=False)
    _native_trade_dates: tuple[date, ...] = field(init=False, repr=False)
    _native_trade_proofs: tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        values = _assess(self.native_calendar, self.source_packets, self.rule)
        for name, value in values.items():
            object.__setattr__(self, name, value)

    @property
    def evidence_hash(self) -> str:
        revalidate_replay_schedule(self)
        return self._evidence_hash


def _span(body: bytes, span: ReplaySourceSpan) -> str:
    _check(type(span) is ReplaySourceSpan, "exact_source_span_required")
    _check(type(span.start) is int and type(span.end) is int, "exact_source_span_required")
    _check(
        0 <= span.start < span.end <= len(body) and span.end - span.start <= 32768,
        "exact_source_span_required",
    )
    text = body[span.start : span.end].decode("utf-8").strip().lower()
    _check(bool(text), "empty_source_span")
    return text


def _semantics(axis: Axis, status: str, text: str) -> None:
    """Narrow axis/claim vocabulary, not a proof of the reviewed interpretation."""
    if status == "unknown":
        return
    if axis == "market":
        _check(
            any(w in text for w in ("market", "exchange", "holiday", "closed", "nasdaq")),
            "market_source_span_required",
        )
    elif axis == "cns":
        _check("cns" in text or "settlement" in text, "cns_source_span_required")
    else:
        _check(
            ("dividend" in text or "corporate action" in text)
            and any(w in text for w in ("allocat", "payment", "funding")),
            "explicit_dividend_funding_span_required",
        )


def _packet(packet: ReplayScheduleSourcePacket) -> ReplayPacketBinding:
    _check(type(packet) is ReplayScheduleSourcePacket, "typed_source_packet_required")
    _check(
        type(packet.notice_id) is str
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,127}", packet.notice_id) is not None,
        "bounded_notice_identity_required",
    )
    _check(type(packet.axis) is str and packet.axis in _STATUSES, "known_source_axis_required")
    _check(
        type(packet.kind) is str
        and packet.kind in _KINDS
        and _KINDS[packet.kind][0] == packet.axis,
        "source_kind_axis_mismatch",
    )
    _check(
        packet.representation
        in ("original_body", "indexed_primary_receipt", "rendered_primary_receipt"),
        "known_source_representation_required",
    )
    _check(
        type(packet.original_bytes) is bytes and 1 <= len(packet.original_bytes) <= 8 * 1024 * 1024,
        "bounded_complete_source_bytes_required",
    )
    _require_sha256_hex(packet.original_sha256, "source body")
    _check(
        hashlib.sha256(packet.original_bytes).hexdigest() == packet.original_sha256,
        "source_body_hash_mismatch",
    )
    if packet.retained_receipt_sha256 is not None:
        _require_sha256_hex(packet.retained_receipt_sha256, "retained receipt")
    _check(
        type(packet.source_url) is str and len(packet.source_url) <= 2048,
        "primary_source_url_required",
    )
    parsed = urlsplit(packet.source_url)
    host = parsed.hostname or ""
    _check(
        parsed.scheme in ("http", "https")
        and not parsed.username
        and not parsed.password
        and (
            host == "nasdaqtrader.com"
            or host.endswith(".nasdaqtrader.com")
            or host == "dtcc.com"
            or host.endswith(".dtcc.com")
        ),
        "primary_source_url_required",
    )
    if packet.representation == "original_body":
        _check(
            type(packet.http_status) is int and packet.http_status == 200,
            "successful_original_http_body_required",
        )
    else:
        _check(packet.http_status is None, "receipt_is_not_original_http_response")
    # Error bodies remain error bodies even if the caller attaches notice text.
    prefix = packet.original_bytes[:8192].decode("utf-8", errors="replace").lower()
    _check(
        re.search(
            r"<title>[^<]*(?:404|403|not found|forbidden|access denied)|^\s*(?:403|404)\b", prefix
        )
        is None,
        "http_error_body_is_not_notice",
    )
    for clock in (packet.requested_at, packet.received_at):
        if clock is not None:
            _check(type(clock) is datetime, "exact_source_clock_required")
            require_utc(clock)
    if packet.requested_at is not None and packet.received_at is not None:
        _check(packet.requested_at <= packet.received_at, "source_clock_rewind")
    _day(packet.coverage_start)
    _day(packet.coverage_end)
    _check(
        packet.coverage_start <= packet.coverage_end
        and (packet.coverage_end - packet.coverage_start).days <= 1100,
        "bounded_source_coverage_required",
    )
    _check(
        type(packet.facts) is tuple and len(packet.facts) <= 128, "bounded_immutable_facts_required"
    )
    seen: set[date] = set()
    for fact in packet.facts:
        _check(type(fact) is ReplayScheduleDayFact, "typed_source_fact_required")
        _day(fact.day)
        _check(
            packet.coverage_start <= fact.day <= packet.coverage_end and fact.day not in seen,
            "source_fact_date_invalid",
        )
        _check(
            type(fact.status) is str and fact.status in _STATUSES[packet.axis],
            "fact_axis_status_mismatch",
        )
        _semantics(packet.axis, fact.status, _span(packet.original_bytes, fact.span))
        if packet.axis == "market" and fact.status == "open":
            _check(fact.day.weekday() < 5, "regular_market_weekend_open_unsupported")
        seen.add(fact.day)
    baseline = packet.weekday_baseline
    if baseline is not None:
        _check(
            type(baseline) is ReplayWeekdayBaseline
            and baseline.name in _BASELINES
            and _BASELINES[baseline.name][0] == packet.axis,
            "named_axis_weekday_baseline_required",
        )
        _check(
            packet.kind
            in ("exchange_calendar", "ordinary_cns_calendar", "dividend_funding_schedule"),
            "notice_cannot_establish_general_weekday_baseline",
        )
        _semantics(
            packet.axis, _BASELINES[baseline.name][1], _span(packet.original_bytes, baseline.span)
        )
    _check(bool(packet.facts) or baseline is not None, "source_packet_has_no_reviewed_claims")
    digest = _hash(
        (
            "reviewed-replay-schedule-packet-v1",
            packet.notice_id,
            packet.axis,
            packet.kind,
            packet.representation,
            packet.source_url,
            packet.original_sha256,
            packet.retained_receipt_sha256,
            packet.requested_at,
            packet.received_at,
            packet.coverage_start,
            packet.coverage_end,
            tuple(sorted(packet.facts, key=lambda f: f.day)),
            baseline,
            packet.http_status,
        )
    )
    return ReplayPacketBinding(
        digest,
        packet.notice_id,
        packet.axis,
        packet.kind,
        packet.representation,
        packet.original_sha256,
        packet.retained_receipt_sha256,
        packet.source_url,
        packet.requested_at,
        packet.received_at,
        packet.coverage_start,
        packet.coverage_end,
    )


def _native(calendar: StockDailyCalendar) -> None:
    _check(type(calendar) is StockDailyCalendar, "typed_native_calendar_required")
    rebuilt = parse_stock_daily_calendar(
        calendar.original_content_json,
        expected_sha256=calendar.content_sha256,
        received_at=calendar.received_at,
        market_timezone=calendar.market_timezone,
    )
    _check(_same(calendar, rebuilt), "native_calendar_revalidation_failed")
    _check(
        len(calendar.sessions) == 706
        and calendar.sessions[0].session_date == _FIRST
        and calendar.sessions[-1].session_date == _LAST_PRICE
        and calendar.sessions[200].session_date == date(2024, 10, 17),
        "fixed_native706_window_required",
    )


# candidate = (priority, status, provenance basis, compact packet hash)
Candidate = tuple[int, str, str, str]


def _selected(day: date, candidates: list[Candidate]) -> ReplayScheduleDay:
    if not candidates:
        return ReplayScheduleDay(day, "unknown", "unknown", ())
    priority = max(c[0] for c in candidates)
    chosen = [c for c in candidates if c[0] == priority]
    statuses = {c[1] for c in chosen}
    hashes = tuple(sorted({c[3] for c in chosen}))
    overridden = tuple(sorted({c[3] for c in candidates if c[0] < priority} - set(hashes)))
    if len(statuses) != 1:
        return ReplayScheduleDay(day, "conflicting", "conflict", hashes, overridden)
    basis: Literal["modeled_weekday", "source_transcription"] = (
        "modeled_weekday"
        if all(c[2] == "modeled_weekday" for c in chosen)
        else "source_transcription"
    )
    return ReplayScheduleDay(day, chosen[0][1], basis, hashes, overridden)


def _assess(
    calendar: StockDailyCalendar,
    packets: tuple[ReplayScheduleSourcePacket, ...],
    rule: RetrospectiveScheduleRule,
) -> dict[str, object]:
    _native(calendar)
    _check(
        type(rule) is RetrospectiveScheduleRule and _same(rule, RetrospectiveScheduleRule()),
        "fixed_finite_schedule_rule_required",
    )
    _check(type(packets) is tuple and len(packets) <= 64, "bounded_immutable_packets_required")
    bound: dict[str, tuple[ReplayScheduleSourcePacket, ReplayPacketBinding]] = {}
    identities: dict[tuple[str, str], str] = {}
    for packet in packets:
        binding = _packet(packet)
        key = (packet.axis, packet.notice_id)
        _check(
            key not in identities or identities[key] == binding.packet_sha256,
            "conflicting_notice_source",
        )
        identities[key] = binding.packet_sha256
        bound[binding.packet_sha256] = (packet, binding)
    ordered = tuple(
        sorted(bound.values(), key=lambda p: (p[1].axis, p[1].notice_id, p[1].packet_sha256))
    )
    dates = tuple(_FIRST + timedelta(days=i) for i in range((_END - _FIRST).days + 1))
    candidates: dict[str, dict[date, list[Candidate]]] = {axis: {} for axis in _STATUSES}
    for packet, binding in ordered:
        table = candidates[packet.axis]
        baseline = packet.weekday_baseline
        if baseline is not None:
            _, weekday, weekend = _BASELINES[baseline.name]
            first, last = max(_FIRST, packet.coverage_start), min(_END, packet.coverage_end)
            day = first
            while day <= last:
                table.setdefault(day, []).append(
                    (
                        0,
                        weekday if day.weekday() < 5 else weekend,
                        "modeled_weekday",
                        binding.packet_sha256,
                    )
                )
                day += timedelta(days=1)
        for fact in packet.facts:
            if _FIRST <= fact.day <= _END:
                table.setdefault(fact.day, []).append(
                    (
                        _KINDS[packet.kind][1],
                        fact.status,
                        "source_transcription",
                        binding.packet_sha256,
                    )
                )
    native_by_date = {s.session_date: s for s in calendar.sessions}
    market: list[ReplayScheduleDay] = []
    sessions = [
        CalendarSession(i, s.opens_at, s.closes_at) for i, s in enumerate(calendar.sessions)
    ]
    conflict = False
    padding_missing = False
    for day in dates:
        available = candidates["market"].get(day, [])
        chosen = _selected(day, available)
        if day <= _LAST_PRICE:
            native_session = native_by_date.get(day)
            native_status = "open" if native_session is not None else "closed"
            contradicts = any(
                c[0] > 0 and c[1] not in (native_status, "unknown") for c in available
            )
            if contradicts:
                conflict = True
                market.append(
                    ReplayScheduleDay(
                        day,
                        "conflicting",
                        "conflict",
                        tuple(
                            sorted(
                                {calendar.content_sha256, *(c[3] for c in available if c[0] > 0)}
                            )
                        ),
                    )
                )
            else:
                market.append(
                    ReplayScheduleDay(
                        day,
                        native_status,
                        "native_calendar",
                        (calendar.content_sha256,),
                        opens_at=None if native_session is None else native_session.opens_at,
                        closes_at=None if native_session is None else native_session.closes_at,
                    )
                )
        elif chosen.status == "open":
            opening = datetime.combine(day, time(9, 30), _NY).astimezone(UTC)
            closing = datetime.combine(day, time(16), _NY).astimezone(UTC)
            market.append(
                ReplayScheduleDay(
                    day,
                    chosen.status,
                    chosen.basis,
                    chosen.packet_hashes,
                    chosen.overridden_packet_hashes,
                    opening,
                    closing,
                )
            )
            sessions.append(CalendarSession(len(sessions), opening, closing))
        else:
            market.append(chosen)
            padding_missing = padding_missing or chosen.status in ("unknown", "conflicting")
    cns = tuple(_selected(d, candidates["cns"].get(d, [])) for d in dates)
    funding = tuple(_selected(d, candidates["dividend_funding"].get(d, [])) for d in dates)
    reasons = tuple(
        reason
        for reason, present in (
            ("native_market_conflict", conflict),
            ("market_padding_incomplete", padding_missing),
        )
        if present
    )
    limitations: tuple[str, ...] = _LIMITATIONS
    if any(b.requested_at is None or b.received_at is None for _, b in ordered):
        limitations = (*limitations, "source_capture_clocks_missing")
    bindings = tuple(b for _, b in ordered)
    graph_hash = _hash(
        (
            "finite-replay-schedule-source-v1",
            calendar.content_sha256,
            calendar.received_at,
            calendar.request_start,
            calendar.request_end,
            calendar.market_timezone,
            bindings,
            rule,
        )
    )
    table_hash = _hash(
        (
            "conditional-retrospective-schedule-v1",
            graph_hash,
            tuple(sessions),
            tuple(market),
            cns,
            funding,
            reasons,
            limitations,
        )
    )
    return {
        "source_packets": tuple(p for p, _ in ordered),
        "packet_bindings": bindings,
        "source_graph_sha256": graph_hash,
        "market_sessions": tuple(sessions),
        "market_days": tuple(market),
        "cns_days": cns,
        "dividend_funding_days": funding,
        "reason_codes": reasons,
        "status": "unavailable" if reasons else "conditionally_prepared",
        "limitations": limitations,
        "_evidence_hash": table_hash,
        "_query_proofs": tuple(
            tuple(_hash(row) for row in table) for table in (market, cns, funding)
        ),
        "_native_trade_dates": tuple(s.session_date for s in calendar.sessions),
        "_native_trade_proofs": tuple(
            _hash(
                (
                    "native-trade-index-v1",
                    i,
                    s.session_date,
                    _hash(market[(s.session_date - _FIRST).days]),
                )
            )
            for i, s in enumerate(calendar.sessions)
        ),
    }


def prepare_retrospective_replay_schedule(
    native_calendar: StockDailyCalendar,
    *,
    source_packets: tuple[ReplayScheduleSourcePacket, ...],
    rule: RetrospectiveScheduleRule,
) -> RetrospectiveReplaySchedule:
    """Validate originals once per invocation; compile finite conditional day tables."""
    try:
        return RetrospectiveReplaySchedule(native_calendar, source_packets, rule)
    except (
        ValueError,
        TypeError,
        AttributeError,
        ArithmeticError,
        KeyError,
        RecursionError,
    ) as error:
        if isinstance(error, ReplayScheduleError):
            raise
        raise ReplayScheduleError() from None


def _scope(value: RetrospectiveReplaySchedule) -> None:
    _check(
        type(value) is RetrospectiveReplaySchedule
        and value.source_profile == "conditional_retrospective_schedule_v1"
        and value.price_session_count == 706
        and value.padding_has_prices
        is value.complete_service_coverage
        is value.qualified
        is value.source_qualified
        is value.strategy_qualified
        is value.full_task5_complete
        is value.authenticated
        is value.investment_eligible
        is value.trading_enabled
        is value.live_authorized
        is False,
        "unqualified_schedule_scope_required",
    )


def revalidate_replay_schedule(value: RetrospectiveReplaySchedule) -> RetrospectiveReplaySchedule:
    """Fresh source-bound reconstruction at a consumer boundary, without a cache."""
    _scope(value)
    rebuilt = prepare_retrospective_replay_schedule(
        value.native_calendar, source_packets=value.source_packets, rule=value.rule
    )
    _check(_same(value, rebuilt), "derived_schedule_revalidation_failed")
    return rebuilt


def _query_row(value: RetrospectiveReplaySchedule, axis: int, index: int) -> ReplayScheduleDay:
    table = (
        value.market_days
        if axis == 0
        else value.cns_days
        if axis == 1
        else value.dividend_funding_days
    )
    _check(
        type(value._query_proofs) is tuple and len(value._query_proofs) == 3, "query_proof_invalid"
    )
    _check(
        type(table) is tuple and type(value._query_proofs[axis]) is tuple,
        "query_table_shape_invalid",
    )
    _check(
        0 <= index < len(table) and index < len(value._query_proofs[axis]),
        "query_day_outside_schedule",
    )
    row = table[index]
    _check(
        type(row) is ReplayScheduleDay
        and row.day == _FIRST + timedelta(days=index)
        and _hash(row) == value._query_proofs[axis][index],
        "derived_schedule_day_changed",
    )
    return row


def _next_open(
    value: RetrospectiveReplaySchedule, after: date
) -> tuple[datetime | None, str | None]:
    if after < _FIRST or after >= _END:
        return None, "market_candidate_outside_schedule"
    offset = (after - _FIRST).days + 1
    for index in range(offset, len(value.market_days)):
        row = _query_row(value, 0, index)
        if row.status in ("unknown", "conflicting"):
            return None, "market_candidate_unknown"
        if row.status == "open":
            return row.opens_at, None
    return None, "market_candidate_outside_schedule"


def modeled_settlement_availability(
    value: RetrospectiveReplaySchedule, *, trade_session_index: int
) -> ReplaySettlementAvailability:
    """Query compiled tables; consumers freshly revalidate once before a replay.

    This helper does not repeatedly rehash retained sources for every order. Only
    native executable rows200..705 are eligible; padding cannot create trades.
    """
    _scope(value)
    _check(
        type(trade_session_index) is int and 200 <= trade_session_index < 706,
        "native_executable_trade_session_required",
    )
    _check(
        type(value._native_trade_dates) is tuple and len(value._native_trade_dates) == 706,
        "query_trade_dates_invalid",
    )
    _check(
        type(value._native_trade_proofs) is tuple and len(value._native_trade_proofs) == 706,
        "query_trade_proofs_invalid",
    )
    trade_day = value._native_trade_dates[trade_session_index]
    _day(trade_day)
    _check(_FIRST <= trade_day <= _LAST_PRICE, "query_trade_date_outside_native_window")
    market_row = _query_row(value, 0, (trade_day - _FIRST).days)
    _check(
        market_row.status == "open"
        and _hash(("native-trade-index-v1", trade_session_index, trade_day, _hash(market_row)))
        == value._native_trade_proofs[trade_session_index],
        "native_trade_index_binding_changed",
    )
    for index in range((trade_day - _FIRST).days + 1, len(value.cns_days)):
        row = _query_row(value, 1, index)
        if row.status in ("limited", "unknown", "conflicting"):
            return ReplaySettlementAvailability(trade_session_index, None, None, "cns_day_unknown")
        if row.status == "ordinary_supported":
            available, reason = _next_open(value, row.day)
            return ReplaySettlementAvailability(trade_session_index, row.day, available, reason)
    return ReplaySettlementAvailability(
        trade_session_index, None, None, "settlement_outside_schedule"
    )


def modeled_dividend_availability(
    value: RetrospectiveReplaySchedule, *, pay_date: date | None
) -> datetime | None:
    """Require explicit independent funding on native pay date and exact candidate."""
    _scope(value)
    if pay_date is None:
        return None
    _day(pay_date)
    candidate, _ = _next_open(value, pay_date)
    if candidate is None:
        return None
    paid = _query_row(value, 2, (pay_date - _FIRST).days)
    following = _query_row(value, 2, (candidate.astimezone(_NY).date() - _FIRST).days)
    if paid.status != "supported" or following.status != "supported":
        return None
    return candidate
