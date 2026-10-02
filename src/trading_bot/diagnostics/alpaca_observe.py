"""Standalone bounded local Alpaca SPY/SIP observations; no broker or daemon.

No reconnect is automatic. A new segment can bind a previous terminal result,
but the interval between segments and initial control state remain unqualified.
The caller supplies existing operator-authorized local credentials explicitly.
"""

import asyncio
import hashlib
import json
import logging
import os
import ssl
import time
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import cast

from websockets.asyncio.client import connect

from trading_bot.clock import Clock, require_utc
from trading_bot.config import LoadedConfig
from trading_bot.diagnostics.alpaca_probe import _loaded_identity, _path, _screen_response
from trading_bot.diagnostics.alpaca_probe_io import (
    read_probe_credential,
)
from trading_bot.domain import ExecutionMode
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.alpaca_native import MAX_PAGE_BYTES, parse_timestamp_ns
from trading_bot.market_data.alpaca_observations import parse_alpaca_observation_frame
from trading_bot.market_data.bundle_codec import _array, _digest, _json, _mapping
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.bundle_store import _open_root, _publish, _read
from trading_bot.market_data.recording import canonical_json

_URL = "wss://stream.data.alpaca.markets/v2/sip"
_REPOSITORY = Path(__file__).resolve().parents[3]
_MAX_TOTAL_BYTES = 32 * 1024 * 1024
_LIMITS = BundleLimits(1_048_576, 1_048_576, 33_554_432, 10000, 32)
_RESULT_KEYS = {
    "schema",
    "plan_hash",
    "started_at_ns",
    "finished_at_ns",
    "receipt_hashes",
    "total_raw_bytes",
    "counts",
    "termination",
    "predecessor_result_hash",
    "segment_gap_before_start",
    "initial_control_state_verified",
    "transport_continuity_verified",
    "source_qualified",
    "execution_enabled",
    "evidence_promotable",
}


class AlpacaObservationError(ValueError):
    def __init__(self) -> None:
        super().__init__("alpaca_observation_capture_invalid")


def _check(condition: bool) -> None:
    if not condition:
        raise AlpacaObservationError()


@dataclass(frozen=True, slots=True, repr=False)
class ObservationPlan:
    code_revision: str
    config_hash: str
    prepared_at_ns: int
    expires_at_ns: int
    credential_file: Path
    output_root: Path
    repository_root: Path
    duration_seconds: int = 60
    max_frames: int = 10000
    predecessor_result_hash: str | None = None

    def __post_init__(self) -> None:
        _check(
            type(self.code_revision) is str
            and len(self.code_revision) == 40
            and all(c in "0123456789abcdef" for c in self.code_revision)
        )
        _require_sha256_hex(self.config_hash, "observation config")
        _check(type(self.prepared_at_ns) is int and self.prepared_at_ns >= 0)
        _check(type(self.expires_at_ns) is int)
        _check(self.expires_at_ns - self.prepared_at_ns == 1800 * 10**9)
        _check(type(self.duration_seconds) is int and 1 <= self.duration_seconds <= 900)
        _check(type(self.max_frames) is int and 1 <= self.max_frames <= 10000)
        _check(
            all(_path(p) for p in (self.credential_file, self.output_root, self.repository_root))
        )
        _check(not self.credential_file.is_relative_to(self.repository_root))
        _check(not self.output_root.is_relative_to(self.repository_root))
        _check(not self.credential_file.is_relative_to(self.output_root))
        if self.predecessor_result_hash is not None:
            _require_sha256_hex(self.predecessor_result_hash, "observation predecessor")

    @property
    def plan_hash(self) -> str:
        return hashlib.sha256(encode_observation_plan(self)).hexdigest()


def encode_observation_plan(plan: ObservationPlan) -> bytes:
    replace(plan)
    return canonical_json(
        {
            "schema": "alpaca-observation-plan-v1",
            "plan": {
                "code_revision": plan.code_revision,
                "config_hash": plan.config_hash,
                "prepared_at_ns": plan.prepared_at_ns,
                "expires_at_ns": plan.expires_at_ns,
                "credential_file": str(plan.credential_file),
                "output_root": str(plan.output_root),
                "repository_root": str(plan.repository_root),
                "duration_seconds": plan.duration_seconds,
                "max_frames": plan.max_frames,
                "predecessor_result_hash": plan.predecessor_result_hash,
            },
        }
    ).encode()


def decode_observation_plan(body: bytes) -> ObservationPlan:
    try:
        row = _mapping(_json(body, max_bytes=16384, limits=_LIMITS), {"schema", "plan"})
        _check(row["schema"] == "alpaca-observation-plan-v1")
        plan = _mapping(row["plan"], set(ObservationPlan.__dataclass_fields__))
        for key in ("credential_file", "output_root", "repository_root"):
            _check(type(plan[key]) is str)
            plan[key] = Path(cast(str, plan[key]))
        return ObservationPlan(**plan)  # type: ignore[arg-type]
    except (ValueError, TypeError, ArithmeticError, OSError):
        raise AlpacaObservationError() from None


def prepare_observation_capture(
    loaded: LoadedConfig,
    *,
    clock: Clock,
    code_revision: str,
    credential_file: Path,
    output_root: Path,
    repository_root: Path,
    duration_seconds: int = 60,
    max_frames: int = 10000,
    predecessor_result_hash: str | None = None,
) -> ObservationPlan:
    _loaded_identity(loaded)
    _check(loaded.config.mode is ExecutionMode.BACKTEST and not loaded.config.live_trading_enabled)
    now = require_utc(clock.now())
    return ObservationPlan(
        code_revision,
        str(loaded.config_hash),
        parse_timestamp_ns(now.isoformat()),
        parse_timestamp_ns((now + timedelta(minutes=30)).isoformat()),
        credential_file,
        output_root,
        repository_root,
        duration_seconds,
        max_frames,
        predecessor_result_hash,
    )


class _FixedConnect(connect):
    def process_redirect(self, exc: Exception) -> Exception:
        # Preserve the original fixed-host exception; never follow Location.
        return exc


def _rows(body: bytes) -> list[object]:
    return _array(_json(body, max_bytes=MAX_PAGE_BYTES, limits=_LIMITS))


def _success(body: bytes, message: str) -> None:
    _check(_rows(body) == [{"T": "success", "msg": message}])


def _subscription(body: bytes) -> None:
    rows = _rows(body)
    _check(len(rows) == 1 and type(rows[0]) is dict)
    row = cast(dict[str, object], rows[0])
    _check(row.get("T") == "subscription")
    for key in ("quotes", "statuses", "lulds"):
        _check(row.get(key) == ["SPY"])
    for key, value in row.items():
        if key not in ("T", "quotes", "statuses", "lulds"):
            _check(
                key in ("trades", "bars", "updatedBars", "dailyBars", "corrections", "cancelErrors")
            )
            _check(value == [])


def _predecessor(descriptor: int, digest: str | None, started_at_ns: int) -> None:
    if digest is None:
        return
    _require_sha256_hex(digest, "observation predecessor")
    body = _read(descriptor, digest + ".observation-result.json", MAX_PAGE_BYTES)
    _check(hashlib.sha256(body).hexdigest() == digest)
    row = _mapping(_json(body, max_bytes=MAX_PAGE_BYTES, limits=_LIMITS), _RESULT_KEYS)
    _check(row["schema"] == "alpaca-observation-result-v1")
    _digest(row["plan_hash"])
    started, finished = row["started_at_ns"], row["finished_at_ns"]
    _check(type(started) is int and type(finished) is int)
    _check(0 <= cast(int, started) <= cast(int, finished) <= started_at_ns)
    hashes = _array(row["receipt_hashes"])
    _check(len(hashes) <= 10000 and len(set(_digest(h) for h in hashes)) == len(hashes))
    total_bytes = row["total_raw_bytes"]
    _check(type(total_bytes) is int)
    _check(
        2 * len(hashes)
        <= cast(int, total_bytes)
        <= min(_MAX_TOTAL_BYTES, len(hashes) * MAX_PAGE_BYTES)
    )
    counts = _mapping(row["counts"], {"quote", "status", "luld"})
    _check(all(type(n) is int and 0 <= n <= len(hashes) * 1000 for n in counts.values()))
    _check(sum(cast(int, n) for n in counts.values()) <= len(hashes) * 1000)
    _check(
        row["termination"]
        in ("frame_limit", "duration_limit", "byte_limit_unretained_frame", "capture_failed")
    )
    # Prior plan/frame bytes are not recursively audited, but every supported
    # plan has 1 <= max_frames <= 10000, which rules out these terminal shapes.
    _check(row["termination"] != "frame_limit" or bool(hashes))
    _check(
        row["termination"] not in ("duration_limit", "byte_limit_unretained_frame")
        or len(hashes) < 10000
    )
    _check(
        row["termination"] != "byte_limit_unretained_frame"
        or cast(int, total_bytes) > _MAX_TOTAL_BYTES - MAX_PAGE_BYTES
    )
    if row["predecessor_result_hash"] is not None:
        _digest(row["predecessor_result_hash"])
    _check(row["segment_gap_before_start"] is True)
    for name in (
        "source_qualified",
        "execution_enabled",
        "evidence_promotable",
        "initial_control_state_verified",
        "transport_continuity_verified",
    ):
        _check(row[name] is False)


async def capture_observations(
    plan: ObservationPlan,
    *,
    loaded: LoadedConfig,
    clock: Clock,
    active_code_revision: str,
    approved_plan_hash: str,
) -> dict[str, object]:
    """Consume one reviewed scope; failures/uncertainty cannot replay its claim."""
    descriptor = -1
    try:
        replace(plan)
        _check(plan.repository_root == _REPOSITORY)
        _loaded_identity(loaded)
        _check(
            loaded.config.mode is ExecutionMode.BACKTEST and not loaded.config.live_trading_enabled
        )
        _check(plan.config_hash == str(loaded.config_hash))
        _check(plan.code_revision == active_code_revision and plan.plan_hash == approved_plan_hash)
        now_ns = parse_timestamp_ns(require_utc(clock.now()).isoformat())
        _check(
            plan.prepared_at_ns <= now_ns
            and now_ns + (plan.duration_seconds + 30) * 10**9 <= plan.expires_at_ns
        )
        descriptor = _open_root(plan.output_root, plan.repository_root)
        _predecessor(descriptor, plan.predecessor_result_hash, now_ns)
        claim = os.open(
            plan.plan_hash + ".observation.attempt",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=descriptor,
        )
        try:
            os.fchmod(claim, 0o600)
            os.fsync(claim)
            os.fsync(descriptor)
        finally:
            os.close(claim)
        _publish(
            descriptor, plan.plan_hash + ".observation-plan.json", encode_observation_plan(plan)
        )
        credential = read_probe_credential(
            plan.credential_file, repository_root=plan.repository_root
        )
        logger = logging.Logger("alpaca-observation-silent")
        logger.disabled = True
        receipt_hashes: list[str] = []
        total_bytes = 0
        previous_receipt: str | None = None
        previous_utc = now_ns
        previous_mono = time.monotonic_ns()
        counts = {"quote": 0, "status": 0, "luld": 0}
        termination = "capture_failed"
        try:
            async with _FixedConnect(
                _URL,
                ssl=ssl.create_default_context(),
                proxy=None,
                compression=None,
                open_timeout=10,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=10,
                max_size=MAX_PAGE_BYTES,
                max_queue=1,
                logger=logger,
            ) as connection:

                async def receive() -> bytes:
                    frame = await connection.recv()
                    body = frame.encode() if type(frame) is str else cast(bytes, frame)
                    _check(type(body) is bytes and 0 < len(body) <= MAX_PAGE_BYTES)
                    # The existing screen requires an object; wrap the exact frame
                    # only for duplicate-key and credential-echo screening. Its
                    # allowance includes the envelope; the raw limit above does not.
                    _screen_response(
                        b'{"frame":' + body + b"}", credential, max_bytes=MAX_PAGE_BYTES + 10
                    )
                    return body

                async with asyncio.timeout(10):
                    _success(await receive(), "connected")
                    await connection.send(
                        json.dumps(
                            {
                                "action": "auth",
                                "key": credential.key_id,
                                "secret": credential.secret_key,
                            }
                        )
                    )
                    _success(await receive(), "authenticated")
                    await connection.send(
                        '{"action":"subscribe","quotes":["SPY"],"statuses":["SPY"],"lulds":["SPY"]}'
                    )
                    _subscription(await receive())
                collection_deadline = asyncio.timeout(plan.duration_seconds)
                try:
                    async with collection_deadline:
                        while len(receipt_hashes) < plan.max_frames:
                            body = await receive()
                            received_ns = parse_timestamp_ns(require_utc(clock.now()).isoformat())
                            monotonic_ns = time.monotonic_ns()
                            _check(
                                previous_utc <= received_ns <= plan.expires_at_ns
                                and monotonic_ns >= previous_mono
                            )
                            if total_bytes + len(body) > _MAX_TOTAL_BYTES:
                                termination = "byte_limit_unretained_frame"
                                break
                            observations = parse_alpaca_observation_frame(
                                body, frame_index=len(receipt_hashes), received_at_ns=received_ns
                            )
                            raw_hash = hashlib.sha256(body).hexdigest()
                            _publish(descriptor, raw_hash + ".raw", body)
                            receipt = {
                                "schema": "alpaca-observation-receipt-v1",
                                "plan_hash": plan.plan_hash,
                                "frame_index": len(receipt_hashes),
                                "body_sha256": raw_hash,
                                "received_at_ns": received_ns,
                                "received_monotonic_ns": monotonic_ns,
                                "previous_receipt_hash": previous_receipt,
                                "observation_hashes": tuple(
                                    o.observation_hash for o in observations
                                ),
                            }
                            encoded = canonical_json(receipt).encode()
                            digest = hashlib.sha256(encoded).hexdigest()
                            _publish(descriptor, digest + ".observation-receipt.json", encoded)
                            receipt_hashes.append(digest)
                            previous_receipt = digest
                            previous_utc, previous_mono = received_ns, monotonic_ns
                            total_bytes += len(body)
                            for observation in observations:
                                counts[observation.kind] += 1
                        else:
                            termination = "frame_limit"
                except TimeoutError:
                    if not collection_deadline.expired():
                        raise
                    termination = "duration_limit"
        except Exception:
            # Never render provider text, headers, credentials or exception repr.
            termination = "capture_failed"
        finished_at_ns = parse_timestamp_ns(require_utc(clock.now()).isoformat())
        _check(previous_utc <= finished_at_ns <= plan.expires_at_ns)
        result = {
            "schema": "alpaca-observation-result-v1",
            "plan_hash": plan.plan_hash,
            "started_at_ns": now_ns,
            "finished_at_ns": finished_at_ns,
            "receipt_hashes": tuple(receipt_hashes),
            "total_raw_bytes": total_bytes,
            "counts": counts,
            "termination": termination,
            "predecessor_result_hash": plan.predecessor_result_hash,
            "segment_gap_before_start": True,
            "initial_control_state_verified": False,
            "transport_continuity_verified": False,
            "source_qualified": False,
            "execution_enabled": False,
            "evidence_promotable": False,
        }
        encoded = canonical_json(result).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        _publish(descriptor, digest + ".observation-result.json", encoded)
        return {
            "result_hash": digest,
            "counts": counts,
            "termination": termination,
            "source_qualified": False,
            "execution_enabled": False,
            "evidence_promotable": False,
        }
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
        raise AlpacaObservationError() from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def audit_observation_capture(
    root: Path, result_hash: str, repository_root: Path
) -> dict[str, object]:
    """Reparse each immutable frame and receipt; never infer halt-free history."""
    descriptor = -1
    try:
        _require_sha256_hex(result_hash, "observation result")
        descriptor = _open_root(root, repository_root)
        body = _read(descriptor, result_hash + ".observation-result.json", MAX_PAGE_BYTES)
        _check(hashlib.sha256(body).hexdigest() == result_hash)
        result = _mapping(
            _json(body, max_bytes=MAX_PAGE_BYTES, limits=_LIMITS),
            _RESULT_KEYS,
        )
        _check(result["schema"] == "alpaca-observation-result-v1")
        plan_hash = _digest(result["plan_hash"])
        plan_body = _read(descriptor, plan_hash + ".observation-plan.json", 16384)
        _check(hashlib.sha256(plan_body).hexdigest() == plan_hash)
        plan = decode_observation_plan(plan_body)
        _check(
            plan.plan_hash == plan_hash
            and plan.output_root == root
            and plan.repository_root == repository_root
        )
        _check(result["predecessor_result_hash"] == plan.predecessor_result_hash)
        for name in (
            "source_qualified",
            "execution_enabled",
            "evidence_promotable",
            "initial_control_state_verified",
            "transport_continuity_verified",
        ):
            _check(result[name] is False)
        _check(result["segment_gap_before_start"] is True)
        started, finished = result["started_at_ns"], result["finished_at_ns"]
        _check(type(started) is int and type(finished) is int)
        start_ns, end_ns = cast(int, started), cast(int, finished)
        _check(plan.prepared_at_ns <= start_ns <= end_ns <= plan.expires_at_ns)
        _predecessor(descriptor, plan.predecessor_result_hash, start_ns)
        hashes = _array(result["receipt_hashes"])
        _check(
            len(hashes) <= plan.max_frames and len(set(_digest(h) for h in hashes)) == len(hashes)
        )
        previous: str | None = None
        last_utc, last_mono = start_ns, 0
        total_bytes = 0
        counts = {"quote": 0, "status": 0, "luld": 0}
        quality = {"inactive": 0, "locked": 0, "crossed": 0, "two_sided_uncrossed": 0}
        skew_count = 0
        maximum_gap_ns: int | None = None
        for index, value in enumerate(hashes):
            digest = _digest(value)
            encoded = _read(descriptor, digest + ".observation-receipt.json", MAX_PAGE_BYTES)
            _check(hashlib.sha256(encoded).hexdigest() == digest)
            receipt = _mapping(
                _json(encoded, max_bytes=MAX_PAGE_BYTES, limits=_LIMITS),
                {
                    "schema",
                    "plan_hash",
                    "frame_index",
                    "body_sha256",
                    "received_at_ns",
                    "received_monotonic_ns",
                    "previous_receipt_hash",
                    "observation_hashes",
                },
            )
            _check(
                receipt["schema"] == "alpaca-observation-receipt-v1"
                and receipt["plan_hash"] == plan_hash
            )
            _check(type(receipt["frame_index"]) is int and receipt["frame_index"] == index)
            _check(receipt["previous_receipt_hash"] == previous)
            received, mono = receipt["received_at_ns"], receipt["received_monotonic_ns"]
            _check(type(received) is int and type(mono) is int)
            received_ns, mono_ns = cast(int, received), cast(int, mono)
            _check(last_utc <= received_ns <= end_ns and last_mono <= mono_ns <= 2**63 - 1)
            if index:
                maximum_gap_ns = max(maximum_gap_ns or 0, mono_ns - last_mono)
            raw_hash = _digest(receipt["body_sha256"])
            raw = _read(descriptor, raw_hash + ".raw", MAX_PAGE_BYTES)
            total_bytes += len(raw)
            _check(total_bytes <= _MAX_TOTAL_BYTES and hashlib.sha256(raw).hexdigest() == raw_hash)
            observations = parse_alpaca_observation_frame(
                raw, frame_index=index, received_at_ns=received_ns
            )
            _check(receipt["observation_hashes"] == [o.observation_hash for o in observations])
            for observation in observations:
                counts[observation.kind] += 1
                skew_count += observation.timestamp_ns > received_ns
                quote = observation.quote
                if quote is not None:
                    bucket = (
                        "inactive"
                        if quote.bid == 0 or quote.ask == 0
                        else "crossed"
                        if quote.bid > quote.ask
                        else "locked"
                        if quote.bid == quote.ask
                        else "two_sided_uncrossed"
                    )
                    quality[bucket] += 1
            previous, last_utc, last_mono = digest, received_ns, mono_ns
        declared_counts = _mapping(result["counts"], {"quote", "status", "luld"})
        _check(all(type(value) is int and value >= 0 for value in declared_counts.values()))
        _check(
            declared_counts == counts
            and type(result["total_raw_bytes"]) is int
            and result["total_raw_bytes"] == total_bytes
        )
        _check(
            result["termination"]
            in ("frame_limit", "duration_limit", "byte_limit_unretained_frame", "capture_failed")
        )
        # Transport close can fail after the final frame, preserving capture_failed.
        _check(result["termination"] != "frame_limit" or len(hashes) == plan.max_frames)
        _check(
            result["termination"] not in ("duration_limit", "byte_limit_unretained_frame")
            or len(hashes) < plan.max_frames
        )
        _check(
            result["termination"] != "byte_limit_unretained_frame"
            or total_bytes > _MAX_TOTAL_BYTES - MAX_PAGE_BYTES
        )
        return {
            "schema": "alpaca-observation-audit-v1",
            "result_hash": result_hash,
            "status": "OBSERVED_UNQUALIFIED" if any(counts.values()) else "BLOCKED_INPUTS",
            "counts": counts,
            "quote_quality": quality,
            "clock_skew_observation_count": skew_count,
            "maximum_interframe_receipt_gap_ns": maximum_gap_ns,
            "termination": result["termination"],
            "reference_bytes_reverified": True,
            "predecessor_result_bytes_reverified": plan.predecessor_result_hash is not None,
            "predecessor_frames_reverified": False,
            "reasons": (
                "initial_control_state_unknown",
                "stream_has_no_verified_gap_sequence",
                "segment_boundaries_are_discontinuities",
                "historical_controls_not_backfilled",
                "quote_eligibility_unverified",
                "customer_costs_not_measured_by_market_data",
            ),
            "source_qualified": False,
            "execution_enabled": False,
            "evidence_promotable": False,
        }
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError, AttributeError):
        raise AlpacaObservationError() from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
