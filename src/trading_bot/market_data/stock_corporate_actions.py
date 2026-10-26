"""Exact retained Alpaca MCP action observations, never a complete action book."""

import hashlib
import json
import re
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.recording import content_hash

_TOOL = "mcp__codex_apps__alpaca_get_corporate_actions"
_FLAGS = (
    "qualified",
    "source_qualified",
    "strategy_qualified",
    "investment_eligible",
    "trading_enabled",
    "live_authorized",
    "authenticated",
    "complete_action_book",
    "point_in_time_verified",
    "cashflow_qualified",
    "is_original_upstream_wire",
)
_DATES = ("process_date", "ex_date", "record_date", "payable_date")
_COMMON = {"id", "corporate_action_type", "symbol", "cusip", "currency", *_DATES}
_CASH = {"rate", "special", "foreign", "due_bill_on_date", "due_bill_off_date"}
_SPLIT = {"old_rate", "new_rate", "due_bill_redemption_date"}
_LIMITATIONS = (
    "mcp_formatted_content_not_original_upstream_http_wire",
    "request_and_receipt_not_independently_authenticated",
    "pagination_data_quality_and_region_not_bound_by_tool_request",
    "response_size_below_limit_does_not_establish_complete_action_book",
    "creation_and_historical_publication_time_not_guaranteed",
    "native_dates_preserved_not_reconciled_to_issuer_dates",
    "currency_not_inferred_from_symbol_cusip_or_foreign_flag",
    "not_cashflow_tax_total_return_or_point_in_time_qualification",
)


class StockCorporateActionsError(ValueError):
    def __init__(self) -> None:
        super().__init__("stock_corporate_actions_invalid")


def _check(condition: bool) -> None:
    if not condition:
        raise StockCorporateActionsError()


def _scope(value: object) -> None:
    _check(all(getattr(value, name) is False for name in _FLAGS))


def _same(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if is_dataclass(left) and not isinstance(left, type):
        return all(_same(getattr(left, f.name), getattr(right, f.name)) for f in fields(left))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same(v, right[k]) for k, v in left.items())
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(
            _same(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


@dataclass(frozen=True, slots=True, repr=False)
class _Unqualified:
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    authenticated: Literal[False] = field(default=False, init=False)
    complete_action_book: Literal[False] = field(default=False, init=False)
    point_in_time_verified: Literal[False] = field(default=False, init=False)
    cashflow_qualified: Literal[False] = field(default=False, init=False)
    is_original_upstream_wire: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True, repr=False)
class StockCorporateActionsRequest(_Unqualified):
    symbols: tuple[str, ...]
    start: date
    end: date
    limit: int = 1000
    sort: Literal["asc", "desc"] = "asc"
    tool: Literal["mcp__codex_apps__alpaca_get_corporate_actions"] = field(
        default="mcp__codex_apps__alpaca_get_corporate_actions", init=False
    )

    def __post_init__(self) -> None:
        try:
            _scope(self)
            _check(type(self.symbols) is tuple and 1 <= len(self.symbols) <= 1000)
            _check(
                all(
                    type(s) is str
                    and re.fullmatch(r"[A-Z0-9][A-Z0-9.$+^=/@_-]{0,31}", s) is not None
                    for s in self.symbols
                )
            )
            _check(len(set(self.symbols)) == len(self.symbols))
            _check(type(self.start) is date and type(self.end) is date and self.start <= self.end)
            _check(type(self.limit) is int and 1 <= self.limit <= 1000)
            _check(type(self.sort) is str and self.sort in {"asc", "desc"})
            _check(type(self.tool) is str and self.tool == _TOOL)
        except (ValueError, TypeError, AttributeError, ArithmeticError):
            raise StockCorporateActionsError() from None

    @property
    def request_sha256(self) -> str:
        self.__post_init__()
        return str(content_hash(("stock-corporate-actions-request-v1", self)))


@dataclass(frozen=True, slots=True, repr=False)
class StockCorporateAction:
    source_index: int
    action_type: Literal["cash_dividends", "forward_splits"]
    action_id: str
    symbol: str
    cusip: str | None
    process_date: date | None
    ex_date: date | None
    record_date: date | None
    payable_date: date | None
    rate: Decimal | None
    old_rate: Decimal | None
    new_rate: Decimal | None
    special: bool | None
    foreign: bool | None
    due_bill_on_date: date | None
    due_bill_off_date: date | None
    due_bill_redemption_date: date | None
    currency: str | None
    missing_native_fields: tuple[str, ...]
    null_native_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True, repr=False)
class StockCorporateActions(_Unqualified):
    request: StockCorporateActionsRequest
    received_at: datetime
    original_content_json: bytes
    content_sha256: str
    native_groups: tuple[str, ...]
    actions: tuple[StockCorporateAction, ...]
    pagination_status: Literal["not_exposed", "continuation_reported", "no_continuation_reported"]
    next_page_token: str | None
    native_data_quality: None = field(default=None, init=False)
    native_region: None = field(default=None, init=False)

    @property
    def available_at(self) -> datetime:
        return self.received_at

    @property
    def evidence_hash(self) -> str:
        value = _validated(self)
        return str(
            content_hash(
                {
                    "schema": "stock-corporate-actions-content-v1",
                    "request_sha256": value.request.request_sha256,
                    "received_at": value.received_at,
                    "content_sha256": value.content_sha256,
                    "native_groups": value.native_groups,
                    "actions": value.actions,
                    "pagination_status": value.pagination_status,
                    "next_page_token": value.next_page_token,
                    "native_data_quality": None,
                    "native_region": None,
                    "complete_action_book": False,
                }
            )
        )


@dataclass(frozen=True, slots=True, repr=False)
class StockCorporateActionsAudit(_Unqualified):
    source: StockCorporateActions
    as_of: datetime
    status: Literal["structural_checks_passed"]
    action_count: int
    counts_by_symbol: tuple[tuple[str, int, int], ...]
    currency_unreported_count: int
    unresolved_native_fields: tuple[tuple[str, str], ...]
    response_limit_reached: bool
    global_process_order_matches_requested: bool | None
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)

    @property
    def evidence_hash(self) -> str:
        _scope(self)
        return str(
            content_hash(
                {
                    "schema": "stock-corporate-actions-audit-v1",
                    "source_evidence_hash": self.source.evidence_hash,
                    "as_of": self.as_of,
                    "status": self.status,
                    "action_count": self.action_count,
                    "counts_by_symbol": self.counts_by_symbol,
                    "currency_unreported_count": self.currency_unreported_count,
                    "unresolved_native_fields": self.unresolved_native_fields,
                    "response_limit_reached": self.response_limit_reached,
                    "global_process_order_matches_requested": (
                        self.global_process_order_matches_requested
                    ),
                    "reason_codes": self.reason_codes,
                    "limitations": self.limitations,
                    "complete_action_book": False,
                }
            )
        )


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        _check(key not in result)
        result[key] = value
    return result


def _constant(_value: str) -> object:
    raise StockCorporateActionsError()


def _object(
    value: object, required: set[str], optional: set[str] | None = None
) -> dict[str, object]:
    _check(type(value) is dict)
    result = cast(dict[str, object], value)
    _check(required <= set(result) <= required | (optional or set()))
    return result


def _date(value: object) -> date | None:
    if value is None:
        return None
    _check(type(value) is str and len(value) == 10)
    parsed = date.fromisoformat(cast(str, value))
    _check(parsed.isoformat() == value)
    return parsed


def _rate(value: object) -> Decimal | None:
    if value is None:
        return None
    _check(type(value) in {int, Decimal})
    return require_bounded_decimal(
        Decimal(cast(int | Decimal, value)), "action rate", positive=True
    )


def _boolean(value: object) -> bool | None:
    _check(value is None or type(value) is bool)
    return cast(bool | None, value)


def parse_stock_corporate_actions(
    original_content_json: bytes,
    *,
    expected_sha256: str,
    request: StockCorporateActionsRequest,
    received_at: datetime,
) -> StockCorporateActions:
    """Parse original MCP result-string bytes; preserve missing fields and dates."""
    try:
        _check(type(request) is StockCorporateActionsRequest)
        request.__post_init__()
        received_at = require_utc(received_at)
        _require_sha256_hex(expected_sha256, "corporate actions")
        _check(
            type(original_content_json) is bytes
            and 0 < len(original_content_json) <= 8 * 1024 * 1024
        )
        _check(hashlib.sha256(original_content_json).hexdigest() == expected_sha256)
        value = _object(
            json.loads(
                original_content_json,
                object_pairs_hook=_pairs,
                parse_float=Decimal,
                parse_constant=_constant,
            ),
            {"request", "announcements"},
            {"next_page_token"},
        )
        _check(
            _same(
                value["request"],
                {
                    "ca_types": None,
                    "start": request.start.isoformat(),
                    "end": request.end.isoformat(),
                    "symbols": list(request.symbols),
                    "cusips": None,
                    "ids": None,
                    "limit": request.limit,
                    "sort": request.sort,
                },
            )
        )
        groups = _object(value["announcements"], set(), {"cash_dividends", "forward_splits"})
        actions: list[StockCorporateAction] = []
        ids: set[str] = set()
        for group, native in groups.items():
            _check(type(native) is list and len(cast(list[object], native)) <= request.limit)
            for item in cast(list[object], native):
                allowed = _COMMON | (_CASH if group == "cash_dividends" else _SPLIT)
                row = _object(item, {"id", "corporate_action_type", "symbol"}, allowed)
                _check(row["corporate_action_type"] == group)
                identity = row["id"]
                _check(type(identity) is str and len(identity) == 36)
                action_id = cast(str, identity)
                _check(str(UUID(action_id)) == action_id and action_id not in ids)
                ids.add(action_id)
                symbol, cusip, currency = row["symbol"], row.get("cusip"), row.get("currency")
                _check(type(symbol) is str and symbol in request.symbols)
                _check(
                    cusip is None
                    or (type(cusip) is str and re.fullmatch(r"[A-Z0-9*@#]{9}", cusip) is not None)
                )
                _check(
                    currency is None
                    or (type(currency) is str and re.fullmatch(r"[A-Z]{3}", currency) is not None)
                )
                process = _date(row.get("process_date"))
                _check(process is None or request.start <= process <= request.end)
                actions.append(
                    StockCorporateAction(
                        len(actions),
                        cast(Literal["cash_dividends", "forward_splits"], group),
                        action_id,
                        cast(str, symbol),
                        cast(str | None, cusip),
                        process,
                        _date(row.get("ex_date")),
                        _date(row.get("record_date")),
                        _date(row.get("payable_date")),
                        _rate(row.get("rate")),
                        _rate(row.get("old_rate")),
                        _rate(row.get("new_rate")),
                        _boolean(row.get("special")),
                        _boolean(row.get("foreign")),
                        _date(row.get("due_bill_on_date")),
                        _date(row.get("due_bill_off_date")),
                        _date(row.get("due_bill_redemption_date")),
                        cast(str | None, currency),
                        tuple(sorted(allowed - set(row))),
                        tuple(sorted(key for key, item in row.items() if item is None)),
                    )
                )
                _check(len(actions) <= request.limit)
        token = value.get("next_page_token")
        _check(token is None or (type(token) is str and 0 < len(token) <= 4096))
        pagination: Literal["not_exposed", "continuation_reported", "no_continuation_reported"] = (
            "not_exposed"
            if "next_page_token" not in value
            else "no_continuation_reported"
            if token is None
            else "continuation_reported"
        )
        return StockCorporateActions(
            request,
            received_at,
            original_content_json,
            expected_sha256,
            tuple(groups),
            tuple(actions),
            pagination,
            cast(str | None, token),
        )
    except (ValueError, TypeError, AttributeError, ArithmeticError, KeyError, RecursionError):
        raise StockCorporateActionsError() from None


def _validated(value: StockCorporateActions) -> StockCorporateActions:
    _check(type(value) is StockCorporateActions)
    _scope(value)
    rebuilt = parse_stock_corporate_actions(
        value.original_content_json,
        expected_sha256=value.content_sha256,
        request=value.request,
        received_at=value.received_at,
    )
    _check(_same(rebuilt, value))
    return rebuilt


def audit_stock_corporate_actions(
    source: StockCorporateActions, *, as_of: datetime
) -> StockCorporateActionsAudit:
    """Revalidate original evidence and summarize exactly the returned observations."""
    try:
        value = _validated(source)
        as_of = require_utc(as_of)
        _check(value.received_at <= as_of)
        counts = tuple(
            (
                symbol,
                sum(
                    r.symbol == symbol and r.action_type == "cash_dividends" for r in value.actions
                ),
                sum(
                    r.symbol == symbol and r.action_type == "forward_splits" for r in value.actions
                ),
            )
            for symbol in value.request.symbols
        )
        unresolved = tuple(
            (row.action_id, name)
            for row in value.actions
            for name in (
                "cusip",
                *_DATES,
                *(("rate",) if row.action_type == "cash_dividends" else ("old_rate", "new_rate")),
            )
            if getattr(row, name) is None
        )
        process = tuple(row.process_date for row in value.actions)
        ordering = (
            None
            if any(day is None for day in process)
            else process
            == tuple(sorted(cast(tuple[date, ...], process), reverse=value.request.sort == "desc"))
        )
        reasons = [
            "pagination_" + value.pagination_status,
            "data_quality_and_region_unreported",
            "action_book_completeness_unverified",
            "historical_publication_unverified",
            "native_dates_not_issuer_reconciled",
        ]
        currency_missing = sum(row.currency is None for row in value.actions)
        if currency_missing:
            reasons.append("native_currency_unreported")
        if unresolved:
            reasons.append("native_fields_unresolved")
        if ordering is False:
            reasons.append("formatted_order_not_global_process_order")
        return StockCorporateActionsAudit(
            value,
            as_of,
            "structural_checks_passed",
            len(value.actions),
            counts,
            currency_missing,
            unresolved,
            len(value.actions) == value.request.limit,
            ordering,
            tuple(reasons),
        )
    except (ValueError, TypeError, AttributeError, ArithmeticError, KeyError, RecursionError):
        raise StockCorporateActionsError() from None
