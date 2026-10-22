"""Pure local per-symbol history projections; known-company failures quarantine whole series."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.market_data.recording import content_hash
from trading_bot.market_data.stock_facts import (
    StockDailyBar,
    StockFactCollection,
    StockObservationReceipt,
    normalize_daily_bars,
)

_Reason = Literal[
    "symbol_history_normalized",
    "source_symbol_not_found",
    "no_normalized_daily_bars",
    "daily_history_validation_failed",
]
_Status = Literal["normalized", "unavailable", "quarantined"]
_LIMITATIONS = (
    "local_symbol_projection_not_native_provider_payload",
    "original_source_hash_is_caller_declared_not_authenticated",
    "coverage_and_calendar_completeness_unverified",
    "quarantined_company_history_is_not_partially_returned",
    "raw_basis_and_completion_remain_caller_declarations",
)


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("stock_history_projection_invalid_batch")


def _object(value: object) -> dict[str, object]:
    _check(isinstance(value, Mapping))
    if not isinstance(value, Mapping):
        raise ValueError("stock_history_projection_invalid_batch")
    _check(all(type(key) is str for key in value))
    return dict(value)


def _symbol(value: object) -> str:
    _check(
        type(value) is str and re.fullmatch(r"[A-Z0-9][A-Z0-9.$+^=/@_-]{0,31}", value) is not None
    )
    return str(value)


@dataclass(frozen=True, slots=True)
class StockHistoryProjectionContext:
    original_source_sha256: str
    original_requested_symbols: tuple[str, ...]
    original_result_index: int | None
    original_not_found_index: int | None
    projected_payload_sha256: str
    is_local_projection: Literal[True] = field(default=True, init=False)
    is_native_provider_payload: Literal[False] = field(default=False, init=False)
    projected_encoding: Literal["json-ascii-sorted-compact-v1"] = field(
        default="json-ascii-sorted-compact-v1", init=False
    )

    @property
    def source_path(self) -> tuple[str | int, ...]:
        if self.original_result_index is not None:
            return ("data", "results", self.original_result_index)
        if self.original_not_found_index is not None:
            return ("data", "not_found", self.original_not_found_index)
        raise ValueError("stock_history_projection_invalid_context")


@dataclass(frozen=True, slots=True)
class StockHistorySymbolOutcome:
    symbol: str
    context: StockHistoryProjectionContext
    normalized: StockFactCollection[StockDailyBar] | None
    status: _Status
    reason_codes: tuple[_Reason, ...]
    is_local_projection: Literal[True] = field(default=True, init=False)
    is_native_provider_payload: Literal[False] = field(default=False, init=False)
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    @property
    def original_source_sha256(self) -> str:
        return self.context.original_source_sha256

    @property
    def original_result_index(self) -> int | None:
        return self.context.original_result_index

    @property
    def explicit_not_found(self) -> bool:
        return self.context.original_not_found_index is not None

    @property
    def projected_payload_sha256(self) -> str:
        return self.context.projected_payload_sha256


@dataclass(frozen=True, slots=True)
class StockHistoryProjectionBatch:
    receipt: StockObservationReceipt
    requested_symbols: tuple[str, ...]
    outcomes: tuple[StockHistorySymbolOutcome, ...]
    request_adjustment_type: Literal["none"] | None
    completed_before: datetime | None
    is_local_projection: Literal[True] = field(default=True, init=False)
    is_native_provider_payload: Literal[False] = field(default=False, init=False)
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)

    @property
    def observation_hash(self) -> str:
        return str(content_hash(("stock-history-projection-v1", self)))


def _correlate(
    payload: Mapping[str, object], requested: tuple[str, ...]
) -> tuple[dict[str, tuple[int, dict[str, object]]], dict[str, int], str | None]:
    root = _object(payload)
    _check(set(root) <= {"data", "guide"})
    guide = root.get("guide")
    _check("guide" not in root or (type(guide) is str and len(str(guide)) <= 65536))
    data = _object(root.get("data"))
    _check(set(data) <= {"results", "not_found"})
    results = data.get("results")
    _check(type(results) is list and len(results) <= 10)
    if not isinstance(results, list):
        raise ValueError("stock_history_projection_invalid_batch")
    not_found = data.get("not_found")
    if not_found is None:
        not_found = []
    _check(type(not_found) is list and len(not_found) <= 10)
    if not isinstance(not_found, list):
        raise ValueError("stock_history_projection_invalid_batch")
    _check(len(results) + len(not_found) <= 10)
    correlated: dict[str, tuple[int, dict[str, object]]] = {}
    total_rows = 0
    for index, item in enumerate(results):
        row = _object(item)
        symbol = _symbol(row.get("symbol"))
        _check(symbol in requested and symbol not in correlated)
        correlated[symbol] = (index, row)
        bars = row.get("bars")
        if type(bars) is list:
            total_rows += len(bars)
            _check(total_rows <= 30000)
    absent: dict[str, int] = {}
    for index, item in enumerate(not_found):
        symbol = _symbol(item)
        _check(symbol in requested and symbol not in correlated and symbol not in absent)
        absent[symbol] = index
    _check(set(requested) == set(correlated).union(absent))
    return correlated, absent, None if guide is None else str(guide)


def _projected_hash(projected: Mapping[str, object]) -> str:
    try:
        encoded = json.dumps(
            dict(projected),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise ValueError("stock_history_projection_invalid_batch") from None
    return hashlib.sha256(encoded).hexdigest()


def normalize_history_by_symbol(
    payload: Mapping[str, object],
    *,
    received_at: datetime,
    observation_sha256: str,
    requested_symbols: tuple[str, ...],
    request_adjustment_type: Literal["none"] | None = None,
    completed_before: datetime | None = None,
) -> StockHistoryProjectionBatch:
    """Validate original batch identity, then normalize or quarantine each whole company."""
    try:
        receipt = StockObservationReceipt(
            "get_equity_historicals", require_utc(received_at), observation_sha256
        )
        cutoff = None if completed_before is None else require_utc(completed_before)
    except ValueError:
        raise ValueError("stock_history_projection_invalid_batch") from None
    _check(
        request_adjustment_type is None
        or (type(request_adjustment_type) is str and request_adjustment_type == "none")
    )
    _check(cutoff is None or cutoff <= receipt.received_at)
    _check(type(requested_symbols) is tuple and 1 <= len(requested_symbols) <= 10)
    requested = tuple(_symbol(item) for item in requested_symbols)
    _check(len(set(requested)) == len(requested))
    correlated, absent, guide = _correlate(payload, requested)
    outcomes = []
    for symbol in requested:
        source_index: int | None = None
        absent_index = absent.get(symbol)
        projected_data: dict[str, object]
        if absent_index is not None:
            projected_data = {"results": [], "not_found": [symbol]}
        else:
            source_index, original_row = correlated[symbol]
            projected_data = {"results": [original_row]}
        projected: dict[str, object] = {"data": projected_data}
        if guide is not None:
            projected["guide"] = guide
        projected_sha256 = _projected_hash(projected)
        context = StockHistoryProjectionContext(
            observation_sha256, requested, source_index, absent_index, projected_sha256
        )
        normalized: StockFactCollection[StockDailyBar] | None
        status: _Status
        reasons: tuple[_Reason, ...]
        try:
            normalized = normalize_daily_bars(
                projected,
                received_at=receipt.received_at,
                observation_sha256=projected_sha256,
                requested_symbols=(symbol,),
                request_adjustment_type=request_adjustment_type,
                completed_before=cutoff,
            )
        except ValueError:
            normalized = None
            status, reasons = "quarantined", ("daily_history_validation_failed",)
        else:
            if absent_index is not None:
                status, reasons = "unavailable", ("source_symbol_not_found",)
            elif not normalized.records:
                status, reasons = "unavailable", ("no_normalized_daily_bars",)
            else:
                status, reasons = "normalized", ("symbol_history_normalized",)
        outcomes.append(StockHistorySymbolOutcome(symbol, context, normalized, status, reasons))
    return StockHistoryProjectionBatch(
        receipt, requested, tuple(outcomes), request_adjustment_type, cutoff
    )
