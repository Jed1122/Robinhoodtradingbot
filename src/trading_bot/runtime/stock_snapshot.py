"""Coherent stock application copies and isolated killed controls, without execution authority.

The root caller must hold the existing operations lock and freshly exclude unresolved
workers. This UID-owned helper takes archive -> controls -> exports locks. It never
copies OAuth or an executable operations namespace. Failed staging is retained.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from trading_bot.clock import require_utc
from trading_bot.config import LoadedConfig
from trading_bot.config.loader import restore_loaded_config
from trading_bot.config.stock_research import StockWorkerAppConfig
from trading_bot.domain import CodeHash, ConfigHash
from trading_bot.market_data.bundle_store import _open_root
from trading_bot.market_data.recording import canonical_json
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.stock_research_jobs import (
    SqlStockResearchJobs,
    StockResearchClaim,
    StockResearchJobState,
    StockResearchResult,
)
from trading_bot.research.stock_screen import CURRENT_PROVIDER_WORKER_PROFILE
from trading_bot.runtime.stock_archive import _read, read_stock_observations
from trading_bot.runtime.stock_archive_lease import StockArchiveLease
from trading_bot.runtime.stock_capture import parse_stock_capture_plan
from trading_bot.runtime.stock_dashboard_export import _projection
from trading_bot.runtime.stock_dashboard_export import _read as _read_export
from trading_bot.runtime.stock_dossier_report import compile_stock_dossier_report
from trading_bot.runtime.stock_research_controls import (
    StockControlRecord,
    StockControlState,
    StockResearchControls,
    _encode,
)
from trading_bot.runtime.stock_research_worker import (
    _cached,
    _plan_hash,
    _requests,
    _screen_body,
    _symbols,
    _verified_capture,
    _verify_targeted_preview,
)
from trading_bot.runtime.stock_snapshot_policy import (
    FULL_REPLAY_V1,
    RECOVERY_INTEGRITY_V1,
    SnapshotValidationPolicy,
)

_MAX_LEDGER_BYTES = 256 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 9_000_000
_MAX_MANIFEST_BYTES = 32 * 1024 * 1024
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ARCHIVE = re.compile(
    r"(?:[0-9a-f]{64}\.stock-(?:observation|capture|dossiers|screen)\.json"
    r"|\.pending-[0-9a-f]{32}|\.stock-research\.lock)\Z"
)
_EXPORT = re.compile(r"(?:stock-research\.json|\.pending-[0-9a-f]{32}|\.stock-research\.lock)\Z")
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_WRITE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_DIRECTORIES = {"state", "archive", "exports"}
_ROOT_FILES = {"canonical-config.json", "saved-control.json", "manifest.json"}


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    manifest_sha256: str
    file_count: int
    total_bytes: int
    claim_count: int
    result_count: int
    pending_count: int
    state_sha256: str
    budget_by_day: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class ControlRestoreResult:
    control_id: str
    generation: int
    state_sha256: str
    offline_only: bool


def _require(value: bool) -> None:
    if not value:
        raise ValueError("stock_snapshot_unavailable")


def _validation_policy(value: SnapshotValidationPolicy) -> None:
    _require(type(value) is str and value in (FULL_REPLAY_V1, RECOVERY_INTEGRITY_V1))


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


class _Window:
    def __init__(self) -> None:
        self.origin = self.last = time.monotonic()

    def check(self) -> None:
        now = time.monotonic()
        _require(self.last <= now < self.origin + 300)
        self.last = now


@contextmanager
def _directory(path: Path) -> Iterator[int]:
    _require(isinstance(path, Path) and path.is_absolute() and path.resolve(strict=True) == path)
    fd = _open_root(path, Path(__file__).resolve().parents[3])
    original = os.fstat(fd)
    try:
        yield fd
        named = path.stat(follow_symlinks=False)
        _require((named.st_dev, named.st_ino) == (original.st_dev, original.st_ino))
        _require(stat.S_ISDIR(named.st_mode) and named.st_uid == os.geteuid())
        _require(stat.S_IMODE(named.st_mode) == 0o700)
    finally:
        os.close(fd)


def _private(info: os.stat_result, limit: int) -> None:
    _require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
        and 0 <= info.st_size <= limit
    )


def _read_bytes(directory: int, name: str, limit: int, window: _Window) -> bytes:
    descriptor = os.open(name, _READ, dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        _private(info, limit)
        result = bytearray()
        while True:
            window.check()
            part = os.read(descriptor, min(1024 * 1024, limit + 1 - len(result)))
            if not part:
                break
            result.extend(part)
            _require(len(result) <= limit)
        _require(len(result) == info.st_size)
        _require(_stamp(info) == _stamp(os.fstat(descriptor)))
        _require(_stamp(info) == _stamp(os.stat(name, dir_fd=directory, follow_symlinks=False)))
        return bytes(result)
    finally:
        os.close(descriptor)


def _write_bytes(directory: int, name: str, raw: bytes, window: _Window) -> None:
    descriptor = os.open(name, _WRITE, 0o600, dir_fd=directory)
    try:
        offset = 0
        while offset < len(raw):
            window.check()
            count = os.write(descriptor, raw[offset : offset + 1024 * 1024])
            _require(count > 0)
            offset += count
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        _private(info, len(raw))
        _require(info.st_size == len(raw))
    finally:
        os.close(descriptor)
    os.fsync(directory)
    _require(_read_bytes(directory, name, len(raw), window) == raw)


def _new_directory(path: Path) -> None:
    _require(path.name not in {"", ".", ".."} and not os.path.lexists(path))
    with _directory(path.parent) as parent:
        os.mkdir(path.name, mode=0o700, dir_fd=parent)
        with _directory(path) as child:
            os.fsync(child)
        os.fsync(parent)


def _inventory(
    directory: int, pattern: re.Pattern[str], *, count: int, limit: int, total: int
) -> dict[str, tuple[int, ...]]:
    rows: dict[str, tuple[int, ...]] = {}
    size = 0
    with os.scandir(directory) as entries:
        for entry in entries:
            _require(len(rows) < count and pattern.fullmatch(entry.name) is not None)
            info = entry.stat(follow_symlinks=False)
            _private(info, limit)
            if entry.name.endswith(".lock"):
                _require(info.st_size == 0)
            size += info.st_size
            _require(size <= total)
            rows[entry.name] = _stamp(info)
    return rows


def _copy_file(
    source: int, target: int, name: str, expected: tuple[int, ...], limit: int, window: _Window
) -> None:
    descriptor = os.open(name, _READ, dir_fd=source)
    output = -1
    try:
        info = os.fstat(descriptor)
        _private(info, limit)
        _require(_stamp(info) == expected)
        output = os.open(name, _WRITE, 0o600, dir_fd=target)
        size, digest = 0, hashlib.sha256()
        while True:
            window.check()
            part = os.read(descriptor, min(1024 * 1024, limit + 1 - size))
            if not part:
                break
            size += len(part)
            _require(size <= limit)
            digest.update(part)
            offset = 0
            while offset < len(part):
                written = os.write(output, part[offset:])
                _require(written > 0)
                offset += written
        _require(size == info.st_size and _stamp(os.fstat(descriptor)) == expected)
        _require(_stamp(os.stat(name, dir_fd=source, follow_symlinks=False)) == expected)
        os.fsync(output)
    finally:
        try:
            if output >= 0:
                os.close(output)
        finally:
            os.close(descriptor)
    copied = _hash_file(target, name, limit, window)
    _require(copied == {"size": size, "sha256": digest.hexdigest()})
    if re.match(r"[0-9a-f]{64}\.stock-", name):
        _require(digest.hexdigest() == name[:64])


def _backup(database: Path, destination: Path, window: _Window) -> None:
    # Even mode=ro SQLite can create WAL/SHM siblings. Pin/copy the quiesced main
    # file and optional committed WAL first, then run the actual backup API only
    # against that isolated input. SHM is reconstructed, never transplanted.
    scratch = destination.parent / ".sqlite-input"
    _new_directory(scratch)
    with _directory(database.parent) as parent:
        pattern = re.compile(re.escape(database.name) + r"(?:-wal|-shm)?\Z")
        pins = _inventory(
            parent, pattern, count=3, limit=_MAX_LEDGER_BYTES, total=_MAX_LEDGER_BYTES
        )
        _require(database.name in pins)
        descriptor = os.open(database.name, _READ, dir_fd=parent)
        try:
            original = os.fstat(descriptor)
            _private(original, _MAX_LEDGER_BYTES)
            _require(original.st_size >= 16 and os.read(descriptor, 16) == b"SQLite format 3\x00")
            with _directory(scratch) as copied:
                for name, stamp in sorted(pins.items()):
                    if name != database.name + "-shm":
                        _copy_file(parent, copied, name, stamp, _MAX_LEDGER_BYTES, window)
                os.fsync(copied)
            source = sqlite3.connect(
                "file:" + quote(str(scratch / database.name), safe="/") + "?mode=ro",
                uri=True,
                timeout=0.1,
            )
            try:
                with _directory(destination.parent) as target:
                    _write_bytes(target, destination.name, b"", window)
                saved = sqlite3.connect(
                    "file:" + quote(str(destination), safe="/") + "?mode=rw", uri=True, timeout=0.1
                )
                try:
                    source.backup(
                        saved, pages=128, progress=lambda *args: window.check(), sleep=0.01
                    )
                    _require(saved.execute("PRAGMA integrity_check(1)").fetchall() == [("ok",)])
                    _require(saved.execute("PRAGMA foreign_key_check").fetchone() is None)
                finally:
                    saved.close()
            finally:
                source.close()
            _require(_stamp(original) == _stamp(os.fstat(descriptor)))
            _require(_stamp(original) == _stamp(database.stat(follow_symlinks=False)))
            _require(
                _inventory(
                    parent, pattern, count=3, limit=_MAX_LEDGER_BYTES, total=_MAX_LEDGER_BYTES
                )
                == pins
            )
        finally:
            os.close(descriptor)
    with _directory(scratch) as copied:
        names = _inventory(
            copied, pattern, count=3, limit=_MAX_LEDGER_BYTES, total=_MAX_LEDGER_BYTES
        )
        for name in names:
            os.unlink(name, dir_fd=copied)
        os.fsync(copied)
    with _directory(destination.parent) as target:
        os.rmdir(scratch.name, dir_fd=target)
        os.fsync(target)
    with _directory(destination.parent) as target:
        copied = os.open(destination.name, _READ, dir_fd=target)
        try:
            _private(os.fstat(copied), _MAX_LEDGER_BYTES)
            os.fsync(copied)
        finally:
            os.close(copied)
        os.fsync(target)


def _json(raw: bytes) -> dict[str, Any]:
    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            _require(key not in result)
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=pairs)
    _require(type(value) is dict and canonical_json(value).encode() == raw)
    return dict(value)


def _control(raw: bytes, now: datetime) -> StockControlState:
    record = StockControlRecord.model_validate_json(raw)
    _require(_encode(record) == raw and record.changed_at <= now)
    return StockControlState(record, hashlib.sha256(raw).hexdigest())


def _control_summary(state: StockControlState) -> dict[str, Any]:
    return {
        "control_id": state.record.control_id,
        "generation": state.record.generation,
        "status": state.record.status,
        "state_sha256": state.sha256,
    }


def _summary(state: StockResearchJobState) -> dict[str, Any]:
    days: dict[str, int] = {}
    for claim in state.claims:
        for day in claim.budget_days:
            days[day] = days.get(day, 0) + claim.planned_calls
    return {
        "claim_count": len(state.claims),
        "result_count": len(state.results),
        "pending_count": state.pending_count,
        "state_sha256": state.state_hash,
        "budget_by_day": days,
    }


def _captured_enrichment_symbols(
    root: Path, archive: StockArchiveLease, claim: StockResearchClaim, manifest_sha256: str
) -> tuple[str, ...]:
    """Use retained intent/requests, including v2 calls that never executed.

    The caller still requires the actual discovery source head and reconstructs the
    complete versioned expected plan. A v1 copy without selected names stays unknown.
    """
    rows = read_stock_observations(
        root, manifest_sha256 + ".stock-capture.json", _directory_fd=archive.directory_fd
    )
    manifest = _read(
        archive.directory_fd, manifest_sha256 + ".stock-capture.json", ".stock-capture.json"
    )
    if manifest["schema_version"] == 2:
        retained = parse_stock_capture_plan(manifest["request_plan"])
        _require(
            _plan_hash(retained) == manifest["request_plan_sha256"] == claim.plan_sha256
            and len(retained) == manifest["planned_calls"] == claim.planned_calls
        )
        return tuple(
            symbol
            for request in retained
            if request.tool == "get_equity_fundamentals"
            for symbol in cast(list[str], request.arguments["symbols"])
        )
    named = [
        item["values"]
        for row in rows
        if row["tool"] == "preview_scan"
        for item in row["arguments"]["filters"]
        if item.get("expression") == "symbol" and item.get("predicate") == "ANY_OF"
    ]
    _require(len(named) <= 1)
    if named:
        return tuple(named[0])
    symbols = tuple(
        symbol
        for row in rows
        if row["tool"] == "get_equity_fundamentals"
        for symbol in row["arguments"]["symbols"]
    )
    _require(bool(symbols))
    return symbols


async def _replay(
    root: Path, loaded: LoadedConfig, code_hash: CodeHash, now: datetime, window: _Window
) -> dict[str, Any]:
    _require(type(loaded.config) is StockWorkerAppConfig)
    database = root / "state" / "ledger.sqlite3"
    check = sqlite3.connect(
        "file:" + quote(str(database), safe="/") + "?mode=rw", uri=True, timeout=0.1
    )
    try:
        _require(check.execute("PRAGMA integrity_check(1)").fetchall() == [("ok",)])
        _require(check.execute("PRAGMA foreign_key_check").fetchone() is None)
    finally:
        check.close()
    engine = create_engine(f"sqlite+aiosqlite:///{database}")
    try:
        factory = async_session_factory(engine)
        jobs = SqlStockResearchJobs(factory, loaded=loaded, code_hash=code_hash, clock=lambda: now)
        state = await jobs.snapshot()
        configurations = await jobs.configuration_history(expected_state_hash=state.state_hash)
        claims = {row.claim_id: row for row in state.claims}
        discovery_symbols: dict[str, tuple[str, ...]] = {}
        with StockArchiveLease(root / "archive") as archive:
            for result in sorted(state.results, key=lambda row: row.sequence):
                window.check()
                claim = claims[result.claim_id]
                if result.manifest_sha256 is None:
                    continue
                policy = StockWorkerAppConfig.model_validate(
                    configurations[claim.config_hash].config.model_dump()
                )
                source_symbols = discovery_symbols.get(str(claim.source_result_sha256))
                _require(claim.phase == "discovery" or source_symbols is not None)
                symbols = () if source_symbols is None else source_symbols
                if (
                    claim.phase == "enrichment"
                    and policy.stock_worker.policy_id == CURRENT_PROVIDER_WORKER_PROFILE
                ):
                    symbols = _captured_enrichment_symbols(
                        root / "archive", archive, claim, result.manifest_sha256
                    )
                plan = _requests(claim.phase, policy, claim.claimed_at, symbols)
                manifest, rows = _verified_capture(
                    archive=archive,
                    root=root / "archive",
                    claim=claim,
                    plan=plan,
                    manifest_sha256=result.manifest_sha256,
                    now=now,
                )
                _require(
                    manifest["attempted_calls"] == result.attempted_calls
                    and manifest["successful_calls"] == result.successful_calls
                    and result.capture_plan_sha256 == claim.plan_sha256
                )
                completed = require_utc(datetime.fromisoformat(manifest["completed_at"]))
                _require(completed <= result.recorded_at)
                if result.report_sha256 is None:
                    continue
                suffix = (
                    ".stock-screen.json" if claim.phase == "discovery" else ".stock-dossiers.json"
                )
                report = _read(archive.directory_fd, result.report_sha256 + suffix, suffix)
                at = require_utc(datetime.fromisoformat(report["as_of"]))
                _require(completed <= at <= result.recorded_at and manifest["status"] == "complete")
                if claim.phase == "discovery":
                    expected = _screen_body(
                        claim=claim,
                        observations=rows,
                        manifest_sha256=result.manifest_sha256,
                        policy=policy,
                        at=at,
                    )
                    _require(canonical_json(report) == canonical_json(expected))
                    _require(report["screen"]["coverage_complete"] is True)
                    discovery_symbols[result.record_sha256] = _symbols(report)
                else:
                    if policy.stock_worker.policy_id == CURRENT_PROVIDER_WORKER_PROFILE:
                        _verify_targeted_preview(
                            rows, symbols=symbols, policy=policy.stock_research, as_of=at
                        )
                    expected = compile_stock_dossier_report(observations=rows, as_of=at)
                    expected["source_manifest_sha256"] = result.manifest_sha256
                    _require(canonical_json(report) == canonical_json(expected))
                    _require(report["normalization_denials"] == [])
                    _require({row["symbol"] for row in report["dossiers"]} == set(symbols))
            if (root / "exports" / "stock-research.json").exists():
                with _directory(root / "exports") as exports:
                    view = _read_export(exports)
                projection_config = configurations[view.config_hash]
                policy = StockWorkerAppConfig.model_validate(projection_config.config.model_dump())
                _require(view.generated_at <= now)
                records: list[StockResearchClaim | StockResearchResult] = [
                    *state.claims,
                    *state.results,
                ]
                records.sort(key=lambda row: row.sequence)
                hashes = {"0" * 64: 0} | {row.record_sha256: row.sequence for row in records}
                _require(view.state_sha256 in hashes)
                prior = [row for row in records if row.sequence <= hashes[view.state_sha256]]
                _require(
                    view.code_hash in {str(code_hash), *(row.code_hash for row in state.claims)}
                )
                past = SqlStockResearchJobs(
                    factory,
                    loaded=projection_config,
                    code_hash=CodeHash(view.code_hash),
                    clock=lambda: view.generated_at,
                )._state(prior, view.generated_at)
                discovery, enrichment = _cached(
                    state=past,
                    archive=archive,
                    root=root / "archive",
                    policy=policy,
                    now=view.generated_at,
                )
                expected_view = _projection(
                    state=past,
                    loaded=projection_config,
                    code_hash=CodeHash(view.code_hash),
                    policy=policy,
                    now=view.generated_at,
                    discovery=discovery,
                    enrichment=enrichment,
                )
                _require(view == expected_view)
        window.check()
        return _summary(state)
    finally:
        await engine.dispose()


async def _recovery_integrity(
    root: Path, loaded: LoadedConfig, code_hash: CodeHash, now: datetime, window: _Window
) -> dict[str, Any]:
    """Validate copied recovery state and retained references without report reconstruction."""
    _require(type(loaded.config) is StockWorkerAppConfig)
    database = root / "state" / "ledger.sqlite3"
    check = sqlite3.connect(
        "file:" + quote(str(database), safe="/") + "?mode=rw", uri=True, timeout=0.1
    )
    try:
        _require(check.execute("PRAGMA integrity_check(1)").fetchall() == [("ok",)])
        _require(check.execute("PRAGMA foreign_key_check").fetchone() is None)
    finally:
        check.close()
    engine = create_engine(f"sqlite+aiosqlite:///{database}")
    try:
        factory = async_session_factory(engine)
        jobs = SqlStockResearchJobs(factory, loaded=loaded, code_hash=code_hash, clock=lambda: now)
        state = await jobs.snapshot()
        configurations = await jobs.configuration_history(expected_state_hash=state.state_hash)
        claims = {row.claim_id: row for row in state.claims}
        discovery_symbols: dict[str, tuple[str, ...]] = {}
        with StockArchiveLease(root / "archive") as archive:
            for result in sorted(state.results, key=lambda row: row.sequence):
                window.check()
                claim = claims[result.claim_id]
                if result.manifest_sha256 is None:
                    continue
                policy = StockWorkerAppConfig.model_validate(
                    configurations[claim.config_hash].config.model_dump()
                )
                source_symbols = discovery_symbols.get(str(claim.source_result_sha256))
                _require(claim.phase == "discovery" or source_symbols is not None)
                symbols = () if source_symbols is None else source_symbols
                if (
                    claim.phase == "enrichment"
                    and policy.stock_worker.policy_id == CURRENT_PROVIDER_WORKER_PROFILE
                ):
                    symbols = _captured_enrichment_symbols(
                        root / "archive", archive, claim, result.manifest_sha256
                    )
                manifest, rows = _verified_capture(
                    archive=archive,
                    root=root / "archive",
                    claim=claim,
                    plan=_requests(claim.phase, policy, claim.claimed_at, symbols),
                    manifest_sha256=result.manifest_sha256,
                    now=now,
                )
                _require(
                    manifest["attempted_calls"] == result.attempted_calls
                    and manifest["successful_calls"] == result.successful_calls
                    and result.capture_plan_sha256 == claim.plan_sha256
                )
                completed = require_utc(datetime.fromisoformat(manifest["completed_at"]))
                _require(completed <= result.recorded_at)
                if result.report_sha256 is not None:
                    suffix = (
                        ".stock-screen.json"
                        if result.phase == "discovery"
                        else ".stock-dossiers.json"
                    )
                    report = _read(archive.directory_fd, result.report_sha256 + suffix, suffix)
                    at = require_utc(datetime.fromisoformat(report["as_of"]))
                    _require(
                        completed <= at <= result.recorded_at and manifest["status"] == "complete"
                    )
                    if claim.phase == "discovery":
                        _require(report["screen"]["coverage_complete"] is True)
                        discovery_symbols[result.record_sha256] = _symbols(report)
                    else:
                        if policy.stock_worker.policy_id == CURRENT_PROVIDER_WORKER_PROFILE:
                            _verify_targeted_preview(
                                rows, symbols=symbols, policy=policy.stock_research, as_of=at
                            )
                        _require(report["normalization_denials"] == [])
                        _require({row["symbol"] for row in report["dossiers"]} == set(symbols))
            if (root / "exports" / "stock-research.json").exists():
                with _directory(root / "exports") as exports:
                    view = _read_export(exports)
                projection_config = configurations[view.config_hash]
                _require(view.generated_at <= now)
                _require(
                    view.code_hash in {str(code_hash), *(row.code_hash for row in state.claims)}
                )
                records: list[StockResearchClaim | StockResearchResult] = [
                    *state.claims,
                    *state.results,
                ]
                records.sort(key=lambda row: row.sequence)
                hashes = {"0" * 64: 0} | {row.record_sha256: row.sequence for row in records}
                _require(view.state_sha256 in hashes)
                prior = [row for row in records if row.sequence <= hashes[view.state_sha256]]
                _require(
                    all(
                        (row.claimed_at if isinstance(row, StockResearchClaim) else row.recorded_at)
                        <= view.generated_at
                        for row in prior
                    )
                )
                past = SqlStockResearchJobs(
                    factory,
                    loaded=projection_config,
                    code_hash=CodeHash(view.code_hash),
                    clock=lambda: view.generated_at,
                )._state(prior, view.generated_at)
                _require(past.state_hash == view.state_sha256)
        window.check()
        return _summary(state)
    finally:
        await engine.dispose()


def _hash_file(directory: int, name: str, limit: int, window: _Window) -> dict[str, Any]:
    descriptor = os.open(name, _READ, dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        _private(info, limit)
        digest, size = hashlib.sha256(), 0
        while True:
            window.check()
            part = os.read(descriptor, min(1024 * 1024, limit + 1 - size))
            if not part:
                break
            size += len(part)
            _require(size <= limit)
            digest.update(part)
        _require(size == info.st_size and _stamp(info) == _stamp(os.fstat(descriptor)))
        _require(_stamp(info) == _stamp(os.stat(name, dir_fd=directory, follow_symlinks=False)))
        return {"sha256": digest.hexdigest(), "size": size}
    finally:
        os.close(descriptor)


def _files(
    root: Path, loaded: LoadedConfig, window: _Window, *, published: bool = True
) -> dict[str, dict[str, Any]]:
    _require(type(loaded.config) is StockWorkerAppConfig)
    policy = StockWorkerAppConfig.model_validate(loaded.config.model_dump()).stock_worker
    files: dict[str, dict[str, Any]] = {}
    with _directory(root) as directory:
        expected = _ROOT_FILES if published else _ROOT_FILES - {"manifest.json"}
        _require(set(os.listdir(directory)) == _DIRECTORIES | expected)
        for name, limit in (("canonical-config.json", 1048576), ("saved-control.json", 8192)):
            raw = _read_bytes(directory, name, limit, window)
            files[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    for tree, pattern, count, limit, total in (
        ("state", re.compile(r"ledger\.sqlite3\Z"), 1, _MAX_LEDGER_BYTES, _MAX_LEDGER_BYTES),
        (
            "archive",
            _ARCHIVE,
            policy.max_archive_files,
            _MAX_ARTIFACT_BYTES,
            policy.max_archive_bytes,
        ),
        ("exports", _EXPORT, 63, 262144, 63 * 262144),
    ):
        with _directory(root / tree) as directory:
            pins = _inventory(directory, pattern, count=count, limit=limit, total=total)
            for name in sorted(pins):
                observed = _hash_file(directory, name, limit, window)
                if tree == "archive" and re.match(r"[0-9a-f]{64}\.stock-", name):
                    _require(name[:64] == observed["sha256"])
                files[tree + "/" + name] = observed
            _require(_inventory(directory, pattern, count=count, limit=limit, total=total) == pins)
    _require("state/ledger.sqlite3" in files)
    return files


def _result(manifest: dict[str, Any], raw: bytes) -> SnapshotResult:
    summary = manifest["application"]
    return SnapshotResult(
        hashlib.sha256(raw).hexdigest(),
        len(manifest["files"]),
        sum(row["size"] for row in manifest["files"].values()),
        summary["claim_count"],
        summary["result_count"],
        summary["pending_count"],
        summary["state_sha256"],
        tuple(sorted(summary["budget_by_day"].items())),
    )


async def create_stock_snapshot(
    *,
    loaded: LoadedConfig,
    code_hash: CodeHash,
    database: Path,
    archive_dir: Path,
    control_dir: Path,
    export_dir: Path,
    destination: Path,
    now: datetime,
    validation_policy: SnapshotValidationPolicy = FULL_REPLAY_V1,
) -> SnapshotResult:
    """Exclusively create one copy. Caller owns the outer root operations barrier."""
    try:
        window, now = _Window(), require_utc(now)
        _validation_policy(validation_policy)
        _require(_HEX.fullmatch(code_hash) is not None)
        _require(restore_loaded_config(loaded.canonical_json, loaded.config_hash) == loaded)
        _require(type(loaded.config) is StockWorkerAppConfig)
        roots = (database.parent, archive_dir, control_dir, export_dir)
        _require(all(not a.is_relative_to(b) for a in roots for b in roots if a != b))
        _require(len(set(roots)) == len(roots))
        _require(all(not destination.is_relative_to(path) for path in roots))
        _new_directory(destination)
        for name in sorted(_DIRECTORIES):
            _new_directory(destination / name)
        controls = StockResearchControls(control_dir, clock=lambda: now)
        with (
            StockArchiveLease(archive_dir) as archive,
            controls._locked() as control,
            StockArchiveLease(export_dir) as exports,
        ):
            saved = controls._read(control)
            pins = []
            policy = StockWorkerAppConfig.model_validate(loaded.config.model_dump()).stock_worker
            for source, target, pattern, count, limit, total in (
                (
                    archive.directory_fd,
                    destination / "archive",
                    _ARCHIVE,
                    policy.max_archive_files,
                    _MAX_ARTIFACT_BYTES,
                    policy.max_archive_bytes,
                ),
                (
                    exports.directory_fd,
                    destination / "exports",
                    _EXPORT,
                    63,
                    262144,
                    63 * 262144,
                ),
            ):
                original = _inventory(source, pattern, count=count, limit=limit, total=total)
                with _directory(target) as copied:
                    for name, stamp in sorted(original.items()):
                        _copy_file(source, copied, name, stamp, limit, window)
                    os.fsync(copied)
                pins.append((source, pattern, count, limit, total, original))
            _backup(database, destination / "state" / "ledger.sqlite3", window)
            with _directory(destination) as directory:
                _write_bytes(directory, "canonical-config.json", loaded.canonical_json, window)
                _write_bytes(directory, "saved-control.json", _encode(saved.record), window)
            validate = _replay if validation_policy == FULL_REPLAY_V1 else _recovery_integrity
            application = await validate(destination, loaded, code_hash, now, window)
            for source, pattern, count, limit, total, original in pins:
                _require(
                    _inventory(source, pattern, count=count, limit=limit, total=total) == original
                )
            _require(controls._read(control) == saved)
            manifest = {
                "schema_version": 1,
                "kind": "stock_application_snapshot",
                "created_at": now.isoformat(),
                "config_hash": str(loaded.config_hash),
                "code_hash": str(code_hash),
                "control": _control_summary(saved),
                "application": application,
                "files": _files(destination, loaded, window, published=False),
            }
            if validation_policy == RECOVERY_INTEGRITY_V1:
                manifest.update(
                    schema_version=2,
                    kind="stock_recovery_snapshot",
                    validation_policy=RECOVERY_INTEGRITY_V1,
                )
            raw = canonical_json(manifest).encode()
            _require(len(raw) <= _MAX_MANIFEST_BYTES)
            with _directory(destination) as directory:
                _write_bytes(directory, "manifest.json", raw, window)
            _require(_files(destination, loaded, window) == manifest["files"])
            window.check()
        window.check()
        return _result(manifest, raw)
    except Exception:
        raise ValueError("stock_snapshot_unavailable") from None


def _load(
    root: Path, window: _Window, validation_policy: SnapshotValidationPolicy = FULL_REPLAY_V1
) -> tuple[dict[str, Any], bytes, LoadedConfig, StockControlState]:
    _validation_policy(validation_policy)
    with _directory(root) as directory:
        raw = _read_bytes(directory, "manifest.json", _MAX_MANIFEST_BYTES, window)
        manifest = _json(raw)
        _require(
            set(manifest)
            == {
                "schema_version",
                "kind",
                "created_at",
                "config_hash",
                "code_hash",
                "control",
                "application",
                "files",
            }
            | ({"validation_policy"} if validation_policy == RECOVERY_INTEGRITY_V1 else set())
        )
        version = 1 if validation_policy == FULL_REPLAY_V1 else 2
        kind = "stock_application_snapshot" if version == 1 else "stock_recovery_snapshot"
        _require(type(manifest["schema_version"]) is int and manifest["schema_version"] == version)
        _require(manifest["kind"] == kind)
        if validation_policy == RECOVERY_INTEGRITY_V1:
            _require(manifest["validation_policy"] == validation_policy)
        _require(_HEX.fullmatch(manifest["code_hash"]) is not None)
        now = require_utc(datetime.fromisoformat(manifest["created_at"]))
        if validation_policy == RECOVERY_INTEGRITY_V1:
            _require(now.isoformat() == manifest["created_at"])
        loaded = restore_loaded_config(
            _read_bytes(directory, "canonical-config.json", 1048576, window),
            ConfigHash(manifest["config_hash"]),
        )
        control = _control(_read_bytes(directory, "saved-control.json", 8192, window), now)
        _require(canonical_json(_control_summary(control)) == canonical_json(manifest["control"]))
    _require(canonical_json(_files(root, loaded, window)) == canonical_json(manifest["files"]))
    return manifest, raw, loaded, control


async def verify_stock_snapshot(
    root: Path,
    *,
    now: datetime | None = None,
    validation_policy: SnapshotValidationPolicy = FULL_REPLAY_V1,
) -> SnapshotResult:
    """Apply the requested policy at the saved time; never renew source TTL."""
    try:
        window = _Window()
        manifest, raw, loaded, _ = _load(root, window, validation_policy)
        observed = require_utc(datetime.fromisoformat(manifest["created_at"]))
        _require(now is None or observed <= require_utc(now))
        validate = _replay if validation_policy == FULL_REPLAY_V1 else _recovery_integrity
        application = await validate(
            root, loaded, CodeHash(manifest["code_hash"]), observed, window
        )
        _require(canonical_json(application) == canonical_json(manifest["application"]))
        _require(_load(root, window, validation_policy)[1] == raw)
        window.check()
        return _result(manifest, raw)
    except Exception:
        raise ValueError("stock_snapshot_unavailable") from None


def restore_snapshot_controls(
    root: Path,
    *,
    destination: Path,
    now: datetime,
    high_water: StockControlState | None = None,
    validation_policy: SnapshotValidationPolicy = FULL_REPLAY_V1,
) -> ControlRestoreResult:
    """Create killed isolated controls. Missing authoritative high-water is offline-only.

    A supplied high-water must come from the caller's locked, owner-validated latest
    same-ID authority. A stale backup cannot establish that a later kill never occurred.
    This helper grants no deployment or replacement of any existing namespace.
    """
    try:
        window, now = _Window(), require_utc(now)
        _, _, _, saved = _load(root, window, validation_policy)
        basis = saved
        if high_water is not None:
            _require(type(high_water) is StockControlState)
            checked = _control(_encode(high_water.record), now)
            _require(checked == high_water)
            _require(checked.record.control_id == saved.record.control_id)
            _require(checked.record.generation >= saved.record.generation)
            if checked.record.generation == saved.record.generation:
                _require(checked == saved)
            if saved.record.status == "killed":
                _require(checked == saved)
            basis = checked
        _new_directory(destination)
        _new_directory(destination / "controls")
        with _directory(destination) as directory:
            _write_bytes(directory, "saved-control.json", _encode(saved.record), window)
            if high_water is not None:
                _write_bytes(
                    directory, "high-water-control.json", _encode(high_water.record), window
                )
        with _directory(destination / "controls") as directory:
            _write_bytes(directory, ".stock-control.lock", b"", window)
            _write_bytes(directory, "stock-control.json", _encode(basis.record), window)
        owner = StockResearchControls(destination / "controls", clock=lambda: now)
        restored = (
            owner.read()
            if basis.record.status == "killed"
            else owner.change("kill", expected_sha256=basis.sha256)
        )
        _require(restored.record.status == "killed" and owner.read() == restored)
        window.check()
        return ControlRestoreResult(
            restored.record.control_id,
            restored.record.generation,
            restored.sha256,
            high_water is None,
        )
    except Exception:
        raise ValueError("stock_snapshot_unavailable") from None
