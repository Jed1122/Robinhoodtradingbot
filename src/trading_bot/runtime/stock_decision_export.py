"""Separate minimal decision projection; dashboard read path never takes a write lease."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from contextlib import suppress
from decimal import localcontext
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from trading_bot.config import LoadedConfig
from trading_bot.market_data.recording import canonical_json
from trading_bot.research.stock_decision_dashboard import (
    DecisionReason,
    DecisionRow,
    DecisionSource,
    DecisionTrack,
    StockDecisionExport,
)
from trading_bot.runtime.stock_dashboard_export import _directory, _policy, _private

if TYPE_CHECKING:
    from trading_bot.research.stock_investment_decisions import StockDecisionReason
    from trading_bot.runtime.stock_investment_plan import CurrentStockPlan

_NAME = "stock-decisions.json"
_MAX_BYTES = 262144
_ENTRY = re.compile(r"(?:stock-decisions\.json|\.stock-research\.lock|\.pending-[0-9a-f]{32})\Z")


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("stock_decision_export_unavailable")


def _track(plan: CurrentStockPlan, horizon: Literal["long_term", "tactical"]) -> DecisionTrack:
    decisions = (
        []
        if plan.rankings is None
        else [r for r in plan.rankings.assessments if r.horizon == horizon]
    )
    ranked = sorted(
        (r for r in decisions if r.ordinal_rank is not None),
        key=lambda r: (r.ordinal_rank, r.symbol),
    )
    remaining = sorted((r for r in decisions if r.ordinal_rank is None), key=lambda r: r.symbol)
    selected = [*ranked[:20], *remaining[:20]]
    eligible_expiries = [
        r.expires_at for r in decisions if r.analytically_eligible and r.expires_at is not None
    ]
    _check(len(eligible_expiries) == sum(r.analytically_eligible for r in decisions))
    rows = []
    for row in selected:

        def reasons(values: tuple[StockDecisionReason, ...]) -> list[DecisionReason]:
            return [
                DecisionReason(
                    code=r.code,
                    fact_name=r.fact_name,
                    value=None if r.value is None else str(r.value),
                    basis=r.basis,
                )
                for r in values
            ]

        rows.append(
            DecisionRow(
                symbol=row.symbol,
                horizon=row.horizon,
                action=row.action,
                analytically_eligible=row.analytically_eligible,
                ordinal_rank=row.ordinal_rank,
                priority_score=None if row.priority_score is None else str(row.priority_score),
                as_of=row.as_of,
                source_received_at=row.source_received_at,
                expires_at=row.expires_at,
                decision_hash=row.decision_hash,
                bullish_evidence=reasons(row.bullish_evidence),
                bearish_evidence=reasons(row.bearish_evidence),
                missing_requirements=list(row.missing_requirements),
                limitations=list(row.limitations),
                sources=[
                    DecisionSource(
                        tool=s.tool,
                        observation_sha256=s.observation_sha256,
                        record_ref=s.record_ref,
                        received_at=s.received_at,
                    )
                    for s in row.source_refs
                ],
            )
        )
    return DecisionTrack(
        horizon=horizon,
        assessed_count=len(decisions),
        eligible_count=sum(r.analytically_eligible for r in decisions),
        omitted_count=len(decisions) - len(rows),
        earliest_eligible_expiry=min(eligible_expiries, default=None),
        decisions=rows,
    )


def project_current_stock_decisions(
    plan: CurrentStockPlan, report_body_sha256: str
) -> StockDecisionExport:
    from trading_bot.runtime.stock_investment_plan import CurrentStockPlan

    try:
        _check(type(plan) is CurrentStockPlan)
        identity = plan.evidence_hash
        with localcontext() as context:
            context.capitals = 1
            return StockDecisionExport(
                generated_at=plan.as_of,
                source_config_hash=plan.source_config_hash,
                analysis_code_hash=plan.analysis_code_hash,
                policy_hash=plan.policy_hash,
                report_body_sha256=report_body_sha256,
                report_evidence_hash=identity,
                plan_status="research_only"
                if plan.allocation is None
                else "portfolio_cash_ceilings",
                needs=list(plan.needs),
                long_term=_track(plan, "long_term"),
                tactical=_track(plan, "tactical"),
            )
    except Exception:
        raise ValueError("stock_decision_export_unavailable") from None


def _body(export: StockDecisionExport) -> bytes:
    _check(type(export) is StockDecisionExport)
    checked = StockDecisionExport.model_validate(export.model_dump())
    body = canonical_json(checked.model_dump(mode="json")).encode()
    _check(0 < len(body) <= _MAX_BYTES)
    return body


def _read(directory: int) -> StockDecisionExport:
    fd = os.open(
        _NAME, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
    )
    try:
        info = os.fstat(fd)
        _check(_private(info) and 0 < info.st_size <= _MAX_BYTES)
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(_MAX_BYTES + 1)
        _check(len(raw) == info.st_size)
        export = StockDecisionExport.model_validate_json(raw)
        _check(_body(export) == raw)
        named = os.stat(_NAME, dir_fd=directory, follow_symlinks=False)
        _check(_private(named) and (named.st_dev, named.st_ino) == (info.st_dev, info.st_ino))
        return export
    finally:
        os.close(fd)


def _inventory(directory: int) -> None:
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries):
            info = entry.stat(follow_symlinks=False)
            _check(
                index < 64
                and _ENTRY.fullmatch(entry.name) is not None
                and _private(info)
                and info.st_size <= _MAX_BYTES
            )


def _write_projection(root: Path, body: bytes) -> None:
    from trading_bot.runtime.stock_archive_lease import StockArchiveLease

    with _directory(root) as directory:
        _inventory(directory)
        with StockArchiveLease(root, _directory_fd=directory):
            _inventory(directory)
            space = os.fstatvfs(directory)
            _check(space.f_bavail * space.f_frsize >= len(body) + 8192 and space.f_favail >= 1)
            temporary = ".pending-" + uuid.uuid4().hex
            try:
                fd = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=directory,
                )
                with os.fdopen(fd, "wb") as stream:
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
                _inventory(directory)
                os.replace(temporary, _NAME, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
                _check(_body(_read(directory)) == body)
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=directory)


def publish_stock_decisions(*, root: Path, export: StockDecisionExport) -> dict[str, object]:
    try:
        body = _body(export)
        _write_projection(root, body)
        return {
            "status": "published",
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }
    except Exception:
        raise ValueError("stock_decision_export_unavailable") from None


class StockDecisionReader:
    def __init__(self, *, root: Path, loaded: LoadedConfig) -> None:
        policy = _policy(loaded)
        self._root = root
        self._config_hash = str(loaded.config_hash)
        self._maximum_age_seconds = policy.stock_research.maximum_source_age_minutes * 60

    @property
    def maximum_age_seconds(self) -> int:
        return self._maximum_age_seconds

    def __call__(self) -> StockDecisionExport:
        try:
            with _directory(self._root) as directory:
                export = _read(directory)
            _check(export.source_config_hash == self._config_hash)
            return export
        except Exception:
            raise ValueError("stock_decision_export_unavailable") from None
