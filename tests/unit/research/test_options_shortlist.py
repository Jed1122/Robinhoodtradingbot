"""Hand-derived policy, chronology and refusal cases for an acquisition universe."""

from dataclasses import replace
from datetime import date, time, timedelta
from decimal import Decimal, localcontext
from itertools import permutations

import pytest

from tests.unit.research._options_shortlist_fixtures import (
    fixture_session,
    imported_case,
    load_shortlist,
    make_case,
)
from trading_bot.domain import CorporateAction, DataHash, InstrumentId
from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.domain.options import ExerciseStyle, OptionContract, OptionKind, SettlementTiming
from trading_bot.market_data.options_records import ChainSnapshot
from trading_bot.market_data.recording import content_hash
from trading_bot.research.options_shortlist_models import ShortlistAction, ShortlistDiscontinuity


def select(case, settings=None):
    from trading_bot.research.options_shortlist import select_options_shortlist

    loaded = load_shortlist()
    return select_options_shortlist(
        case,
        settings=settings or loaded.config.options.research_shortlist,
        config_hash=loaded.config_hash,
        code_hash=DataHash("b" * 64),
        input_hash=content_hash(case),
    )


def rechain(case, definitions):
    chain = next(r for r in case.records if type(r.value) is ChainSnapshot)
    chain = replace(
        chain, value=ChainSnapshot("SPY", tuple(r.value.contract_id for r in definitions))
    )
    return replace(case, records=(*definitions, chain))


@pytest.mark.parametrize(
    "dtes,chosen",
    [
        ((20,), None),
        ((21,), 21),
        ((30,), 30),
        ((45,), 45),
        ((46,), None),
        ((29, 31), 29),
        ((21, 30, 45), 30),
    ],
)
def test_dte_bounds_and_earlier_expiry_tie(dtes, chosen):
    case = make_case(dtes=dtes)
    result = select(case)
    if chosen is None:
        assert result.reasons == ("no_common_eligible_expiry",)
        assert result.candidates == ()
    else:
        assert tuple(c.kind for c in result.candidates) == (OptionKind.CALL, OptionKind.PUT)
        assert {c.expiration for c in result.candidates} == {
            case.current_session.trading_date + timedelta(days=chosen)
        }
        assert [c.strike for c in result.candidates] == [Decimal("99"), Decimal("99")]


@pytest.mark.parametrize("kind", [OptionContract, ChainSnapshot])
def test_future_and_conflicting_future_records_do_not_change_decisions(kind):
    case = make_case()
    row = next(r for r in case.records if type(r.value) is kind)
    later = case.current_session.opens_at + timedelta(minutes=1)
    future = replace(row, event_at=later, available_at=later)
    result = select(
        replace(case, records=(*case.records, future, replace(future, raw_hash="f" * 64)))
    )
    before = select(case)
    assert result.candidates == before.candidates
    assert result.decision_hash == before.decision_hash
    assert result.input_hash != before.input_hash


def test_permutations_and_chain_member_order_do_not_change_decisions():
    case = make_case()
    before = select(case)
    for rows in permutations(case.records):
        after = select(replace(case, records=rows))
        assert after.candidates == before.candidates
        assert after.decision_hash == before.decision_hash
    rows = tuple(
        replace(r, value=replace(r.value, contract_ids=tuple(reversed(r.value.contract_ids))))
        if type(r.value) is ChainSnapshot
        else r
        for r in case.records
    )
    assert select(replace(case, records=rows)).decision_hash == before.decision_hash


def test_independent_call_put_strikes_and_no_common_expiry():
    case = make_case()
    rows = []
    for record in case.records:
        if type(record.value) is OptionContract:
            contract = record.value
            if contract.kind is OptionKind.PUT:
                strike = contract.strike + 3
                contract = replace(
                    contract,
                    strike=strike,
                    standardized_id=f"SPY   240201P{int(strike * 1000):08d}",
                )
            rows.append(replace(record, value=contract))
    result = select(rechain(case, tuple(rows)))
    assert [c.strike for c in result.candidates] == [Decimal("99"), Decimal("102")]
    case = make_case(dtes=(30, 31))
    rows = tuple(
        r
        for r in case.records
        if type(r.value) is OptionContract
        and (
            (r.value.expiration.day == 1 and r.value.kind is OptionKind.CALL)
            or (r.value.expiration.day == 2 and r.value.kind is OptionKind.PUT)
        )
    )
    assert select(rechain(case, rows)).reasons == ("no_common_eligible_expiry",)


@pytest.mark.parametrize(
    "prior_day,target_day,close",
    [
        (date(2024, 1, 5), date(2024, 1, 8), time(16)),
        (date(2023, 12, 29), date(2024, 1, 2), time(16)),
        (date(2024, 3, 8), date(2024, 3, 11), time(16)),
        (date(2024, 11, 1), date(2024, 11, 4), time(16)),
        (date(2024, 11, 29), date(2024, 12, 2), time(13)),
    ],
)
def test_explicit_regular_sessions_handle_closures_dst_and_early_close(
    prior_day, target_day, close
):
    case = make_case(current=fixture_session(target_day), prior=fixture_session(prior_day, close))
    assert select(case).status == "selected"


@pytest.mark.parametrize("endpoint", ["prior", "current"])
@pytest.mark.parametrize(
    "opening,closing",
    [
        (time(9, 30), time(16, 15)),
        (time(9, 30), time(13, 15)),
        (time(0), time(18, 59)),
        (time(9, 31), time(16)),
    ],
)
def test_consistently_mislabeled_regular_sessions_are_denied(endpoint, opening, closing):
    case = make_case()
    session = case.prior_session if endpoint == "prior" else case.current_session
    assert session is not None
    altered = fixture_session(session.trading_date, closing)
    altered = replace(
        altered,
        opens_at=altered.opens_at + timedelta(hours=opening.hour - 9, minutes=opening.minute - 30),
    )
    # Rebuild calendar, close, chain evidence and contract sessions consistently.
    # Agreement among caller-supplied records is not proof of a regular session.
    case = make_case(**{endpoint: altered})
    assert select(case).reasons == ("calendar_unverified",)
    assert select(case).candidates == ()


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("calendar", None, "calendar_unverified"),
        ("prior_session", None, "calendar_unverified"),
        ("closes", (), "prior_close_unavailable"),
        ("action_evidence", None, "action_coverage_unverified"),
        ("chain_evidence", None, "source_evidence_unverified"),
        ("records", (), "chain_unavailable"),
    ],
)
def test_missing_inputs_deny_without_fallback(field, value, reason):
    result = select(replace(make_case(), **{field: value}))
    assert result.reasons == (reason,)
    assert result.candidates == ()


def test_calendar_gap_intervening_session_and_late_calendar_deny():
    case = make_case()
    missing = replace(case.calendar, days=case.calendar.days[1:])
    assert select(replace(case, calendar=missing)).reasons == ("calendar_unverified",)
    days = tuple(
        replace(d, regular_session=fixture_session(d.trading_date))
        if d.trading_date == date(2024, 1, 1)
        else d
        for d in case.calendar.days
    )
    assert select(replace(case, calendar=replace(case.calendar, days=days))).reasons == (
        "calendar_unverified",
    )
    late = replace(
        case.calendar.evidence, available_at=case.current_session.opens_at + timedelta(seconds=1)
    )
    assert select(replace(case, calendar=replace(case.calendar, evidence=late))).reasons == (
        "calendar_unverified",
    )


@pytest.mark.parametrize(
    "change", ["utc_day", "options_close", "interpolated", "future", "wrong_day"]
)
def test_reference_close_cannot_be_substituted(change):
    case = make_case()
    close = case.closes[0]
    bar = close.bar
    if change == "utc_day":
        close = replace(close, bar=replace(bar, starts_at=bar.starts_at.replace(hour=0, minute=0)))
    elif change == "options_close":
        close = replace(
            close,
            bar=replace(bar, ends_at=bar.ends_at + timedelta(minutes=15)),
            available_at=bar.ends_at + timedelta(minutes=16),
        )
    elif change == "interpolated":
        close = replace(close, bar=replace(bar, interpolated=True))
    elif change == "future":
        close = replace(close, available_at=case.current_session.opens_at + timedelta(seconds=1))
    else:
        close = replace(
            close,
            bar=replace(
                bar,
                starts_at=bar.starts_at - timedelta(days=1),
                ends_at=bar.ends_at - timedelta(days=1),
            ),
        )
    assert select(replace(case, closes=(close,))).reasons == ("prior_close_unavailable",)


def test_future_close_ignored_visible_revision_selected_and_conflict_invalid():
    case = make_case()
    close = case.closes[0]
    revision = replace(close, bar=replace(close.bar, close=Decimal("101")))
    future = replace(revision, available_at=case.current_session.opens_at + timedelta(seconds=1))
    assert select(replace(case, closes=(close, future))).decision_hash == select(case).decision_hash
    with pytest.raises(DomainValidationError):
        select(replace(case, closes=(close, revision)))
    revision = replace(revision, available_at=close.available_at + timedelta(minutes=1))
    assert [c.strike for c in select(replace(case, closes=(close, revision))).candidates] == [
        101,
        101,
    ]


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("split", "reference_discontinuity"),
        ("merger", "reference_discontinuity"),
        ("denomination_change", "reference_discontinuity"),
        ("deliverable_change", "reference_discontinuity"),
        ("unknown", "action_coverage_unverified"),
    ],
)
def test_visible_discontinuities_and_unknown_actions_deny(kind, reason):
    case = make_case()
    known = case.prior_session.closes_at
    if kind == "split":
        action = CorporateAction(
            InstrumentId("SPY"),
            kind,
            case.current_session.trading_date,
            known,
            Decimal("2"),
            None,
            DataHash("a" * 64),
        )
    else:
        action = ShortlistDiscontinuity(
            "SPY", kind, case.current_session.trading_date, known, DataHash("a" * 64)
        )
    assert select(replace(case, actions=(ShortlistAction(action, known),))).reasons == (reason,)
    later = case.current_session.opens_at + timedelta(seconds=1)
    future = ShortlistAction(replace(action, announced_at=later), later)
    assert select(replace(case, actions=(future,))).decision_hash == select(case).decision_hash


def test_dividend_retains_context_without_adjusting_close_or_contract_selection():
    case = make_case()
    known = case.prior_session.closes_at
    action = CorporateAction(
        InstrumentId("SPY"),
        "dividend",
        case.current_session.trading_date,
        known,
        None,
        Decimal("2"),
        DataHash("a" * 64),
    )
    result = select(replace(case, actions=(ShortlistAction(action, known),)))
    before = select(case)
    assert [c.contract_id for c in result.candidates] == [c.contract_id for c in before.candidates]
    assert result.candidates[0].reference_close_hash == before.candidates[0].reference_close_hash
    assert result.decision_hash != before.decision_hash


@pytest.mark.parametrize("change", ["missing", "late", "coverage", "wrong_underlying"])
def test_chain_gaps_and_unavailable_evidence_deny(change):
    case = make_case()
    if change == "missing":
        case = replace(case, records=case.records[1:])
    elif change == "late":
        case = replace(
            case,
            chain_evidence=replace(
                case.chain_evidence,
                available_at=case.current_session.opens_at + timedelta(microseconds=1),
            ),
        )
    elif change == "coverage":
        case = replace(
            case,
            chain_evidence=replace(
                case.chain_evidence, covers_through=case.prior_session.closes_at
            ),
        )
    else:
        rows = tuple(
            replace(r, value=replace(r.value, underlying="QQQ", deliverable_symbol="QQQ"))
            if type(r.value) is OptionContract
            else r
            for r in case.records
        )
        case = replace(case, records=rows)
    assert select(case).reasons == ("chain_unavailable",)


def test_duplicate_economic_identity_and_visible_revision_conflict_are_input_errors():
    case = make_case()
    rows = tuple(r for r in case.records if type(r.value) is OptionContract)
    duplicate = replace(rows[0], value=replace(rows[0].value, contract_id="other-id"))
    with pytest.raises(DomainValidationError):
        select(rechain(case, (*rows, duplicate)))
    with pytest.raises(DomainValidationError):
        select(replace(case, records=(*case.records, replace(rows[0], raw_hash="f" * 64))))


@pytest.mark.parametrize(
    "field,value",
    [
        ("exercise_style", ExerciseStyle.EUROPEAN),
        ("settlement_timing", SettlementTiming.AM),
        ("eligible_sessions", (fixture_session(date(2024, 1, 3)),)),
    ],
)
def test_unsupported_contracts_do_not_become_candidates(field, value):
    case = make_case()
    rows = tuple(
        replace(r, value=replace(r.value, **{field: value}))
        if type(r.value) is OptionContract
        else r
        for r in case.records
    )
    assert select(replace(case, records=rows)).reasons == ("no_common_eligible_expiry",)


def test_conflicting_standardized_identity_is_not_silently_sorted():
    case = make_case()
    record = case.records[0]
    bad = replace(record, value=replace(record.value, standardized_id="SPY   240201C00999000"))
    with pytest.raises(DomainValidationError):
        select(replace(case, records=(bad, *case.records[1:])))


def test_imports_disabled_settings_and_bounds_cannot_grant_authority():
    assert select(imported_case()).reasons == ("source_evidence_unverified",)
    settings = load_shortlist().config.options.research_shortlist
    assert select(make_case(), settings.model_copy(update={"enabled": False})).reasons == (
        "shortlist_disabled",
    )
    with pytest.raises(DomainValidationError):
        select(make_case(), settings.model_copy(update={"max_input_records": 1}))
    result = select(make_case())
    assert not any(
        (
            result.production_eligible,
            result.evidence_promotable,
            result.live_authorized,
            result.download_authorized,
        )
    )


def test_decimal_context_cannot_change_strike_ranking():
    case = make_case()
    before = select(case)
    with localcontext() as context:
        context.prec = 2
        after = select(case)
    assert after.decision_hash == before.decision_hash
