"""Bounded individual-stock MCP observations; research receipts confer no authority."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import stat
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from trading_bot.brokers.robinhood_mcp_schema_gate import JsonValue
from trading_bot.brokers.robinhood_mcp_sdk import RobinhoodMcpSdkConnection
from trading_bot.brokers.stock_research_mcp import (
    PROFILE_SHA256,
    STOCK_RESEARCH_TOOLS,
    StockResearchTransport,
    _arguments,
    _profile,
)
from trading_bot.clock import require_utc
from trading_bot.market_data.bundle_store import _open_root
from trading_bot.runtime.capability_capture import _suppress_untrusted_dependency_logs


class StockCaptureError(RuntimeError):
    """Sanitized failure boundary; never contains provider text."""


_MAX_ARTIFACT_BYTES = 9_000_000


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _raise_pending_cancellation() -> None:
    task = asyncio.current_task()
    if task is not None and task.cancelling():
        raise asyncio.CancelledError


@dataclass(frozen=True, slots=True, init=False)
class StockCaptureRequest:
    tool: str
    encoded_arguments: bytes

    def __init__(self, tool: str, arguments: Mapping[str, JsonValue]) -> None:
        try:
            if tool not in STOCK_RESEARCH_TOOLS:
                raise ValueError("outside research profile")
            body = _json(dict(arguments))
            snapshot = json.loads(body)
            _arguments(tool, snapshot, _profile()[tool])
            object.__setattr__(self, "tool", tool)
            object.__setattr__(self, "encoded_arguments", body)
        except Exception:
            raise StockCaptureError("stock research plan invalid") from None

    @property
    def arguments(self) -> dict[str, JsonValue]:
        value: dict[str, JsonValue] = json.loads(self.encoded_arguments)
        return value


def parse_stock_capture_plan(value: object) -> tuple[StockCaptureRequest, ...]:
    """Job inputs, not a competing investment/runtime configuration system."""
    try:
        if type(value) is not list or not 1 <= len(value) <= 32:
            raise ValueError("bounded plan required")
        result = []
        for row in value:
            if type(row) is not dict or set(row) != {"tool", "arguments"}:
                raise ValueError("invalid plan row")
            if type(row["tool"]) is not str or type(row["arguments"]) is not dict:
                raise ValueError("invalid plan fields")
            result.append(StockCaptureRequest(row["tool"], row["arguments"]))
        return tuple(result)
    except Exception:
        raise StockCaptureError("stock research plan invalid") from None


def _private_directory(root: Path) -> int:
    if not root.is_absolute() or root.resolve() != root:
        raise StockCaptureError("private stock artifact directory required")
    if root.is_relative_to(Path(__file__).resolve().parents[3]):
        raise StockCaptureError("stock observations must remain outside source checkout")
    try:
        # Reuse the component-wise O_NOFOLLOW walk; a parent swap cannot make a
        # checked path follow a newly introduced symlink during the final open.
        return _open_root(root, Path(__file__).resolve().parents[3])
    except Exception:
        raise StockCaptureError("private stock artifact directory required") from None


def _duplicate_directory(directory: int) -> int:
    """Borrow an internal verified handle without reopening its mutable path."""
    descriptor = -1
    try:
        if type(directory) is not int or directory < 0:
            raise ValueError
        descriptor = os.dup(directory)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise ValueError
        return descriptor
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        raise StockCaptureError("private stock artifact directory required") from None


def _publish(directory: int, body: bytes, suffix: str) -> tuple[str, str]:
    if len(body) > _MAX_ARTIFACT_BYTES:
        raise StockCaptureError("stock research artifact exceeds bound")
    digest = hashlib.sha256(body).hexdigest()
    name = digest + suffix
    temporary = ".pending-" + uuid.uuid4().hex
    published = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        published = True
        os.fsync(directory)
    except BaseException:
        if published:
            os.unlink(name, dir_fd=directory)
        raise
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory)
    return name, digest


async def capture_stock_observations(
    *,
    transport: StockResearchTransport,
    requests: Sequence[StockCaptureRequest],
    output_dir: Path,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    transport_authenticated: bool,
    before_call: Callable[[int, StockCaptureRequest], Awaitable[object]] | None = None,
    _directory_fd: int | None = None,
) -> dict[str, object]:
    """No retries. Partial acquisitions retain observations and an explicit manifest.

    The caller owns schema validation and authenticated transport construction. These
    are SDK-level native results, not retained HTTP wire frames or historical data
    qualification. External text is stored as data and never interpreted as commands.
    An optional caller-owned admission hook completes before each attempted send.
    Its denial preserves the existing sanitized partial-manifest contract.
    """
    directory = -1
    try:
        if (
            type(transport_authenticated) is not bool
            or not 1 <= len(requests) <= 32
            or (before_call is not None and not callable(before_call))
        ):
            raise StockCaptureError("stock research plan invalid")
        # Validate the complete immutable request graph before any provider call.
        plan = tuple(StockCaptureRequest(item.tool, item.arguments) for item in requests)
        directory = (
            _private_directory(output_dir)
            if _directory_fd is None
            else _duplicate_directory(_directory_fd)
        )
        started = require_utc(clock())
        last_received = started
        deadline = time.monotonic() + 300
        observations: list[dict[str, object]] = []
        attempted = 0
        failure: str | None = None
        cancelled: asyncio.CancelledError | None = None
        try:
            for index, request in enumerate(plan):
                if index:
                    await sleep(1.0)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    failure = "research_run_budget_exhausted"
                    break
                if before_call is not None:
                    guard_deadline = time.monotonic() + min(45, remaining)
                    try:
                        admitted = await asyncio.wait_for(
                            before_call(index, request), timeout=min(45, remaining)
                        )
                        if admitted is not None:
                            raise ValueError("stock research admission invalid")
                    except Exception:
                        failure = "research_call_failed"
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        failure = "research_run_budget_exhausted"
                        break
                    if time.monotonic() >= guard_deadline:
                        failure = "research_call_failed"
                        break
                request_started = require_utc(clock())
                if request_started < last_received:
                    raise StockCaptureError("stock research receipt clock invalid")
                _raise_pending_cancellation()
                attempted += 1
                try:
                    result = await asyncio.wait_for(
                        transport.call_tool(request.tool, request.arguments),
                        timeout=min(45, remaining),
                    )
                    _raise_pending_cancellation()
                    received = require_utc(clock())
                    if received < request_started:
                        raise StockCaptureError("stock research receipt clock invalid")
                    if result.is_error or type(result.structured_content) is not dict:
                        raise ValueError("missing structured result")
                    payload = _json(result.structured_content)
                    if len(payload) > 8_388_608:
                        raise ValueError("result exceeds observation bound")
                except StockCaptureError:
                    raise
                except Exception:
                    failure = "research_call_failed"
                    break
                envelope = {
                    "schema_version": 1,
                    "provider": "robinhood_official_mcp",
                    "tool": request.tool,
                    "arguments": request.arguments,
                    "request_started_at": request_started.isoformat(),
                    "received_at": received.isoformat(),
                    "available_at": received.isoformat(),
                    "schema_profile_sha256": PROFILE_SHA256,
                    "tool_schema_sha256": _profile()[request.tool]["schemaSha256"],
                    "payload_sha256": hashlib.sha256(payload).hexdigest(),
                    "payload": result.structured_content,
                    "transport_authenticated": transport_authenticated,
                    "native_http_wire_receipt": False,
                    "qualified": False,
                    "live_enabled": False,
                }
                name, digest = _publish(directory, _json(envelope), ".stock-observation.json")
                observations.append({"file": name, "sha256": digest, "tool": request.tool})
                last_received = received
        except asyncio.CancelledError as exc:
            failure = "research_capture_cancelled"
            cancelled = exc
        completed = require_utc(clock())
        if completed < last_received:
            raise StockCaptureError("stock research receipt clock invalid")
        manifest = {
            "schema_version": 1,
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat(),
            "request_plan_sha256": hashlib.sha256(
                _json([{"tool": item.tool, "arguments": item.arguments} for item in plan])
            ).hexdigest(),
            "planned_calls": len(plan),
            "attempted_calls": attempted,
            "successful_calls": len(observations),
            "status": "complete" if failure is None else "partial",
            "failure_code": failure,
            "schema_profile_sha256": PROFILE_SHA256,
            "observations": observations,
            "transport_authenticated": transport_authenticated,
            "native_http_wire_receipt": False,
            "qualified": False,
            "live_enabled": False,
        }
        name, digest = _publish(directory, _json(manifest), ".stock-capture.json")
        if cancelled is not None:
            raise cancelled
        return {
            key: manifest[key]
            for key in (
                "status",
                "planned_calls",
                "attempted_calls",
                "successful_calls",
                "failure_code",
                "transport_authenticated",
                "qualified",
                "live_enabled",
            )
        } | {"manifest_file": name, "manifest_sha256": digest}
    except Exception:
        raise StockCaptureError("stock research capture failed safely") from None
    finally:
        if directory >= 0:
            os.close(directory)


def run_stock_capture(*, oauth_store: Path, plan: object, output_dir: Path) -> dict[str, object]:
    requests = parse_stock_capture_plan(plan)
    try:
        descriptor = _private_directory(output_dir)
    except Exception:
        raise StockCaptureError("private stock artifact directory required") from None

    async def capture() -> dict[str, object]:
        async with RobinhoodMcpSdkConnection(oauth_store_dir=oauth_store) as connection:
            session = connection.stock_research_session
            await session.validate_tools()
            return await capture_stock_observations(
                transport=StockResearchTransport(session),
                requests=requests,
                output_dir=output_dir,
                transport_authenticated=True,
                _directory_fd=descriptor,
            )

    try:
        # No callback is installed: expired/revoked grants cannot silently open login.
        with _suppress_untrusted_dependency_logs():
            return asyncio.run(capture())
    except Exception:
        raise StockCaptureError("stock research capture failed safely") from None
    finally:
        os.close(descriptor)


def read_stock_capture_plan(path: Path) -> object:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= 131072:
            raise StockCaptureError("stock research plan invalid")
        body = os.read(descriptor, 131073)
        if not 0 < len(body) <= 131072:
            raise StockCaptureError("stock research plan invalid")
        return json.loads(body)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oauth-store", type=Path, required=True)
    parser.add_argument("--requests-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = read_stock_capture_plan(args.requests_file)
        print(
            json.dumps(
                run_stock_capture(
                    oauth_store=args.oauth_store,
                    plan=plan,
                    output_dir=args.output_dir,
                ),
                sort_keys=True,
            )
        )
        return 0
    except Exception:
        print('{"status":"failed","reason":"stock_research_capture_failed","live_enabled":false}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
