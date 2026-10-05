"""Tests for the critical per-module branch-coverage gate."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "check_critical_branch_coverage.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("critical_branch_coverage", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source(root: Path, relative_path: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# synthetic source\n")
    return path


def _report(
    path: Path,
    entries: dict[str, dict[str, object]],
    branch_coverage: object = True,
) -> Path:
    payload: dict[str, object] = {"files": entries}
    if branch_coverage is not None:
        payload["meta"] = {"branch_coverage": branch_coverage}
    path.write_text(json.dumps(payload))
    return path


def _entry(total: object, covered: object) -> dict[str, object]:
    return {"summary": {"num_branches": total, "covered_branches": covered}}


def test_accepts_per_file_threshold_boundary_with_absolute_and_relative_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    absolute = _source(root, "src/trading_bot/risk/absolute.py")
    _source(root, "src/trading_bot/execution/relative.py")
    _source(root, "src/trading_bot/domain/order_state_machine.py")
    report = _report(
        tmp_path / "coverage.json",
        {
            str(absolute): _entry(10, 9),
            "src/trading_bot/execution/relative.py": _entry(20, 18),
            "src/trading_bot/domain/order_state_machine.py": _entry(0, 0),
        },
    )

    assert _load_checker().check_critical_branch_coverage(report, root) == []


def test_fails_when_a_discovered_critical_file_is_missing_from_report(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _source(root, "src/trading_bot/risk/missing.py")
    report = _report(tmp_path / "coverage.json", {})

    errors = _load_checker().check_critical_branch_coverage(report, root)

    assert errors == ["missing branch coverage for src/trading_bot/risk/missing.py"]


def test_requires_options_trial_history_and_execution_lease_branches(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _source(root, "src/trading_bot/risk/anchor.py")
    _source(root, "src/trading_bot/persistence/options_trial.py")
    _source(root, "src/trading_bot/persistence/options_risk.py")
    _source(root, "src/trading_bot/persistence/lease.py")
    report = _report(
        tmp_path / "coverage.json",
        {
            "src/trading_bot/risk/anchor.py": _entry(0, 0),
        },
    )
    assert _load_checker().check_critical_branch_coverage(report, root) == [
        "missing branch coverage for src/trading_bot/persistence/lease.py",
        "missing branch coverage for src/trading_bot/persistence/options_risk.py",
        "missing branch coverage for src/trading_bot/persistence/options_trial.py",
    ]


def test_requires_scoped_capability_verification_branches(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _source(root, "src/trading_bot/capabilities/verification.py")
    report = _report(tmp_path / "coverage.json", {})
    assert _load_checker().check_critical_branch_coverage(report, root) == [
        "missing branch coverage for src/trading_bot/capabilities/verification.py",
    ]


def test_requires_incremental_historical_owner_branch_report(tmp_path):
    root = tmp_path / "project"
    _source(root, "src/trading_bot/simulation/etf_incremental_history.py")
    report = _report(tmp_path / "coverage.json", {})
    assert _load_checker().check_critical_branch_coverage(report, root) == [
        "missing branch coverage for src/trading_bot/simulation/etf_incremental_history.py"
    ]


@pytest.mark.parametrize(
    "relative_path",
    [
        "src/trading_bot/domain/owned_order_lifecycle.py",
        "src/trading_bot/persistence/owned_order_journal.py",
    ],
)
def test_owned_lifecycle_cannot_escape_the_critical_branch_gate(tmp_path, relative_path):
    root = tmp_path / "project"
    _source(root, relative_path)
    report = _report(tmp_path / "coverage.json", {})
    assert _load_checker().check_critical_branch_coverage(report, root) == [
        f"missing branch coverage for {relative_path}"
    ]


@pytest.mark.parametrize(
    "relative_path",
    [
        "src/trading_bot/persistence/paper_cycle_journal.py",
        "src/trading_bot/runtime/paper_promotion.py",
        "src/trading_bot/runtime/paper_promotion_runtime.py",
        "src/trading_bot/runtime/etf_forward_paper.py",
        "src/trading_bot/persistence/etf_forward_paper.py",
    ],
)
def test_requires_every_paper_owner_and_promotion_branch_report(tmp_path, relative_path):
    root = tmp_path / "project"
    _source(root, relative_path)
    report = _report(tmp_path / "coverage.json", {})
    assert _load_checker().check_critical_branch_coverage(report, root) == [
        f"missing branch coverage for {relative_path}",
    ]


def test_requires_durable_recorded_options_runtime_branches(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _source(root, "src/trading_bot/runtime/options_recorded_session.py")
    report = _report(tmp_path / "coverage.json", {})
    assert _load_checker().check_critical_branch_coverage(report, root) == [
        "missing branch coverage for src/trading_bot/runtime/options_recorded_session.py",
    ]


def test_requires_etf_strategy_coordinator_branches(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _source(root, "src/trading_bot/simulation/etf_strategy.py")
    report = _report(tmp_path / "coverage.json", {})
    assert _load_checker().check_critical_branch_coverage(report, root) == [
        "missing branch coverage for src/trading_bot/simulation/etf_strategy.py",
    ]


@pytest.mark.parametrize(
    "relative_path",
    [
        "src/trading_bot/simulation/etf_native_history.py",
        "src/trading_bot/simulation/etf_native_models.py",
        "src/trading_bot/persistence/etf_native_checkpoint.py",
    ],
)
def test_requires_native_execution_and_recovery_branch_reports(tmp_path, relative_path):
    root = tmp_path / "project"
    _source(root, relative_path)
    report = _report(tmp_path / "coverage.json", {})
    assert _load_checker().check_critical_branch_coverage(report, root) == [
        f"missing branch coverage for {relative_path}"
    ]


@pytest.mark.parametrize(
    "relative_path",
    [
        "src/trading_bot/domain/options_account.py",
        "src/trading_bot/reconciliation/options.py",
        "src/trading_bot/runtime/options_monitor.py",
    ],
)
def test_requires_each_discovered_options_module_to_have_branch_coverage(
    tmp_path: Path, relative_path: str
) -> None:
    root = tmp_path / "project"
    _source(root, relative_path)
    report = _report(tmp_path / "coverage.json", {})

    assert _load_checker().check_critical_branch_coverage(report, root) == [
        f"missing branch coverage for {relative_path}",
    ]


def test_accepts_exact_90_percent_branch_coverage_for_options_modules(tmp_path: Path) -> None:
    root = tmp_path / "project"
    options_modules = [
        "src/trading_bot/domain/options_account.py",
        "src/trading_bot/reconciliation/options.py",
        "src/trading_bot/runtime/options_monitor.py",
    ]
    for relative_path in options_modules:
        _source(root, relative_path)
    report = _report(
        tmp_path / "coverage.json",
        {relative_path: _entry(10, 9) for relative_path in options_modules},
    )

    assert _load_checker().check_critical_branch_coverage(report, root) == []


@pytest.mark.parametrize(
    "relative_path",
    [
        "src/trading_bot/domain/options_account.py",
        "src/trading_bot/reconciliation/options.py",
        "src/trading_bot/runtime/options_monitor.py",
    ],
)
def test_rejects_invalid_branch_coverage_for_each_options_module(
    tmp_path: Path, relative_path: str
) -> None:
    root = tmp_path / "project"
    _source(root, relative_path)
    report = _report(tmp_path / "coverage.json", {relative_path: _entry(10, 11)})

    assert _load_checker().check_critical_branch_coverage(report, root) == [
        f"invalid branch counters for {relative_path}",
    ]


def test_requires_discovered_simulation_lifecycle_modules(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _source(root, "src/trading_bot/risk/anchor.py")
    _source(root, "src/trading_bot/simulation/lifecycle_accounting.py")
    _source(root, "src/trading_bot/simulation/lifecycle_codec.py")
    _source(root, "src/trading_bot/simulation/lifecycle_models.py")
    report = _report(
        tmp_path / "coverage.json",
        {"src/trading_bot/risk/anchor.py": _entry(0, 0)},
    )

    errors = _load_checker().check_critical_branch_coverage(report, root)

    assert errors == [
        "missing branch coverage for src/trading_bot/simulation/lifecycle_accounting.py",
        "missing branch coverage for src/trading_bot/simulation/lifecycle_codec.py",
        "missing branch coverage for src/trading_bot/simulation/lifecycle_models.py",
    ]


def test_requires_historical_options_execution_branches(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _source(root, "src/trading_bot/simulation/options_historical_execution.py")
    _source(root, "src/trading_bot/simulation/options_historical_models.py")
    report = _report(tmp_path / "coverage.json", {})
    assert _load_checker().check_critical_branch_coverage(report, root) == [
        "missing branch coverage for src/trading_bot/simulation/options_historical_execution.py",
        "missing branch coverage for src/trading_bot/simulation/options_historical_models.py",
    ]


def test_requires_each_etf_history_owner_branch_report(tmp_path: Path) -> None:
    root = tmp_path / "project"
    names = ("etf_history.py", "etf_history_state.py")
    for name in names:
        _source(root, "src/trading_bot/simulation/" + name)
    report = _report(tmp_path / "coverage.json", {})
    assert _load_checker().check_critical_branch_coverage(report, root) == [
        "missing branch coverage for src/trading_bot/simulation/" + name for name in names
    ]


@pytest.mark.parametrize(
    "relative_path",
    [
        "src/trading_bot/simulation/etf_fixture_execution.py",
        "src/trading_bot/research/etf_costs.py",
    ],
)
def test_requires_etf_execution_and_charge_branch_reports(
    tmp_path: Path, relative_path: str
) -> None:
    root = tmp_path / "project"
    _source(root, relative_path)
    report = _report(tmp_path / "coverage.json", {})
    assert _load_checker().check_critical_branch_coverage(report, root) == [
        f"missing branch coverage for {relative_path}",
    ]


def test_requires_historical_account_journal_branches(tmp_path: Path) -> None:
    root = tmp_path / "project"
    names = ("options_account_journal.py", "options_account_journal_models.py")
    for name in names:
        _source(root, "src/trading_bot/research/" + name)
    report = _report(tmp_path / "coverage.json", {})
    assert _load_checker().check_critical_branch_coverage(report, root) == [
        "missing branch coverage for src/trading_bot/research/" + name for name in names
    ]


def test_fails_a_single_module_below_threshold_even_if_the_combined_rate_is_90_percent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    _source(root, "src/trading_bot/risk/below_threshold.py")
    _source(root, "src/trading_bot/execution/above_threshold.py")
    report = _report(
        tmp_path / "coverage.json",
        {
            "src/trading_bot/risk/below_threshold.py": _entry(10, 8),
            "src/trading_bot/execution/above_threshold.py": _entry(10, 10),
        },
    )

    errors = _load_checker().check_critical_branch_coverage(report, root)

    assert errors == ["branch coverage below 90% for src/trading_bot/risk/below_threshold.py: 8/10"]


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({}, "missing branch summary"),
        (_entry(10, None), "invalid branch counters"),
        (_entry(-1, 0), "invalid branch counters"),
        (_entry(2, 3), "invalid branch counters"),
    ],
)
def test_fails_for_absent_or_invalid_branch_counters(
    tmp_path: Path, entry: dict[str, object], expected: str
) -> None:
    root = tmp_path / "project"
    _source(root, "src/trading_bot/risk/counters.py")
    report = _report(tmp_path / "coverage.json", {"src/trading_bot/risk/counters.py": entry})

    errors = _load_checker().check_critical_branch_coverage(report, root)

    assert errors == [f"{expected} for src/trading_bot/risk/counters.py"]


def test_accepts_zero_branch_module_only_with_measured_counters(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _source(root, "src/trading_bot/risk/linear.py")
    report = _report(
        tmp_path / "coverage.json",
        {"src/trading_bot/risk/linear.py": _entry(0, 0)},
    )

    assert _load_checker().check_critical_branch_coverage(report, root) == []


@pytest.mark.parametrize("branch_coverage", [False, None])
def test_fails_when_report_was_not_collected_with_branch_coverage(
    tmp_path: Path, branch_coverage: object
) -> None:
    root = tmp_path / "project"
    _source(root, "src/trading_bot/risk/line_only.py")
    report = _report(
        tmp_path / "coverage.json",
        {"src/trading_bot/risk/line_only.py": _entry(0, 0)},
        branch_coverage=branch_coverage,
    )

    errors = _load_checker().check_critical_branch_coverage(report, root)

    assert errors == ["coverage report meta.branch_coverage is not true"]


def test_rejects_report_path_that_only_matches_by_suffix(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _source(root, "src/trading_bot/risk/identity.py")
    report = _report(
        tmp_path / "coverage.json",
        {"somewhere/src/trading_bot/risk/identity.py": _entry(10, 10)},
    )

    errors = _load_checker().check_critical_branch_coverage(report, root)

    assert errors == ["missing branch coverage for src/trading_bot/risk/identity.py"]


def test_rejects_duplicate_report_aliases_for_a_critical_file(tmp_path: Path) -> None:
    root = tmp_path / "project"
    source = _source(root, "src/trading_bot/risk/duplicated.py")
    report = _report(
        tmp_path / "coverage.json",
        {
            str(source): _entry(10, 10),
            "src/trading_bot/risk/duplicated.py": _entry(10, 10),
        },
    )

    errors = _load_checker().check_critical_branch_coverage(report, root)

    assert errors == ["duplicate branch coverage entries for src/trading_bot/risk/duplicated.py"]


def test_rejects_a_root_without_discovered_critical_modules(tmp_path: Path) -> None:
    root = tmp_path / "empty-project"
    root.mkdir()
    report = _report(tmp_path / "coverage.json", {})

    assert _load_checker().check_critical_branch_coverage(report, root) == [
        "no critical source modules discovered"
    ]
