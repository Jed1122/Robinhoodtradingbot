"""Canonical research reports that retain accepted and rejected attempts."""

from dataclasses import dataclass

from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.metrics import PerformanceMetrics

DISCLAIMER = "Research results do not guarantee future performance or profitability."


@dataclass(frozen=True, slots=True)
class ResearchAttempt:
    family: str
    parameter_hash: str
    status: str
    reason_codes: tuple[str, ...]
    metrics: PerformanceMetrics | None


@dataclass(frozen=True, slots=True)
class ResearchRunRecord:
    run_id: str
    strategy_version: str
    code_hash: str
    config_hash: str
    data_manifest_hash: str
    cost_assumptions: tuple[tuple[str, str], ...]
    parameter_grid: tuple[tuple[str, tuple[str, ...]], ...]
    data_limitations: tuple[str, ...]
    code_clean: bool = True


@dataclass(frozen=True, slots=True)
class ResearchReport:
    run: ResearchRunRecord
    attempts: tuple[ResearchAttempt, ...]
    disclaimer: str
    report_hash: str


def build_research_report(
    run: ResearchRunRecord, *, attempts: tuple[ResearchAttempt, ...]
) -> ResearchReport:
    payload = {"attempts": attempts, "disclaimer": DISCLAIMER, "run": run}
    return ResearchReport(run, attempts, DISCLAIMER, content_hash(payload))


def render_json(report: ResearchReport) -> str:
    return canonical_json(report)


def render_markdown(report: ResearchReport) -> str:
    lines = [
        f"# Research Report {report.run.run_id}",
        "",
        f"Strategy: `{report.run.strategy_version}`",
        (
            f"Code/config/data: `{report.run.code_hash}` / `{report.run.config_hash}` / "
            f"`{report.run.data_manifest_hash}`"
        ),
        "",
        "## Data limitations",
        *(f"- {item}" for item in report.run.data_limitations),
        "",
        "## Cost assumptions",
        *(f"- {name}: {value}" for name, value in report.run.cost_assumptions),
        "",
        "## Parameter grid",
        *(f"- {name}: {', '.join(values)}" for name, values in report.run.parameter_grid),
        "",
        "## Attempted candidates",
        *(
            f"- {item.family} [{item.status}]: {', '.join(item.reason_codes)}"
            for item in report.attempts
        ),
        "",
        f"> {report.disclaimer}",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "ResearchAttempt",
    "ResearchReport",
    "ResearchRunRecord",
    "build_research_report",
    "render_json",
    "render_markdown",
]
