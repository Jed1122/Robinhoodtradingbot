"""Immutable coverage declarations and diagnostic manifests, never purchase authority."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain import ConfigHash, DataHash
from trading_bot.domain.options import OptionContract
from trading_bot.market_data.options_source_models import check, hashes, window
from trading_bot.market_data.recording import content_hash
from trading_bot.research.options_shortlist_v2 import VerifiedShortlistResult

PHASES = frozenset(
    {
        "warmup",
        "initialization",
        "entry",
        "monitoring",
        "exit",
        "underlying_quotes",
        "expiry",
        "settlement",
        "reference",
    }
)
REASONS = frozenset(
    {
        "coverage_requirements_missing",
        "coverage_identity_mismatch",
        "preregistration_late",
        "selection_sessions_incomplete",
        "selection_denied",
        "source_audit_invalidated",
        "source_coverage_gap",
        "source_semantics_unverified",
        "quote_semantics_incompatible",
        "coverage_obligations_incomplete",
        "research_history_insufficient",
        "duplicate_resolution_request",
        "coverage_contract_unverified",
    }
)


def text(value: str) -> None:
    check(type(value) is str and 0 < len(value) <= 1024 and all(32 <= ord(c) <= 126 for c in value))


def strings(values: tuple[str, ...]) -> None:
    check(type(values) is tuple and len(values) <= 25000)
    for value in values:
        text(value)
    check(values == tuple(sorted(set(values))))


@dataclass(frozen=True, slots=True)
class CoverageWindow:
    dataset: str
    schema: str
    symbol: str
    stype_in: str
    start_ns: int
    end_ns: int
    requirement_ids: tuple[str, ...]
    selection_hashes: tuple[DataHash, ...]

    def __post_init__(self) -> None:
        for value in (self.dataset, self.schema, self.symbol, self.stype_in):
            text(value)
        check(self.stype_in in {"raw_symbol", "parent", "instrument_id"})
        window(self.start_ns, self.end_ns)
        strings(self.requirement_ids)
        hashes(self.selection_hashes)


@dataclass(frozen=True, slots=True)
class CoverageSemantics:
    dataset: str
    schema: str
    stype_in: str
    start_ns: int
    end_ns: int
    observation_kind: Literal["event_quote", "interval_quote", "trade_bar", "reference"]
    initialization: Literal["snapshot_and_updates", "interval_observation", "not_applicable"]
    consumer_id: str
    consumer_hash: DataHash

    def __post_init__(self) -> None:
        for value in (self.dataset, self.schema, self.stype_in, self.consumer_id):
            text(value)
        window(self.start_ns, self.end_ns)
        check(self.observation_kind in {"event_quote", "interval_quote", "trade_bar", "reference"})
        check(
            self.initialization
            in {"snapshot_and_updates", "interval_observation", "not_applicable"}
        )
        hashes((self.consumer_hash,))

    @property
    def fact_hash(self) -> DataHash:
        return content_hash({"kind": "coverage_semantics", "semantics": self})


@dataclass(frozen=True, slots=True)
class CoverageRequirement:
    requirement_id: str
    role: str
    session_ids: tuple[str, ...]
    window: CoverageWindow
    semantics_hash: DataHash
    consumer_hash: DataHash
    preregistration_hash: DataHash
    missing_dependencies: tuple[str, ...]

    def __post_init__(self) -> None:
        text(self.requirement_id)
        check(type(self.role) is str and self.role in PHASES)
        strings(self.session_ids)
        check(bool(self.session_ids) and type(self.window) is CoverageWindow)
        check(self.window.requirement_ids == (self.requirement_id,))
        for digest in (self.semantics_hash, self.consumer_hash, self.preregistration_hash):
            hashes((digest,))
        strings(self.missing_dependencies)


@dataclass(frozen=True, slots=True)
class StudyCoverageRequirements:
    preregistration_hash: DataHash
    preregistered_at: datetime
    selection_frozen_at: datetime
    config_hash: ConfigHash
    shortlist_code_hash: DataHash
    consumer_id: str
    consumer_hash: DataHash
    requested_start_ns: int
    requested_end_ns: int
    session_ids: tuple[str, ...]
    purpose: Literal["engineering_pilot", "qualification"]
    observation_requirement: Literal["event_age", "interval_screening"]
    requirements: tuple[CoverageRequirement, ...]
    semantics: tuple[CoverageSemantics, ...]
    contracts: tuple[OptionContract, ...]

    def __post_init__(self) -> None:
        for digest in (
            self.preregistration_hash,
            DataHash(self.config_hash),
            self.shortlist_code_hash,
            self.consumer_hash,
        ):
            hashes((digest,))
        require_utc(self.preregistered_at)
        require_utc(self.selection_frozen_at)
        text(self.consumer_id)
        window(self.requested_start_ns, self.requested_end_ns)
        strings(self.session_ids)
        check(bool(self.session_ids))
        check(type(self.purpose) is str and self.purpose in {"engineering_pilot", "qualification"})
        check(
            type(self.observation_requirement) is str
            and self.observation_requirement in {"event_age", "interval_screening"}
        )
        for values, kind in (
            (self.requirements, CoverageRequirement),
            (self.semantics, CoverageSemantics),
            (self.contracts, OptionContract),
        ):
            check(
                type(values) is tuple
                and len(values) <= 25000
                and all(type(v) is kind for v in values)
            )
        check(len({r.requirement_id for r in self.requirements}) == len(self.requirements))
        check(len({s.fact_hash for s in self.semantics}) == len(self.semantics))
        check(len({content_hash(c) for c in self.contracts}) == len(self.contracts))


@dataclass(frozen=True, slots=True)
class CoverageBatch:
    dataset: str
    schema: str
    stype_in: str
    start_ns: int
    end_ns: int
    symbols: tuple[str, ...]
    request_hashes: tuple[DataHash, ...]

    def __post_init__(self) -> None:
        for value in (self.dataset, self.schema, self.stype_in):
            text(value)
        window(self.start_ns, self.end_ns)
        strings(self.symbols)
        check(1 <= len(self.symbols) <= 100)
        hashes(self.request_hashes)
        check(len(self.symbols) == len(self.request_hashes))


@dataclass(frozen=True, slots=True)
class CoverageManifest:
    status: Literal["requirements_complete", "blocked"]
    sessions: tuple[VerifiedShortlistResult, ...]
    requests: tuple[CoverageWindow, ...]
    batches: tuple[CoverageBatch, ...]
    coverage_links: tuple[tuple[str, tuple[DataHash, ...]], ...]
    missing_sessions: tuple[str, ...]
    incomplete_obligations: tuple[str, ...]
    reasons: tuple[str, ...]
    requirements_hash: DataHash | None
    research_minimums: tuple[tuple[str, int], ...]
    schema: Literal["options-acquisition-manifest-v1"] = field(
        default="options-acquisition-manifest-v1", init=False
    )
    production_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    download_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    economic_eligible: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        check(type(self.status) is str and self.status in {"requirements_complete", "blocked"})
        for values, kind in (
            (self.sessions, VerifiedShortlistResult),
            (self.requests, CoverageWindow),
            (self.batches, CoverageBatch),
        ):
            check(
                type(values) is tuple
                and len(values) <= 25000
                and all(type(v) is kind for v in values)
            )
        for labels in (self.missing_sessions, self.incomplete_obligations, self.reasons):
            strings(labels)
        check(set(self.reasons) <= REASONS)
        check((self.status == "blocked") == bool(self.reasons))
        if self.requirements_hash is not None:
            hashes((self.requirements_hash,))
        check(type(self.coverage_links) is tuple)
        for ident, digests in self.coverage_links:
            text(ident)
            hashes(digests)
        check(type(self.research_minimums) is tuple)
        for name, value in self.research_minimums:
            text(name)
            check(type(value) is int and value > 0)

    @property
    def manifest_hash(self) -> DataHash:
        return content_hash(self)
