"""Immutable causal-feed contracts; source assertions are always reverified."""

from dataclasses import dataclass, field
from typing import Literal

from trading_bot.domain import DataHash
from trading_bot.domain.options import OptionContract, OptionSession
from trading_bot.market_data.options_records import OptionsDataRecord
from trading_bot.market_data.options_source_models import (
    PrivateArtifactRef,
    SourceEvidenceBundle,
    VerificationContext,
    check,
    hashes,
    identity,
    instant,
    window,
)
from trading_bot.market_data.options_source_verify import ceil_available_at
from trading_bot.market_data.recording import content_hash

type QuoteScope = Literal["consolidated", "exchange_specific"]
type EventState = Literal["quote", "reset", "gap", "halt", "session_boundary"]


@dataclass(frozen=True, slots=True)
class QuoteFeedBinding:
    manifest: PrivateArtifactRef
    source_id: str
    source_kind: Literal["synthetic", "imported"]
    quote_scope: QuoteScope
    initialization: Literal["snapshot_last_v1"]

    def __post_init__(self) -> None:
        check(type(self.manifest) is PrivateArtifactRef)
        identity(self.source_id)
        check(self.source_kind in ("synthetic", "imported"))
        check((self.source_kind == "synthetic") == self.source_id.startswith("synthetic."))
        check(self.quote_scope in ("consolidated", "exchange_specific"))
        # This policy is currently justified only by explicitly fabricated source
        # protocols. Native F_SNAPSHOT/F_LAST alone do NOT establish real readiness.
        check(self.initialization == "snapshot_last_v1")

    @property
    def fact(self) -> dict[str, object]:
        return {
            "kind": "quote-stream-feed-v1",
            "manifest_hash": self.manifest.sha256,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "quote_scope": self.quote_scope,
            "initialization": self.initialization,
        }


@dataclass(frozen=True, slots=True)
class QuoteStreamRequest:
    feeds: tuple[QuoteFeedBinding, ...]
    source_bundle: SourceEvidenceBundle
    context: VerificationContext
    contracts: tuple[OptionContract, ...]
    sessions: tuple[OptionSession, ...]
    start_ns: int
    end_ns: int

    def __post_init__(self) -> None:
        window(self.start_ns, self.end_ns)
        check(type(self.feeds) is tuple and len(self.feeds) == 2)
        check(all(type(f) is QuoteFeedBinding for f in self.feeds))
        check({f.quote_scope for f in self.feeds} == {"consolidated", "exchange_specific"})
        check(len({f.manifest.sha256 for f in self.feeds}) == 2)
        check(len({f.source_kind for f in self.feeds}) == 1)
        check(type(self.source_bundle) is SourceEvidenceBundle)
        check(type(self.context) is VerificationContext)
        check(
            (self.context.start_ns, self.context.end_ns, self.context.as_of_ns)
            == (self.start_ns, self.end_ns, self.start_ns)
        )
        check(type(self.contracts) is tuple and 0 < len(self.contracts) <= 10000)
        check(all(type(c) is OptionContract and c.underlying == "SPY" for c in self.contracts))
        check(len({c.standardized_id for c in self.contracts}) == len(self.contracts))
        check(len({c.contract_id for c in self.contracts}) == len(self.contracts))
        check(type(self.sessions) is tuple and 0 < len(self.sessions) <= 10000)
        check(all(type(s) is OptionSession for s in self.sessions))
        check(
            all(
                a.closes_at <= b.opens_at
                for a, b in zip(self.sessions, self.sessions[1:], strict=False)
            )
        )


@dataclass(frozen=True, slots=True)
class OptionsMarketEvent:
    event_ns: int
    available_ns: int
    source: str
    source_hash: DataHash
    record_ordinal: int | None
    symbol: str
    quote_scope: QuoteScope
    state: EventState
    record: OptionsDataRecord | None
    quality_reasons: tuple[str, ...]
    production_eligible: Literal[False] = field(default=False, init=False)
    economic_evidence: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        check(type(self.event_ns) is int and 0 <= self.event_ns < 2**64)
        instant(self.available_ns)
        identity(self.source)
        hashes((self.source_hash,))
        check(
            self.record_ordinal is None
            or (type(self.record_ordinal) is int and 0 <= self.record_ordinal < 10000000)
        )
        check(type(self.symbol) is str and 0 < len(self.symbol) <= 21)
        check(self.quote_scope in ("consolidated", "exchange_specific"))
        check(self.state in ("quote", "reset", "gap", "halt", "session_boundary"))
        check(self.record is None or type(self.record) is OptionsDataRecord)
        check((self.state == "quote") == (self.record is not None))
        if self.record is not None:
            instant(self.event_ns)
            check(self.event_ns <= self.available_ns)
            check(self.record_ordinal is not None)
            check(self.record.source == self.source + ":" + self.quote_scope)
            check(self.record.event_at == ceil_available_at(self.event_ns))
            check(self.record.available_at == ceil_available_at(self.available_ns))
        elif not 0 < self.event_ns <= self.available_ns:
            check("native_bad_timestamp" in self.quality_reasons)
        check(type(self.quality_reasons) is tuple)
        check(all(type(r) is str and 0 < len(r) <= 64 for r in self.quality_reasons))
        check(self.quality_reasons == tuple(sorted(set(self.quality_reasons))))

    @property
    def identity(self) -> str:
        return content_hash({"schema": "options-market-event-v1", "event": self})

    def can_follow(self, decision_available_ns: int) -> bool:
        """Ordering predicate only, never a fill promise or execution capability."""
        instant(decision_available_ns)
        return (
            self.state == "quote"
            and self.record is not None
            and not self.quality_reasons
            and self.available_ns > decision_available_ns
        )
