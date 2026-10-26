"""Bounded Alpha Vantage listing observations; no universe selection or authentication."""

import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, date, datetime
from typing import Literal, cast

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.recording import content_hash

_HEADER = ("symbol", "name", "exchange", "assetType", "ipoDate", "delistingDate", "status")
_FLAGS = (
    "qualified",
    "source_qualified",
    "strategy_qualified",
    "investment_eligible",
    "trading_enabled",
    "live_authorized",
    "authenticated",
    "historical_vintage_verified",
    "is_original_upstream_wire",
)
_LIMITATIONS = (
    "requested_historical_date_not_original_historical_data_vintage",
    "listing_status_and_dates_are_provider_observations_not_authenticated_membership",
    "stock_asset_label_is_not_common_stock_classification",
    "symbols_names_and_exchanges_are_not_permanent_security_identifiers",
    "as_of_symbol_identity_unverified_current_aliases_may_rewrite_historical_symbols",
    "duplicates_and_missingness_preserved_without_selection_or_deduplication",
    "provider_omissions_date_boundaries_and_completeness_unverified",
    "mcp_decoded_csv_not_original_upstream_http_wire",
    "no_prices_liquidity_actions_strategy_or_trading_authority",
)


class StockListingSnapshotError(ValueError):
    def __init__(self) -> None:
        super().__init__("stock_listing_snapshot_invalid")


def _check(value: bool) -> None:
    if not value:
        raise StockListingSnapshotError()


def _utc(value: datetime) -> datetime:
    _check(type(value) is datetime)
    return require_utc(value)


def _scope(value: object) -> None:
    _check(all(getattr(value, name) is False for name in _FLAGS))


@dataclass(frozen=True, slots=True, repr=False)
class _Scope:
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    authenticated: Literal[False] = field(default=False, init=False)
    historical_vintage_verified: Literal[False] = field(default=False, init=False)
    is_original_upstream_wire: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True, repr=False)
class StockListingRequest(_Scope):
    requested_date: date
    state: Literal["active", "delisted"]
    return_full_data: Literal[True] = field(default=True, init=False)
    tool: Literal["mcp__codex_apps__alpha_vantage_listing_status"] = field(
        default="mcp__codex_apps__alpha_vantage_listing_status", init=False
    )

    def __post_init__(self) -> None:
        try:
            _scope(self)
            _check(type(self.requested_date) is date)
            _check(type(self.state) is str and self.state in {"active", "delisted"})
            _check(self.return_full_data is True)
            _check(
                type(self.tool) is str
                and self.tool == "mcp__codex_apps__alpha_vantage_listing_status"
            )
        except (ValueError, TypeError, AttributeError):
            raise StockListingSnapshotError() from None

    @property
    def request_sha256(self) -> str:
        self.__post_init__()
        return str(content_hash(("alpha-vantage-listing-request-v1", self)))


@dataclass(frozen=True, slots=True, repr=False)
class StockListingRecord:
    row_index: int
    symbol: str
    name: str
    exchange: str
    asset_type: str
    ipo_date_raw: str
    delisting_date_raw: str
    status: str
    ipo_date: date | None
    delisting_date: date | None
    permanent_security_id: None = field(default=None, init=False)
    common_stock_classification: None = field(default=None, init=False)


def _raw(row: StockListingRecord) -> tuple[str, ...]:
    return (
        row.symbol,
        row.name,
        row.exchange,
        row.asset_type,
        row.ipo_date_raw,
        row.delisting_date_raw,
        row.status,
    )


@dataclass(frozen=True, slots=True, repr=False)
class StockListingSnapshot(_Scope):
    request: StockListingRequest
    received_at: datetime
    original_csv: bytes
    csv_sha256: str
    rows: tuple[StockListingRecord, ...]
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)

    @property
    def available_at(self) -> datetime:
        return self.received_at

    @property
    def evidence_hash(self) -> str:
        value = _validated(self)
        return str(
            content_hash(
                {
                    "schema": "alpha-vantage-listing-snapshot-v1",
                    "request_sha256": value.request.request_sha256,
                    "received_at": value.received_at,
                    "csv_sha256": value.csv_sha256,
                    "rows": value.rows,
                    "limitations": value.limitations,
                    "source_qualified": False,
                    "historical_vintage_verified": False,
                }
            )
        )


@dataclass(frozen=True, slots=True, repr=False)
class StockListingDuplicate:
    symbol: str
    row_indices: tuple[int, ...]
    kind: Literal["exact", "conflicting"]
    differing_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True, repr=False)
class StockListingQuality(_Scope):
    snapshot: StockListingSnapshot
    as_of: datetime
    row_count: int
    distinct_symbol_count: int
    asset_type_counts: tuple[tuple[str, int], ...]
    exchange_counts: tuple[tuple[str, int], ...]
    status_counts: tuple[tuple[str, int], ...]
    empty_field_counts: tuple[tuple[str, int], ...]
    date_missingness: tuple[tuple[str, int, int], ...]
    duplicate_groups: tuple[StockListingDuplicate, ...]
    duplicate_extra_rows: int
    duplicate_row_count: int
    future_ipo_row_indices: tuple[int, ...]
    delisting_before_requested_row_indices: tuple[int, ...]
    delisting_after_requested_row_indices: tuple[int, ...]
    inverted_lifecycle_row_indices: tuple[int, ...]
    status_mismatch_row_indices: tuple[int, ...]
    reason_codes: tuple[str, ...]
    blocked_uses: tuple[str, ...]
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)

    @property
    def evidence_hash(self) -> str:
        _scope(self)
        return str(
            content_hash(
                {
                    "schema": "alpha-vantage-listing-quality-v1",
                    "snapshot_sha256": self.snapshot.evidence_hash,
                    "assessment": {
                        item.name: getattr(self, item.name)
                        for item in fields(self)
                        if item.name != "snapshot"
                    },
                }
            )
        )


def _date(value: str) -> date | None:
    if value in {"", "null"}:
        return None
    _check(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is not None)
    return date.fromisoformat(value)


def parse_stock_listing_snapshot(
    original_csv: bytes,
    *,
    expected_sha256: str,
    request: StockListingRequest,
    received_at: datetime,
) -> StockListingSnapshot:
    """Rehash original decoded CSV, preserving every native field and duplicate row."""
    try:
        _check(type(request) is StockListingRequest)
        request.__post_init__()
        received_at = _utc(received_at)
        _check(request.requested_date <= received_at.date())
        _require_sha256_hex(expected_sha256, "listing CSV")
        _check(type(original_csv) is bytes and 0 < len(original_csv) <= 8 * 1024 * 1024)
        _check(hashlib.sha256(original_csv).hexdigest() == expected_sha256)
        reader = csv.reader(io.StringIO(original_csv.decode("utf-8"), newline=""), strict=True)
        _check(tuple(next(reader)) == _HEADER)
        records: list[StockListingRecord] = []
        for index, row in enumerate(reader):
            _check(index < 30000 and len(row) == 7)
            _check(
                all(
                    len(value) <= 4096 and all(char.isprintable() for char in value)
                    for value in row
                )
            )
            records.append(
                StockListingRecord(
                    index,
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    _date(row[4]),
                    _date(row[5]),
                )
            )
        return StockListingSnapshot(
            request, received_at, original_csv, expected_sha256, tuple(records)
        )
    except (ValueError, TypeError, AttributeError, csv.Error, StopIteration, RecursionError):
        raise StockListingSnapshotError() from None


def _same(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if is_dataclass(left) and not isinstance(left, type):
        return all(
            _same(getattr(left, item.name), getattr(right, item.name)) for item in fields(left)
        )
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(
            _same(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same(left[key], right[key]) for key in left)
    return bool(left == right)


def _validated(value: StockListingSnapshot) -> StockListingSnapshot:
    _check(type(value) is StockListingSnapshot)
    _scope(value)
    rebuilt = parse_stock_listing_snapshot(
        value.original_csv,
        expected_sha256=value.csv_sha256,
        request=value.request,
        received_at=value.received_at,
    )
    _check(_same(value, rebuilt))
    return rebuilt


def assess_stock_listing_snapshot(
    snapshot: StockListingSnapshot, *, as_of: datetime
) -> StockListingQuality:
    """Describe retained listing scope and ambiguity; never select or merge securities."""
    try:
        snapshot = _validated(snapshot)
        as_of = _utc(as_of)
        _check(snapshot.received_at <= as_of)
        rows = snapshot.rows
        grouped: dict[str, list[StockListingRecord]] = defaultdict(list)
        for row in rows:
            grouped[row.symbol].append(row)
        duplicates = []
        for symbol, group in sorted(grouped.items()):
            if len(group) < 2:
                continue
            differing = tuple(
                name
                for index, name in enumerate(_HEADER)
                if len({_raw(row)[index] for row in group}) > 1
            )
            kind: Literal["exact", "conflicting"] = "conflicting" if differing else "exact"
            duplicates.append(
                StockListingDuplicate(
                    symbol, tuple(row.row_index for row in group), kind, differing
                )
            )
        future = tuple(
            row.row_index
            for row in rows
            if row.ipo_date is not None and row.ipo_date > snapshot.request.requested_date
        )
        past = tuple(
            row.row_index
            for row in rows
            if row.delisting_date is not None
            and row.delisting_date < snapshot.request.requested_date
        )
        after = tuple(
            row.row_index
            for row in rows
            if row.delisting_date is not None
            and row.delisting_date > snapshot.request.requested_date
        )
        inverted = tuple(
            row.row_index
            for row in rows
            if row.ipo_date is not None
            and row.delisting_date is not None
            and row.delisting_date < row.ipo_date
        )
        expected_status = "Active" if snapshot.request.state == "active" else "Delisted"
        status_mismatch = tuple(row.row_index for row in rows if row.status != expected_status)
        empty = tuple(
            (name, sum(_raw(row)[index] == "" for row in rows))
            for index, name in enumerate(_HEADER)
        )
        missing_dates = tuple(
            (
                name,
                sum(_raw(row)[index] == "" for row in rows),
                sum(_raw(row)[index] == "null" for row in rows),
            )
            for index, name in ((4, "ipoDate"), (5, "delistingDate"))
        )
        reasons = []
        blocked = [
            "common_stock_selection",
            "permanent_security_identity",
            "historical_vintage_strategy",
            "historical_membership_completeness",
            "source_qualification",
            "investment_selection",
            "live_trading",
        ]
        if not rows:
            reasons.append("empty_snapshot")
        if any(count for name, count in empty if name not in {"ipoDate", "delistingDate"}):
            reasons.append("empty_native_identity_fields")
        if any(row.ipo_date is None for row in rows):
            reasons.append("missing_ipo_dates")
        if duplicates:
            reasons.append("duplicate_symbols")
            blocked.append("unambiguous_symbol_membership")
        if any(group.kind == "conflicting" for group in duplicates):
            reasons.append("conflicting_duplicate_symbols")
        if (
            future
            or inverted
            or status_mismatch
            or (snapshot.request.state == "active" and past)
            or (snapshot.request.state == "delisted" and after)
        ):
            reasons.append("requested_date_membership_contradictions")
            blocked.append("requested_date_membership")
        return StockListingQuality(
            snapshot,
            as_of,
            len(rows),
            len(grouped),
            tuple(sorted(Counter(row.asset_type for row in rows).items())),
            tuple(sorted(Counter(row.exchange for row in rows).items())),
            tuple(sorted(Counter(row.status for row in rows).items())),
            empty,
            missing_dates,
            tuple(duplicates),
            sum(len(group.row_indices) - 1 for group in duplicates),
            sum(len(group.row_indices) for group in duplicates),
            future,
            past,
            after,
            inverted,
            status_mismatch,
            tuple(reasons),
            tuple(blocked),
        )
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
        raise StockListingSnapshotError() from None


_PANEL_PREFIX = "stock-task4-historical-panel-v1"
_PANEL_NAME_REGEX = (
    "warrants?|rights?|units?|preferred|depositary|depository|ADR|ADS|ETF|fund|trust"
)
_PANEL_RULES = (
    "duplicate_symbol",
    "asset_type_not_Stock",
    "exchange_not_NYSE_NASDAQ",
    "ticker_not_exact_AZ1to4",
    "empty_name",
    "ipo_missing_or_after_2023Jan1",
    "excluded_name_word",
)


@dataclass(frozen=True, slots=True, repr=False)
class StockPanelDecision:
    row_index: int
    symbol: str
    exclusion_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True, repr=False)
class StockPanelDenominator:
    rule: str
    before: int
    excluded_here: int
    remaining: int


@dataclass(frozen=True, slots=True, repr=False)
class StockHistoryPanelMember:
    record: StockListingRecord
    order_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class StockHistoryPanel(_Scope):
    snapshot: StockListingSnapshot
    source_receipt_sha256: str
    intent_sha256: str
    intent_created_at: datetime
    raw_row_count: int
    eligible_count: int
    decisions: tuple[StockPanelDecision, ...]
    denominators: tuple[StockPanelDenominator, ...]
    selected: tuple[StockHistoryPanelMember, ...]
    selection_complete: bool
    requested_count: Literal[12] = field(default=12, init=False)
    no_replacement: Literal[True] = field(default=True, init=False)
    benchmark_only_symbols: tuple[Literal["SPY"], ...] = field(default=("SPY",), init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)

    @property
    def evidence_hash(self) -> str:
        _scope(self)
        return str(
            content_hash(
                {
                    "schema": _PANEL_PREFIX,
                    "snapshot_sha256": self.snapshot.evidence_hash,
                    "selection": {
                        item.name: getattr(self, item.name)
                        for item in fields(self)
                        if item.name != "snapshot"
                    },
                }
            )
        )


def _json_pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        _check(key not in result)
        result[key] = value
    return result


def _constant(_value: str) -> object:
    raise StockListingSnapshotError()


def _document(raw: bytes, expected: str, maximum: int) -> dict[str, object]:
    _require_sha256_hex(expected, "listing evidence")
    _check(type(raw) is bytes and 0 < len(raw) <= maximum)
    _check(hashlib.sha256(raw).hexdigest() == expected)
    value = json.loads(raw, object_pairs_hook=_json_pairs, parse_constant=_constant)
    _check(type(value) is dict)
    return cast(dict[str, object], value)


def _receipt_clock(text: object) -> datetime:
    _check(type(text) is str)
    value = cast(str, text)
    if value.endswith(" UTC"):
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)
    return _utc(datetime.fromisoformat(value))


def select_stock_history_panel(
    snapshot: StockListingSnapshot,
    *,
    original_source_receipt: bytes,
    expected_source_receipt_sha256: str,
    original_intent: bytes,
    expected_intent_sha256: str,
) -> StockHistoryPanel:
    """Execute only the frozen v1 twelve-slot listing rule; never replace missing outcomes."""
    try:
        snapshot = _validated(snapshot)
        source = _document(original_source_receipt, expected_source_receipt_sha256, 8 * 1024 * 1024)
        intent = _document(original_intent, expected_intent_sha256, 65536)
        request = {"date": "2024-01-01", "state": "active", "return_full_data": True}
        _check(
            snapshot.request.requested_date == date(2024, 1, 1)
            and snapshot.request.state == "active"
        )
        expected_request = {"tool": snapshot.request.tool, "args": request}
        _check(_same(source["request"], expected_request))
        _check(
            _receipt_clock(source["started_at"])
            <= _receipt_clock(source["received_at"])
            == snapshot.received_at
        )
        result = source["result"]
        _check(type(result) is dict)
        result = cast(dict[str, object], result)
        _check(result.get("isError") is False)
        content, structured = result["content"], result["structuredContent"]
        _check(type(content) is list and len(content) == 1 and type(content[0]) is dict)
        item = cast(dict[str, object], cast(list[object], content)[0])
        _check(item.get("type") == "text" and type(item.get("text")) is str)
        _check(type(structured) is dict and set(structured) == {"result"})
        structured = cast(dict[str, object], structured)
        text = cast(str, item["text"])
        _check(text == structured["result"] and text.encode() == snapshot.original_csv)
        _check(type(intent["schema_version"]) is int and intent["schema_version"] == 1)
        _check(intent["contract_id"] == _PANEL_PREFIX and intent["live_enabled"] is False)
        created_at = _receipt_clock(intent["created_at"])
        _check(snapshot.received_at <= created_at)
        frame = intent["sampling_frame"]
        _check(type(frame) is dict)
        frame = cast(dict[str, object], frame)
        _check(frame["receipt_sha256"] == expected_source_receipt_sha256)
        _check(frame["tool"] == snapshot.request.tool and _same(frame["request"], request))
        expected_selection = {
            "asset_type": "Stock",
            "case_insensitive": True,
            "count": 12,
            "duplicate_rule": (
                "quarantine every row whose ticker occurs more than once across ALL asset types"
            ),
            "exchanges": ["NYSE", "NASDAQ"],
            "excluded_name_whole_word_regex": _PANEL_NAME_REGEX,
            "hash_separator_byte_hex": "00",
            "hash_utf8_prefix": _PANEL_PREFIX,
            "latest_ipo_date": "2023-01-01",
            "name_required": True,
            "no_replacement": True,
            "sort": "SHA256(UTF8(prefix) + byte00 + UTF8(symbol)), then symbol",
            "symbol_regex": "[A-Z]{1,4}",
        }
        _check(_same(intent["selection"], expected_selection))
        counts = Counter(row.symbol for row in snapshot.rows)
        name_pattern = re.compile(r"\b(?:" + _PANEL_NAME_REGEX + r")\b", re.IGNORECASE)
        decisions = []
        candidates = []
        for row in snapshot.rows:
            passed = (
                counts[row.symbol] == 1,
                row.asset_type == "Stock",
                row.exchange in {"NYSE", "NASDAQ"},
                re.fullmatch(r"[A-Z]{1,4}", row.symbol) is not None,
                bool(row.name.strip()),
                row.ipo_date is not None and row.ipo_date <= date(2023, 1, 1),
                name_pattern.search(row.name) is None,
            )
            reasons = tuple(
                name for name, keep in zip(_PANEL_RULES, passed, strict=True) if not keep
            )
            decisions.append(StockPanelDecision(row.row_index, row.symbol, reasons))
            if not reasons:
                order = hashlib.sha256(
                    _PANEL_PREFIX.encode() + b"\x00" + row.symbol.encode()
                ).hexdigest()
                candidates.append(StockHistoryPanelMember(row, order))
        remaining = decisions[:]
        denominators = []
        for rule in _PANEL_RULES:
            before = len(remaining)
            remaining = [item for item in remaining if rule not in item.exclusion_reasons]
            denominators.append(
                StockPanelDenominator(rule, before, before - len(remaining), len(remaining))
            )
        selected = tuple(
            sorted(candidates, key=lambda member: (member.order_sha256, member.record.symbol))[:12]
        )
        return StockHistoryPanel(
            snapshot,
            expected_source_receipt_sha256,
            expected_intent_sha256,
            created_at,
            len(snapshot.rows),
            len(candidates),
            tuple(decisions),
            tuple(denominators),
            selected,
            len(selected) == 12,
        )
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, RecursionError):
        raise StockListingSnapshotError() from None
