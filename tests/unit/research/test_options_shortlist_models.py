"""Boundary validation prevents coercion, origin mixing and caller authority."""

from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tests.unit.research._options_shortlist_fixtures import (
    imported_case,
    make_case,
    selected_result,
)
from trading_bot.domain.decimal_utils import DomainValidationError


def test_complete_synthetic_and_unverified_imported_inputs_are_representable() -> None:
    assert make_case().source_kind == "synthetic"
    assert imported_case().source_kind == "imported"


@pytest.mark.parametrize("bad", [True, 100.0, Decimal("NaN"), Decimal("Infinity")])
def test_money_cannot_coerce_or_be_nonfinite(bad: object) -> None:
    with pytest.raises(DomainValidationError):
        replace(make_case().closes[0].bar, close=bad)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_kind", "imported"),
        ("source_kind", True),
        ("option_source", "different"),
        ("records", []),
        ("actions", []),
        ("closes", [None]),
        ("current_session", None),
        ("prior_session", "2023-12-29"),
        ("calendar", {}),
        ("chain_evidence", True),
        ("action_evidence", {}),
    ],
)
def test_session_rejects_mixed_origins_or_wrong_nested_types(field, value) -> None:
    with pytest.raises(DomainValidationError):
        replace(make_case(), **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("raw_hash", "bad"),
        ("source", ""),
        ("source_kind", "unknown"),
        ("semantics", "verified-real"),
        ("available_at", date(2024, 1, 1)),
    ],
)
def test_evidence_is_exact_and_cannot_claim_verification(field, value) -> None:
    with pytest.raises((DomainValidationError, ValueError)):
        replace(make_case().chain_evidence, **{field: value})


def test_evidence_interval_and_calendar_identity_are_checked() -> None:
    case = make_case()
    with pytest.raises(DomainValidationError):
        replace(case.chain_evidence, covers_through=case.prior_session.opens_at - timedelta(days=1))
    with pytest.raises(DomainValidationError):
        replace(case.calendar, days=(*case.calendar.days, case.calendar.days[0]))
    with pytest.raises(DomainValidationError):
        replace(case.calendar.days[0], trading_date=date(2023, 12, 28))
    with pytest.raises(DomainValidationError):
        replace(case.calendar, evidence=None)


@pytest.mark.parametrize(
    "field,value",
    [
        ("price_basis", "adjusted"),
        ("coverage_label", "nbbo"),
        ("evidence", None),
        ("bar", {}),
    ],
)
def test_close_basis_and_types_are_explicit(field, value) -> None:
    with pytest.raises(DomainValidationError):
        replace(make_case().closes[0], **{field: value})


def test_close_cannot_arrive_before_completion_or_use_another_source() -> None:
    close = make_case().closes[0]
    with pytest.raises(DomainValidationError):
        replace(close, available_at=close.bar.starts_at)
    with pytest.raises(DomainValidationError):
        replace(close, evidence=replace(close.evidence, source="different"))


def test_result_is_frozen_and_has_no_caller_authority() -> None:
    result = selected_result()
    for flag in (
        "production_eligible",
        "evidence_promotable",
        "download_authorized",
        "live_authorized",
    ):
        assert getattr(result, flag) is False
        with pytest.raises((TypeError, ValueError), match="init=False"):
            replace(result, **{flag: True})
        assert getattr(result, flag) is False
    with pytest.raises(FrozenInstanceError):
        result.status = "no_candidate"


@pytest.mark.parametrize(
    "field,value",
    [
        ("candidates", ()),
        ("status", "no_candidate"),
        ("reasons", ("unknown",)),
        ("input_record_count", True),
        ("input_record_count", -1),
        ("config_hash", "bad"),
        ("version", "new-version"),
    ],
)
def test_result_status_and_identity_cannot_conflict(field, value) -> None:
    with pytest.raises(DomainValidationError):
        replace(selected_result(), **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("strike", 1.5),
        ("kind", "call"),
        ("expiration", True),
        ("selected_input_hashes", (("x", "bad"),)),
        ("contract_id", ""),
    ],
)
def test_candidates_reject_inexact_or_incomplete_identity(field, value) -> None:
    with pytest.raises(DomainValidationError):
        replace(selected_result().candidates[0], **{field: value})
