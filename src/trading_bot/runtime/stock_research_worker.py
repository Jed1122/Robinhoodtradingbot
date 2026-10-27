"""Durable one-shot individual-stock research; no account or execution operations."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import stat
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import AsyncExitStack, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from trading_bot.brokers.robinhood_mcp_schema_gate import JsonValue
from trading_bot.brokers.robinhood_mcp_sdk import RobinhoodMcpSdkConnection
from trading_bot.brokers.robinhood_mcp_transport import McpToolResult, McpToolSession
from trading_bot.brokers.stock_research_mcp import PROFILE_SHA256, StockResearchTransport
from trading_bot.clock import require_utc
from trading_bot.code_identity import resolve_code_identity, verify_deployed_image_attestation
from trading_bot.config import LoadedConfig, load_config
from trading_bot.config.loader import restore_loaded_config
from trading_bot.config.stock_research import StockResearchSettings, StockWorkerAppConfig
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
from trading_bot.research.stock_screen import (
    CURRENT_PROVIDER_WORKER_PROFILE,
    discovery_requests,
    screen_stocks,
)
from trading_bot.research.stock_screen import (
    _key as _stock_filter_key,
)
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
from trading_bot.runtime.stock_research_controls import (
    StockControlGrant,
    StockResearchControlError,
    StockResearchControls,
)


class StockWorkerError(ValueError):
    """Fixed stage code; never external exception text."""


@dataclass(frozen=True, slots=True)
class StockResearchWatch:
    """Caller-bound refresh priorities, without account access or authentication claims.

    The runtime owner must publish and preserve its own watch manifest. Supplying this
    value does not establish that a position exists or authorize an investment.
    """

    held_symbols: tuple[str, ...]
    watch_symbols: tuple[str, ...]
    as_of: datetime
    expires_at: datetime
    source_sha256: str

    def __post_init__(self) -> None:
        for symbols in (self.held_symbols, self.watch_symbols):
            _check(
                type(symbols) is tuple
                and len(symbols) <= 20
                and all(
                    type(symbol) is str
                    and re.fullmatch(r"[A-Z][A-Z0-9.\-/]{0,14}", symbol) is not None
                    for symbol in symbols
                )
                and len(set(symbols)) == len(symbols),
                "watch_unavailable",
            )
        _check(require_utc(self.as_of) < require_utc(self.expires_at), "watch_unavailable")
        _check(
            type(self.source_sha256) is str
            and re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is not None,
            "watch_unavailable",
        )


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
        discovery_requests(policy.stock_research, worker_profile_id=policy.stock_worker.policy_id)
        if phase == "discovery"
        else list(
            enrichment_requests(
                symbols=symbols,
                as_of=at,
                policy=policy.stock_research,
                worker_profile_id=policy.stock_worker.policy_id,
            )
        )
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
    report = {
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
            worker_profile_id=policy.stock_worker.policy_id,
        ),
        "qualified": False,
        "investment_eligible": False,
        "live_enabled": False,
    }
    if policy.stock_worker.policy_id == CURRENT_PROVIDER_WORKER_PROFILE:
        report["worker_profile_id"] = policy.stock_worker.policy_id
    return report


def _verify_targeted_preview(
    observations: tuple[dict[str, Any], ...],
    *,
    symbols: tuple[str, ...],
    policy: StockResearchSettings,
    as_of: datetime,
) -> None:
    """Require complete named refresh without imposing new-entry universe screens."""
    try:
        at = require_utc(as_of)
        expected = enrichment_requests(
            symbols=symbols,
            as_of=at,
            policy=policy,
            worker_profile_id=CURRENT_PROVIDER_WORKER_PROFILE,
        )[1]
        expected_arguments = cast(dict[str, Any], expected["arguments"])
        previews = [row for row in observations if row["tool"] == "preview_scan"]
        _check(len(previews) == 1)
        row = previews[0]
        _check(row["arguments"] == expected_arguments)
        received = require_utc(datetime.fromisoformat(row["received_at"]))
        _check(
            received <= at
            and at - received <= timedelta(minutes=policy.maximum_source_age_minutes)
            and type(row["observation_sha256"]) is str
            and re.fullmatch(r"[0-9a-f]{64}", row["observation_sha256"]) is not None
        )
        result = row["payload"]["data"]["result"]
        _check(
            Counter(_stock_filter_key(item, echoed=True) for item in result["filters_applied"])
            == Counter(
                _stock_filter_key(item, echoed=False) for item in expected_arguments["filters"]
            )
        )
        rows = result["results"]
        _check(
            type(rows) is list
            and type(result["total_items"]) is int
            and result["total_items"] == len(rows) == len(symbols)
        )
        _check({item["ticker"] for item in rows} == set(symbols))
        _check(
            len({item["instrument_id"] for item in rows}) == len(rows)
            and all(
                type(item["instrument_id"]) is str
                and 1 <= len(item["instrument_id"]) <= 128
                and item["instrument_type"] == "EQUITY"
                and item["columns"].get("Asset type") == "STOCK"
                for item in rows
            )
        )
    except (ValueError, KeyError, TypeError, OverflowError):
        raise StockWorkerError("targeted_refresh_incomplete") from None


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
            if policy.stock_worker.policy_id == CURRENT_PROVIDER_WORKER_PROFILE:
                _verify_targeted_preview(
                    rows, symbols=symbols, policy=policy.stock_research, as_of=at
                )
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
    watch: StockResearchWatch | None = None,
) -> tuple[Phase, tuple[str, ...], str | None]:
    priorities: tuple[str, ...] = ()
    if watch is not None:
        now = require_utc(now)
        _check(type(watch) is StockResearchWatch, "watch_unavailable")
        watch.__post_init__()
        _check(
            policy.stock_worker.policy_id == CURRENT_PROVIDER_WORKER_PROFILE,
            "watch_profile_required",
        )
        _check(
            watch.as_of <= now < watch.expires_at
            and now - watch.as_of
            <= timedelta(minutes=policy.stock_research.maximum_source_age_minutes),
            "watch_unavailable",
        )
        priorities = tuple(dict.fromkeys((*watch.held_symbols, *watch.watch_symbols)))
        _check(
            len(priorities) <= policy.stock_research.shortlist_count,
            "watch_coverage_capacity_exceeded",
        )
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
        if policy.stock_worker.policy_id == CURRENT_PROVIDER_WORKER_PROFILE:
            candidates = tuple(
                dict.fromkeys(symbol for symbol in symbols if symbol not in priorities)
            )
            capacity = policy.stock_research.shortlist_count - len(priorities)
            if 0 < capacity < len(candidates):
                # The ledger owner has verified the result/claim join. Only completed
                # enrichment cohorts for this configuration and code advance fairness.
                enrichment_claims = {
                    item.claim_id
                    for item in state.claims
                    if item.phase == "enrichment"
                    and item.config_hash == source.config_hash
                    and item.code_hash == source.code_hash
                }
                completed = sum(
                    item.status == "succeeded" and item.claim_id in enrichment_claims
                    for item in state.results
                )
                offset = completed % len(candidates)
                candidates = (*candidates[offset:], *candidates[:offset])
            symbols = (*priorities, *candidates[:capacity])
        elif watch is not None:
            symbols = tuple(dict.fromkeys((*priorities, *symbols)))[
                : policy.stock_research.shortlist_count
            ]
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


class _ControlledStockTransport(StockResearchTransport):
    def __init__(
        self, session: McpToolSession, controls: StockResearchControls, grant: StockControlGrant
    ) -> None:
        super().__init__(session)
        self._controls, self._grant = controls, grant

    async def call_tool(self, name: str, arguments: Mapping[str, JsonValue]) -> McpToolResult:
        # This barrier spans the awaited dispatch, not merely its earlier admission hook.
        with self._controls.permit(self._grant):
            return await super().call_tool(name, arguments)


async def run_stock_research_cycle(
    *,
    loaded: LoadedConfig,
    code_hash: CodeHash,
    factory: object,
    oauth_store: Path,
    output_dir: Path,
    controls: StockResearchControls | None = None,
    watch: StockResearchWatch | None = None,
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
        if type(controls) is not StockResearchControls:
            return _blocked("control_denied")
        grant = controls.grant(config_hash=str(loaded.config_hash), code_hash=str(code_hash))
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
                state=state,
                discovery=discovery,
                enrichment=enrichment,
                policy=policy,
                now=now,
                watch=watch,
            )
            plan = _requests(phase, policy, now, symbols)
            plan_sha256 = _plan_hash(plan)
            archive.admit(remaining_calls=len(plan), policy=policy.stock_worker)
            gate()
            with controls.permit(grant):
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
                        async with AsyncExitStack() as connections:
                            with controls.permit(grant):
                                connection = await connections.enter_async_context(
                                    RobinhoodMcpSdkConnection(oauth_store_dir=oauth_store)
                                )
                                session = connection.stock_research_session
                                gate()
                                reason = "schema_mismatch"
                                _check(await session.validate_tools() == PROFILE_SHA256, reason)
                            gate()
                            reason = "runtime_failure"
                            next_index = 0

                            async def before_call(index: int, request: StockCaptureRequest) -> None:
                                nonlocal next_index
                                with controls.permit(grant):
                                    pass
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
                                transport=_ControlledStockTransport(session, controls, grant),
                                requests=plan,
                                output_dir=output_dir,
                                clock=clock,
                                sleep=sleep,
                                transport_authenticated=True,
                                retain_request_plan=(
                                    policy.stock_worker.policy_id == CURRENT_PROVIDER_WORKER_PROFILE
                                ),
                                before_call=before_call,
                                _directory_fd=archive.directory_fd,
                            )
                        gate()  # Transport closed before report publication or cache promotion.
                    with controls.permit(grant):
                        pass
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
                            if policy.stock_worker.policy_id == CURRENT_PROVIDER_WORKER_PROFILE:
                                _verify_targeted_preview(
                                    observations,
                                    symbols=symbols,
                                    policy=policy.stock_research,
                                    as_of=at,
                                )
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
                    with controls.permit(grant) if report_sha256 is not None else nullcontext():
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
            except Exception as exc:
                if isinstance(exc, StockResearchControlError):
                    reason = "control_denied"
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
    except StockWorkerError as exc:
        reason = str(exc)
        return _blocked(
            reason
            if reason
            in {
                "watch_coverage_capacity_exceeded",
                "watch_unavailable",
                "watch_profile_required",
            }
            else "artifact_unavailable"
        )
    except StockArchiveError:
        return _blocked("storage_full")
    except StockResearchJobError:
        return _blocked("ledger_unavailable")
    except StockResearchControlError:
        return _blocked("control_denied")
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


def load_stock_worker_configuration(root: Path) -> LoadedConfig:
    """One canonical graph for startup, resume and inert image policy observation."""
    # Docker's inert safety flags are not policy overrides. Every other alias,
    # spelling or value still reaches the loader's immutable-policy denial.
    environment = {
        key: value
        for key, value in os.environ.items()
        if not (key in {"LIVE_TRADING_ENABLED", "PREDICTION_LIVE_ENABLED"} and value == "false")
    }
    return load_config(
        root / "base.yaml",
        root / "hybrid/paper.yaml",
        root / "hybrid/safety-envelope.yaml",
        environment,
        hybrid_policy_path=root / "hybrid/policy.yaml",
        stock_research_policy_path=root / "hybrid/stock-research.yaml",
        stock_worker_policy_path=root / "hybrid/stock-worker.yaml",
    )


def load_stock_worker_identity(
    root: Path, *, image_digest: str | None = None, image_attestation: Path | None = None
) -> tuple[LoadedConfig, CodeHash]:
    """Shared startup/resume identity; no arbitrary hash, credential or provider operation."""
    _check((image_digest is None) == (image_attestation is None), "worker_startup_blocked")
    loaded = load_stock_worker_configuration(root)
    if image_digest is not None:
        if image_attestation is None:
            raise StockWorkerError("worker_startup_blocked")
        deployed = verify_deployed_image_attestation(
            image_attestation,
            expected_image_digest=image_digest,
        )
        _check(deployed.deployment_config_hash == str(loaded.config_hash))
        return loaded, deployed.code_hash
    identity = resolve_code_identity(Path(__file__).resolve().parents[3], None)
    _check(not identity.dirty and not identity.non_promotable and identity.git_commit is not None)
    return loaded, identity.code_hash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repository = Path(__file__).resolve().parents[3]
    parser.add_argument("--config-root", type=Path, default=repository / "configs")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--oauth-store", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--control-dir", type=Path, help="Required explicit collector authority")
    parser.add_argument(
        "--watch-dir", type=Path, help="Separate private caller-owned refresh watch"
    )
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
        _check(args.export_only or args.control_dir is not None, "worker_startup_blocked")
        loaded, code_hash = load_stock_worker_identity(
            args.config_root,
            image_digest=args.image_digest,
            image_attestation=args.image_attestation,
        )
        from typing import TypedDict

        class WatchOptions(TypedDict, total=False):
            watch: StockResearchWatch

        watch_options: WatchOptions = {}
        if args.watch_dir is not None:
            from trading_bot.runtime.stock_research_watch import read_stock_research_watch

            _check(not args.export_only, "worker_startup_blocked")
            _check(
                type(loaded.config) is StockWorkerAppConfig
                and loaded.config.stock_worker.policy_id == CURRENT_PROVIDER_WORKER_PROFILE,
                "worker_startup_blocked",
            )
            watch_root = args.watch_dir
            _check(watch_root.is_absolute() and watch_root.resolve(strict=True) == watch_root)
            for other in (
                repository,
                args.config_root,
                args.archive_dir,
                args.control_dir,
                args.export_dir,
                args.oauth_store,
            ):
                if other is not None:
                    reserved_root = other.resolve()
                    _check(
                        not watch_root.is_relative_to(reserved_root)
                        and not reserved_root.is_relative_to(watch_root)
                    )
            supplied_watch = read_stock_research_watch(root=watch_root)
            # A python -m entry point owns a distinct __main__ class identity.
            # Preserve all verified fields while constructing this module's type.
            watch_options["watch"] = StockResearchWatch(
                supplied_watch.held_symbols,
                supplied_watch.watch_symbols,
                supplied_watch.as_of,
                supplied_watch.expires_at,
                supplied_watch.source_sha256,
            )

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
                            controls=StockResearchControls(args.control_dir),
                            **watch_options,
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
