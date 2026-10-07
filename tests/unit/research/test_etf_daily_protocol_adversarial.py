"""Synthetic boundary attacks cannot alter the daily protocol's denied capabilities."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from tests.unit.research.test_etf_daily_protocol import api, daily_bar, protocol, session_dates
from trading_bot.domain import BarInterval
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import EtfBenchmarkDistribution

D = Decimal
MARKERS = (
    "source_qualified",
    "cost_qualified",
    "execution_enabled",
    "economic_admitted",
    "evidence_promotable",
)


def request():
    p = protocol()
    return api().EtfDailyRequest(p, (daily_bar(p.sessions[0]),), (), D("500"))


def distribution(day=None):
    ex = protocol().sessions[101] if day is None else day
    return EtfBenchmarkDistribution(ex, ex + timedelta(days=7), D(".20"), content_hash("cash"))


@pytest.mark.parametrize("record", ["protocol", "bar", "request"])
@pytest.mark.parametrize("marker", MARKERS)
@pytest.mark.parametrize("value", [True, 0, None, "false"])
def test_direct_revalidation_denies_unsafe_capability_marker_mutation(record, marker, value):
    # Removing exact-false validation would admit claimed capabilities or coerced booleans.
    r = request()
    target = {"protocol": r.protocol, "bar": r.bars[0], "request": r}[record]
    object.__setattr__(target, marker, value)
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        target.__post_init__()


@pytest.mark.parametrize("record", ["protocol", "bar"])
@pytest.mark.parametrize("marker", MARKERS)
def test_request_denies_nested_marker_tampering_instead_of_resetting_it(record, marker):
    # Reconstructing init=False fields must not silently erase the supplied tampering.
    r = request()
    target = r.protocol if record == "protocol" else r.bars[0]
    object.__setattr__(target, marker, True)
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        r.__post_init__()


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocol_id", "qualified-daily-study"),
        ("first_rebalance", date(2016, 5, 27)),
        ("warmup_bars", 99),
        ("warmup_bars", D("100")),
        ("rebalance_sessions", 1),
        ("settlement_sessions", 1),
        ("quantity_increment", D(".01")),
        ("price_increment", D(".01")),
        ("minimum_notional", D("0")),
        ("minimum_notional", 1),
        ("minimum_notional", True),
        ("fractional_terms_verified", True),
        ("limitations", ()),
        ("limitations", ("all_assumptions_verified",)),
        ("limitations", []),
    ],
)
@pytest.mark.parametrize("through_request", [False, True])
def test_fixed_protocol_fields_cannot_be_mutated_or_laundered(field, value, through_request):
    # A mutable protocol identity or erased limitations would misidentify its evidence.
    r = request()
    object.__setattr__(r.protocol, field, value)
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        (r if through_request else r.protocol).__post_init__()


@pytest.mark.parametrize(
    "sessions",
    [
        (),
        session_dates(100),
        list(session_dates()),
        tuple(reversed(session_dates())),
        (*session_dates(), session_dates()[-1]),
        (*session_dates()[:100], *session_dates()[101:]),
        (date(2015, 12, 31), *session_dates()[1:]),
        (*session_dates(), date(2016, 6, 11)),  # Saturday cannot be an eligible session.
        (*session_dates(), date(2024, 1, 2)),
        (datetime(2016, 1, 7, tzinfo=UTC), *session_dates()[1:]),
    ],
)
def test_malformed_or_out_of_scope_session_sequences_deny(sessions):
    # Removing session/order/window/anchor checks changes the preregistered schedule.
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        replace(protocol(), sessions=sessions)


@pytest.mark.parametrize(
    "field,value",
    [
        ("config_hash", "0" * 64),
        ("canonical_config", "{}"),
        ("risk_equity_reference", D("1000")),
        ("holdout_start", datetime(2025, 1, 1, tzinfo=UTC)),
        ("requested_start", datetime(2017, 1, 1, tzinfo=UTC)),
        ("windows", (10, 20)),
        ("symbols", ("QQQ",)),
        ("rebalance_sessions", 1),
        ("execution_enabled", True),
        ("evidence_promotable", True),
    ],
)
def test_study_mismatch_is_not_accepted_as_the_fixed_candidate(field, value):
    # Skipping canonical-study reconstruction would accept a different policy or authority.
    r = request()
    object.__setattr__(r.protocol.study, field, value)
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        r.__post_init__()


@pytest.mark.parametrize(
    "field,value",
    [
        ("open", D("0")),
        ("close", D("NaN")),
        ("high", D("99")),
        ("low", D("101")),
        ("volume", D("-1")),
        ("open", 100),
        ("instrument_id", "QQQ"),
        ("interval", BarInterval.ONE_MINUTE),
        ("interpolated", True),
        ("data_hash", "invalid"),
    ],
)
def test_nested_malformed_raw_prices_and_identity_deny(field, value):
    # Bypassing nested Bar validation would admit fabricated/interpolated or invalid prices.
    r = request()
    object.__setattr__(r.bars[0].raw, field, value)
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        r.__post_init__()


def test_raw_feature_difference_is_denied_even_when_both_bars_are_valid():
    # Accepting two price bases would silently change the fixed signal/execution relationship.
    r = request()
    altered = replace(r.bars[0].feature, close=D("100.10"))
    object.__setattr__(r.bars[0], "feature", altered)
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        r.__post_init__()


@pytest.mark.parametrize("field", ["starts_at", "ends_at"])
def test_bar_session_mismatch_and_non_utc_timestamps_deny(field):
    r = request()
    stamp = getattr(r.bars[0].raw, field) + timedelta(days=1)
    object.__setattr__(r.bars[0].raw, field, stamp)
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        r.__post_init__()


@pytest.mark.parametrize("field", ["starts_at", "ends_at"])
def test_naive_bar_timestamp_cannot_enter_the_request(field):
    r = request()
    object.__setattr__(r.bars[0].raw, field, getattr(r.bars[0].raw, field).replace(tzinfo=None))
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        r.__post_init__()


@pytest.mark.parametrize("basis", ["total-return-adjusted", "split-adjusted", "", None])
def test_unsupported_feature_or_execution_basis_deny(basis):
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        replace(protocol(), price_basis=basis)


def test_unknown_basis_is_retained_without_source_or_economic_admission():
    # Replacing unknown with a supported assumption would conceal missing source knowledge.
    p = replace(protocol(), price_basis="unknown")
    r = api().EtfDailyRequest(p, (daily_bar(p.sessions[0]),), (), D("500"))
    assert r.protocol.price_basis == "unknown"
    for target in (r, r.protocol, r.bars[0]):
        assert all(getattr(target, marker) is False for marker in MARKERS)
    assert "raw_unadjusted_and_no_splits_assumed_not_verified" in p.limitations


@pytest.mark.parametrize(
    "field,value",
    [
        ("cash_per_share", D("NaN")),
        ("cash_per_share", D("-.01")),
        ("cash_per_share", 1),
        ("source_hash", "invalid"),
        ("ex_date", datetime(2016, 5, 27, tzinfo=UTC)),
        ("pay_date", date(2016, 1, 1)),
        ("execution_enabled", True),
        ("evidence_promotable", True),
        ("source_kind", "qualified-market-distribution"),
    ],
)
def test_nested_malformed_distribution_and_claimed_capabilities_deny(field, value):
    # Reconstructing distribution init=False fields must not launder asserted qualification.
    row = distribution()
    object.__setattr__(row, field, value)
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        replace(request(), distributions=(row,))


@pytest.mark.parametrize("conflict", ["identical", "amount", "pay_date", "hash"])
def test_duplicate_distribution_ex_date_denies_identical_and_conflicting_deliveries(conflict):
    # Counting a second ex-date row would double-credit entitlement or hide a revision.
    row = distribution()
    second = {
        "identical": row,
        "amount": replace(row, cash_per_share=D(".21")),
        "pay_date": replace(row, pay_date=row.pay_date + timedelta(days=1)),
        "hash": replace(row, source_hash=content_hash("another-receipt")),
    }[conflict]
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        replace(request(), distributions=(row, second))


@pytest.mark.parametrize("scope", ["pre_study", "holdout", "non_session"])
def test_distribution_entitlement_cannot_use_out_of_scope_ex_dates(scope):
    day = {
        "pre_study": date(2015, 12, 31),
        "holdout": date(2024, 1, 2),
        "non_session": date(2016, 6, 11),
    }[scope]
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        replace(request(), distributions=(distribution(day),))


def test_post_holdout_pay_date_remains_an_unpaid_obligation_not_an_evaluated_outcome():
    # Rejecting/rolling an actual future pay date would lose an explicit unresolved obligation.
    p = protocol()
    row = EtfBenchmarkDistribution(p.sessions[-1], date(2024, 1, 2), D(".20"), content_hash("late"))
    r = replace(request(), distributions=(row,))
    assert r.distributions[0].pay_date == date(2024, 1, 2)
    assert r.evidence_promotable is False and r.economic_admitted is False


def test_unsafely_mutated_holdout_bar_is_denied_at_request_boundary():
    # A nested object mutated after construction must not bypass the holdout wall.
    r = request()
    object.__setattr__(r.bars[0], "session_date", date(2024, 1, 2))
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        r.__post_init__()


@pytest.mark.parametrize("rows", ["duplicate", "reverse", "outside_sessions"])
def test_bar_sequences_cannot_duplicate_reorder_or_add_unregistered_sessions(rows):
    r = request()
    first, second = (daily_bar(day) for day in r.protocol.sessions[:2])
    bars = {
        "duplicate": (first, first),
        "reverse": (second, first),
        "outside_sessions": (daily_bar(date(2016, 12, 30)),),
    }[rows]
    with pytest.raises(ValueError, match=r"^etf_daily_invalid$"):
        replace(r, bars=bars)
