"""Offline source-bound stock prices; hashes establish integrity, not authenticity.

Historical study timestamps and current receipt clocks are intentionally separate.
No currency, distribution, historical fundamentals or trade authority is inferred.
"""

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any, Literal, cast

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.recording import content_hash
from trading_bot.market_data.stock_daily_series import (
    StockDailyCalendar,
    parse_stock_daily_calendar,
)
from trading_bot.market_data.stock_split_comparison import (
    StockSplitRequest,
    StockSplitSeries,
    parse_stock_split_series,
)
from trading_bot.research.hybrid_strategies import PriceBar

STUDY_SYMBOLS = ("AXP", "AAPL", "BAC", "CVX", "KO", "KHC", "MCO", "OXY", "SPY")
_MAX_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class StockStudyInputs:
    bars: tuple[tuple[PriceBar, ...], ...]
    opens_at: tuple[datetime, ...]
    membership_use_not_before: datetime
    source_available_at: datetime
    manifest_sha256: str
    original_input_sha256s: tuple[tuple[str, str], ...]
    evidence_hash: str
    quote_currency: None = field(default=None, init=False)
    qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class StockStudyObservations:
    """Native observation output; construction is not source authentication.

    Use the original-file loader for source validation, never a caller-prepared
    instance as a substitute for rereading its complete pinned originals.
    """

    prices: StockStudyInputs
    calendar: StockDailyCalendar
    raw_series: tuple[StockSplitSeries, ...]
    split_series: tuple[StockSplitSeries, ...]
    quote_currency: None = field(default=None, init=False)
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    authenticated: Literal[False] = field(default=False, init=False)

    @property
    def evidence_hash(self) -> str:
        return str(
            content_hash(
                (
                    "stock-study-observations-v1",
                    self.prices.evidence_hash,
                    (
                        self.calendar.content_sha256,
                        self.calendar.received_at,
                        self.calendar.market_timezone,
                    ),
                    tuple(
                        (series.request.request_sha256, series.content_sha256, series.received_at)
                        for series in self.raw_series
                    ),
                    tuple(
                        (series.request.request_sha256, series.content_sha256, series.received_at)
                        for series in self.split_series
                    ),
                )
            )
        )


def _check(condition: bool) -> None:
    if not condition:
        raise ValueError("stock_study_inputs_invalid")


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in items:
        _check(key not in value)
        value[key] = item
    return value


def _constant(_value: str) -> None:
    raise ValueError("stock_study_inputs_invalid")


def _json(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    _check(type(value) is dict)
    return value  # type: ignore[no-any-return]


def _utc(value: str) -> datetime:
    _check(type(value) is str and len(value) <= 64)
    if value.endswith(" UTC"):
        value = value[:-4].replace(" ", "T") + "+00:00"
    return require_utc(datetime.fromisoformat(value))


def _stamp(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_at(directory: int, name: str) -> bytes:
    _check(
        type(name) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", name) is not None
    )
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        _check(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and 0 < before.st_size <= _MAX_BYTES
        )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(_MAX_BYTES + 1)
        _check(len(raw) == before.st_size)
        _check(
            _stamp(before)
            == _stamp(os.fstat(descriptor))
            == _stamp(os.stat(name, dir_fd=directory, follow_symlinks=False))
        )
        return raw
    finally:
        os.close(descriptor)


def _content(receipt: dict[str, Any], *, wrapped: bool, cutoff: datetime) -> bytes:
    _check(_utc(receipt["started_at"]) <= _utc(receipt["received_at"]) <= cutoff)
    result = receipt["result"]
    _check(type(result) is dict and result.get("isError", False) is False)
    blocks = result["content"]
    _check(type(blocks) is list and len(blocks) == 1)
    block = blocks[0]
    _check(type(block) is dict and block.get("type") == "text" and type(block.get("text")) is str)
    raw = cast(str, block["text"]).encode("utf-8")
    _check(0 < len(raw) <= _MAX_BYTES)
    if wrapped:
        _check(result["structuredContent"] == {"result": block["text"]})
    else:
        _check(_json(raw) == result["structuredContent"])
    return raw


def load_stock_study_inputs(
    evidence_directory: Path,
    manifest_path: Path,
    *,
    expected_manifest_sha256: str,
) -> StockStudyInputs:
    """Rehash all declared originals and rebuild all nine calendar-bound series.

    Only the already frozen no-split nine-symbol study is admitted here. Other
    cohorts or observed split factors require a separately specified adapter.
    Every native unknown interpolation/currency remains unknown in its original.
    """
    return _load_stock_study_originals(
        evidence_directory, manifest_path, expected_manifest_sha256=expected_manifest_sha256
    ).prices


def load_stock_study_observations(
    evidence_directory: Path,
    manifest_path: Path,
    *,
    expected_manifest_sha256: str,
) -> StockStudyObservations:
    """Freshly validate all pinned originals and retain native OHLC/volume fields.

    The fixed no-split study admission is identical to the legacy price loader.
    Unknown currency/interpolation and current receipt clocks stay unchanged.
    No caller-provided cache, factor, signal or prepared input is accepted.
    """
    return _load_stock_study_originals(
        evidence_directory, manifest_path, expected_manifest_sha256=expected_manifest_sha256
    )


def _load_stock_study_originals(
    evidence_directory: Path,
    manifest_path: Path,
    *,
    expected_manifest_sha256: str,
) -> StockStudyObservations:
    """One complete whole-original read/decode shared by both public projections."""
    descriptors: list[int] = []
    try:
        _require_sha256_hex(expected_manifest_sha256, "stock study manifest")
        for root in (evidence_directory, manifest_path.parent):
            _check(isinstance(root, Path) and root.is_absolute() and root.resolve() == root)
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(descriptor)
        source_dir, manifest_dir = descriptors
        raw_manifest = _read_at(manifest_dir, manifest_path.name)
        _check(hashlib.sha256(raw_manifest).hexdigest() == expected_manifest_sha256)
        manifest = _json(raw_manifest)
        _check(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1)
        _check(manifest["kind"] == "primary_common_nine_original_input_handoff")
        _check(
            all(
                manifest[k] is False
                for k in ("qualified", "source_qualified", "investment_eligible", "live_enabled")
            )
        )
        cutoff = _utc(manifest["as_of"])
        bindings = manifest["all_original_input_bindings"]
        _check(type(bindings) is dict and 20 <= len(bindings) <= 128)
        originals: dict[str, bytes] = {}
        for name, pin in bindings.items():
            _check(type(pin) is dict and type(pin["bytes"]) is int)
            _require_sha256_hex(pin["sha256"], "stock input")
            body = _read_at(source_dir, name)
            _check(len(body) == pin["bytes"] and hashlib.sha256(body).hexdigest() == pin["sha256"])
            originals[name] = body

        def original(ref: dict[str, Any]) -> dict[str, Any]:
            _check(type(ref) is dict and type(ref["file"]) is str)
            pin = bindings[ref["file"]]
            _check(ref["sha256"] == pin["sha256"] and ref["bytes"] == pin["bytes"])
            return _json(originals[ref["file"]])

        frame = original(manifest["primary_frame"])
        member_at = datetime.combine(
            datetime.fromisoformat(frame["membership_use_not_before"]).date(), time(), UTC
        )
        cal_ref = manifest["calendar"]
        cal_receipt = original(cal_ref)
        _check(cal_receipt["request"]["tool"] == "mcp__codex_apps__alpaca_get_calendar")
        cal_bytes = _content(cal_receipt, wrapped=True, cutoff=cutoff)
        calendar = parse_stock_daily_calendar(
            cal_bytes,
            expected_sha256=cal_ref["content_text_utf8_sha256"],
            received_at=_utc(cal_receipt["received_at"]),
            market_timezone=cal_ref["explicit_interpretation_timezone"],
        )
        _check(
            cal_receipt["request"]["args"]
            == {
                "start_date": calendar.request_start.isoformat(),
                "end_date": calendar.request_end.isoformat(),
            }
        )
        _check(type(cal_ref["sessions"]) is int and len(calendar.sessions) == cal_ref["sessions"])
        _check(
            221 <= len(calendar.sessions) <= 10000 and member_at <= calendar.sessions[-1].closes_at
        )
        symbols = manifest["symbols"]
        _check(type(symbols) is list and tuple(row["symbol"] for row in symbols) == STUDY_SYMBOLS)
        bars: list[tuple[PriceBar, ...]] = []
        raw_series: list[StockSplitSeries] = []
        split_series: list[StockSplitSeries] = []
        receipts = [_utc(cal_receipt["received_at"])]
        for symbol, row in zip(STUDY_SYMBOLS, symbols, strict=True):
            refs = row["original_receipts"]
            _check(type(refs) is list and len(refs) == 2 and refs[0]["file"] != refs[1]["file"])
            pair = []
            adjustments: tuple[Literal["none", "split"], ...] = ("none", "split")
            for adjustment, ref in zip(adjustments, refs, strict=True):
                receipt = original(ref)
                request = receipt["request"]
                args = request["args"]
                _check(request["tool"] == "mcp__robinhood_2__get_equity_historicals")
                _check(
                    set(args)
                    == {
                        "symbols",
                        "start_time",
                        "end_time",
                        "interval",
                        "bounds",
                        "adjustment_type",
                    }
                )
                _check(
                    args["symbols"] == [symbol]
                    and args["interval"] == "day"
                    and args["bounds"] == "regular"
                    and args["adjustment_type"] == adjustment
                )
                req = StockSplitRequest(
                    symbol, _utc(args["start_time"]), _utc(args["end_time"]), adjustment
                )
                _check(
                    req.start_time.date()
                    <= calendar.request_start
                    <= calendar.request_end
                    < req.end_time.date()
                )
                body = _content(receipt, wrapped=False, cutoff=cutoff)
                received_at = _utc(receipt["received_at"])
                series = parse_stock_split_series(
                    body,
                    expected_sha256=ref["content_text_utf8_sha256"],
                    request=req,
                    received_at=received_at,
                )
                _check(
                    not series.null_bar_indices
                    and not series.results_missing
                    and not series.bars_missing
                    and not series.not_found
                )
                _check(len(series.bars) == len(calendar.sessions))
                for native, session in zip(series.bars, calendar.sessions, strict=True):
                    _check(
                        native.begins_at == datetime.combine(session.session_date, time(), UTC)
                        and session.closes_at <= received_at
                        and native.volume > 0
                        and native.interpolated is not True
                        and native.session == "reg"
                    )
                pair.append(series)
                receipts.append(received_at)
            _check(pair[0].bars == pair[1].bars)
            raw_series.append(pair[0])
            split_series.append(pair[1])
            bars.append(
                tuple(
                    PriceBar(s.closes_at, b.open_price, b.close_price)
                    for b, s in zip(pair[1].bars, calendar.sessions, strict=True)
                )
            )
        hashes = tuple(sorted((name, pin["sha256"]) for name, pin in bindings.items()))
        digest = str(
            content_hash(
                (
                    "stock-study-inputs-v1",
                    expected_manifest_sha256,
                    hashes,
                    member_at,
                    max(receipts),
                )
            )
        )
        prices = StockStudyInputs(
            tuple(bars),
            tuple(s.opens_at for s in calendar.sessions),
            member_at,
            max(receipts),
            expected_manifest_sha256,
            hashes,
            digest,
        )
        return StockStudyObservations(prices, calendar, tuple(raw_series), tuple(split_series))
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        ArithmeticError,
        AttributeError,
        RecursionError,
    ):
        raise ValueError("stock_study_inputs_invalid") from None
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
