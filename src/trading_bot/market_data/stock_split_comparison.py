"""Pure one-event comparison of retained MCP content, never source qualification."""

import hashlib
import json
import re
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Literal, cast

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.alpaca_native import parse_timestamp_ns
from trading_bot.market_data.recording import content_hash

_MAX_BYTES = 8 * 1024 * 1024
_FLAGS = (
    "qualified",
    "source_qualified",
    "strategy_qualified",
    "investment_eligible",
    "trading_enabled",
    "live_authorized",
    "is_original_upstream_wire",
)
_LIMITATIONS = (
    "mcp_content_not_original_upstream_http_wire",
    "request_and_receipt_evidence_not_independently_authenticated",
    "one_event_not_source_wide_corporate_action_coverage",
    "calendar_and_issuer_evidence_not_authenticated",
    "native_interpolation_omission_remains_unknown",
    "split_price_changes_not_total_returns_or_historical_availability",
)


class StockSplitComparisonError(ValueError):
    def __init__(self) -> None:
        super().__init__("stock_split_comparison_invalid")


def _check(condition: bool) -> None:
    if not condition:
        raise StockSplitComparisonError()


def _utc(value: datetime) -> datetime:
    _check(type(value) is datetime)
    return require_utc(value)


def _scope(value: object) -> None:
    _check(all(getattr(value, name) is False for name in _FLAGS))


@dataclass(frozen=True, slots=True, repr=False)
class _Unqualified:
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    is_original_upstream_wire: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True, repr=False)
class StockSplitRequest(_Unqualified):
    symbol: str
    start_time: datetime
    end_time: datetime
    adjustment_type: Literal["none", "split"]
    interval: Literal["day"] = field(default="day", init=False)
    bounds: Literal["regular"] = field(default="regular", init=False)
    tool: Literal["get_equity_historicals"] = field(default="get_equity_historicals", init=False)

    def __post_init__(self) -> None:
        try:
            _scope(self)
            _check(type(self.symbol) is str)
            _check(re.fullmatch(r"[A-Z0-9][A-Z0-9.$+^=/@_-]{0,31}", self.symbol) is not None)
            _check(_utc(self.start_time) < _utc(self.end_time))
            _check(type(self.adjustment_type) is str and self.adjustment_type in {"none", "split"})
            _check(type(self.interval) is str and self.interval == "day")
            _check(type(self.bounds) is str and self.bounds == "regular")
            _check(type(self.tool) is str and self.tool == "get_equity_historicals")
        except (ValueError, TypeError, AttributeError, OverflowError):
            raise StockSplitComparisonError() from None

    @property
    def request_sha256(self) -> str:
        self.__post_init__()
        return str(content_hash(("stock-split-request-v1", self)))


@dataclass(frozen=True, slots=True, repr=False)
class StockSplitBar:
    source_index: int
    begins_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    interpolated: bool | None
    session: str | None


@dataclass(frozen=True, slots=True, repr=False)
class StockSplitSeries(_Unqualified):
    request: StockSplitRequest
    received_at: datetime
    original_content_json: bytes
    content_sha256: str
    bars: tuple[StockSplitBar, ...]
    null_bar_indices: tuple[int, ...]
    results_missing: bool
    bars_missing: bool
    not_found: bool

    @property
    def null_bar_count(self) -> int:
        return len(self.null_bar_indices)


@dataclass(frozen=True, slots=True, repr=False)
class StockSplitComparison(_Unqualified):
    raw: StockSplitSeries
    split: StockSplitSeries
    event_date: date
    new_shares_per_old_share: Fraction
    as_of: datetime
    status: Literal["sample_consistent", "sample_inconsistent", "unresolved"]
    reason_codes: tuple[str, ...]
    pre_event_price_factor: Fraction | None = None
    post_event_price_factor: Fraction | None = None
    pre_event_volume_factor: Fraction | None = None
    post_event_volume_factor: Fraction | None = None
    calendar_authenticated: Literal[False] = field(default=False, init=False)
    issuer_authenticated: Literal[False] = field(default=False, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)

    @property
    def available_at(self) -> datetime:
        return max(self.raw.received_at, self.split.received_at)

    @property
    def evidence_hash(self) -> str:
        _scope(self)
        return str(
            content_hash(
                {
                    "schema": "stock-split-comparison-v1",
                    "raw": _evidence(self.raw),
                    "split": _evidence(self.split),
                    "event_date": self.event_date,
                    "new_shares_per_old_share": str(self.new_shares_per_old_share),
                    "as_of": self.as_of,
                    "status": self.status,
                    "reason_codes": self.reason_codes,
                    "factors": tuple(
                        None if value is None else str(value)
                        for value in (
                            self.pre_event_price_factor,
                            self.post_event_price_factor,
                            self.pre_event_volume_factor,
                            self.post_event_volume_factor,
                        )
                    ),
                    "limitations": self.limitations,
                    "source_qualified": False,
                    "is_original_upstream_wire": False,
                }
            )
        )


def _evidence(series: StockSplitSeries) -> dict[str, object]:
    return {
        "request_sha256": series.request.request_sha256,
        "content_sha256": series.content_sha256,
        "received_at": series.received_at,
        "bars": series.bars,
        "null_bar_indices": series.null_bar_indices,
        "results_missing": series.results_missing,
        "bars_missing": series.bars_missing,
        "not_found": series.not_found,
    }


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        _check(key not in result)
        result[key] = value
    return result


def _constant(_value: str) -> object:
    raise StockSplitComparisonError()


def _object(
    value: object, required: set[str], optional: set[str] | None = None
) -> dict[str, object]:
    _check(type(value) is dict)
    result = cast(dict[str, object], value)
    _check(required <= set(result) <= required | (optional or set()))
    return result


def _price(value: object) -> Decimal:
    _check(type(value) is str and 0 < len(value) <= 512)
    text = cast(str, value)
    _check(
        re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", text) is not None
    )
    return require_bounded_decimal(Decimal(text), "split price", positive=True)


def _timestamp(value: object) -> datetime:
    _check(type(value) is str and 0 < len(value) <= 64)
    text = cast(str, value)
    stamp = _utc(datetime.fromisoformat(text))
    _check(parse_timestamp_ns(text) == parse_timestamp_ns(stamp.isoformat()))
    return stamp


def parse_stock_split_series(
    original_content_json: bytes,
    *,
    expected_sha256: str,
    request: StockSplitRequest,
    received_at: datetime,
) -> StockSplitSeries:
    """Validate original MCP text bytes and declared request/receipt without any I/O."""
    try:
        _check(type(request) is StockSplitRequest)
        request.__post_init__()
        received_at = _utc(received_at)
        _require_sha256_hex(expected_sha256, "stock split content")
        _check(
            type(original_content_json) is bytes and 0 < len(original_content_json) <= _MAX_BYTES
        )
        _check(hashlib.sha256(original_content_json).hexdigest() == expected_sha256)
        wire = _object(
            json.loads(
                original_content_json,
                object_pairs_hook=_pairs,
                parse_float=Decimal,
                parse_constant=_constant,
            ),
            {"data", "guide"},
        )
        guide = wire["guide"]
        _check(type(guide) is str and len(guide.encode()) <= 1024 * 1024)
        data = _object(wire["data"], {"results"}, {"not_found"})
        absent = data.get("not_found")
        _check(absent is None or type(absent) is list)
        not_found = False
        if absent is not None:
            _check(absent == [] or absent == [request.symbol])
            not_found = bool(absent)
        results = data["results"]
        _check(results is None or type(results) is list)
        rows = [] if results is None else cast(list[object], results)
        _check(len(rows) <= 1 and not (rows and not_found))
        native_bars: list[object] = []
        bars_missing = False
        if rows:
            item = _object(rows[0], {"symbol", "interval", "bounds", "bars"})
            _check(item["symbol"] == request.symbol)
            _check(item["interval"] == "day" and item["bounds"] == "regular")
            _check(item["bars"] is None or type(item["bars"]) is list)
            bars_missing = item["bars"] is None
            native_bars = [] if bars_missing else cast(list[object], item["bars"])
        _check(len(native_bars) <= 10000)
        bars: list[StockSplitBar] = []
        nulls: list[int] = []
        previous: datetime | None = None
        for index, entry in enumerate(native_bars):
            if entry is None:
                nulls.append(index)
                continue
            bar = _object(
                entry,
                {"begins_at", "open_price", "high_price", "low_price", "close_price", "volume"},
                {"interpolated", "session"},
            )
            stamp = _timestamp(bar["begins_at"])
            _check(request.start_time <= stamp <= request.end_time and stamp <= received_at)
            _check(previous is None or previous < stamp)
            previous = stamp
            opening, high, low, closing = tuple(
                _price(bar[key]) for key in ("open_price", "high_price", "low_price", "close_price")
            )
            _check(low <= min(opening, closing) <= max(opening, closing) <= high)
            volume = bar["volume"]
            _check(type(volume) is int and 0 <= volume <= 2**63 - 1)
            interpolated, session = bar.get("interpolated"), bar.get("session")
            _check("interpolated" not in bar or type(interpolated) is bool)
            _check("session" not in bar or (type(session) is str and session in {"", "reg"}))
            _check(interpolated is not True or volume == 0)
            bars.append(
                StockSplitBar(
                    index,
                    stamp,
                    opening,
                    high,
                    low,
                    closing,
                    cast(int, volume),
                    cast(bool | None, interpolated),
                    cast(str | None, session),
                )
            )
        return StockSplitSeries(
            request,
            received_at,
            original_content_json,
            expected_sha256,
            tuple(bars),
            tuple(nulls),
            results is None,
            bars_missing,
            not_found,
        )
    except (ValueError, TypeError, AttributeError, ArithmeticError, KeyError, RecursionError):
        raise StockSplitComparisonError() from None


def _same(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if is_dataclass(left) and not isinstance(left, type):
        return all(
            _same(getattr(left, item.name), getattr(right, item.name)) for item in fields(left)
        )
    if isinstance(left, tuple) and isinstance(right, tuple):
        return len(left) == len(right) and all(
            _same(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


def _validated(series: StockSplitSeries) -> StockSplitSeries:
    _check(type(series) is StockSplitSeries)
    _scope(series)
    rebuilt = parse_stock_split_series(
        series.original_content_json,
        expected_sha256=series.content_sha256,
        request=series.request,
        received_at=series.received_at,
    )
    _check(_same(rebuilt, series))
    return rebuilt


def _factors(
    pairs: tuple[tuple[StockSplitBar, StockSplitBar], ...],
) -> tuple[Fraction, Fraction] | None:
    prices, volumes = set(), set()
    for raw, split in pairs:
        for name in ("open_price", "high_price", "low_price", "close_price"):
            prices.add(Fraction(getattr(split, name)) / Fraction(getattr(raw, name)))
        volumes.add(Fraction(split.volume, raw.volume))
    if len(prices) != 1 or len(volumes) != 1:
        return None
    return next(iter(prices)), next(iter(volumes))


def compare_stock_split_series(
    *,
    raw: StockSplitSeries,
    split: StockSplitSeries,
    event_date: date,
    new_shares_per_old_share: Fraction,
    as_of: datetime,
) -> StockSplitComparison:
    """Reparse evidence and compare exact pre/post factors for one caller-frozen event."""
    try:
        raw, split = _validated(raw), _validated(split)
        as_of = _utc(as_of)
        _check(raw.received_at <= as_of and split.received_at <= as_of)
        a, b = raw.request, split.request
        _check(a.adjustment_type == "none" and b.adjustment_type == "split")
        _check((a.symbol, a.start_time, a.end_time) == (b.symbol, b.start_time, b.end_time))
        _check(type(event_date) is date and a.start_time.date() <= event_date <= a.end_time.date())
        _check(type(new_shares_per_old_share) is Fraction and new_shares_per_old_share > 0)
        _check(
            max(new_shares_per_old_share.numerator, new_shares_per_old_share.denominator)
            <= 2**63 - 1
        )

        def unresolved(reason: str) -> StockSplitComparison:
            return StockSplitComparison(
                raw, split, event_date, new_shares_per_old_share, as_of, "unresolved", (reason,)
            )

        if not raw.bars or not split.bars:
            return unresolved("empty_series")
        if raw.null_bar_count or split.null_bar_count:
            return unresolved("null_bar_rows")
        if tuple(row.begins_at for row in raw.bars) != tuple(row.begins_at for row in split.bars):
            return unresolved("timestamp_mismatch")
        pairs = tuple(zip(raw.bars, split.bars, strict=True))
        before = tuple(pair for pair in pairs if pair[0].begins_at.date() < event_date)
        after = tuple(pair for pair in pairs if pair[0].begins_at.date() >= event_date)
        if not before or not after:
            return unresolved("event_sides_missing")
        if any(row.interpolated is True for row in raw.bars + split.bars):
            return unresolved("source_declared_interpolated")
        if any(row.volume == 0 for row in raw.bars + split.bars):
            return unresolved("zero_volume")
        pre, post = _factors(before), _factors(after)
        if pre is None or post is None:
            return unresolved("nonconstant_factors")
        consistent = (
            pre[0] / post[0] == 1 / new_shares_per_old_share
            and pre[1] / post[1] == new_shares_per_old_share
        )
        return StockSplitComparison(
            raw,
            split,
            event_date,
            new_shares_per_old_share,
            as_of,
            "sample_consistent" if consistent else "sample_inconsistent",
            () if consistent else ("event_factor_mismatch",),
            pre[0],
            post[0],
            pre[1],
            post[1],
        )
    except (ValueError, TypeError, AttributeError, ArithmeticError, KeyError, RecursionError):
        raise StockSplitComparisonError() from None
