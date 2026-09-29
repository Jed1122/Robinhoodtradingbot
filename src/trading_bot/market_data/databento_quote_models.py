"""Native observations, not canonical quotes, source verification or trading authority."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from trading_bot.market_data.databento_bar_models import NativeCondition, _hash, _integer
from trading_bot.market_data.databento_batch import require

QUALITY_CODES = (
    "native_bad_book",
    "native_bad_timestamp",
    "native_crossed_quote",
    "native_empty_size",
    "native_incomplete_event",
    "native_invalid_price",
    "native_publisher_specific",
    "native_provider_inconsistent",
    "native_undefined_quote",
)
UNDEF_PRICE = 2**63 - 1


@dataclass(frozen=True, slots=True)
class NativeQuoteRequest:
    dataset: str
    schema: str
    stype_in: str
    symbols: tuple[str, ...]
    start_ns: int
    end_ns: int

    def __post_init__(self) -> None:
        require((self.dataset, self.schema) in (("OPRA.PILLAR", "cmbp-1"), ("XNAS.ITCH", "mbp-1")))
        require(self.stype_in == "raw_symbol" and type(self.symbols) is tuple)
        require(0 < len(self.symbols) <= 10000)
        require(all(type(symbol) is str for symbol in self.symbols))
        require(self.symbols == tuple(sorted(set(self.symbols))))
        if self.dataset == "XNAS.ITCH":
            require(self.symbols == ("SPY",))
        else:
            require(all(re.fullmatch(r"SPY   [0-9]{6}[CP][0-9]{8}", s) for s in self.symbols))
        require(_integer(self.start_ns, 1, 2**63 - 1))
        require(_integer(self.end_ns, 1, 2**63 - 1) and self.start_ns < self.end_ns)

    def query(self) -> dict[str, object]:
        return dict(
            dataset=self.dataset,
            schema=self.schema,
            stype_in=self.stype_in,
            symbols=list(self.symbols),
            stype_out="instrument_id",
            start=self.start_ns,
            end=self.end_ns,
            limit=None,
            encoding="dbn",
            compression="zstd",
        )


def quality_reasons(
    *,
    schema: str,
    publisher_id: int,
    side: str,
    ts_in_delta: int,
    flags: int,
    ts_event: int,
    ts_recv: int,
    action: str,
    bid_px: int,
    ask_px: int,
    bid_sz: int,
    ask_sz: int,
) -> tuple[str, ...]:
    reasons = []
    # Quarantine disagreement with the documented normalization. This does not
    # certify era-specific availability, initialization, gaps or executable state.
    if schema == "cmbp-1" and (
        ts_in_delta != 0
        or (action != "T" and publisher_id != 30)
        or (action == "T" and (side != "N" or publisher_id == 30))
    ):
        reasons.append("native_provider_inconsistent")
    if flags & 8 or not 0 < ts_event <= ts_recv < 2**63:
        reasons.append("native_bad_timestamp")
    if flags & 4:
        reasons.append("native_bad_book")
    if flags & 2:
        reasons.append("native_publisher_specific")
    if action != "R":
        if not flags & 128:
            reasons.append("native_incomplete_event")
        if UNDEF_PRICE in (bid_px, ask_px):
            reasons.append("native_undefined_quote")
        elif bid_px < 0 or ask_px <= 0:
            reasons.append("native_invalid_price")
        elif bid_px > ask_px:
            reasons.append("native_crossed_quote")
        if bid_sz in (0, 2**32 - 1) or ask_sz in (0, 2**32 - 1):
            reasons.append("native_empty_size")
    return tuple(sorted(reasons))


@dataclass(frozen=True, slots=True)
class NativeQuoteRow:
    record_ordinal: int
    dbn_version: int
    schema: str
    raw_symbol: str
    publisher_id: int
    instrument_id: int
    ts_event: int
    ts_recv: int
    price: int
    size: int
    action: str
    side: str
    flags: int
    ts_in_delta: int
    bid_px: int
    ask_px: int
    bid_sz: int
    ask_sz: int
    bid_pb: int | None
    ask_pb: int | None
    bid_ct: int | None
    ask_ct: int | None
    depth: int | None
    sequence: int | None
    raw_record_hex: str
    record_hash: str
    raw_hash: str
    disposition: Literal["accepted", "rejected", "control"]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        require(_integer(self.record_ordinal, 0, 9999999) and _integer(self.dbn_version, 1, 3))
        require(self.schema in ("cmbp-1", "mbp-1"))
        require(type(self.raw_symbol) is str and 0 < len(self.raw_symbol) <= 21)
        require(_integer(self.publisher_id, 1, 65535))
        require(_integer(self.instrument_id, 1, 2**32 - 2))
        for value in (self.ts_event, self.ts_recv):
            require(_integer(value, 0, 2**64 - 1))
        for value in (self.bid_px, self.ask_px, self.price):
            require(_integer(value, -(2**63), 2**63 - 1))
        for value in (self.bid_sz, self.ask_sz, self.size):
            require(_integer(value, 0, 2**32 - 1))
        require(_integer(self.flags, 0, 255) and _integer(self.ts_in_delta, -(2**31), 2**31 - 1))
        require(self.action in ("A", "C", "M", "R", "T") and self.side in ("A", "B", "N"))
        for optional_value in (
            self.bid_pb,
            self.ask_pb,
            self.bid_ct,
            self.ask_ct,
            self.depth,
            self.sequence,
        ):
            require(optional_value is None or _integer(optional_value, 0, 2**32 - 1))
        if self.schema == "cmbp-1":
            require(_integer(self.bid_pb, 0, 65535) and _integer(self.ask_pb, 0, 65535))
            require(all(v is None for v in (self.bid_ct, self.ask_ct, self.depth, self.sequence)))
        else:
            require(self.bid_pb is None and self.ask_pb is None and self.depth == 0)
            require(all(v is not None for v in (self.bid_ct, self.ask_ct, self.sequence)))
        require(
            type(self.raw_record_hex) is str
            and re.fullmatch(r"[0-9a-f]{160}", self.raw_record_hex) is not None
        )
        require(_hash(self.record_hash) and _hash(self.raw_hash))
        require(
            type(self.reasons) is tuple
            and self.reasons
            == quality_reasons(
                schema=self.schema,
                publisher_id=self.publisher_id,
                side=self.side,
                ts_in_delta=self.ts_in_delta,
                flags=self.flags,
                ts_event=self.ts_event,
                ts_recv=self.ts_recv,
                action=self.action,
                bid_px=self.bid_px,
                ask_px=self.ask_px,
                bid_sz=self.bid_sz,
                ask_sz=self.ask_sz,
            )
        )
        expected = "control" if self.action == "R" else "rejected" if self.reasons else "accepted"
        require(self.disposition == expected)


@dataclass(frozen=True, slots=True)
class NativeQuoteProfile:
    request: NativeQuoteRequest
    raw_hash: str
    dbn_version: int
    decoded_count: int
    accepted_count: int
    rejected_count: int
    control_count: int
    adjacent_repeat_count: int
    first_recv_ns: int | None
    last_recv_ns: int | None
    quality_counts: tuple[tuple[str, int], ...]
    historical_availability_verified: Literal[False] = field(default=False, init=False)
    economic_evidence: Literal[False] = field(default=False, init=False)
    production_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    download_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        require(type(self.request) is NativeQuoteRequest and _hash(self.raw_hash))
        require(_integer(self.dbn_version, 1, 3))
        for value in (
            self.decoded_count,
            self.accepted_count,
            self.rejected_count,
            self.control_count,
            self.adjacent_repeat_count,
        ):
            require(_integer(value, 0, 10000000))
        require(
            self.decoded_count == self.accepted_count + self.rejected_count + self.control_count
        )
        require(self.adjacent_repeat_count <= max(0, self.decoded_count - 1))
        require(type(self.quality_counts) is tuple)
        require(all(type(p) is tuple and len(p) == 2 for p in self.quality_counts))
        require(
            tuple(k for k, _ in self.quality_counts)
            == tuple(sorted({k for k, _ in self.quality_counts}))
        )
        require(
            all(
                k in QUALITY_CODES and _integer(v, 1, self.decoded_count)
                for k, v in self.quality_counts
            )
        )
        if self.decoded_count:
            require(_integer(self.first_recv_ns, self.request.start_ns, self.request.end_ns - 1))
            require(_integer(self.last_recv_ns, self.first_recv_ns, self.request.end_ns - 1))  # type: ignore[arg-type]
        else:
            require(self.first_recv_ns is None and self.last_recv_ns is None)


@dataclass(frozen=True, slots=True)
class QuoteChunk:
    sha256: str
    byte_count: int

    def __post_init__(self) -> None:
        require(_hash(self.sha256) and _integer(self.byte_count, 1, 1048576))


@dataclass(frozen=True, slots=True)
class QuoteArchive:
    name: str
    sha256: str
    size: int
    chunks: tuple[QuoteChunk, ...]

    def __post_init__(self) -> None:
        require(
            type(self.name) is str
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.name) is not None
        )
        require(".." not in self.name and _hash(self.sha256) and _integer(self.size, 1, 536870912))
        require(type(self.chunks) is tuple and 0 < len(self.chunks) <= 8192)
        require(all(type(c) is QuoteChunk for c in self.chunks))
        require(sum(c.byte_count for c in self.chunks) == self.size)


@dataclass(frozen=True, slots=True)
class NativeQuotePart:
    path: str
    sha256: str
    byte_count: int
    record_count: int

    def __post_init__(self) -> None:
        require(
            type(self.path) is str
            and re.fullmatch(
                r"parts/receive_date=\d{4}-\d{2}-\d{2}/[0-9a-f]{64}\.parquet", self.path
            )
            is not None
        )
        require(_hash(self.sha256) and Path(self.path).stem == self.sha256)
        require(_integer(self.byte_count, 1, 16777216) and _integer(self.record_count, 1, 10000))


@dataclass(frozen=True, slots=True)
class VerifiedQuoteStage:
    manifest_path: Path = field(repr=False)
    manifest_hash: str
    config_hash: str
    request: NativeQuoteRequest
    profile: NativeQuoteProfile
    parts: tuple[NativeQuotePart, ...]
    archives: tuple[QuoteArchive, ...]
    conditions: tuple[NativeCondition, ...]
    production_eligible: Literal[False] = field(default=False, init=False)
    economic_evidence: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    download_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        require(isinstance(self.manifest_path, Path) and self.manifest_path.is_absolute())
        require(_hash(self.manifest_hash) and _hash(self.config_hash))
        require(self.manifest_path.name == self.manifest_hash + ".json")
        require(
            type(self.request) is NativeQuoteRequest and type(self.profile) is NativeQuoteProfile
        )
        require(self.profile.request == self.request)
        require(type(self.parts) is tuple and len(self.parts) <= 10000)
        require(all(type(p) is NativeQuotePart for p in self.parts))
        require(len({p.path for p in self.parts}) == len(self.parts))
        require(sum(p.record_count for p in self.parts) == self.profile.decoded_count)
        require(type(self.archives) is tuple and len(self.archives) == 4)
        require(all(type(a) is QuoteArchive for a in self.archives))
        names = tuple(a.name for a in self.archives)
        require(names == tuple(sorted(set(names))))
        require({"manifest.json", "metadata.json", "condition.json"} < set(names))
        require(
            type(self.conditions) is tuple
            and all(type(c) is NativeCondition for c in self.conditions)
        )
