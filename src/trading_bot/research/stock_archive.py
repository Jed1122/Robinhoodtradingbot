"""Rehash retained SDK observation receipts before descriptive stock analysis."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from trading_bot.brokers.stock_research_mcp import (
    PROFILE_SHA256,
    STOCK_RESEARCH_TOOLS,
    _arguments,
    _profile,
)
from trading_bot.clock import require_utc


def _read(directory: int, name: str, suffix: str) -> dict[str, Any]:
    if re.fullmatch("[0-9a-f]{64}" + re.escape(suffix), name) is None:
        raise ValueError("stock_archive_invalid")
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
            or metadata.st_nlink != 1
            or not 0 < metadata.st_size <= 9_000_000
        ):
            raise ValueError("stock_archive_invalid")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            body = handle.read(9_000_001)
        if len(body) != metadata.st_size or hashlib.sha256(body).hexdigest() != name[:64]:
            raise ValueError("stock_archive_invalid")
        value: dict[str, Any] = json.loads(body)
        if type(value) is not dict:
            raise ValueError("stock_archive_invalid")
        return value
    finally:
        os.close(descriptor)


def read_stock_observations(root: Path, manifest_file: str) -> tuple[dict[str, Any], ...]:
    """Only manifest-committed observations count; crash orphans are ignored.

    Rehashing proves retained-byte integrity, not independent vendor attestation or
    data/economic qualification. Provider text remains untrusted data.
    """
    directory = -1
    try:
        if not root.is_absolute() or root.resolve() != root:
            raise ValueError("stock_archive_invalid")
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        metadata = os.fstat(directory)
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise ValueError("stock_archive_invalid")
        manifest = _read(directory, manifest_file, ".stock-capture.json")
        rows = manifest["observations"]
        counts = tuple(
            manifest[name] for name in ("planned_calls", "attempted_calls", "successful_calls")
        )
        if any(type(value) is not int for value in counts):
            raise ValueError("stock_archive_invalid")
        planned, attempted, successful = counts
        if not (1 <= planned <= 32 and 0 <= successful <= attempted <= planned):
            raise ValueError("stock_archive_invalid")
        if manifest["status"] == "complete":
            if (
                planned != attempted
                or attempted != successful
                or manifest["failure_code"] is not None
            ):
                raise ValueError("stock_archive_invalid")
        elif (
            manifest["failure_code"]
            not in {
                "research_call_failed",
                "research_capture_cancelled",
                "research_run_budget_exhausted",
            }
            or successful >= planned
        ):
            raise ValueError("stock_archive_invalid")
        manifest_start = require_utc(datetime.fromisoformat(manifest["started_at"]))
        manifest_end = require_utc(datetime.fromisoformat(manifest["completed_at"]))
        if manifest_start > manifest_end:
            raise ValueError("stock_archive_invalid")
        authenticated = manifest["transport_authenticated"]
        if type(authenticated) is not bool or manifest["native_http_wire_receipt"] is not False:
            raise ValueError("stock_archive_invalid")
        if (
            manifest["schema_version"] != 1
            or manifest["schema_profile_sha256"] != PROFILE_SHA256
            or manifest["qualified"] is not False
            or manifest["live_enabled"] is not False
            or manifest["status"] not in {"complete", "partial"}
            or type(rows) is not list
            or not 0 <= len(rows) <= 32
            or manifest["successful_calls"] != len(rows)
        ):
            raise ValueError("stock_archive_invalid")
        result = []
        previous_received = manifest_start
        seen: set[str] = set()
        for row in rows:
            if row["sha256"] != row["file"][:64] or row["tool"] not in STOCK_RESEARCH_TOOLS:
                raise ValueError("stock_archive_invalid")
            if row["file"] in seen:
                raise ValueError("stock_archive_invalid")
            seen.add(row["file"])
            item = _read(directory, row["file"], ".stock-observation.json")
            if (
                item["schema_version"] != 1
                or item["provider"] != "robinhood_official_mcp"
                or item["tool"] != row["tool"]
                or item["schema_profile_sha256"] != PROFILE_SHA256
                or item["tool_schema_sha256"] != _profile()[item["tool"]]["schemaSha256"]
                or item["qualified"] is not False
                or item["live_enabled"] is not False
                or item["native_http_wire_receipt"] is not False
                or type(item["transport_authenticated"]) is not bool
                or item["transport_authenticated"] != authenticated
                or item["available_at"] != item["received_at"]
            ):
                raise ValueError("stock_archive_invalid")
            _arguments(item["tool"], item["arguments"], _profile()[item["tool"]])
            start = require_utc(datetime.fromisoformat(item["request_started_at"]))
            end = require_utc(datetime.fromisoformat(item["received_at"]))
            if not previous_received <= start <= end <= manifest_end:
                raise ValueError("stock_archive_invalid")
            previous_received = end
            encoded = json.dumps(
                item["payload"], sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
            if hashlib.sha256(encoded).hexdigest() != item["payload_sha256"]:
                raise ValueError("stock_archive_invalid")
            result.append(item | {"observation_sha256": row["sha256"]})
        return tuple(result)
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
        raise ValueError("stock_archive_invalid") from None
    finally:
        if directory >= 0:
            os.close(directory)
