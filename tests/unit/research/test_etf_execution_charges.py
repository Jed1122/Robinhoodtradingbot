"""RED contracts for pure fee attribution, not fills, broker rules, or risk approval."""

import importlib
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_UP, Decimal, Inexact, Overflow, Rounded, Underflow, localcontext

import pytest

from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_costs import EtfCostEvidence, EtfCostInterval

D = Decimal
START = datetime(2020, 1, 1, tzinfo=UTC)
END = datetime(2021, 1, 1, tzinfo=UTC)
KNOWN = datetime(2019, 12, 1, tzinfo=UTC)
AT = datetime(2020, 6, 3, 12, tzinfo=UTC)
SHA = "a" * 64
OTHER_SHA = "b" * 64
ZERO = D("0")
FILL_QUANTITY = D(".4")
PRICE = D("100")
_DEFAULT_COSTS = object()
ROLE_SPECS = (
    ("commission_per_share", "USD/share", ".02"),
    ("minimum_commission", "USD/order", ".03"),
    ("regulatory_per_notional", "USD/USD", ".0001"),
    ("extra_slippage", "bps", "7"),
    ("latency", "seconds", ".01"),
    ("cash_rate", "whole_percent/year", "2.5"),
    ("operating_cost", "USD/day", "5"),
)


def cost_evidence(**rates):
    return EtfCostEvidence(
        intervals=tuple(
            EtfCostInterval(role, unit, rates.get(role, D(value)), "USD", START, END, KNOWN, SHA)
            for role, unit, value in ROLE_SPECS
        ),
        source_kind="synthetic",
        calibration_hashes=(),
    )


def api():
    module = importlib.import_module("trading_bot.research.etf_costs")
    if not callable(getattr(module, "etf_execution_charges", None)):
        pytest.fail("pure ETF execution-charge function is missing")
    return module


def charge(
    costs=_DEFAULT_COSTS,
    *,
    at=AT,
    prior_quantity=ZERO,
    quantity=FILL_QUANTITY,
    price=PRICE,
    prior_schedule_hash=None,
):
    return api().etf_execution_charges(
        cost_evidence() if costs is _DEFAULT_COSTS else costs,
        at=at,
        prior_quantity=prior_quantity,
        quantity=quantity,
        price=price,
        prior_schedule_hash=prior_schedule_hash,
    )


@pytest.mark.parametrize(
    ("prior", "quantity", "commission", "regulatory", "total"),
    [
        ("0", ".4", ".03", ".004", ".034"),
        (".4", ".6", "0", ".006", ".006"),
        ("1", "1", ".01", ".01", ".02"),
        ("2", "3", ".06", ".03", ".09"),
        ("1", ".5", "0", ".005", ".005"),
        ("1.5", ".5", ".01", ".005", ".015"),
        ("100", "1", ".02", ".01", ".03"),
    ],
)
def test_partial_fill_charges_are_incremental_with_one_order_minimum(
    prior, quantity, commission, regulatory, total
):
    first = charge()
    result = charge(
        prior_quantity=D(prior),
        quantity=D(quantity),
        prior_schedule_hash=first.fee_schedule_hash if D(prior) > 0 else None,
    )
    assert result.commission_usd == D(commission)
    assert result.regulatory_fee_usd == D(regulatory)
    assert result.total_fee_usd == D(total)


def test_partial_fill_fee_totals_match_single_fill_without_recharging_minimum():
    first = charge()
    results = tuple(
        charge(
            prior_quantity=D(prior),
            quantity=D(quantity),
            prior_schedule_hash=first.fee_schedule_hash if D(prior) > 0 else None,
        )
        for prior, quantity in (("0", ".4"), (".4", ".6"), ("1", "1"), ("2", "3"))
    )
    assert sum((result.commission_usd for result in results), D("0")) == D(".10")
    assert sum((result.regulatory_fee_usd for result in results), D("0")) == D(".05")
    assert sum((result.total_fee_usd for result in results), D("0")) == D(".15")
    single = charge(quantity=D("5"))
    assert single.commission_usd == D(".10")
    assert single.regulatory_fee_usd == D(".05")
    assert single.total_fee_usd == D(".15")


def test_regulatory_upper_bound_uses_only_current_quantity_and_current_price():
    first = charge()
    result = charge(
        prior_quantity=D(".4"),
        quantity=D(".6"),
        price=D("200"),
        prior_schedule_hash=first.fee_schedule_hash,
    )
    assert result.commission_usd == 0
    assert result.regulatory_fee_usd == D(".012")
    assert result.total_fee_usd == D(".012")


@pytest.mark.parametrize(
    ("prior", "quantity", "commission", "total"),
    [("0", ".4", ".008", ".012"), (".4", ".6", ".012", ".018")],
)
def test_zero_minimum_still_charges_exact_current_per_share_fee(prior, quantity, commission, total):
    costs = cost_evidence(minimum_commission=D("0"))
    first = charge(costs)
    result = charge(
        costs,
        prior_quantity=D(prior),
        quantity=D(quantity),
        prior_schedule_hash=first.fee_schedule_hash if D(prior) > 0 else None,
    )
    assert result.commission_usd == D(commission)
    assert result.total_fee_usd == D(total)


def test_zero_per_share_rate_charges_minimum_only_on_first_positive_fill():
    costs = cost_evidence(commission_per_share=D("0"), regulatory_per_notional=D("0"))
    first = charge(costs)
    later = charge(costs, prior_quantity=D(".4"), prior_schedule_hash=first.fee_schedule_hash)
    assert first.commission_usd == first.total_fee_usd == D(".03")
    assert later.commission_usd == later.total_fee_usd == 0


def test_explicit_zero_fee_roles_are_not_missing_roles_or_promotable_evidence():
    result = charge(
        cost_evidence(
            commission_per_share=D("0"), minimum_commission=D("0"), regulatory_per_notional=D("0")
        )
    )
    assert result.commission_usd == result.regulatory_fee_usd == result.total_fee_usd == 0
    assert result.evidence_promotable is False and result.execution_enabled is False
    assert result.regulatory_side_assumption == "both-sides-unverified-upper-bound"


def test_spread_slippage_operating_cash_rate_and_latency_are_not_deducted_as_fees():
    first = charge()
    changed = charge(
        cost_evidence(
            extra_slippage=D("25"), operating_cost=D("100"), cash_rate=D("1"), latency=D("20")
        )
    )
    assert first.commission_usd == changed.commission_usd == D(".03")
    assert first.regulatory_fee_usd == changed.regulatory_fee_usd == D(".004")
    assert first.total_fee_usd == changed.total_fee_usd == D(".034")
    assert first.cost_hash != changed.cost_hash


def test_result_is_immutable_hash_bound_and_truthfully_labels_unverified_side_assumption():
    costs = cost_evidence()
    result = charge(costs)
    assert type(result) is api().EtfExecutionCharges
    assert result.cost_hash == costs.cost_hash
    assert result.fee_schedule_hash == content_hash(
        tuple(sorted(costs.intervals, key=lambda item: item.role))
    )
    assert result.observed_at == AT
    assert result.regulatory_side_assumption == "both-sides-unverified-upper-bound"
    assert result.evidence_promotable is False
    assert result.execution_enabled is False
    with pytest.raises(FrozenInstanceError):
        result.total_fee_usd = D("0")
    with pytest.raises((TypeError, ValueError)):
        replace(result, evidence_promotable=True)
    with pytest.raises((TypeError, ValueError)):
        replace(result, execution_enabled=True)


def test_recorded_provenance_and_calibration_hash_do_not_certify_fee_assumptions():
    costs = replace(cost_evidence(), source_kind="recorded", calibration_hashes=(OTHER_SHA,))
    result = charge(costs)
    assert result.total_fee_usd == D(".034")
    assert result.cost_hash == costs.cost_hash
    assert result.regulatory_side_assumption == "both-sides-unverified-upper-bound"
    assert result.evidence_promotable is False and result.execution_enabled is False


def test_hostile_ambient_decimal_context_cannot_round_fees_or_mutate_caller_context():
    costs = cost_evidence()
    with localcontext() as context:
        context.prec = 1
        context.rounding = ROUND_UP
        context.Emin = -1
        context.Emax = 1
        for signal in (Inexact, Rounded, Overflow, Underflow):
            context.traps[signal] = True
        context.flags[Inexact] = True
        old_flags = dict(context.flags)
        old_traps = dict(context.traps)
        result = charge(costs)
        assert result.commission_usd == D(".03")
        assert result.regulatory_fee_usd == D(".004")
        assert result.total_fee_usd == D(".034")
        assert (context.prec, context.rounding, context.Emin, context.Emax) == (1, ROUND_UP, -1, 1)
        assert dict(context.flags) == old_flags
        assert dict(context.traps) == old_traps


@pytest.mark.parametrize("field", ["prior_quantity", "quantity", "price"])
@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        0,
        1.0,
        "1",
        D("NaN"),
        D("sNaN"),
        D("Infinity"),
        D("-1"),
        D("1E513"),
        D("1" * 513),
    ],
)
def test_financial_arguments_reject_coercion_nonfinite_negative_and_unbounded_values(field, value):
    with pytest.raises(ValueError):
        charge(**{field: value})


@pytest.mark.parametrize("field", ["quantity", "price"])
@pytest.mark.parametrize("value", [D("0"), D("-0")])
def test_zero_fill_or_price_is_rejected_instead_of_charging_a_cancel_or_no_fill(field, value):
    # Cancellation and no-fill observations have no execution charge call.
    # Rejecting zero fills prevents an accidental per-order minimum debit.
    with pytest.raises(ValueError):
        charge(**{field: value})


@pytest.mark.parametrize(
    "at",
    [
        True,
        1.0,
        "2020-06-03T12:00:00Z",
        date(2020, 6, 3),
        datetime(2020, 6, 3),
        datetime(2020, 6, 3, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_observation_time_requires_exact_canonical_utc_datetime(at):
    with pytest.raises(ValueError):
        charge(at=at)


@pytest.mark.parametrize("costs", [None, True, (), [], {}, object()])
def test_unknown_cost_evidence_objects_are_rejected(costs):
    with pytest.raises(ValueError):
        charge(costs)


@pytest.mark.parametrize("role", [role for role, _, _ in ROLE_SPECS])
def test_every_role_requires_active_coverage_even_when_not_used_in_fee_formula(role):
    costs = cost_evidence()
    rows = tuple(replace(row, ends_at=AT) if row.role == role else row for row in costs.intervals)
    with pytest.raises(ValueError):
        charge(replace(costs, intervals=rows))


@pytest.mark.parametrize("role", [role for role, _, _ in ROLE_SPECS])
def test_future_only_interval_is_not_current_cost_coverage(role):
    costs = cost_evidence()
    rows = tuple(
        replace(row, starts_at=AT + timedelta(microseconds=1)) if row.role == role else row
        for row in costs.intervals
    )
    with pytest.raises(ValueError):
        charge(replace(costs, intervals=rows))


@pytest.mark.parametrize("role", [role for role, _, _ in ROLE_SPECS])
def test_rate_must_be_known_by_its_start_not_just_by_charge_observation(role):
    costs = cost_evidence()
    row = next(row for row in costs.intervals if row.role == role)
    object.__setattr__(row, "known_at", START + timedelta(microseconds=1))
    with pytest.raises(ValueError):
        charge(costs)


def test_future_known_active_rate_is_rejected():
    costs = cost_evidence()
    object.__setattr__(costs.intervals[0], "known_at", AT + timedelta(microseconds=1))
    with pytest.raises(ValueError):
        charge(costs)


def test_interval_start_is_inclusive():
    result = charge(at=START)
    assert result.total_fee_usd == D(".034")
    assert result.observed_at == START


def test_adjacent_half_open_intervals_select_successor_at_exact_boundary():
    costs = cost_evidence()
    old = tuple(replace(row, ends_at=AT) for row in costs.intervals)
    new = tuple(
        replace(
            row,
            starts_at=AT,
            known_at=AT,
            value=D(".04") if row.role == "commission_per_share" else row.value,
            source_hash=OTHER_SHA,
        )
        for row in costs.intervals
    )
    split = replace(costs, intervals=(*old, *new))
    before = charge(split, at=AT - timedelta(microseconds=1), quantity=D("2"))
    after = charge(split, at=AT, quantity=D("2"))
    assert before.commission_usd == D(".04")
    assert after.commission_usd == D(".08")
    assert before.regulatory_fee_usd == after.regulatory_fee_usd == D(".02")
    assert before.total_fee_usd == D(".06")
    assert after.total_fee_usd == D(".10")
    assert before.fee_schedule_hash != after.fee_schedule_hash


def test_valid_future_interval_changes_never_rewrite_current_charge_amounts():
    costs = cost_evidence()
    future = tuple(
        replace(
            row,
            starts_at=END,
            ends_at=datetime(2022, 1, 1, tzinfo=UTC),
            known_at=datetime(2020, 12, 1, tzinfo=UTC),
            source_hash=OTHER_SHA,
        )
        for row in costs.intervals
    )
    expanded = replace(costs, intervals=(*costs.intervals, *future))
    revised_future = tuple(replace(row, value=D("99")) for row in future)
    changed = replace(costs, intervals=(*costs.intervals, *revised_future))
    first = charge(expanded)
    second = charge(changed)
    assert first.commission_usd == second.commission_usd == D(".03")
    assert first.regulatory_fee_usd == second.regulatory_fee_usd == D(".004")
    assert first.total_fee_usd == second.total_fee_usd == D(".034")
    assert first.cost_hash == expanded.cost_hash
    assert second.cost_hash == changed.cost_hash
    assert first.cost_hash != second.cost_hash
    assert first.fee_schedule_hash == second.fee_schedule_hash


@pytest.mark.parametrize("value", [D("0"), D("-0")])
def test_active_latency_must_be_strictly_positive(value):
    costs = cost_evidence()
    row = next(row for row in costs.intervals if row.role == "latency")
    object.__setattr__(row, "value", value)
    with pytest.raises(ValueError):
        charge(costs)


@pytest.mark.parametrize("role", [role for role, _, _ in ROLE_SPECS])
def test_missing_role_cannot_be_interpreted_as_zero_by_bypassing_frozen_constructor(role):
    costs = cost_evidence()
    object.__setattr__(
        costs, "intervals", tuple(row for row in costs.intervals if row.role != role)
    )
    with pytest.raises(ValueError):
        charge(costs)


@pytest.mark.parametrize("kind", ["duplicate", "overlap", "mutable", "unknown", "oversized"])
def test_function_revalidates_corrupted_interval_collection(kind):
    costs = cost_evidence()
    if kind == "duplicate":
        rows = (*costs.intervals, costs.intervals[0])
    elif kind == "overlap":
        rows = (*costs.intervals, replace(costs.intervals[0], starts_at=AT))
    elif kind == "mutable":
        rows = list(costs.intervals)
    elif kind == "unknown":
        rows = (object(), *costs.intervals[1:])
    else:
        rows = costs.intervals * 1500
    object.__setattr__(costs, "intervals", rows)
    with pytest.raises(ValueError):
        charge(costs)


@pytest.mark.parametrize("role", [role for role, _, _ in ROLE_SPECS])
@pytest.mark.parametrize("value", [True, D("NaN"), D("-1"), D("1E513")])
def test_nested_rate_values_are_revalidated_for_all_roles(role, value):
    costs = cost_evidence()
    row = next(row for row in costs.intervals if row.role == role)
    object.__setattr__(row, "value", value)
    with pytest.raises(ValueError):
        charge(costs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("role", "unknown"),
        ("unit", "bps"),
        ("currency", "EUR"),
        ("source_hash", "not-a-digest"),
        ("starts_at", datetime(2020, 1, 1)),
        ("ends_at", START),
        ("known_at", True),
    ],
)
def test_nested_cost_metadata_is_revalidated_before_fee_arithmetic(field, value):
    costs = cost_evidence()
    object.__setattr__(costs.intervals[0], field, value)
    with pytest.raises(ValueError):
        charge(costs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_kind", "verified"),
        ("calibration_hashes", []),
        ("calibration_hashes", (SHA, SHA)),
        ("calibration_hashes", ("invalid",)),
        ("calibration_status", "verified"),
        ("spread_in_fill_price", False),
        ("spread_in_fill_price", 1),
        ("execution_enabled", True),
        ("execution_enabled", 0),
        ("evidence_promotable", True),
        ("evidence_promotable", 0),
    ],
)
def test_cost_evidence_metadata_and_false_authority_markers_are_revalidated(field, value):
    costs = cost_evidence()
    object.__setattr__(costs, field, value)
    with pytest.raises(ValueError):
        charge(costs)


def test_invalid_fixture_text_is_not_echoed_by_fee_boundary_error():
    costs = cost_evidence()
    marker = "fixture-invalid-marker-must-not-escape"
    object.__setattr__(costs.intervals[0], "source_hash", marker)
    with pytest.raises(ValueError) as error:
        charge(costs)
    assert marker not in str(error.value)


@pytest.mark.parametrize("value", [None, True, 0, "bad", "A" * 64, "a" * 63, "g" * 64, OTHER_SHA])
def test_continuation_requires_exact_matching_active_fee_schedule_hash(value):
    with pytest.raises(ValueError):
        charge(prior_quantity=D(".4"), prior_schedule_hash=value)


@pytest.mark.parametrize("value", [True, "bad", SHA])
def test_first_fill_cannot_claim_a_prior_schedule_hash(value):
    with pytest.raises(ValueError):
        charge(prior_quantity=D("0"), prior_schedule_hash=value)


def test_first_fill_rejects_even_a_matching_hash_as_prior_schedule_claim():
    first = charge()
    with pytest.raises(ValueError):
        charge(prior_quantity=D("0"), prior_schedule_hash=first.fee_schedule_hash)


def test_reordered_active_intervals_keep_same_schedule_hash_and_continuation_fees():
    costs = cost_evidence()
    first = charge(costs)
    reordered = replace(costs, intervals=tuple(reversed(costs.intervals)))
    result = charge(
        reordered,
        prior_quantity=D(".4"),
        quantity=D(".6"),
        prior_schedule_hash=first.fee_schedule_hash,
    )
    assert result.fee_schedule_hash == first.fee_schedule_hash
    assert result.commission_usd == 0
    assert result.regulatory_fee_usd == result.total_fee_usd == D(".006")


def test_partial_fill_crossing_fee_epoch_rejects_old_schedule_instead_of_repricing_paid_minimum():
    costs = cost_evidence()
    old = tuple(replace(row, ends_at=AT) for row in costs.intervals)
    new = tuple(
        replace(
            row,
            starts_at=AT,
            known_at=AT,
            source_hash=OTHER_SHA,
            value=D(".04") if row.role == "commission_per_share" else row.value,
        )
        for row in costs.intervals
    )
    split = replace(costs, intervals=(*old, *new))
    first = charge(split, at=AT - timedelta(microseconds=1))
    assert first.commission_usd == D(".03")
    with pytest.raises(ValueError):
        charge(
            split,
            at=AT,
            prior_quantity=D(".4"),
            quantity=D(".6"),
            prior_schedule_hash=first.fee_schedule_hash,
        )


@pytest.mark.parametrize("role", [role for role, _, _ in ROLE_SPECS])
def test_schedule_hash_binds_every_active_role_and_rejects_changed_schedule_continuation(role):
    costs = cost_evidence()
    first = charge(costs)
    revised = replace(
        costs,
        intervals=tuple(
            replace(row, value=D("2")) if row.role == role else row for row in costs.intervals
        ),
    )
    fresh = charge(revised)
    assert first.fee_schedule_hash != fresh.fee_schedule_hash
    with pytest.raises(ValueError):
        charge(revised, prior_quantity=D(".4"), prior_schedule_hash=first.fee_schedule_hash)
