"""Cost metadata is exact immutable evidence, never permission or assumed zeros."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest


def interval(**overrides):
    from trading_bot.research.etf_costs import EtfCostInterval

    args = dict(
        role="commission_per_share",
        unit="USD/share",
        value=Decimal("0.01"),
        currency="USD",
        starts_at=datetime(2016, 1, 1, tzinfo=UTC),
        ends_at=datetime(2026, 1, 1, tzinfo=UTC),
        known_at=datetime(2015, 12, 1, tzinfo=UTC),
        source_hash="a" * 64,
    )
    args.update(overrides)
    return EtfCostInterval(**args)


def evidence():
    from trading_bot.research.etf_costs import EtfCostEvidence

    roles = (
        ("commission_per_share", "USD/share"),
        ("minimum_commission", "USD/order"),
        ("regulatory_per_notional", "USD/USD"),
        ("extra_slippage", "bps"),
        ("latency", "seconds"),
        ("cash_rate", "whole_percent/year"),
        ("operating_cost", "USD/day"),
    )
    return EtfCostEvidence(
        intervals=tuple(interval(role=r, unit=u) for r, u in roles),
        source_kind="synthetic",
        calibration_hashes=(),
    )


def test_cost_record_is_hash_bound_and_cannot_promote_synthetic_assumptions():
    costs = evidence()
    assert not costs.evidence_promotable and not costs.execution_enabled
    assert costs.spread_in_fill_price is True
    assert costs.calibration_status == "unverified"
    changed = replace(
        costs, intervals=(replace(costs.intervals[0], value=Decimal("0.02")), *costs.intervals[1:])
    )
    assert changed.cost_hash != costs.cost_hash
    with pytest.raises(FrozenInstanceError):
        costs.source_kind = "recorded"
    with pytest.raises((TypeError, ValueError), match="init=False"):
        replace(costs, evidence_promotable=True)
    with pytest.raises((TypeError, ValueError), match="init=False"):
        replace(costs, calibration_status="verified")


@pytest.mark.parametrize(
    "value", [True, 0.1, "0.01", Decimal("NaN"), Decimal("Infinity"), Decimal("-1")]
)
def test_financial_values_require_exact_bounded_nonnegative_decimal(value):
    with pytest.raises(ValueError):
        interval(value=value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"currency": "EUR"},
        {"role": "mystery"},
        {"unit": "percent"},
        {"source_hash": "bad"},
        {"starts_at": datetime(2016, 1, 1)},
        {"ends_at": datetime(2016, 1, 1, tzinfo=UTC)},
    ],
)
def test_inconsistent_units_windows_and_identities_deny(overrides):
    with pytest.raises(ValueError):
        interval(**overrides)


def test_missing_roles_duplicates_and_mutable_inputs_cannot_mean_zero_cost():
    costs = evidence()
    for values in (
        (),
        costs.intervals[:-1],
        (*costs.intervals, costs.intervals[0]),
        list(costs.intervals),
    ):
        with pytest.raises(ValueError):
            replace(costs, intervals=values)
    with pytest.raises(ValueError):
        replace(costs, source_kind="verified")


def test_recorded_is_provenance_not_a_calibration_or_authority_claim():
    costs = replace(evidence(), source_kind="recorded", calibration_hashes=("b" * 64,))
    assert not costs.evidence_promotable and not costs.execution_enabled
    with pytest.raises(ValueError):
        replace(costs, calibration_hashes=("bad",))
