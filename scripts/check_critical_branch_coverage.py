"""Fail CI when critical modules fall below the per-file branch threshold."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

MINIMUM_BRANCH_COVERAGE_PERCENT = 90
MINIMUM_STOCK_HOST_COVERAGE_PERCENT = 95
SOURCE_ROOT = Path("src/trading_bot")


def _critical_modules(root: Path) -> tuple[Path, ...]:
    """Retained shared safety modules; legacy strategy gates are retired."""
    source_root = root / SOURCE_ROOT
    modules: set[Path] = set()
    for directory in ("risk", "execution", "lifecycle"):
        modules.update((source_root / directory).rglob("*.py"))
    for relative in (
        "domain/order_state_machine.py",
        "domain/owned_order_lifecycle.py",
        "capabilities/verification.py",
        "persistence/lease.py",
        "persistence/owned_order_journal.py",
        "persistence/owned_economic_journal.py",
        "persistence/paper_cycle_journal.py",
        "runtime/paper_promotion.py",
        "runtime/paper_promotion_runtime.py",
    ):
        candidate = source_root / relative
        if candidate.is_file():
            modules.add(candidate)
    modules.update((source_root / "accounting").glob("*.py"))
    modules.update((source_root / "simulation").glob("lifecycle*.py"))
    return tuple(
        sorted(
            (path.resolve() for path in modules if not path.name.startswith(("options", "etf_"))),
            key=str,
        )
    )


def _stock_modules(root: Path) -> tuple[Path, ...]:
    """Require whole current stock modules, including unexecuted source files."""
    source_root = root / SOURCE_ROOT
    modules = set(source_root.rglob("stock_*.py"))
    modules.update((source_root / "hybrid").glob("*.py"))
    modules.update((root / "infra/hybrid").glob("stock_*.py"))
    for relative in (
        "market_data/alpaca_stock_minutes.py",
        "market_data/sec_submissions.py",
        "market_data/sec_companyfacts.py",
    ):
        candidate = source_root / relative
        if candidate.is_file():
            modules.add(candidate)
    return tuple(sorted((path.resolve() for path in modules), key=str))


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
    critical = set(_critical_modules(root))
    modules = sorted(critical | set(_stock_modules(root)), key=str)
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
    host_total = host_covered = 0
    host_valid = True
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
        if module in critical and total and covered * 100 < total * MINIMUM_BRANCH_COVERAGE_PERCENT:
            errors.append(
                f"branch coverage below {MINIMUM_BRANCH_COVERAGE_PERCENT}% for {relative}: "
                f"{covered}/{total}"
            )
        if module.parent == (root / "infra/hybrid"):
            summary = details["summary"]
            statements = summary.get("num_statements")
            covered_lines = summary.get("covered_lines")
            if (
                type(statements) is not int
                or type(covered_lines) is not int
                or statements < 0
                or covered_lines < 0
                or covered_lines > statements
            ):
                errors.append(f"invalid statement counters for {relative}")
                host_valid = False
            else:
                host_total += statements + total
                host_covered += covered_lines + covered
    hosts = tuple((root / "infra/hybrid").glob("stock_*.py"))
    if hosts and host_valid and not errors:
        if not host_total:
            errors.append("stock host coverage has no measured statements or branches")
        elif host_covered * 100 < host_total * MINIMUM_STOCK_HOST_COVERAGE_PERCENT:
            errors.append(
                f"stock host combined coverage below {MINIMUM_STOCK_HOST_COVERAGE_PERCENT}%: "
                f"{host_covered}/{host_total}"
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
