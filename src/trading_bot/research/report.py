"""Canonical research reports that retain accepted and rejected attempts."""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_bot.clock import require_utc
from trading_bot.domain import Bar, DataHash
from trading_bot.market_data.recording import (
    ResearchDataManifest,
    canonical_json,
    content_hash,
)
from trading_bot.research.metrics import PerformanceMetrics

DISCLAIMER = "Research results do not guarantee future performance or profitability."
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class ResearchDatasetSnapshot:
    """Canonical cleaned bars and request provenance retained with the report."""

    as_of: datetime
    requested_start: datetime
    requested_end: datetime
    bars_by_symbol: tuple[tuple[str, tuple[Bar, ...]], ...]
    raw_hashes: tuple[DataHash, ...]
    provider_evidence_hash: str
    collection_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.as_of)
        require_utc(self.requested_start)
        require_utc(self.requested_end)
        if self.requested_start >= self.requested_end or self.requested_end != self.as_of:
            raise ValueError("research request interval is invalid")
        symbols = tuple(symbol for symbol, _ in self.bars_by_symbol)
        if len(symbols) != len(set(symbols)):
            raise ValueError("research dataset contains duplicate symbols")

    @property
    def cleaned_hashes(self) -> tuple[DataHash, ...]:
        return tuple(
            content_hash({"bars": bars, "symbol": symbol})
            for symbol, bars in self.bars_by_symbol
        )


@dataclass(frozen=True, slots=True)
class ResearchAttempt:
    family: str
    parameter_hash: str
    status: str
    reason_codes: tuple[str, ...]
    metrics: PerformanceMetrics | None
    strategy_id: str = ""
    strategy_version: str = ""
    parameters: tuple[tuple[str, str], ...] = ()
    stressed_metrics: PerformanceMetrics | None = None
    fold_total_returns_pct: tuple[Decimal, ...] = ()
    benchmark_total_return_pct: Decimal | None = None
    monte_carlo_loss_probability_pct: Decimal | None = None
    maximum_single_opportunity_profit_contribution_pct: Decimal | None = None
    parameter_neighbor_stressed_total_returns_pct: tuple[Decimal | None, ...] = ()


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
    code_clean: bool = False
    universe_symbols: tuple[str, ...] = ()
    benchmark_symbol: str = ""
    provider_evidence_hash: str = ""
    run_reason_codes: tuple[str, ...] = ()
    data_manifest: ResearchDataManifest | None = None
    dataset_snapshot: ResearchDatasetSnapshot | None = None
    selected_strategy_id: str = ""
    selected_strategy_version: str = ""
    selected_parameter_hash: str = ""


@dataclass(frozen=True, slots=True)
class ResearchReport:
    run: ResearchRunRecord
    attempts: tuple[ResearchAttempt, ...]
    disclaimer: str
    report_hash: str


def candidate_promotion_identity(
    strategy_id: str,
    strategy_version: str,
    parameter_hash: str,
) -> str:
    return f"{strategy_id}:{strategy_version}:{parameter_hash}"


def _report_payload(
    run: ResearchRunRecord,
    attempts: tuple[ResearchAttempt, ...],
    disclaimer: str,
) -> dict[str, object]:
    return {"attempts": attempts, "disclaimer": disclaimer, "run": run}


def build_research_report(
    run: ResearchRunRecord, *, attempts: tuple[ResearchAttempt, ...]
) -> ResearchReport:
    payload = _report_payload(run, attempts, DISCLAIMER)
    return ResearchReport(run, attempts, DISCLAIMER, content_hash(payload))


def report_integrity_reason_codes(report: ResearchReport) -> tuple[str, ...]:
    """Recompute every persisted content-addressing relationship."""

    reasons: set[str] = set()
    if _SHA256_HEX.fullmatch(str(report.report_hash)) is None or str(
        content_hash(_report_payload(report.run, report.attempts, report.disclaimer))
    ) != str(report.report_hash):
        reasons.add("report_hash_invalid")
    if report.disclaimer != DISCLAIMER:
        reasons.add("research_disclaimer_invalid")
    if (
        type(report.run.code_clean) is not bool
        or any(
            _SHA256_HEX.fullmatch(value) is None
            for value in (
                report.run.code_hash,
                report.run.config_hash,
                report.run.data_manifest_hash,
                report.run.provider_evidence_hash,
            )
        )
    ):
        reasons.add("research_identity_hash_invalid")
    manifest = report.run.data_manifest
    snapshot = report.run.dataset_snapshot
    if manifest is None:
        reasons.add("data_manifest_preimage_missing")
    else:
        rebuilt = ResearchDataManifest.create(
            raw_hashes=manifest.raw_hashes,
            cleaned_hashes=manifest.cleaned_hashes,
            corporate_action_coverage=manifest.corporate_action_coverage,
            point_in_time_universe=manifest.point_in_time_universe,
            survivorship_limitations=manifest.survivorship_limitations,
            licensing_limitations=manifest.licensing_limitations,
            known_gaps=manifest.known_gaps,
        )
        if (
            rebuilt.manifest_hash != manifest.manifest_hash
            or str(manifest.manifest_hash) != report.run.data_manifest_hash
        ):
            reasons.add("data_manifest_hash_invalid")
    if snapshot is None:
        reasons.add("research_dataset_snapshot_missing")
    elif manifest is not None and (
        snapshot.raw_hashes != manifest.raw_hashes
        or snapshot.cleaned_hashes != manifest.cleaned_hashes
        or snapshot.provider_evidence_hash != report.run.provider_evidence_hash
        or not set(snapshot.collection_reason_codes).issubset(manifest.known_gaps)
    ):
        reasons.add("research_dataset_manifest_mismatch")
    return tuple(sorted(reasons))


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
            (
                f"- {item.family} / {item.strategy_version or item.strategy_id} "
                f"[{item.status}]: {', '.join(item.reason_codes)}"
            )
            for item in report.attempts
        ),
        "",
        f"> {report.disclaimer}",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "ResearchAttempt",
    "ResearchDatasetSnapshot",
    "ResearchReport",
    "ResearchRunRecord",
    "build_research_report",
    "candidate_promotion_identity",
    "render_json",
    "render_markdown",
    "report_integrity_reason_codes",
]
