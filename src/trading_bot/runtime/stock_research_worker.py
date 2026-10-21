"""Durable one-shot individual-stock research; no account or execution operations."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import stat
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from trading_bot.brokers.robinhood_mcp_sdk import RobinhoodMcpSdkConnection
from trading_bot.brokers.stock_research_mcp import PROFILE_SHA256, StockResearchTransport
from trading_bot.clock import require_utc
from trading_bot.code_identity import resolve_code_identity, verify_deployed_image_attestation
from trading_bot.config import LoadedConfig, load_config
from trading_bot.config.loader import restore_loaded_config
from trading_bot.config.stock_research import StockWorkerAppConfig
from trading_bot.domain import CodeHash
from trading_bot.market_data.recording import canonical_json
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.stock_research_jobs import (
    Phase,
    SqlStockResearchJobs,
    StockResearchClaim,
    StockResearchJobError,
    StockResearchJobState,
    StockResearchResult,
)
from trading_bot.research.stock_requests import enrichment_requests
from trading_bot.research.stock_screen import discovery_requests, screen_stocks
from trading_bot.runtime.capability_capture import _suppress_untrusted_dependency_logs
from trading_bot.runtime.stock_archive import _read, read_stock_observations
from trading_bot.runtime.stock_archive_lease import StockArchiveError, StockArchiveLease
from trading_bot.runtime.stock_capture import (
    StockCaptureRequest,
    _json,
    _private_directory,
    _publish,
    _raise_pending_cancellation,
    capture_stock_observations,
    parse_stock_capture_plan,
)
from trading_bot.runtime.stock_dossier_report import (
    compile_stock_dossier_report,
    publish_stock_dossier_report,
)


class StockWorkerError(ValueError):
    """Fixed stage code; never external exception text."""


def _plan_hash(plan: tuple[StockCaptureRequest, ...]) -> str:
    return hashlib.sha256(
        _json([{"tool": item.tool, "arguments": item.arguments} for item in plan])
    ).hexdigest()


def _check(valid: bool, reason: str = "artifact_unavailable") -> None:
    if not valid:
        raise StockWorkerError(reason)


def _requests(
    phase: Phase, policy: StockWorkerAppConfig, at: datetime, symbols: tuple[str, ...]
) -> tuple[StockCaptureRequest, ...]:
    rows = (
        discovery_requests(policy.stock_research)
        if phase == "discovery"
        else list(enrichment_requests(symbols=symbols, as_of=at, policy=policy.stock_research))
    )
    return parse_stock_capture_plan(rows)


def _verified_capture(
    *,
    archive: StockArchiveLease,
    root: Path,
    claim: StockResearchClaim,
    plan: tuple[StockCaptureRequest, ...],
    manifest_sha256: str,
    now: datetime,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    manifest = _read(
        archive.directory_fd, manifest_sha256 + ".stock-capture.json", ".stock-capture.json"
    )
    observations = read_stock_observations(
        root, manifest_sha256 + ".stock-capture.json", _directory_fd=archive.directory_fd
    )
    _check(
        manifest["request_plan_sha256"] == claim.plan_sha256 == _plan_hash(plan)
        and manifest["planned_calls"] == claim.planned_calls == len(plan)
        and manifest["transport_authenticated"] is True
        and manifest["schema_profile_sha256"] == PROFILE_SHA256
    )
    start = require_utc(datetime.fromisoformat(manifest["started_at"]))
    end = require_utc(datetime.fromisoformat(manifest["completed_at"]))
    _check(claim.claimed_at <= start <= end <= now)
    for request, row in zip(plan, observations, strict=False):
        _check(row["tool"] == request.tool and row["arguments"] == request.arguments)
    if manifest["status"] == "complete":
        _check(end <= claim.deadline_at)
    return manifest, observations


def _screen_body(
    *,
    claim: StockResearchClaim,
    observations: tuple[dict[str, Any], ...],
    manifest_sha256: str,
    policy: StockWorkerAppConfig,
    at: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "claim_id": claim.claim_id,
        "config_hash": claim.config_hash,
        "code_hash": claim.code_hash,
        "schema_profile_sha256": PROFILE_SHA256,
        "source_manifest_sha256": manifest_sha256,
        "plan_sha256": claim.plan_sha256,
        "as_of": at.isoformat(),
        "screen": screen_stocks(
            [row for row in observations if row["tool"] == "preview_scan"],
            policy=policy.stock_research,
            as_of=at,
        ),
        "qualified": False,
        "investment_eligible": False,
        "live_enabled": False,
    }


def _symbols(report: dict[str, Any]) -> tuple[str, ...]:
    return tuple(row["symbol"] for row in report["screen"]["opportunities"])


def _cached(
    *,
    state: StockResearchJobState,
    archive: StockArchiveLease,
    root: Path,
    policy: StockWorkerAppConfig,
    now: datetime,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    discovery = enrichment = None
    for head in (state.discovery_head, state.enrichment_head):
        if head is None:
            continue
        claim = next(item for item in state.claims if item.claim_id == head.claim_id)
        _check(head.manifest_sha256 is not None and head.report_sha256 is not None)
        suffix = ".stock-screen.json" if head.phase == "discovery" else ".stock-dossiers.json"
        report = _read(archive.directory_fd, str(head.report_sha256) + suffix, suffix)
        at = require_utc(datetime.fromisoformat(report["as_of"]))
        _check(claim.claimed_at <= at <= head.recorded_at <= now)
        symbols: tuple[str, ...] = ()
        if head.phase == "enrichment":
            rows = read_stock_observations(
                root,
                str(head.manifest_sha256) + ".stock-capture.json",
                _directory_fd=archive.directory_fd,
            )
            symbols = tuple(
                symbol
                for row in rows
                if row["tool"] == "get_equity_fundamentals"
                for symbol in row["arguments"]["symbols"]
            )
        plan = _requests(head.phase, policy, claim.claimed_at, symbols)
        manifest, rows = _verified_capture(
            archive=archive,
            root=root,
            claim=claim,
            plan=plan,
            manifest_sha256=str(head.manifest_sha256),
            now=now,
        )
        _check(manifest["status"] == "complete")
        _check(require_utc(datetime.fromisoformat(manifest["completed_at"])) <= at)
        if head.phase == "discovery":
            expected = _screen_body(
                claim=claim,
                observations=rows,
                manifest_sha256=str(head.manifest_sha256),
                policy=policy,
                at=at,
            )
            _check(report == expected and report["screen"]["coverage_complete"] is True)
            discovery = report
        else:
            expected = compile_stock_dossier_report(observations=rows, as_of=at)
            expected["source_manifest_sha256"] = head.manifest_sha256
            _check(report == expected and report["normalization_denials"] == [])
            _check({row["symbol"] for row in report["dossiers"]} == set(symbols))
            enrichment = report
    return discovery, enrichment


def _select(
    *,
    state: StockResearchJobState,
    discovery: dict[str, Any] | None,
    enrichment: dict[str, Any] | None,
    policy: StockWorkerAppConfig,
    now: datetime,
) -> tuple[Phase, tuple[str, ...], str | None]:
    head = state.discovery_head
    if (
        head is not None
        and discovery is not None
        and state.claims
        and state.claims[-1].claim_id == head.claim_id
    ):
        source = next(item for item in state.claims if item.claim_id == head.claim_id)
        fresh = now - source.claimed_at <= timedelta(
            minutes=policy.stock_research.maximum_source_age_minutes
        )
        symbols = _symbols(discovery)
        due = enrichment is None
        if enrichment is not None and state.enrichment_head is not None:
            old = next(
                item for item in state.claims if item.claim_id == state.enrichment_head.claim_id
            )
            due = {row["symbol"] for row in enrichment["dossiers"]} != set(
                symbols
            ) or now - old.claimed_at >= timedelta(
                minutes=policy.stock_worker.enrichment_refresh_minutes
            )
        if fresh and symbols and due:
            return "enrichment", symbols, head.record_sha256
    return "discovery", (), None


def _summary(result: StockResearchResult, claim: StockResearchClaim) -> dict[str, object]:
    return {
        "status": result.status,
        "reason": result.reason,
        "phase": claim.phase,
        "claim_id": claim.claim_id,
        "planned_calls": claim.planned_calls,
        "attempted_calls": result.attempted_calls,
        "successful_calls": result.successful_calls,
        "manifest_sha256": result.manifest_sha256,
        "report_sha256": result.report_sha256,
        "qualified": False,
        "investment_eligible": False,
        "live_enabled": False,
    }


def _blocked(reason: str) -> dict[str, object]:
    return {"status": "blocked", "reason": reason, "live_enabled": False}


async def run_stock_research_cycle(
    *,
    loaded: LoadedConfig,
    code_hash: CodeHash,
    factory: object,
    oauth_store: Path,
    output_dir: Path,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """One cycle, committed reservation before SDK construction, no retries/catch-up.

    The runtime caller supplies verified code identity; this function does not attest
    an arbitrary injected hash. Cancellation or uncertain capture/commit leaves the
    full reservation pending. It never scans orphan files to guess a lost outcome.
    """
    started = monotonic()
    last = started
    try:
        restored = restore_loaded_config(loaded.canonical_json, loaded.config_hash)
        _check(restored == loaded and type(restored.config) is StockWorkerAppConfig)
        policy = StockWorkerAppConfig.model_validate(restored.config.model_dump())
        jobs = SqlStockResearchJobs(factory, loaded=loaded, code_hash=code_hash, clock=clock)
        deadline = started + policy.stock_worker.max_run_seconds
        active_claim: StockResearchClaim | None = None

        def gate() -> None:
            nonlocal last
            _raise_pending_cancellation()
            at = monotonic()
            _check(
                type(at) in {float, int} and math.isfinite(at) and last <= at < deadline,
                "runtime_failure",
            )
            if active_claim is not None:
                wall = require_utc(clock())
                _check(
                    active_claim.claimed_at <= wall < active_claim.deadline_at,
                    "runtime_failure",
                )
            last = at

        with StockArchiveLease(output_dir) as archive:
            gate()
            state = await jobs.snapshot()
            now = require_utc(clock())
            if state.claims:
                previous = state.claims[-1]
                minutes = max(previous.scan_minutes, policy.stock_research.scan_minutes)
                if now < previous.claimed_at + timedelta(minutes=minutes):
                    return _blocked("not_due")
            discovery, enrichment = _cached(
                state=state, archive=archive, root=output_dir, policy=policy, now=now
            )
            phase, symbols, source = _select(
                state=state, discovery=discovery, enrichment=enrichment, policy=policy, now=now
            )
            plan = _requests(phase, policy, now, symbols)
            plan_sha256 = _plan_hash(plan)
            archive.admit(remaining_calls=len(plan), policy=policy.stock_worker)
            gate()
            claim = await jobs.reserve(
                phase=phase,
                plan_sha256=plan_sha256,
                planned_calls=len(plan),
                expected_state_hash=state.state_hash,
                source_result_sha256=source,
            )
            active_claim = claim
            captured: dict[str, object] | None = None
            capture_started = terminal_attempted = False
            reason = "runtime_failure"
            try:
                gate()
                _check(plan == _requests(phase, policy, claim.claimed_at, symbols))
                await jobs.assert_active(claim, plan_sha256=plan_sha256, planned_calls=len(plan))
                gate()
                reason = "auth_unavailable"
                async with asyncio.timeout(deadline - monotonic()):
                    with _suppress_untrusted_dependency_logs():
                        async with RobinhoodMcpSdkConnection(
                            oauth_store_dir=oauth_store
                        ) as connection:
                            session = connection.stock_research_session
                            gate()
                            reason = "schema_mismatch"
                            _check(await session.validate_tools() == PROFILE_SHA256, reason)
                            gate()
                            reason = "runtime_failure"
                            next_index = 0

                            async def before_call(index: int, request: StockCaptureRequest) -> None:
                                nonlocal next_index
                                gate()
                                _check(index == next_index and request == plan[index])
                                _check(_plan_hash(plan) == claim.plan_sha256)
                                await jobs.assert_active(
                                    claim, plan_sha256=plan_sha256, planned_calls=len(plan)
                                )
                                archive.admit(
                                    remaining_calls=len(plan) - index, policy=policy.stock_worker
                                )
                                gate()
                                next_index += 1

                            capture_started = True
                            captured = await capture_stock_observations(
                                transport=StockResearchTransport(session),
                                requests=plan,
                                output_dir=output_dir,
                                clock=clock,
                                sleep=sleep,
                                transport_authenticated=True,
                                before_call=before_call,
                                _directory_fd=archive.directory_fd,
                            )
                        gate()  # Transport closed before report publication or cache promotion.
                    reason = "artifact_unavailable"
                    manifest, observations = _verified_capture(
                        archive=archive,
                        root=output_dir,
                        claim=claim,
                        plan=plan,
                        manifest_sha256=str(captured["manifest_sha256"]),
                        now=require_utc(clock()),
                    )
                    report_sha256 = None
                    if manifest["status"] == "partial":
                        reason = "capture_partial"
                    else:
                        archive.admit(remaining_calls=0, policy=policy.stock_worker)
                        gate()
                        at = require_utc(clock())
                        reason = "report_failed"
                        if phase == "discovery":
                            report = _screen_body(
                                claim=claim,
                                observations=observations,
                                manifest_sha256=str(captured["manifest_sha256"]),
                                policy=policy,
                                at=at,
                            )
                            if report["screen"]["coverage_complete"] is not True:
                                reason = "screen_incomplete"
                            else:
                                name, digest = _publish(
                                    archive.directory_fd,
                                    canonical_json(report).encode(),
                                    ".stock-screen.json",
                                )
                                _check(
                                    _read(archive.directory_fd, name, ".stock-screen.json")
                                    == report
                                )
                                report_sha256 = digest
                        else:
                            published = publish_stock_dossier_report(
                                root=output_dir,
                                manifest_file=str(captured["manifest_file"]),
                                as_of=at,
                                _directory_fd=archive.directory_fd,
                            )
                            report = _read(
                                archive.directory_fd,
                                str(published["report_file"]),
                                ".stock-dossiers.json",
                            )
                            _check(report["normalization_denials"] == [])
                            _check({row["symbol"] for row in report["dossiers"]} == set(symbols))
                            report_sha256 = str(published["report_sha256"])
                    gate()
                    await jobs.assert_active(
                        claim, plan_sha256=plan_sha256, planned_calls=len(plan)
                    )
                    gate()
                    terminal_attempted = True
                    result = await jobs.finish(
                        claim,
                        status="succeeded" if report_sha256 is not None else "blocked",
                        reason="complete" if report_sha256 is not None else reason,
                        capture_plan_sha256=manifest["request_plan_sha256"],
                        attempted_calls=manifest["attempted_calls"],
                        successful_calls=manifest["successful_calls"],
                        manifest_sha256=str(captured["manifest_sha256"]),
                        report_sha256=report_sha256,
                        require_active_before_success=True,
                    )
                    return _summary(result, claim)
            except asyncio.CancelledError:
                # The capture may have published a cancellation manifest but did
                # not return its identity. Keep the charged claim; never guess.
                raise
            except Exception:
                _raise_pending_cancellation()
                if terminal_attempted or (capture_started and captured is None):
                    return _blocked(reason)
                try:
                    manifest_sha256 = capture_plan = None
                    attempted = successful = 0
                    if captured is not None:
                        manifest, _ = _verified_capture(
                            archive=archive,
                            root=output_dir,
                            claim=claim,
                            plan=plan,
                            manifest_sha256=str(captured["manifest_sha256"]),
                            now=require_utc(clock()),
                        )
                        manifest_sha256 = str(captured["manifest_sha256"])
                        capture_plan = manifest["request_plan_sha256"]
                        attempted, successful = (
                            manifest["attempted_calls"],
                            manifest["successful_calls"],
                        )
                    result = await jobs.finish(
                        claim,
                        status="blocked",
                        reason=reason,
                        capture_plan_sha256=capture_plan,
                        attempted_calls=attempted,
                        successful_calls=successful,
                        manifest_sha256=manifest_sha256,
                        report_sha256=None,
                    )
                    return _summary(result, claim)
                except Exception:
                    return _blocked(reason)
    except asyncio.CancelledError:
        raise
    except StockArchiveError:
        return _blocked("storage_full")
    except StockResearchJobError:
        return _blocked("ledger_unavailable")
    except Exception:
        return _blocked("artifact_unavailable")


@contextmanager
def _existing_private_ledger(path: Path) -> Iterator[int]:
    """Validate an existing ledger; the collection command never creates/resets one."""
    directory = descriptor = -1
    try:
        _check(path.is_absolute() and path.resolve() == path)
        _check(not any(character in str(path) for character in "?#"))
        directory = _private_directory(path.parent)
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory,
        )
        info = os.fstat(descriptor)
        _check(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_nlink == 1
            and info.st_size >= 16
            and os.read(descriptor, 16) == b"SQLite format 3\x00"
        )
        yield descriptor
    finally:
        try:
            if descriptor >= 0:
                os.close(descriptor)
        finally:
            if directory >= 0:
                os.close(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repository = Path(__file__).resolve().parents[3]
    parser.add_argument("--config-root", type=Path, default=repository / "configs")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--oauth-store", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument(
        "--export-dir", type=Path, help="Separate private dashboard projection directory"
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Reconstruct the projection without broker calls or a new research claim",
    )
    parser.add_argument("--image-digest", help="Operator-verified executing immutable image digest")
    parser.add_argument("--image-attestation", type=Path, help="Root-owned release attestation")
    args = parser.parse_args(argv)
    try:
        _check(not args.export_only or args.export_dir is not None, "worker_startup_blocked")
        _check(
            (args.image_digest is None) == (args.image_attestation is None),
            "worker_startup_blocked",
        )
        root = args.config_root
        loaded = load_config(
            root / "base.yaml",
            root / "hybrid/paper.yaml",
            root / "hybrid/safety-envelope.yaml",
            os.environ,
            hybrid_policy_path=root / "hybrid/policy.yaml",
            stock_research_policy_path=root / "hybrid/stock-research.yaml",
            stock_worker_policy_path=root / "hybrid/stock-worker.yaml",
        )
        if args.image_digest is not None:
            deployed = verify_deployed_image_attestation(
                args.image_attestation, expected_image_digest=args.image_digest
            )
            _check(deployed.deployment_config_hash == str(loaded.config_hash))
            code_hash = deployed.code_hash
        else:
            identity = resolve_code_identity(repository, None)
            _check(
                not identity.dirty
                and not identity.non_promotable
                and identity.git_commit is not None
            )
            code_hash = identity.code_hash
        from trading_bot.logging import _install_logging_settings, configure_logging

        _install_logging_settings(loaded.config.logging, loaded.safety_envelope.logging)
        configure_logging("INFO")

        async def execute() -> dict[str, object]:
            url = f"sqlite+aiosqlite:///{args.database}"
            with _existing_private_ledger(args.database) as descriptor:
                engine = create_engine(url, existing_file_descriptor=descriptor)
                try:
                    factory = async_session_factory(engine)
                    result = (
                        {"status": "succeeded", "reason": "export_only", "live_enabled": False}
                        if args.export_only
                        else await run_stock_research_cycle(
                            loaded=loaded,
                            code_hash=code_hash,
                            factory=factory,
                            oauth_store=args.oauth_store,
                            output_dir=args.archive_dir,
                        )
                    )
                    if args.export_dir is not None:
                        from trading_bot.runtime.stock_dashboard_export import (
                            export_stock_dashboard,
                        )

                        try:
                            publication = await export_stock_dashboard(
                                loaded=loaded,
                                code_hash=code_hash,
                                factory=factory,
                                archive_dir=args.archive_dir,
                                export_dir=args.export_dir,
                            )
                            result["dashboard_export_status"] = "published"
                            result["dashboard_export_sha256"] = publication["sha256"]
                        except Exception:
                            result["dashboard_export_status"] = "blocked"
                    return result
                finally:
                    await engine.dispose()

        result = asyncio.run(execute())
        print(json.dumps(result, sort_keys=True))
        if result.get("dashboard_export_status") == "blocked":
            return 2
        return 0 if result["status"] == "succeeded" or result.get("reason") == "not_due" else 2
    except Exception:
        print(json.dumps(_blocked("worker_startup_blocked"), sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
