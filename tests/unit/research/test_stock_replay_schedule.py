"""Fictional retained calendar packets; no provider observations or economic outcomes."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from trading_bot.market_data.stock_daily_series import parse_stock_daily_calendar

MODULE = "trading_bot.research.stock_replay_schedule"
CAPTURE = datetime(2026, 10, 26, 12, tzinfo=UTC)
# These dates construct a fictional full-shape native calendar, never provider evidence.
CLOSED = {
    "2024-01-15",
    "2024-02-19",
    "2024-03-29",
    "2024-05-27",
    "2024-06-19",
    "2024-07-04",
    "2024-09-02",
    "2024-11-28",
    "2024-12-25",
    "2025-01-01",
    "2025-01-09",
    "2025-01-20",
    "2025-02-17",
    "2025-04-18",
    "2025-05-26",
    "2025-06-19",
    "2025-07-04",
    "2025-09-01",
    "2025-11-27",
    "2025-12-25",
    "2026-01-01",
    "2026-01-19",
    "2026-02-16",
    "2026-04-03",
    "2026-05-25",
    "2026-06-19",
    "2026-07-03",
    "2026-09-07",
}


class _Module:
    def __getattr__(self, name):
        assert importlib.util.find_spec(MODULE) is not None, (
            "finite replay schedule module is missing"
        )
        return getattr(importlib.import_module(MODULE), name)


@pytest.fixture
def m():
    return _Module()


@pytest.fixture
def native():
    day = date(2024, 1, 2)
    rows = []
    while day <= date(2026, 10, 23):
        if day.weekday() < 5 and day.isoformat() not in CLOSED:
            rows.append({"date": str(day), "open": f"{day}T09:30:00", "close": f"{day}T16:00:00"})
        day += timedelta(days=1)
    assert len(rows) == 706 and rows[200]["date"] == "2024-10-17"
    body = json.dumps(
        {"request": {"start_date": "2024-01-02", "end_date": "2026-10-23"}, "calendar": rows}
    ).encode()
    return parse_stock_daily_calendar(
        body,
        expected_sha256=hashlib.sha256(body).hexdigest(),
        received_at=CAPTURE,
        market_timezone="America/New_York",
    )


def packet(
    m,
    axis="market",
    *,
    facts=(),
    baseline=True,
    label="fictional-2026",
    start=date(2026, 1, 1),
    end=date(2026, 12, 31),
    kind=None,
    representation="original_body",
    missing_clocks=False,
    http_status=200,
):
    kinds = {
        "market": "exchange_calendar",
        "cns": "ordinary_cns_calendar",
        "dividend_funding": "dividend_funding_schedule",
    }
    names = {
        "market": "market_regular_weekdays_v1",
        "cns": "ordinary_cns_weekdays_v1",
        "dividend_funding": "dividend_funding_weekdays_v1",
    }
    # Each claim is bound to its own exact UTF-8 byte span in the complete fictional body.
    body = f"FICTIONAL RETAINED PACKET {label}\n".encode()
    baseline_text = {
        "market": b"Regular exchange market sessions follow the stated weekdays and holidays.\n",
        "cns": b"Ordinary CNS settlement follows the stated weekdays and holidays.\n",
        "dividend_funding": (
            b"Scheduled dividend payments are allocated on the stated funding weekdays.\n"
        ),
    }[axis]
    lo = len(body)
    body += baseline_text
    baseline_value = (
        m.ReplayWeekdayBaseline(names[axis], m.ReplaySourceSpan(lo, len(body)))
        if baseline
        else None
    )
    built = []
    for day, status in facts:
        line = f"{day} {axis} {status}: reviewed fictional source statement.\n".encode()
        lo = len(body)
        body += line
        built.append(m.ReplayScheduleDayFact(day, status, m.ReplaySourceSpan(lo, len(body))))
    return m.ReplayScheduleSourcePacket(
        notice_id=label,
        axis=axis,
        kind=kind or kinds[axis],
        representation=representation,
        source_url="https://www.nasdaqtrader.com/Trader.aspx?id=Calendar"
        if axis == "market"
        else "https://www.dtcc.com/example/fictional-notice",
        original_bytes=body,
        original_sha256=hashlib.sha256(body).hexdigest(),
        requested_at=None if missing_clocks else CAPTURE - timedelta(seconds=1),
        received_at=None if missing_clocks else CAPTURE,
        coverage_start=start,
        coverage_end=end,
        facts=tuple(built),
        weekday_baseline=baseline_value,
        http_status=http_status,
    )


def prepare(m, native, *packets):
    return m.prepare_retrospective_replay_schedule(
        native, source_packets=tuple(packets), rule=m.RetrospectiveScheduleRule()
    )


def row(result, axis, day):
    return next(x for x in getattr(result, f"{axis}_days") if x.day == day)


def test_native706_prefix_and_fourteen_schedule_only_padding_sessions(m, native):
    result = prepare(m, native, packet(m))
    assert result.status == "conditionally_prepared"
    assert len(result.market_sessions) == 720
    assert tuple((s.opens_at, s.closes_at) for s in result.market_sessions[:706]) == tuple(
        (s.opens_at, s.closes_at) for s in native.sessions
    )
    assert result.market_sessions[706].opens_at == datetime(2026, 10, 26, 13, 30, tzinfo=UTC)
    assert result.market_sessions[-1].opens_at == datetime(2026, 11, 12, 14, 30, tzinfo=UTC)
    assert result.price_session_count == 706 and result.padding_has_prices is False
    assert not hasattr(result.market_sessions[706], "price")


def test_dst_padding_uses_new_york_schedule_instants(m, native):
    result = prepare(m, native, packet(m))
    nov2 = next(s for s in result.market_sessions if s.opens_at.date() == date(2026, 11, 2))
    assert nov2.opens_at == datetime(2026, 11, 2, 14, 30, tzinfo=UTC)
    assert nov2.closes_at == datetime(2026, 11, 2, 21, tzinfo=UTC)


def test_no_packet_does_not_invent_clear_padding_or_dividend_funding(m, native):
    result = prepare(m, native)
    assert result.status == "unavailable"
    assert result.reason_codes == ("market_padding_incomplete",)
    assert row(result, "market", date(2026, 10, 26)).status == "unknown"
    assert row(result, "dividend_funding", date(2026, 10, 26)).status == "unknown"
    assert len(result.market_sessions) == 706


def test_market_unknown_before_known_open_blocks_exact_candidate(m, native):
    p = packet(m, facts=((date(2026, 10, 27), "open"),), baseline=False)
    result = prepare(m, native, p, packet(m, "cns"))
    # Last native trade settles Monday26, but Tuesday27 is known; Monday is not relevant
    # to the strict-after candidate, while an unknown Wednesday must not be skipped.
    assert m.modeled_settlement_availability(
        result, trade_session_index=705
    ).available_at == datetime(2026, 10, 27, 13, 30, tzinfo=UTC)
    assert m.modeled_dividend_availability(result, pay_date=date(2026, 10, 27)) is None


def test_unknown_market_day_before_later_supported_candidate_is_not_skipped(m, native):
    p = packet(m, facts=((date(2026, 10, 28), "open"),), baseline=False)
    result = prepare(m, native, p, packet(m, "cns"))
    value = m.modeled_settlement_availability(result, trade_session_index=705)
    assert value.settlement_date == date(2026, 10, 26)
    assert value.available_at is None and value.reason == "market_candidate_unknown"


def test_january9_exchange_closure_does_not_disable_settlement(m, native):
    p = packet(m, "cns", start=date(2025, 1, 1), end=date(2025, 12, 31))
    result = prepare(m, native, packet(m), p)
    index = next(i for i, s in enumerate(native.sessions) if s.session_date == date(2025, 1, 8))
    value = m.modeled_settlement_availability(result, trade_session_index=index)
    assert row(result, "market", date(2025, 1, 9)).status == "closed"
    assert value.settlement_date == date(2025, 1, 9)
    assert value.available_at == datetime(2025, 1, 10, 14, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "holiday,trade,settles,available",
    [
        (
            date(2025, 10, 13),
            date(2025, 10, 10),
            date(2025, 10, 14),
            datetime(2025, 10, 15, 13, 30, tzinfo=UTC),
        ),
        (
            date(2026, 11, 11),
            date(2026, 10, 23),
            date(2026, 10, 26),
            datetime(2026, 10, 27, 13, 30, tzinfo=UTC),
        ),
    ],
)
def test_exchange_open_no_cns_holidays_have_independent_axis(
    m, native, holiday, trade, settles, available
):
    p = packet(
        m, "cns", facts=((holiday, "closed"),), start=date(2025, 1, 1), end=date(2026, 12, 31)
    )
    result = prepare(m, native, packet(m), p)
    assert row(result, "market", holiday).status == "open"
    assert row(result, "cns", holiday).status == "closed"
    index = next(i for i, s in enumerate(native.sessions) if s.session_date == trade)
    value = m.modeled_settlement_availability(result, trade_session_index=index)
    assert value.settlement_date == settles and value.available_at == available


def test_limited_service_day_blocks_settlement_until_service_specific_notice(m, native):
    annual = packet(
        m,
        "cns",
        facts=((date(2025, 4, 18), "limited"),),
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
    )
    result = prepare(m, native, packet(m), annual)
    index = next(i for i, s in enumerate(native.sessions) if s.session_date == date(2025, 4, 17))
    assert (
        m.modeled_settlement_availability(result, trade_session_index=index).reason
        == "cns_day_unknown"
    )
    notice = packet(
        m,
        "cns",
        facts=((date(2025, 4, 18), "closed"),),
        baseline=False,
        label="fictional-good-friday",
        kind="ordinary_cns_notice",
        start=date(2025, 4, 18),
        end=date(2025, 4, 18),
    )
    corrected = prepare(m, native, packet(m), annual, notice)
    value = m.modeled_settlement_availability(corrected, trade_session_index=index)
    assert value.settlement_date == date(2025, 4, 21)
    assert value.available_at == datetime(2025, 4, 22, 13, 30, tzinfo=UTC)
    assert row(corrected, "cns", date(2025, 4, 18)).overridden_packet_hashes


def test_july3_dividend_funding_does_not_inherit_cns_closure(m, native):
    cns = packet(m, "cns", facts=((date(2026, 7, 3), "closed"),))
    fund = packet(
        m,
        "dividend_funding",
        facts=((date(2026, 7, 3), "supported"), (date(2026, 7, 6), "supported")),
        baseline=False,
    )
    result = prepare(m, native, packet(m), cns, fund)
    assert row(result, "cns", date(2026, 7, 3)).status == "closed"
    assert row(result, "dividend_funding", date(2026, 7, 3)).status == "supported"
    assert m.modeled_dividend_availability(result, pay_date=date(2026, 7, 3)) == datetime(
        2026, 7, 6, 13, 30, tzinfo=UTC
    )
    without = prepare(m, native, packet(m), cns)
    assert m.modeled_dividend_availability(without, pay_date=date(2026, 7, 3)) is None


def test_posthorizon_native_pay_candidate_is_exact_not_later_cns_open(m, native):
    cns = packet(m, "cns", facts=((date(2026, 11, 11), "closed"),))
    fund = packet(
        m,
        "dividend_funding",
        facts=((date(2026, 11, 10), "supported"), (date(2026, 11, 12), "supported")),
        baseline=False,
    )
    result = prepare(m, native, packet(m), cns, fund)
    assert m.modeled_dividend_availability(result, pay_date=date(2026, 11, 10)) is None
    full = packet(
        m,
        "dividend_funding",
        facts=((date(2026, 11, 10), "supported"), (date(2026, 11, 11), "supported")),
        baseline=False,
    )
    assert m.modeled_dividend_availability(
        prepare(m, native, packet(m), cns, full), pay_date=date(2026, 11, 10)
    ) == datetime(2026, 11, 11, 14, 30, tzinfo=UTC)


def test_unknown_cns_day_is_not_skipped_for_later_clear_day(m, native):
    cns = packet(m, "cns", facts=((date(2026, 10, 27), "ordinary_supported"),), baseline=False)
    result = prepare(m, native, packet(m), cns)
    value = m.modeled_settlement_availability(result, trade_session_index=705)
    assert value.settlement_date is None and value.reason == "cns_day_unknown"


def test_conflicting_equal_specificity_facts_are_not_ordered_by_notice_id(m, native):
    a = packet(
        m, facts=((date(2026, 10, 27), "open"),), baseline=False, label="a", kind="market_notice"
    )
    b = packet(
        m, facts=((date(2026, 10, 27), "closed"),), baseline=False, label="z", kind="market_notice"
    )
    result = prepare(m, native, packet(m), a, b, packet(m, "cns"))
    assert row(result, "market", date(2026, 10, 27)).status == "conflicting"
    assert (
        m.modeled_settlement_availability(result, trade_session_index=705).reason
        == "market_candidate_unknown"
    )
    assert (
        result.evidence_hash == prepare(m, native, b, packet(m, "cns"), a, packet(m)).evidence_hash
    )


def test_native_market_contradiction_cannot_rewrite_native_prefix(m, native):
    bad = packet(m, facts=((date(2026, 10, 23), "closed"),))
    result = prepare(m, native, bad)
    assert result.status == "unavailable" and "native_market_conflict" in result.reason_codes
    assert len(result.market_sessions[:706]) == 706
    assert result.market_sessions[705].opens_at == native.sessions[705].opens_at


def test_exact_duplicate_packets_dedupe_without_changing_evidence(m, native):
    p = packet(m)
    a = prepare(m, native, p)
    b = prepare(m, native, p, p)
    assert a.evidence_hash == b.evidence_hash and len(b.packet_bindings) == 1


def test_missing_capture_clocks_stay_missing_and_not_saved_time(m, native):
    p = packet(m, missing_clocks=True, representation="indexed_primary_receipt", http_status=None)
    result = prepare(m, native, p)
    assert result.packet_bindings[0].requested_at is None
    assert result.packet_bindings[0].received_at is None
    assert "source_capture_clocks_missing" in result.limitations
    assert row(result, "market", date(2026, 10, 26)).basis == "modeled_weekday"
    assert result.packet_bindings[0].representation == "indexed_primary_receipt"


@pytest.mark.parametrize("status", [403, 404, 500, None, True])
def test_failed_or_unverified_original_http_body_cannot_support_service(m, native, status):
    p = packet(m, http_status=status)
    with pytest.raises(ValueError):
        prepare(m, native, p)


def test_error_body_cannot_be_rebranded_as_successful_notice(m, native):
    p = packet(m)
    body = b"<html><title>404 Not Found</title></html>" + p.original_bytes
    p = replace(p, original_bytes=body, original_sha256=hashlib.sha256(body).hexdigest())
    with pytest.raises(ValueError):
        prepare(m, native, p)


@pytest.mark.parametrize(
    "change",
    [
        {"original_sha256": "0" * 64},
        {"received_at": CAPTURE - timedelta(seconds=2)},
        {"requested_at": datetime(2026, 1, 1)},
        {"received_at": datetime(2026, 1, 1)},
        {"coverage_start": datetime(2026, 1, 1, tzinfo=UTC)},
        {"coverage_end": date(2025, 1, 1)},
        {"source_url": "https://untrusted.example/Calendar"},
        {"axis": "dividend_funding"},
        {"representation": "unknown"},
        {"facts": []},
    ],
)
def test_packet_mutations_fail_closed(m, native, change):
    p = replace(packet(m), **change)
    with pytest.raises(ValueError):
        prepare(m, native, p)


@pytest.mark.parametrize("span", [(-1, 20), (1, 1), (0, 100000), (True, 2)])
def test_fact_requires_real_exact_retained_source_span(m, native, span):
    p = packet(m, facts=((date(2026, 10, 27), "closed"),))
    bad = replace(p.facts[0], span=m.ReplaySourceSpan(*span))
    with pytest.raises(ValueError):
        prepare(m, native, replace(p, facts=(bad,)))


def test_fact_cannot_be_outside_source_coverage_or_cross_axis(m, native):
    p = packet(m, facts=((date(2026, 10, 27), "supported"),))
    with pytest.raises(ValueError):
        prepare(m, native, p)
    p = packet(m, facts=((date(2025, 10, 27), "closed"),))
    with pytest.raises(ValueError):
        prepare(m, native, p)


def test_source_span_and_complete_body_are_both_evidence_bound(m, native):
    p = packet(m)
    before = prepare(m, native, p)
    body = p.original_bytes + b"Unrelated retained source footnote.\n"
    after = prepare(
        m, native, replace(p, original_bytes=body, original_sha256=hashlib.sha256(body).hexdigest())
    )
    assert before.evidence_hash != after.evidence_hash
    assert (
        row(before, "market", date(2026, 10, 26)).packet_hashes
        != row(after, "market", date(2026, 10, 26)).packet_hashes
    )


def test_native_calendar_reparsed_and_derived_clock_tamper_rejected(m, native):
    first = replace(native.sessions[0], opens_at=native.sessions[0].opens_at + timedelta(minutes=1))
    changed = replace(native, sessions=(first, *native.sessions[1:]))
    with pytest.raises(ValueError):
        prepare(m, changed, packet(m))


def test_short_or_shifted_native_price_calendar_is_rejected(m, native):
    with pytest.raises(ValueError):
        prepare(m, replace(native, sessions=native.sessions[:-1]), packet(m))


def test_revalidation_rejects_forged_derived_day_history(m, native):
    result = prepare(m, native, packet(m))
    bad = replace(result.cns_days[0], status="ordinary_supported")
    object.__setattr__(result, "cns_days", (bad, *result.cns_days[1:]))
    with pytest.raises(ValueError):
        m.revalidate_replay_schedule(result)
    with pytest.raises(ValueError):
        _ = result.evidence_hash


@pytest.mark.parametrize(
    "flag",
    [
        "qualified",
        "source_qualified",
        "investment_eligible",
        "trading_enabled",
        "live_authorized",
        "complete_service_coverage",
    ],
)
def test_no_schedule_can_acquire_execution_or_full_source_authority(m, native, flag):
    result = prepare(m, native, packet(m))
    assert getattr(result, flag) is False
    with pytest.raises((ValueError, TypeError)):
        replace(result, **{flag: True})
    object.__setattr__(result, flag, True)
    with pytest.raises(ValueError):
        m.revalidate_replay_schedule(result)


@pytest.mark.parametrize("index", [199, 706, -1, True])
def test_only_actual_native_executable_trade_rows_have_settlement_queries(m, native, index):
    result = prepare(m, native, packet(m), packet(m, "cns"))
    with pytest.raises(ValueError):
        m.modeled_settlement_availability(result, trade_session_index=index)


def test_calendar_end_never_invents_2027_or_later_funding(m, native):
    result = prepare(m, native, packet(m), packet(m, "dividend_funding"))
    assert result.market_days[-1].day == date(2026, 11, 12)
    assert m.modeled_dividend_availability(result, pay_date=date(2026, 11, 12)) is None
    assert m.modeled_dividend_availability(result, pay_date=None) is None


def test_query_rejects_mutated_compact_day_without_rehashing_sources(m, native):
    result = prepare(m, native, packet(m), packet(m, "cns"))
    day = date(2026, 10, 26)
    at = next(i for i, x in enumerate(result.cns_days) if x.day == day)
    changed = replace(result.cns_days[at], status="closed")
    object.__setattr__(
        result, "cns_days", (*result.cns_days[:at], changed, *result.cns_days[at + 1 :])
    )
    with pytest.raises(ValueError):
        m.modeled_settlement_availability(result, trade_session_index=705)


def test_rendered_receipt_and_partial_missing_clock_are_retained(m, native):
    p = packet(m, representation="rendered_primary_receipt", http_status=None)
    p = replace(p, received_at=None, retained_receipt_sha256="1" * 64)
    result = prepare(m, native, p)
    binding = result.packet_bindings[0]
    assert binding.representation == "rendered_primary_receipt"
    assert binding.requested_at == CAPTURE - timedelta(seconds=1) and binding.received_at is None
    assert binding.retained_receipt_sha256 == "1" * 64


def test_facility_or_cns_span_cannot_become_dividend_funding_support(m, native):
    p = packet(m, "cns")
    disguised = replace(
        p,
        axis="dividend_funding",
        kind="dividend_funding_schedule",
        weekday_baseline=m.ReplayWeekdayBaseline(
            "dividend_funding_weekdays_v1", p.weekday_baseline.span
        ),
    )
    with pytest.raises(ValueError, match="dividend"):
        prepare(m, native, disguised)


@pytest.mark.parametrize("flag", ["strategy_qualified", "full_task5_complete", "authenticated"])
def test_no_additional_qualification_authority(m, native, flag):
    result = prepare(m, native, packet(m))
    assert getattr(result, flag) is False
    object.__setattr__(result, flag, True)
    with pytest.raises(ValueError):
        m.revalidate_replay_schedule(result)


def test_utf8_source_remains_valid_when_error_scan_boundary_splits_character(m, native):
    p = packet(m)
    body = (
        p.original_bytes + b"x" * (8191 - len(p.original_bytes)) + "€".encode() + b" retained tail"
    )
    result = prepare(
        m, native, replace(p, original_bytes=body, original_sha256=hashlib.sha256(body).hexdigest())
    )
    assert result.status == "conditionally_prepared"


def test_full_source_hashing_is_once_per_preparation_not_per_day_or_query(m, native, monkeypatch):
    p, c = packet(m), packet(m, "cns")
    bodies = {p.original_bytes, c.original_bytes}
    original_hash = hashlib.sha256
    calls = []

    def counted(data=b"", **kwargs):
        if data in bodies:
            calls.append(data)
        return original_hash(data, **kwargs)

    monkeypatch.setattr(hashlib, "sha256", counted)
    result = prepare(m, native, p, c)
    assert len(calls) == 2
    for _ in range(20):
        assert m.modeled_settlement_availability(
            result, trade_session_index=705
        ).available_at == datetime(2026, 10, 27, 13, 30, tzinfo=UTC)
    assert len(calls) == 2


def test_conflicting_same_notice_bytes_are_rejected_not_vintage_sorted(m, native):
    a = packet(m)
    body = a.original_bytes + b" Conflicting later copy."
    b = replace(a, original_bytes=body, original_sha256=hashlib.sha256(body).hexdigest())
    with pytest.raises(ValueError, match="conflicting_notice"):
        prepare(m, native, a, b)


@pytest.mark.parametrize(
    "wrong",
    [
        date(2026, 10, 22),
        date(2026, 10, 21),
        "2026-10-23",
        datetime(2026, 10, 23, tzinfo=UTC),
        True,
        None,
    ],
)
def test_cached_trade_date_cannot_accelerate_or_retype_native_session(m, native, wrong):
    result = prepare(m, native, packet(m), packet(m, "cns"))
    object.__setattr__(result, "_native_trade_dates", (*result._native_trade_dates[:-1], wrong))
    with pytest.raises(ValueError):
        m.modeled_settlement_availability(result, trade_session_index=705)


def test_cached_native_trade_dates_cannot_be_reordered(m, native):
    result = prepare(m, native, packet(m), packet(m, "cns"))
    dates = result._native_trade_dates
    object.__setattr__(result, "_native_trade_dates", (*dates[:-2], dates[-1], dates[-2]))
    with pytest.raises(ValueError):
        m.modeled_settlement_availability(result, trade_session_index=705)


def test_cached_native_trade_dates_cannot_be_replaced_by_foreign_panel(m, native):
    result = prepare(m, native, packet(m), packet(m, "cns"))
    object.__setattr__(result, "_native_trade_dates", tuple(date(2026, 10, 22) for _ in range(706)))
    with pytest.raises(ValueError):
        m.modeled_settlement_availability(result, trade_session_index=705)


def test_native_index_proof_cannot_be_reordered_or_replaced(m, native):
    result = prepare(m, native, packet(m), packet(m, "cns"))
    proofs = result._native_trade_proofs
    object.__setattr__(result, "_native_trade_proofs", (*proofs[:-2], proofs[-1], proofs[-2]))
    with pytest.raises(ValueError):
        m.modeled_settlement_availability(result, trade_session_index=705)


def test_other_compact_axes_cannot_be_replaced_by_market_proofs(m, native):
    result = prepare(m, native, packet(m), packet(m, "cns"))
    proofs = result._query_proofs
    object.__setattr__(result, "_query_proofs", (proofs[0], proofs[0], proofs[2]))
    with pytest.raises(ValueError):
        m.modeled_settlement_availability(result, trade_session_index=705)


def test_mutated_unused_calendar_views_do_not_change_owned_query_date(m, native):
    result = prepare(m, native, packet(m), packet(m, "cns"))
    last = result.market_sessions[705]
    early = replace(last, opens_at=last.opens_at - timedelta(days=1))
    object.__setattr__(
        result,
        "market_sessions",
        (*result.market_sessions[:705], early, *result.market_sessions[706:]),
    )
    answer = m.modeled_settlement_availability(result, trade_session_index=705)
    assert answer.settlement_date == date(2026, 10, 26)
    assert answer.available_at == datetime(2026, 10, 27, 13, 30, tzinfo=UTC)
    with pytest.raises(ValueError):
        m.revalidate_replay_schedule(result)
