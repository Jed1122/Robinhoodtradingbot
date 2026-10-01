"""Cost metadata is exact immutable evidence, never permission or assumed zeros."""

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

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


@pytest.fixture
def cost_study():
    from trading_bot.config import load_config
    from trading_bot.research.etf_study import freeze_etf_study

    configs = Path(__file__).parents[3] / "configs"
    return freeze_etf_study(
        load_config(
            configs / "base.yaml",
            configs / "backtest.yaml",
            configs / "safety-envelope.yaml",
            {"TRADING_BOT__EQUITY_STRATEGIES__ETF_PILOT__ENABLED": "true"},
        ),
        code_hash="a" * 64,
        source_plan_hash="b" * 64,
        cost_plan_hash="c" * 64,
        holdout_previously_examined=False,
    )


def _cost_package(root, study):
    root.chmod(0o700)
    source = b"Synthetic cost fixture, not an actual fee schedule or calibration."
    digest = hashlib.sha256(source).hexdigest()
    path = root / (digest + ".raw")
    path.write_bytes(source)
    path.chmod(0o600)
    intervals = [
        dict(
            role=item.role,
            unit=item.unit,
            value=str(item.value),
            currency=item.currency,
            starts_at="2016-01-01T00:00:00.000000Z",
            ends_at="2026-01-01T00:00:00.000000Z",
            known_at="2015-12-01T00:00:00.000000Z",
            source_hash=digest,
        )
        for item in evidence().intervals
    ]
    return dict(
        schema="etf-cost-manifest-v1",
        study_hash=study.study_hash,
        cost_plan_hash=study.cost_plan_hash,
        source_kind="synthetic",
        starts_at="2016-01-01T00:00:00.000000Z",
        ends_at="2026-01-01T00:00:00.000000Z",
        intervals=intervals,
        calibration_hashes=[],
    )


def _write_cost_manifest(root, manifest):
    body = json.dumps(manifest).encode()
    path = root / (hashlib.sha256(body).hexdigest() + ".json")
    path.write_bytes(body)
    path.chmod(0o600)
    return path


def _load_costs(root, path, study):
    from trading_bot.research.etf_costs import load_etf_cost_evidence

    return load_etf_cost_evidence(path, root, study)


def test_private_cost_package_loads_exact_values_without_certifying_evidence(tmp_path, cost_study):
    manifest = _cost_package(tmp_path, cost_study)
    path = _write_cost_manifest(tmp_path, manifest)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    costs = _load_costs(tmp_path, path, cost_study)
    assert costs.intervals[0].value == Decimal("0.01")
    assert len(costs.intervals) == 7
    assert costs.cost_hash == _load_costs(tmp_path, path, cost_study).cost_hash
    assert costs.calibration_status == "unverified"
    assert costs.execution_enabled is False and costs.evidence_promotable is False
    assert costs.spread_in_fill_price is True
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


@pytest.mark.parametrize(
    "change",
    [
        "missing_role",
        "gap",
        "overlap",
        "known_later",
        "wrong_unit",
        "wrong_currency",
        "float",
        "noncanonical_decimal",
        "wrong_study",
        "wrong_plan",
        "wrong_era",
        "unknown_key",
        "zero_latency",
        "missing_source",
        "missing_calibration",
    ],
)
def test_cost_loader_rejects_incomplete_or_unsafe_inputs(tmp_path, cost_study, change):
    manifest = _cost_package(tmp_path, cost_study)
    first = manifest["intervals"][0]
    if change == "missing_role":
        manifest["intervals"].pop()
    elif change == "gap":
        first["starts_at"] = "2016-01-02T00:00:00.000000Z"
    elif change == "overlap":
        manifest["intervals"].append(dict(first))
    elif change == "known_later":
        first["known_at"] = "2016-01-01T00:00:00.000001Z"
    elif change == "wrong_unit":
        first["unit"] = "bps"
    elif change == "wrong_currency":
        first["currency"] = "EUR"
    elif change == "float":
        first["value"] = 0.01
    elif change == "noncanonical_decimal":
        first["value"] = "1e-2"
    elif change == "wrong_study":
        manifest["study_hash"] = "d" * 64
    elif change == "wrong_plan":
        manifest["cost_plan_hash"] = "d" * 64
    elif change == "wrong_era":
        manifest["ends_at"] = "2025-01-01T00:00:00.000000Z"
    elif change == "unknown_key":
        manifest["calibration_verified"] = True
    elif change == "zero_latency":
        next(i for i in manifest["intervals"] if i["role"] == "latency")["value"] = "0"
    elif change == "missing_source":
        first["source_hash"] = "f" * 64
    elif change == "missing_calibration":
        manifest["calibration_hashes"] = ["f" * 64]
    path = _write_cost_manifest(tmp_path, manifest)
    with pytest.raises(ValueError, match=r"^etf_cost_source_invalid$"):
        _load_costs(tmp_path, path, cost_study)


def test_effective_date_changes_are_exact_and_gap_free(tmp_path, cost_study):
    manifest = _cost_package(tmp_path, cost_study)
    first = manifest["intervals"][0]
    updated = dict(first, starts_at="2020-01-01T00:00:00.000000Z", value="0.02")
    first["ends_at"] = updated["starts_at"]
    manifest["intervals"].append(updated)
    costs = _load_costs(tmp_path, _write_cost_manifest(tmp_path, manifest), cost_study)
    rates = [i for i in costs.intervals if i.role == "commission_per_share"]
    assert [(i.value, i.starts_at.year, i.ends_at.year) for i in rates] == [
        (Decimal("0.01"), 2016, 2020),
        (Decimal("0.02"), 2020, 2026),
    ]


def test_recorded_labels_and_calibration_bytes_do_not_bless_costs(tmp_path, cost_study):
    manifest = _cost_package(tmp_path, cost_study)
    manifest["source_kind"] = "recorded"
    manifest["calibration_hashes"] = [manifest["intervals"][0]["source_hash"]]
    costs = _load_costs(tmp_path, _write_cost_manifest(tmp_path, manifest), cost_study)
    assert costs.source_kind == "recorded"
    assert costs.calibration_hashes
    assert costs.calibration_status == "unverified" and not costs.evidence_promotable


@pytest.mark.parametrize("target", ["manifest", "source"])
def test_cost_loader_detects_substituted_bytes(tmp_path, cost_study, target):
    manifest = _cost_package(tmp_path, cost_study)
    path = _write_cost_manifest(tmp_path, manifest)
    changed = (
        path
        if target == "manifest"
        else tmp_path / (manifest["intervals"][0]["source_hash"] + ".raw")
    )
    changed.write_bytes(changed.read_bytes() + b" ")
    with pytest.raises(ValueError, match=r"^etf_cost_source_invalid$"):
        _load_costs(tmp_path, path, cost_study)


@pytest.mark.parametrize("target", ["manifest", "source", "root"])
def test_cost_loader_denies_symlinks(tmp_path, cost_study, target):
    manifest = _cost_package(tmp_path, cost_study)
    path = _write_cost_manifest(tmp_path, manifest)
    root = tmp_path
    if target == "root":
        root = tmp_path / "alias"
        root.symlink_to(tmp_path, target_is_directory=True)
        path = root / path.name
    else:
        item = (
            path
            if target == "manifest"
            else tmp_path / (manifest["intervals"][0]["source_hash"] + ".raw")
        )
        saved = item.with_suffix(".original")
        item.rename(saved)
        item.symlink_to(saved)
    with pytest.raises(ValueError, match=r"^etf_cost_source_invalid$"):
        _load_costs(root, path, cost_study)


def test_oversized_input_and_secret_bearing_fields_have_sanitized_errors(tmp_path, cost_study):
    manifest = _cost_package(tmp_path, cost_study)
    for value in ("private-value-never-echo", "x" * 1048577):
        manifest["intervals"][0]["value"] = value
        path = _write_cost_manifest(tmp_path, manifest)
        with pytest.raises(ValueError, match=r"^etf_cost_source_invalid$"):
            _load_costs(tmp_path, path, cost_study)
