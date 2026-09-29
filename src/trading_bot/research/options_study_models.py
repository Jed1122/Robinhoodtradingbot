"""Frozen study identities and observed-history preimages, never trusted counts."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain import Bar, ConfigHash, DataHash
from trading_bot.domain.enums import BarInterval
from trading_bot.domain.options import OptionContract, OptionSession
from trading_bot.market_data.options_session_inputs import _ns
from trading_bot.market_data.options_source_models import (
    SourceEvidenceBundle,
    VerificationContext,
    check,
    hashes,
    identity,
    instant,
    window,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.research.options_acquisition_models import CoverageSemantics

CAPITAL_TIERS = tuple(Decimal(n) for n in (100, 500, 1000, 2500, 5000, 10000, 25000, 50000))
REJECTION_CRITERIA = (
    "after_cost_lower_bound_positive",
    "canonical_research_minimums",
    "full_policy_feasible",
    "genuine_sources",
    "no_censored_obligations",
)


def session_ids(values: tuple[str, ...]) -> None:
    check(type(values) is tuple and 0 < len(values) <= 25000)
    for value in values:
        identity(value)
    check(len(set(values)) == len(values))


def sessions(values: tuple[OptionSession, ...]) -> None:
    check(type(values) is tuple and 0 < len(values) <= 25000)
    check(all(type(s) is OptionSession for s in values))
    session_ids(tuple(s.session_id for s in values))
    check(len({s.trading_date for s in values}) == len(values))
    check(all(a.closes_at <= b.opens_at for a, b in pairwise(values)))


@dataclass(frozen=True, slots=True)
class HistoryObservation:
    bar: Bar
    available_at: datetime
    session: OptionSession
    native_hashes: tuple[DataHash, ...]

    def __post_init__(self) -> None:
        check(type(self.bar) is Bar and type(self.session) is OptionSession)
        check(self.bar.instrument_id == "SPY" and self.bar.interval is BarInterval.ONE_DAY)
        check(not self.bar.interpolated)
        require_utc(self.available_at)
        check(self.bar.starts_at == self.session.opens_at)
        check(self.bar.ends_at == self.session.closes_at)
        check(self.available_at >= self.bar.ends_at)
        hashes(self.native_hashes, nonempty=True)


@dataclass(frozen=True, slots=True)
class VerifiedHistoryCoverage:
    """Verification inputs; constructing this object does not verify any source."""

    observations: tuple[HistoryObservation, ...]
    sessions: tuple[OptionSession, ...]
    start_ns: int
    end_ns: int
    actions_coverage_hash: DataHash
    source_bundle: SourceEvidenceBundle
    context: VerificationContext

    def __post_init__(self) -> None:
        window(self.start_ns, self.end_ns)
        sessions(self.sessions)
        check(type(self.observations) is tuple and 0 < len(self.observations) <= 25000)
        check(all(type(o) is HistoryObservation for o in self.observations))
        check(tuple(o.session for o in self.observations) == self.sessions)
        check(len({o.bar.data_hash for o in self.observations}) == len(self.observations))
        native = tuple(h for o in self.observations for h in o.native_hashes)
        check(len(native) <= 25000 and len(set(native)) == len(native))
        check(self.start_ns <= _ns(self.sessions[0].opens_at))
        check(_ns(self.sessions[-1].closes_at) < self.end_ns)
        check(all(_ns(o.available_at) <= self.end_ns for o in self.observations))
        hashes((self.actions_coverage_hash,))
        check(type(self.source_bundle) is SourceEvidenceBundle)
        check(type(self.context) is VerificationContext)
        check(
            (self.context.start_ns, self.context.end_ns, self.context.as_of_ns)
            == (self.start_ns, self.end_ns, self.end_ns)
        )

    @property
    def history_hash(self) -> DataHash:
        return content_hash(
            {
                "schema": "options-observed-history-v1",
                "observations": self.observations,
                "sessions": self.sessions,
                "start_ns": self.start_ns,
                "end_ns": self.end_ns,
                "actions_coverage_hash": self.actions_coverage_hash,
                "context": self.context,
                "source_hashes": tuple(
                    sorted(
                        r.sha256
                        for r in self.source_bundle.references + self.source_bundle.manifests
                    )
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class StudyFold:
    fold_id: str
    train_session_ids: tuple[str, ...]
    test_session_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        identity(self.fold_id)
        session_ids(self.train_session_ids)
        session_ids(self.test_session_ids)


@dataclass(frozen=True, slots=True)
class OptionsStudySpec:
    purpose: Literal["engineering_pilot", "qualification"]
    registered_at: datetime
    selection_frozen_at: datetime
    outcome_access_started_at: datetime | None
    decision_sessions: tuple[OptionSession, ...]
    declared_history_start_ns: int
    history_hash: DataHash
    source_hashes: tuple[DataHash, ...]
    availability_hash: DataHash
    config_hash: ConfigHash
    code_hash: DataHash
    consumer_hash: DataHash
    hypothesis: Literal["unvalidated-momentum-20-100-v1"]
    shortlist_version: Literal["spy-prior-close-atm-30d-v1"]
    exit_policy: Literal["signal_invalidation_or_prior_session_expiry"]
    scenario_hashes: tuple[tuple[str, DataHash], ...]
    cost_hash: DataHash
    capital_tiers: tuple[Decimal, ...]
    folds: tuple[StudyFold, ...]
    final_session_ids: tuple[str, ...]
    embargo_ns: int
    max_outcome_ns: int
    block_lengths_ns: tuple[int, ...]
    bootstrap_seed: int
    execution_seed: int
    rejection_criteria: tuple[str, ...]
    contracts: tuple[OptionContract, ...]
    coverage_semantics: tuple[CoverageSemantics, ...]
    initialization_sessions: tuple[OptionSession, ...]
    schema: Literal["options-study-v1"] = field(default="options-study-v1", init=False)

    def __post_init__(self) -> None:
        check(self.purpose in ("engineering_pilot", "qualification"))
        require_utc(self.registered_at)
        require_utc(self.selection_frozen_at)
        if self.outcome_access_started_at is not None:
            require_utc(self.outcome_access_started_at)
        sessions(self.decision_sessions)
        instant(self.declared_history_start_ns)
        hashes(self.source_hashes, nonempty=True)
        for digest in (
            self.history_hash,
            self.availability_hash,
            DataHash(self.config_hash),
            self.code_hash,
            self.consumer_hash,
            self.cost_hash,
        ):
            hashes((digest,))
        check(self.hypothesis == "unvalidated-momentum-20-100-v1")
        check(self.shortlist_version == "spy-prior-close-atm-30d-v1")
        check(self.exit_policy == "signal_invalidation_or_prior_session_expiry")
        check(type(self.scenario_hashes) is tuple and len(self.scenario_hashes) == 3)
        check(all(type(p) is tuple and len(p) == 2 for p in self.scenario_hashes))
        check(
            tuple(name for name, _ in self.scenario_hashes)
            == ("base", "conservative", "optimistic")
        )
        for _, digest in self.scenario_hashes:
            hashes((digest,))
        check(
            type(self.capital_tiers) is tuple
            and all(type(c) is Decimal for c in self.capital_tiers)
        )
        check(self.capital_tiers == CAPITAL_TIERS)
        check(type(self.folds) is tuple and len(self.folds) <= 25000)
        check(all(type(f) is StudyFold for f in self.folds))
        check(len({f.fold_id for f in self.folds}) == len(self.folds))
        session_ids(self.final_session_ids)
        instant(self.embargo_ns)
        instant(self.max_outcome_ns)
        check(type(self.block_lengths_ns) is tuple and 0 < len(self.block_lengths_ns) <= 100)
        for value in self.block_lengths_ns:
            instant(value)
        check(self.block_lengths_ns == tuple(sorted(set(self.block_lengths_ns))))
        check(
            all(
                type(v) is int and 0 <= v < 2**63
                for v in (self.bootstrap_seed, self.execution_seed)
            )
        )
        check(
            type(self.rejection_criteria) is tuple and self.rejection_criteria == REJECTION_CRITERIA
        )
        check(type(self.contracts) is tuple and len(self.contracts) <= 25000)
        check(all(type(c) is OptionContract for c in self.contracts))
        check(len({content_hash(c) for c in self.contracts}) == len(self.contracts))
        check(type(self.coverage_semantics) is tuple and len(self.coverage_semantics) <= 25000)
        check(all(type(s) is CoverageSemantics for s in self.coverage_semantics))
        check(len({s.fact_hash for s in self.coverage_semantics}) == len(self.coverage_semantics))
        check(type(self.initialization_sessions) is tuple)
        if self.initialization_sessions:
            sessions(self.initialization_sessions)
            check(len(self.initialization_sessions) == len(self.decision_sessions))
            check(
                all(
                    a.closes_at <= b.opens_at
                    for a, b in zip(
                        self.initialization_sessions, self.decision_sessions, strict=True
                    )
                )
            )

    @property
    def study_hash(self) -> DataHash:
        return content_hash(self)


@dataclass(frozen=True, slots=True)
class StudyRegistrationReport:
    study_hash: DataHash
    history_hash: DataHash
    observed_daily_bars: int
    verified_history_calendar_days: int
    genuine_sources: bool
    reasons: tuple[str, ...]
    economic_eligible: Literal[False] = field(default=False, init=False)
    production_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    download_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        hashes((self.study_hash,))
        hashes((self.history_hash,))
        check(type(self.observed_daily_bars) is int and 0 <= self.observed_daily_bars <= 25000)
        check(
            type(self.verified_history_calendar_days) is int
            and self.verified_history_calendar_days >= 0
        )
        check(type(self.genuine_sources) is bool)
        check(type(self.reasons) is tuple and self.reasons == tuple(sorted(set(self.reasons))))
