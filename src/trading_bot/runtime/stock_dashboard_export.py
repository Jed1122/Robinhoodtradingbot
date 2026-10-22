"""Private stock projection storage; the dashboard reader never opens a broker or ledger."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trading_bot.clock import require_utc
from trading_bot.config import LoadedConfig
from trading_bot.config.loader import restore_loaded_config
from trading_bot.config.stock_research import StockWorkerAppConfig
from trading_bot.domain import CodeHash
from trading_bot.market_data.bundle_store import _open_root
from trading_bot.market_data.recording import canonical_json
from trading_bot.research.stock_dashboard import StockDashboardExport

if TYPE_CHECKING:
    from trading_bot.persistence.stock_research_jobs import StockResearchJobState

_NAME = "stock-research.json"
_MAX_BYTES = 262144
_MAX_FILES = 64
_ENTRY = re.compile(r"(?:stock-research\.json|\.stock-research\.lock|\.pending-[0-9a-f]{32})\Z")


class StockDashboardExportError(ValueError):
    """Fixed local error without paths, provider text or credentials."""


def _policy(loaded: LoadedConfig) -> StockWorkerAppConfig:
    restored = restore_loaded_config(loaded.canonical_json, loaded.config_hash)
    if restored != loaded or type(restored.config) is not StockWorkerAppConfig:
        raise StockDashboardExportError("stock_dashboard_export_unavailable")
    return StockWorkerAppConfig.model_validate(restored.config.model_dump())


def _private(info: os.stat_result) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
    )


@contextmanager
def _directory(root: Path) -> Iterator[int]:
    descriptor = -1
    try:
        if not root.is_absolute() or root.resolve(strict=True) != root:
            raise ValueError
        descriptor = _open_root(root, Path(__file__).resolve().parents[3])
        info = os.fstat(descriptor)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError
        yield descriptor
    except Exception:
        raise StockDashboardExportError("stock_dashboard_export_unavailable") from None
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                raise StockDashboardExportError("stock_dashboard_export_unavailable") from None


def _body(export: StockDashboardExport) -> bytes:
    if type(export) is not StockDashboardExport:
        raise ValueError
    checked = StockDashboardExport.model_validate(export.model_dump())
    body = canonical_json(checked.model_dump(mode="json")).encode()
    if not 0 < len(body) <= _MAX_BYTES:
        raise ValueError
    return body


def _read(directory: int) -> StockDashboardExport:
    descriptor = os.open(
        _NAME, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
    )
    try:
        info = os.fstat(descriptor)
        if not _private(info) or not 0 < info.st_size <= _MAX_BYTES:
            raise ValueError
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            body = stream.read(_MAX_BYTES + 1)
        if len(body) != info.st_size:
            raise ValueError
        projection = StockDashboardExport.model_validate_json(body)
        if _body(projection) != body:
            raise ValueError
        named = os.stat(_NAME, dir_fd=directory, follow_symlinks=False)
        if not _private(named) or (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError
        return projection
    finally:
        os.close(descriptor)


def _inventory(directory: int) -> None:
    count = 0
    with os.scandir(directory) as entries:
        for entry in entries:
            count += 1
            info = entry.stat(follow_symlinks=False)
            if (
                count >= _MAX_FILES
                or _ENTRY.fullmatch(entry.name) is None
                or not _private(info)
                or info.st_size > _MAX_BYTES
            ):
                raise ValueError


def publish_stock_dashboard(*, root: Path, export: StockDashboardExport) -> dict[str, object]:
    """Atomically replace only the derived projection; never repair/delete unrelated files."""
    try:
        body = _body(export)
        with _directory(root) as directory:
            _inventory(directory)  # No lock file is created in an unrelated directory.
            from trading_bot.runtime.stock_archive_lease import StockArchiveLease

            with StockArchiveLease(root, _directory_fd=directory):
                _inventory(directory)
                space = os.fstatvfs(directory)
                if space.f_bavail * space.f_frsize < len(body) + 8192 or space.f_favail < 1:
                    raise ValueError
                temporary = ".pending-" + uuid.uuid4().hex
                try:
                    descriptor = os.open(
                        temporary,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                        0o600,
                        dir_fd=directory,
                    )
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(body)
                        stream.flush()
                        os.fsync(stream.fileno())
                    _inventory(directory)
                    os.replace(temporary, _NAME, src_dir_fd=directory, dst_dir_fd=directory)
                    os.fsync(directory)
                    if _body(_read(directory)) != body:
                        raise ValueError
                finally:
                    with suppress(FileNotFoundError):
                        os.unlink(temporary, dir_fd=directory)
        return {
            "status": "published",
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }
    except Exception:
        raise StockDashboardExportError("stock_dashboard_export_unavailable") from None


class StockDashboardReader:
    """Optional synchronous filesystem reader; no database/provider/credential operation."""

    def __init__(self, *, root: Path, loaded: LoadedConfig) -> None:
        policy = _policy(loaded)
        self._root, self._config_hash = root, str(loaded.config_hash)
        self._maximum_age_seconds = policy.stock_research.maximum_source_age_minutes * 60

    @property
    def maximum_age_seconds(self) -> int:
        return self._maximum_age_seconds

    def __call__(self) -> StockDashboardExport:
        try:
            with _directory(self._root) as directory:
                projection = _read(directory)
            if projection.config_hash != self._config_hash:
                raise ValueError
            return projection
        except Exception:
            raise StockDashboardExportError("stock_dashboard_export_unavailable") from None


def _projection(
    *,
    state: StockResearchJobState,
    loaded: LoadedConfig,
    code_hash: CodeHash,
    policy: StockWorkerAppConfig,
    now: datetime,
    discovery: dict[str, Any] | None,
    enrichment: dict[str, Any] | None,
) -> StockDashboardExport:
    latest = state.claims[-1] if state.claims else None
    result = next(
        (row for row in state.results if latest and row.claim_id == latest.claim_id), None
    )
    last_result = state.results[-1] if state.results else None
    worker = {
        "last_claim_at": latest.claimed_at if latest else None,
        "last_result_at": result.recorded_at
        if result
        else last_result.recorded_at
        if last_result
        else None,
        "phase": latest.phase if latest else None,
        "status": result.status if result else "pending" if latest else "never_run",
        "reason": result.reason if result else None,
        "pending_claims": state.pending_count,
        "reserved_today": state.reserved_today,
        "daily_limit": policy.stock_research.max_daily_calls,
        "remaining_calls": max(0, policy.stock_research.max_daily_calls - state.reserved_today),
        "next_eligible_at": latest.claimed_at
        + timedelta(minutes=max(latest.scan_minutes, policy.stock_research.scan_minutes))
        if latest
        else None,
    }
    projected: dict[str, Any] = {}
    for phase, head, report in (
        ("discovery", state.discovery_head, discovery),
        ("enrichment", state.enrichment_head, enrichment),
    ):
        projected[phase] = None
        if head is None or report is None:
            continue
        claim = next(row for row in state.claims if row.claim_id == head.claim_id)
        section: dict[str, Any] = {
            "claimed_at": claim.claimed_at,
            "as_of": datetime.fromisoformat(report["as_of"]),
            "report_sha256": head.report_sha256,
            "manifest_sha256": head.manifest_sha256,
        }
        if phase == "discovery":
            screen = report["screen"]
            section.update(
                {
                    "candidate_count": screen["candidate_count"],
                    "scorable_count": screen["scorable_count"],
                    "opportunities": [
                        {
                            "symbol": row["symbol"],
                            "research_priority_score": row["research_priority_score"],
                            "available_at": datetime.fromisoformat(row["available_at"]),
                            "source_observation_sha256": row["source_observation_sha256"],
                            "metrics": {
                                name: row["metrics"][name]
                                for name in (
                                    "roe",
                                    "net_margin",
                                    "annual_eps_growth",
                                    "quarterly_revenue_growth",
                                    "earnings_yield",
                                    "fcf_yield",
                                )
                            },
                        }
                        for row in screen["opportunities"]
                    ],
                }
            )
        else:
            section["dossiers"] = [
                {"symbol": row["symbol"], "gaps": row["gaps"]} for row in report["dossiers"]
            ]
        projected[phase] = section
    return StockDashboardExport.model_validate(
        {
            "schema_version": 1,
            "kind": "stock_research_dashboard",
            "generated_at": now,
            "config_hash": str(loaded.config_hash),
            "code_hash": str(code_hash),
            "state_sha256": state.state_hash,
            "worker": worker,
            **projected,
            "qualified": False,
            "investment_eligible": False,
            "live_enabled": False,
        }
    )


async def export_stock_dashboard(
    *,
    loaded: LoadedConfig,
    code_hash: CodeHash,
    factory: object,
    archive_dir: Path,
    export_dir: Path,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Reconstruct under the acquisition lease; rehash all evidence before exporting."""
    try:
        policy = _policy(loaded)
        from trading_bot.persistence.stock_research_jobs import SqlStockResearchJobs
        from trading_bot.runtime.stock_archive_lease import StockArchiveLease
        from trading_bot.runtime.stock_research_worker import _cached

        with StockArchiveLease(archive_dir) as archive:
            with _directory(export_dir) as directory:
                a, b = os.fstat(archive.directory_fd), os.fstat(directory)
                if (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino):
                    raise ValueError
            jobs = SqlStockResearchJobs(factory, loaded=loaded, code_hash=code_hash, clock=clock)
            state = await jobs.snapshot()
            now = require_utc(state.observed_at)
            discovery, enrichment = _cached(
                state=state, archive=archive, root=archive_dir, policy=policy, now=now
            )
            projection = _projection(
                state=state,
                loaded=loaded,
                code_hash=code_hash,
                policy=policy,
                now=now,
                discovery=discovery,
                enrichment=enrichment,
            )
            if require_utc(clock()) < now:
                raise ValueError
            return publish_stock_dashboard(root=export_dir, export=projection)
    except Exception:
        raise StockDashboardExportError("stock_dashboard_export_unavailable") from None
