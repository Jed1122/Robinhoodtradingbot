"""Exact native observations. Intake integrity is not historical source verification."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from typing import Literal

from trading_bot.config.loader import LoadedConfig
from trading_bot.domain import DataHash, ExecutionMode
from trading_bot.market_data.databento_batch import DatabentoImportError, require
from trading_bot.market_data.databento_native_io import DefinitionLimits

MINUTE_NS = 60_000_000_000
QUALITY_CODES = ("native_undefined_ohlc", "native_nonpositive_price", "native_invalid_ohlc")


def _integer(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _hash(value: str) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


@dataclass(frozen=True, slots=True)
class NativeBarRequest:
    start_ns: int
    end_ns: int

    def __post_init__(self) -> None:
        require(_integer(self.start_ns, 1, 2**63 - 1))
        require(_integer(self.end_ns, 1, 2**63 - 1) and self.start_ns < self.end_ns)

    def query(self) -> dict[str, object]:
        return {
            "dataset": "XNAS.ITCH",
            "schema": "ohlcv-1m",
            "symbols": ["SPY"],
            "stype_in": "raw_symbol",
            "stype_out": "instrument_id",
            "start": self.start_ns,
            "end": self.end_ns,
            "limit": None,
            "encoding": "dbn",
            "compression": "zstd",
        }


def quality_reasons(prices: tuple[int | None, ...]) -> tuple[str, ...]:
    if any(value is None for value in prices):
        return ("native_undefined_ohlc",)
    values = tuple(value for value in prices if value is not None)
    if any(value <= 0 for value in values):
        return ("native_nonpositive_price",)
    opening, high, low, closing = values
    if not low <= min(opening, closing) <= max(opening, closing) <= high:
        return ("native_invalid_ohlc",)
    return ()


@dataclass(frozen=True, slots=True)
class NativeBarRow:
    record_ordinal: int
    dbn_version: int
    publisher_id: int
    instrument_id: int
    interval_start_ns: int
    open_nanos: int | None
    high_nanos: int | None
    low_nanos: int | None
    close_nanos: int | None
    volume: int
    record_hash: DataHash
    raw_hash: DataHash
    disposition: Literal["accepted", "rejected", "duplicate"]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        require(_integer(self.record_ordinal, 0, 10_000_000 - 1))
        require(_integer(self.dbn_version, 1, 3))
        require(_integer(self.publisher_id, 1, 2**16 - 1))
        require(_integer(self.instrument_id, 1, 2**32 - 2))
        require(_integer(self.interval_start_ns, 1, 2**63 - 1))
        require(self.interval_start_ns % MINUTE_NS == 0)
        require(_integer(self.volume, 0, 2**64 - 1))
        prices = (self.open_nanos, self.high_nanos, self.low_nanos, self.close_nanos)
        require(all(value is None or _integer(value, -(2**63), 2**63 - 2) for value in prices))
        require(_hash(self.record_hash) and _hash(self.raw_hash))
        require(type(self.reasons) is tuple and self.reasons == quality_reasons(prices))
        require(self.disposition in ("accepted", "rejected", "duplicate"))
        if self.disposition != "duplicate":
            require(self.disposition == ("rejected" if self.reasons else "accepted"))


@dataclass(frozen=True, slots=True)
class NativeBarProfile:
    request: NativeBarRequest
    raw_hash: DataHash
    dbn_version: int
    decoded_count: int
    accepted_count: int
    rejected_count: int
    duplicate_count: int
    first_interval_ns: int | None
    last_interval_ns: int | None
    mapping_counts: tuple[tuple[str, int], ...]
    quality_counts: tuple[tuple[str, int], ...]
    historical_availability_verified: Literal[False] = field(default=False, init=False)
    economic_evidence: Literal[False] = field(default=False, init=False)
    production_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    download_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        require(type(self.request) is NativeBarRequest and _hash(self.raw_hash))
        require(_integer(self.dbn_version, 1, 3))
        for value in (
            self.decoded_count,
            self.accepted_count,
            self.rejected_count,
            self.duplicate_count,
        ):
            require(_integer(value, 0, 10_000_000))
        require(
            self.decoded_count == self.accepted_count + self.rejected_count + self.duplicate_count
        )
        for counts, allowed in (
            (self.mapping_counts, ("mapping_count", "mapping_interval_count")),
            (self.quality_counts, QUALITY_CODES),
        ):
            require(type(counts) is tuple)
            require(all(type(pair) is tuple and len(pair) == 2 for pair in counts))
            require(tuple(key for key, _ in counts) == tuple(sorted({key for key, _ in counts})))
            require(all(key in allowed and _integer(value, 0, 10_000_000) for key, value in counts))
        if self.decoded_count:
            require(
                _integer(self.first_interval_ns, self.request.start_ns, self.request.end_ns - 1)
            )
            require(_integer(self.last_interval_ns, self.request.start_ns, self.request.end_ns - 1))
            if self.first_interval_ns is None or self.last_interval_ns is None:
                raise DatabentoImportError()
            require(self.first_interval_ns <= self.last_interval_ns)
        else:
            require(self.first_interval_ns is None and self.last_interval_ns is None)


def native_limits(loaded: LoadedConfig) -> DefinitionLimits:
    """Map the existing canonical graph, never load a second policy or grant authority."""
    require(type(loaded) is LoadedConfig)
    settings = loaded.config.options.native_data
    require(settings.enabled and loaded.config.options.enabled)
    require(loaded.config.mode in (ExecutionMode.BACKTEST, ExecutionMode.SIMULATION))
    require(not loaded.config.live_trading_enabled and loaded.config.runtime.start_paused)
    return DefinitionLimits(
        **{item.name: getattr(settings, item.name) for item in fields(DefinitionLimits)}
    )
