"""Pure native-shape filing evidence; caller-declared provenance is unqualified."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, cast

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.recording import content_hash
from trading_bot.market_data.stock_events import (
    StockEventReceipt,
    StockFiling,
    StockFilingCollection,
    _date,
    normalize_filing_index,
)

_FLAGS = (
    "qualified",
    "source_qualified",
    "strategy_qualified",
    "investment_eligible",
    "trading_enabled",
    "live_authorized",
)
_ERRORS = (ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RecursionError)
_MAX_ENVELOPE = 8_388_608
_MAX_OFFSET = 2**31 - 1
_MAX_COUNT = 2**63 - 1


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("stock_filing_facts_invalid")


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except _ERRORS:
        raise ValueError("stock_filing_facts_invalid") from None


def _text(value: object, maximum: int = 512, *, empty: bool = False) -> str:
    _check(type(value) is str)
    text = cast(str, value)
    _check((empty or bool(text)) and len(text) <= maximum)
    _check(all(character.isprintable() for character in text))
    return text


def _mapping(value: object, allowed: set[str], required: set[str]) -> dict[str, object]:
    _check(type(value) is dict)
    result = cast(dict[str, object], value)
    _check(all(type(key) is str for key in result))
    _check(required <= result.keys() <= allowed)
    return result


def _integer(value: object, lower: int, upper: int) -> int:
    _check(type(value) is int and lower <= value <= upper)
    return cast(int, value)


def _rows(value: object, maximum: int) -> list[object]:
    if value is None:
        return []
    _check(type(value) is list and len(cast(list[object], value)) <= maximum)
    return cast(list[object], value)


def _axes(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    values = _rows(value, 64)
    names = tuple(_text(item) for item in values)
    _check(len(set(names)) == len(names))
    return names


def _check_axes(value: tuple[str, ...] | None) -> None:
    if value is not None:
        _check(type(value) is tuple)
        _axes(list(value))


def _scope(value: object, maximum: int) -> tuple[str, ...]:
    _check(type(value) is tuple and 1 <= len(cast(tuple[object, ...], value)) <= maximum)
    result = tuple(_text(item) for item in cast(tuple[object, ...], value))
    _check(len(set(result)) == len(result))
    return result


def _payload(payload: object, allowed: set[str], required: set[str]) -> dict[str, object]:
    root = _mapping(payload, {"data", "guide"}, {"data", "guide"})
    guide = root["guide"]
    _check(type(guide) is str and len(guide.encode("utf-8")) <= 1_048_576)
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False)
    size = 0
    for chunk in encoder.iterencode(root):
        size += len(chunk.encode("utf-8"))
        _check(size <= _MAX_ENVELOPE)
    return _mapping(root["data"], allowed, required)


def _optional(present: bool, value: object) -> None:
    _check(type(present) is bool and (present or value is None))


def _start(present: bool, raw: str | None, end: date) -> date | None:
    _optional(present, raw)
    _check(type(end) is date)
    start = _date(raw) if raw is not None else None
    _check(start is None or start <= end)
    return start


def _numeric(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    _check(type(raw) is str and len(raw) <= 512)
    if raw == "":
        return None
    _check(
        re.fullmatch(r"[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", raw) is not None
    )
    result = Decimal(raw)
    _check(result.is_finite())
    parts = result.as_tuple()
    _check(len(parts.digits) <= 128 and -1000 <= cast(int, parts.exponent) <= 1000)
    return result


@dataclass(frozen=True, slots=True, repr=False)
class _Unqualified:
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    publication_at: None = field(default=None, init=False)


def _flags(value: _Unqualified) -> None:
    _check(all(getattr(value, name) is False for name in _FLAGS))
    _check(value.publication_at is None)


def _checked[T: _Unqualified](value: object, model: type[T]) -> T:
    _check(type(value) is model)
    original = cast(T, value)
    _flags(original)
    if isinstance(original, StockFilingReceipt):
        _check(original.hash_is_caller_declared is True)
    if isinstance(original, StockFilingCatalog):
        _check(original.history_complete is False)
    rebuilt = replace(original)
    _check(original == rebuilt)
    if isinstance(original, StockFilingFact) and original.numeric_value is not None:
        # Decimal equality alone would erase signed zero and coefficient/exponent detail.
        _check(type(original.numeric_value) is Decimal)
        parsed = cast(StockFilingFact, rebuilt).numeric_value
        _check(type(parsed) is Decimal)
        _check(original.numeric_value.as_tuple() == cast(Decimal, parsed).as_tuple())
    return original


@dataclass(frozen=True, slots=True, repr=False)
class StockFilingReceipt(_Unqualified):
    tool: Literal["get_sec_filing_facts_catalog", "get_sec_filing_facts"]
    received_at: datetime
    observation_sha256: str
    hash_is_caller_declared: Literal[True] = field(default=True, init=False)

    def __post_init__(self) -> None:
        with _errors():
            _flags(self)
            _check(self.tool in ("get_sec_filing_facts_catalog", "get_sec_filing_facts"))
            _require_sha256_hex(self.observation_sha256, "stock observation")
            object.__setattr__(self, "received_at", require_utc(self.received_at))
            _check(self.hash_is_caller_declared is True)

    @property
    def available_at(self) -> datetime:
        return self.received_at


def _receipt(value: StockFilingReceipt, tool: str) -> None:
    _checked(value, StockFilingReceipt)
    _check(value.tool == tool)


def _slots(
    records: tuple[StockFilingConcept | StockFilingPeriod | StockFilingFact, ...],
    nulls: tuple[int, ...],
    maximum: int,
    missing: bool,
) -> None:
    _check(type(records) is tuple and type(nulls) is tuple and type(missing) is bool)
    total = len(records) + len(nulls)
    _check(total <= maximum and (not missing or total == 0))
    positions = tuple(item.row_index for item in records)
    _check(all(type(index) is int and 0 <= index < total for index in (*positions, *nulls)))
    _check(positions == tuple(sorted(set(positions))) and nulls == tuple(sorted(set(nulls))))
    _check(set(positions).isdisjoint(nulls) and set(positions) | set(nulls) == set(range(total)))


@dataclass(frozen=True, slots=True, repr=False)
class StockFilingPeriod(_Unqualified):
    row_index: int
    period: str
    end_date: date
    start_date_present: bool
    start_date_raw: str | None
    receipt: StockFilingReceipt
    start_date: date | None = field(init=False)

    def __post_init__(self) -> None:
        with _errors():
            _flags(self)
            _receipt(self.receipt, "get_sec_filing_facts_catalog")
            _integer(self.row_index, 0, 255)
            _text(self.period)
            object.__setattr__(
                self,
                "start_date",
                _start(self.start_date_present, self.start_date_raw, self.end_date),
            )


def _period_identity(value: StockFilingPeriod | StockFilingFact) -> tuple[object, ...]:
    return (value.period, value.end_date, value.start_date_present, value.start_date_raw)


@dataclass(frozen=True, slots=True, repr=False)
class StockFilingConcept(_Unqualified):
    row_index: int
    concept: str
    is_text_block: bool
    periods: tuple[StockFilingPeriod, ...]
    periods_missing: bool
    null_period_indices: tuple[int, ...]
    axis_names_raw: tuple[str, ...] | None
    receipt: StockFilingReceipt

    def __post_init__(self) -> None:
        with _errors():
            _flags(self)
            _receipt(self.receipt, "get_sec_filing_facts_catalog")
            _integer(self.row_index, 0, 4999)
            _text(self.concept)
            _check(type(self.is_text_block) is bool)
            _check(type(self.periods) is tuple)
            for period in self.periods:
                _checked(period, StockFilingPeriod)
                _check(period.receipt == self.receipt)
            _slots(self.periods, self.null_period_indices, 256, self.periods_missing)
            _check(len({_period_identity(p) for p in self.periods}) == len(self.periods))
            _check_axes(self.axis_names_raw)


@dataclass(frozen=True, slots=True, repr=False)
class StockFilingCatalog(_Unqualified):
    receipt: StockFilingReceipt
    requested_filing_id: str
    requested_offset: int
    records: tuple[StockFilingConcept, ...]
    count: int
    next_offset_present: bool
    next_offset: int | None
    concepts_missing: bool
    null_row_indices: tuple[int, ...]
    history_complete: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        with _errors():
            _flags(self)
            _receipt(self.receipt, "get_sec_filing_facts_catalog")
            _text(self.requested_filing_id)
            _integer(self.requested_offset, 0, _MAX_OFFSET)
            _integer(self.count, 0, _MAX_COUNT)
            _optional(self.next_offset_present, self.next_offset)
            if self.next_offset is not None:
                _check(type(self.next_offset) is int and self.next_offset >= 0)
            _check(self.history_complete is False and type(self.records) is tuple)
            for record in self.records:
                _checked(record, StockFilingConcept)
                _check(record.receipt == self.receipt)
            _slots(self.records, self.null_row_indices, 5000, self.concepts_missing)
            _check(len({record.concept for record in self.records}) == len(self.records))

    @property
    def available_at(self) -> datetime:
        return self.receipt.received_at

    @property
    def catalog_hash(self) -> str:
        with _errors():
            return str(content_hash(("stock-filing-catalog-v1", self)))


@dataclass(frozen=True, slots=True, repr=False)
class StockFilingFact(_Unqualified):
    row_index: int
    filing_id: str
    concept: str
    entity: str
    period: str
    axes_raw: tuple[str, ...] | None
    char_value: str
    end_date: date
    start_date_present: bool
    start_date_raw: str | None
    unit_present: bool
    unit_raw: str | None
    value_present: bool
    value_raw: str | None
    decimals_present: bool
    decimals_raw: int | None
    receipt: StockFilingReceipt
    start_date: date | None = field(init=False)
    numeric_value: Decimal | None = field(init=False)

    def __post_init__(self) -> None:
        with _errors():
            _flags(self)
            _receipt(self.receipt, "get_sec_filing_facts")
            _integer(self.row_index, 0, 19999)
            for text in (self.filing_id, self.concept, self.entity, self.period):
                _text(text)
            _check_axes(self.axes_raw)
            _check(type(self.char_value) is str and len(self.char_value) <= 65536)
            _check("\x00" not in self.char_value)
            object.__setattr__(
                self,
                "start_date",
                _start(self.start_date_present, self.start_date_raw, self.end_date),
            )
            _optional(self.unit_present, self.unit_raw)
            if self.unit_raw is not None:
                _text(self.unit_raw, 128, empty=True)
            _optional(self.value_present, self.value_raw)
            object.__setattr__(self, "numeric_value", _numeric(self.value_raw))
            _optional(self.decimals_present, self.decimals_raw)
            if self.decimals_raw is not None:
                _integer(self.decimals_raw, -1000, 1000)


def _fact_identity(value: StockFilingFact) -> tuple[object, ...]:
    return (
        value.row_index,
        value.filing_id,
        value.concept,
        value.entity,
        value.period,
        value.axes_raw,
        value.char_value,
        value.end_date,
        value.start_date_present,
        value.start_date_raw,
        value.unit_present,
        value.unit_raw,
        value.value_present,
        value.value_raw,
        value.decimals_present,
        value.decimals_raw,
        value.receipt,
        tuple(getattr(value, name) for name in _FLAGS),
        value.publication_at,
    )


@dataclass(frozen=True, slots=True, repr=False)
class StockFilingFacts(_Unqualified):
    receipt: StockFilingReceipt
    requested_filing_ids: tuple[str, ...]
    requested_concepts: tuple[str, ...]
    records: tuple[StockFilingFact, ...]
    facts_missing: bool
    null_row_indices: tuple[int, ...]
    missing_requested_concepts: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        with _errors():
            _flags(self)
            _receipt(self.receipt, "get_sec_filing_facts")
            _scope(self.requested_filing_ids, 3)
            _scope(self.requested_concepts, 10)
            _check(type(self.records) is tuple)
            for record in self.records:
                _checked(record, StockFilingFact)
                _check(record.receipt == self.receipt)
                _check(record.filing_id in self.requested_filing_ids)
                _check(record.concept in self.requested_concepts)
            _slots(self.records, self.null_row_indices, 20000, self.facts_missing)
            present = {record.concept for record in self.records}
            object.__setattr__(
                self,
                "missing_requested_concepts",
                tuple(name for name in self.requested_concepts if name not in present),
            )

    @property
    def available_at(self) -> datetime:
        return self.receipt.received_at

    @property
    def facts_hash(self) -> str:
        with _errors():
            # Raw strings preserve exact numeric representation without narrowing the
            # declared exponent range to the shared trading-Decimal hash bound.
            return str(
                content_hash(
                    (
                        "stock-filing-facts-v1",
                        self.receipt,
                        self.requested_filing_ids,
                        self.requested_concepts,
                        tuple(_fact_identity(row) for row in self.records),
                        self.facts_missing,
                        self.null_row_indices,
                        self.missing_requested_concepts,
                        tuple(getattr(self, name) for name in _FLAGS),
                        self.publication_at,
                    )
                )
            )


def _legacy_flags(value: StockFilingCollection | StockFiling) -> None:
    _check(
        all(
            getattr(value, name) is False
            for name in (
                "qualified",
                "source_qualified",
                "strategy_qualified",
                "trading_enabled",
                "live_enabled",
            )
        )
    )


def _index(index: StockFilingCollection) -> StockFilingCollection:
    _check(type(index) is StockFilingCollection and type(index.receipt) is StockEventReceipt)
    _legacy_flags(index)
    _check(index.history_complete is False and index.scope_verified is True)
    _check(
        index.receipt.tool == "get_sec_filing_index"
        and index.receipt.hash_is_caller_declared is True
    )
    _require_sha256_hex(index.receipt.observation_sha256, "stock observation")
    require_utc(index.receipt.received_at)
    _check(type(index.records) is tuple and type(index.limitations) is tuple)
    _integer(index.null_row_count, 0, 1000)
    _check(type(index.response_results_missing) is bool)
    _check(len(index.records) + index.null_row_count <= 1000)
    _check(not index.response_results_missing or (not index.records and index.null_row_count == 0))
    rows: list[object] = []
    for record in index.records:
        _check(type(record) is StockFiling and type(record.receipt) is StockEventReceipt)
        _legacy_flags(record)
        _check(record.source_url is None and record.publication_at is None)
        _check(record.receipt == index.receipt and record.receipt.hash_is_caller_declared is True)
        _check(type(record.date_filed) is date)
        rows.append(
            {
                "filing_id": record.filing_id,
                "date_filed": record.date_filed.isoformat(),
                "form_type": record.form_type,
                "description": record.description,
            }
        )
    rows.extend([None] * index.null_row_count)
    data: dict[str, object] = {
        "symbol": index.requested_symbol,
        "filings": None if index.response_results_missing else rows,
    }
    if index.next_cursor is not None:
        data["next"] = index.next_cursor
    rebuilt = normalize_filing_index(
        {"data": data},
        received_at=index.receipt.received_at,
        observation_sha256=index.receipt.observation_sha256,
        requested_symbol=index.requested_symbol,
    )
    _check(rebuilt == index)
    return rebuilt


@dataclass(frozen=True, slots=True, repr=False)
class StockFilingEvidence(_Unqualified):
    index: StockFilingCollection
    catalog: StockFilingCatalog
    facts: StockFilingFacts
    filing: StockFiling
    as_of: datetime

    def __post_init__(self) -> None:
        with _errors():
            _flags(self)
            object.__setattr__(self, "as_of", require_utc(self.as_of))
            _index(self.index)
            _checked(self.catalog, StockFilingCatalog)
            _checked(self.facts, StockFilingFacts)
            _check(
                all(
                    value.available_at <= self.as_of
                    for value in (self.index, self.catalog, self.facts)
                )
            )
            _check(self.facts.requested_filing_ids == (self.catalog.requested_filing_id,))
            matches = tuple(
                row
                for row in self.index.records
                if row.filing_id == self.catalog.requested_filing_id
            )
            _check(len(matches) == 1 and self.filing is matches[0])
            concepts = {row.concept: row for row in self.catalog.records}
            for name in self.facts.requested_concepts:
                _check(name in concepts)
                _check(
                    concepts[name].is_text_block is False and concepts[name].axis_names_raw == ()
                )
            for row in self.facts.records:
                _check(row.axes_raw == ())
                periods = concepts[row.concept].periods
                _check(sum(_period_identity(p) == _period_identity(row) for p in periods) == 1)

    @property
    def available_at(self) -> datetime:
        return max(self.index.available_at, self.catalog.available_at, self.facts.available_at)

    @property
    def evidence_hash(self) -> str:
        with _errors():
            return str(
                content_hash(
                    (
                        "stock-filing-evidence-v1",
                        self.index.observation_hash,
                        self.catalog.catalog_hash,
                        self.facts.facts_hash,
                        self.as_of,
                        self.available_at,
                        tuple(getattr(self, name) for name in _FLAGS),
                        self.publication_at,
                    )
                )
            )


def normalize_filing_catalog(
    payload: object,
    *,
    received_at: datetime,
    observation_sha256: str,
    requested_filing_id: str,
    requested_offset: int = 0,
) -> StockFilingCatalog:
    """Normalize one observed catalog page without cursor following or completion claims."""
    with _errors():
        receipt = StockFilingReceipt(
            "get_sec_filing_facts_catalog", received_at, observation_sha256
        )
        data = _payload(payload, {"concepts", "count", "next_offset"}, {"concepts", "count"})
        records: list[StockFilingConcept] = []
        nulls: list[int] = []
        for index, item in enumerate(_rows(data["concepts"], 5000)):
            if item is None:
                nulls.append(index)
                continue
            row = _mapping(
                item,
                {"concept", "is_text_block", "periods", "axis_names"},
                {"concept", "is_text_block", "periods", "axis_names"},
            )
            periods: list[StockFilingPeriod] = []
            null_periods: list[int] = []
            for period_index, value in enumerate(_rows(row["periods"], 256)):
                if value is None:
                    null_periods.append(period_index)
                    continue
                p = _mapping(value, {"period", "end_date", "start_date"}, {"period", "end_date"})
                periods.append(
                    StockFilingPeriod(
                        period_index,
                        cast(str, p["period"]),
                        _date(p["end_date"]),
                        "start_date" in p,
                        cast(str | None, p.get("start_date")),
                        receipt,
                    )
                )
            records.append(
                StockFilingConcept(
                    index,
                    cast(str, row["concept"]),
                    cast(bool, row["is_text_block"]),
                    tuple(periods),
                    row["periods"] is None,
                    tuple(null_periods),
                    _axes(row["axis_names"]),
                    receipt,
                )
            )
        return StockFilingCatalog(
            receipt,
            requested_filing_id,
            requested_offset,
            tuple(records),
            cast(int, data["count"]),
            "next_offset" in data,
            cast(int | None, data.get("next_offset")),
            data["concepts"] is None,
            tuple(nulls),
        )


def normalize_filing_facts(
    payload: object,
    *,
    received_at: datetime,
    observation_sha256: str,
    requested_filing_ids: tuple[str, ...],
    requested_concepts: tuple[str, ...],
) -> StockFilingFacts:
    """Retain native fact states without scaling decimals or using character fallback."""
    with _errors():
        receipt = StockFilingReceipt("get_sec_filing_facts", received_at, observation_sha256)
        _scope(requested_filing_ids, 3)
        _scope(requested_concepts, 10)
        data = _payload(payload, {"facts"}, {"facts"})
        required = {"filing_id", "concept", "entity", "period", "axises", "char_value", "end_date"}
        allowed = required | {"start_date", "unit", "value", "decimals"}
        records: list[StockFilingFact] = []
        nulls: list[int] = []
        for index, value in enumerate(_rows(data["facts"], 20000)):
            if value is None:
                nulls.append(index)
                continue
            row = _mapping(value, allowed, required)
            records.append(
                StockFilingFact(
                    index,
                    cast(str, row["filing_id"]),
                    cast(str, row["concept"]),
                    cast(str, row["entity"]),
                    cast(str, row["period"]),
                    _axes(row["axises"]),
                    cast(str, row["char_value"]),
                    _date(row["end_date"]),
                    "start_date" in row,
                    cast(str | None, row.get("start_date")),
                    "unit" in row,
                    cast(str | None, row.get("unit")),
                    "value" in row,
                    cast(str | None, row.get("value")),
                    "decimals" in row,
                    cast(int | None, row.get("decimals")),
                    receipt,
                )
            )
        return StockFilingFacts(
            receipt,
            requested_filing_ids,
            requested_concepts,
            tuple(records),
            data["facts"] is None,
            tuple(nulls),
        )


def _positioned(
    rows: tuple[tuple[int, dict[str, object]], ...],
    nulls: tuple[int, ...],
    missing: bool,
) -> list[object] | None:
    if missing:
        return None
    result: list[object] = [None] * (len(rows) + len(nulls))
    for index, row in rows:
        result[index] = row
    return result


def _period_wire(value: StockFilingPeriod) -> dict[str, object]:
    result: dict[str, object] = {"period": value.period, "end_date": value.end_date.isoformat()}
    if value.start_date_present:
        result["start_date"] = value.start_date_raw
    return result


def _concept_wire(value: StockFilingConcept) -> dict[str, object]:
    return {
        "concept": value.concept,
        "is_text_block": value.is_text_block,
        "axis_names": None if value.axis_names_raw is None else list(value.axis_names_raw),
        "periods": _positioned(
            tuple((period.row_index, _period_wire(period)) for period in value.periods),
            value.null_period_indices,
            value.periods_missing,
        ),
    }


def _fact_wire(value: StockFilingFact) -> dict[str, object]:
    result: dict[str, object] = {
        "filing_id": value.filing_id,
        "concept": value.concept,
        "entity": value.entity,
        "period": value.period,
        "axises": None if value.axes_raw is None else list(value.axes_raw),
        "char_value": value.char_value,
        "end_date": value.end_date.isoformat(),
    }
    for name in ("start_date", "value", "unit", "decimals"):
        if getattr(value, name + "_present"):
            result[name] = getattr(value, name + "_raw")
    return result


def _catalog_rebuilt(value: StockFilingCatalog) -> StockFilingCatalog:
    _checked(value, StockFilingCatalog)
    data: dict[str, object] = {
        "concepts": _positioned(
            tuple((row.row_index, _concept_wire(row)) for row in value.records),
            value.null_row_indices,
            value.concepts_missing,
        ),
        "count": value.count,
    }
    if value.next_offset_present:
        data["next_offset"] = value.next_offset
    return normalize_filing_catalog(
        {"data": data, "guide": ""},
        received_at=value.receipt.received_at,
        observation_sha256=value.receipt.observation_sha256,
        requested_filing_id=value.requested_filing_id,
        requested_offset=value.requested_offset,
    )


def _facts_rebuilt(value: StockFilingFacts) -> StockFilingFacts:
    _checked(value, StockFilingFacts)
    rows = _positioned(
        tuple((row.row_index, _fact_wire(row)) for row in value.records),
        value.null_row_indices,
        value.facts_missing,
    )
    return normalize_filing_facts(
        {"data": {"facts": rows}, "guide": ""},
        received_at=value.receipt.received_at,
        observation_sha256=value.receipt.observation_sha256,
        requested_filing_ids=value.requested_filing_ids,
        requested_concepts=value.requested_concepts,
    )


def bind_filing_evidence(
    index: StockFilingCollection,
    catalog: StockFilingCatalog,
    facts: StockFilingFacts,
    *,
    as_of: datetime,
) -> StockFilingEvidence:
    """Bind one opaque filing and exact dimension-free native period contexts."""
    with _errors():
        index = _index(index)
        catalog = _catalog_rebuilt(catalog)
        facts = _facts_rebuilt(facts)
        matches = tuple(
            row for row in index.records if row.filing_id == catalog.requested_filing_id
        )
        _check(len(matches) == 1)
        return StockFilingEvidence(index, catalog, facts, matches[0], as_of)
