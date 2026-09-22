"""Fail CI when critical modules fall below the per-file branch threshold."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

MINIMUM_BRANCH_COVERAGE_PERCENT = 90
SOURCE_ROOT = Path("src/trading_bot")


def _critical_modules(root: Path) -> tuple[Path, ...]:
    source_root = root / SOURCE_ROOT
    modules: list[Path] = []
    for directory in ("risk", "execution", "lifecycle"):
        candidate = source_root / directory
        if candidate.is_dir():
            modules.extend(candidate.rglob("*.py"))

    order_state_machine = source_root / "domain" / "order_state_machine.py"
    if order_state_machine.is_file():
        modules.append(order_state_machine)

    capability_verification = source_root / "capabilities" / "verification.py"
    if capability_verification.is_file():
        modules.append(capability_verification)

    for filename in ("lease.py", "options_trial.py", "options_risk.py"):
        persistence_module = source_root / "persistence" / filename
        if persistence_module.is_file():
            modules.append(persistence_module)

    recorded_options_runtime = source_root / "runtime" / "options_recorded_session.py"
    if recorded_options_runtime.is_file():
        modules.append(recorded_options_runtime)

    for relative_path in (
        Path("domain/options_account.py"),
        Path("reconciliation/options.py"),
        Path("runtime/options_monitor.py"),
    ):
        options_module = source_root / relative_path
        if options_module.is_file():
            modules.append(options_module)

    simulation_directory = source_root / "simulation"
    if simulation_directory.is_dir():
        modules.extend(simulation_directory.glob("lifecycle*.py"))
        modules.extend(simulation_directory.glob("options_replay*.py"))

    return tuple(sorted((module.resolve() for module in modules), key=str))


def _normalize_report_path(report_path: str, root: Path) -> Path | None:
    candidate = Path(report_path)
    normalized = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        normalized.relative_to(root)
    except ValueError:
        return None
    return normalized


def _coverage_by_source_path(files: Mapping[str, Any], root: Path) -> dict[Path, list[Any]]:
    normalized: dict[Path, list[Any]] = {}
    for report_path, details in files.items():
        if not isinstance(report_path, str):
            continue
        source_path = _normalize_report_path(report_path, root)
        if source_path is not None:
            normalized.setdefault(source_path, []).append(details)
    return normalized


def _branch_counters(details: Any) -> tuple[int, int] | None:
    if not isinstance(details, Mapping):
        return None
    summary = details.get("summary")
    if not isinstance(summary, Mapping):
        return None
    total = summary.get("num_branches")
    covered = summary.get("covered_branches")
    if (
        isinstance(total, bool)
        or isinstance(covered, bool)
        or not isinstance(total, int)
        or not isinstance(covered, int)
        or total < 0
        or covered < 0
        or covered > total
    ):
        return None
    return total, covered


def check_critical_branch_coverage(report: Path, root: Path) -> list[str]:
    """Return deterministic errors for critical modules that fail branch coverage."""
    root = root.resolve()
    modules = _critical_modules(root)
    if not modules:
        return ["no critical source modules discovered"]
    try:
        payload = json.loads(report.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return [f"cannot read coverage report: {error}"]

    meta = payload.get("meta") if isinstance(payload, Mapping) else None
    if not isinstance(meta, Mapping) or meta.get("branch_coverage") is not True:
        return ["coverage report meta.branch_coverage is not true"]

    files = payload.get("files") if isinstance(payload, Mapping) else None
    if not isinstance(files, Mapping):
        return ["coverage report has no files mapping"]

    measured = _coverage_by_source_path(files, root)
    errors: list[str] = []
    for module in modules:
        relative = module.relative_to(root).as_posix()
        entries = measured.get(module)
        if entries is None:
            errors.append(f"missing branch coverage for {relative}")
            continue
        if len(entries) > 1:
            errors.append(f"duplicate branch coverage entries for {relative}")
            continue
        details = entries[0]
        counters = _branch_counters(details)
        if counters is None:
            summary = details.get("summary") if isinstance(details, Mapping) else None
            message = "invalid branch counters"
            if not isinstance(summary, Mapping):
                message = "missing branch summary"
            errors.append(f"{message} for {relative}")
            continue
        total, covered = counters
        if total and covered * 100 < total * MINIMUM_BRANCH_COVERAGE_PERCENT:
            errors.append(
                f"branch coverage below {MINIMUM_BRANCH_COVERAGE_PERCENT}% for {relative}: "
                f"{covered}/{total}"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path, help="pytest-cov JSON report")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    arguments = parser.parse_args()

    errors = check_critical_branch_coverage(arguments.report, arguments.root)
    if errors:
        for error in errors:
            print(f"critical branch coverage: {error}")
        return 1
    print("critical branch coverage: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
