"""Deterministic complete-coverage planning, without pricing, transport or purchasing."""

from collections import defaultdict
from dataclasses import replace
from typing import TYPE_CHECKING

from trading_bot.config import LoadedConfig
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.market_data.databento_bar_models import native_limits
from trading_bot.market_data.options_session_inputs import _ns
from trading_bot.market_data.options_source_models import check
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.options_acquisition_models import (
    CoverageBatch,
    CoverageManifest,
    CoverageRequirement,
    CoverageWindow,
    StudyCoverageManifest,
    StudyCoverageRequirements,
)

if TYPE_CHECKING:
    from trading_bot.research.options_study_models import OptionsStudySpec, VerifiedHistoryCoverage
from trading_bot.research.options_shortlist_v2 import (
    VerifiedShortlistResult,
    verified_shortlist_code_hash,
)


def union_coverage_windows(windows: tuple[CoverageWindow, ...]) -> tuple[CoverageWindow, ...]:
    check(type(windows) is tuple and len(windows) <= 25000)
    check(all(type(item) is CoverageWindow for item in windows))
    groups: dict[tuple[str, str, str, str], list[CoverageWindow]] = defaultdict(list)
    for item in windows:
        groups[(item.dataset, item.schema, item.stype_in, item.symbol)].append(item)
    result = []
    for key in sorted(groups):
        merged: list[CoverageWindow] = []
        for item in sorted(groups[key], key=lambda w: (w.start_ns, w.end_ns, w.requirement_ids)):
            if not merged or item.start_ns > merged[-1].end_ns:
                merged.append(item)
            else:
                previous = merged[-1]
                merged[-1] = replace(
                    previous,
                    end_ns=max(previous.end_ns, item.end_ns),
                    requirement_ids=tuple(
                        sorted(set(previous.requirement_ids) | set(item.requirement_ids))
                    ),
                    selection_hashes=tuple(
                        sorted(set(previous.selection_hashes) | set(item.selection_hashes))
                    ),
                )
        result.extend(merged)
    return tuple(result)


def batch_coverage_requests(requests: tuple[CoverageWindow, ...]) -> tuple[CoverageBatch, ...]:
    groups: dict[tuple[str, str, str, int, int], list[CoverageWindow]] = defaultdict(list)
    for item in union_coverage_windows(requests):
        groups[(item.dataset, item.schema, item.stype_in, item.start_ns, item.end_ns)].append(item)
    result = []
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda w: w.symbol)
        for index in range(0, len(members), 100):
            chunk = members[index : index + 100]
            result.append(
                CoverageBatch(
                    *key,
                    tuple(w.symbol for w in chunk),
                    tuple(sorted(content_hash(w) for w in chunk)),
                )
            )
    return tuple(result)


def _covers(values: tuple[CoverageRequirement, ...], start: int, end: int) -> bool:
    cursor = start
    for item in sorted(values, key=lambda r: (r.window.start_ns, r.window.end_ns)):
        if item.window.start_ns > cursor:
            return False
        cursor = max(cursor, item.window.end_ns)
        if cursor >= end:
            return True
    return False


def _phases(
    result: VerifiedShortlistResult,
    study: StudyCoverageRequirements,
    incomplete: set[str],
    reasons: set[str],
) -> None:
    applicable = tuple(r for r in study.requirements if result.session_id in r.session_ids)
    as_of = _ns(result.as_of)
    selected = {c.standardized_id for c in result.candidates}
    for item in applicable:
        if (
            item.role not in {"warmup", "underlying_quotes", "reference"}
            and item.window.symbol not in selected
        ):
            reasons.add("coverage_identity_mismatch")
    terms = {content_hash(contract): contract for contract in study.contracts}
    for candidate in result.candidates:
        contract_hash = dict(candidate.selected_input_hashes).get("contract")
        contract = terms.get(contract_hash) if contract_hash is not None else None
        if contract is None or contract.standardized_id != candidate.standardized_id:
            reasons.add("coverage_contract_unverified")
            continue
        last, settlement = _ns(contract.last_trading_at), _ns(contract.settlement_at)
        scoped = tuple(r for r in applicable if r.window.symbol == candidate.standardized_id)
        by_role = {
            role: tuple(r for r in scoped if r.role == role)
            for role in ("initialization", "entry", "monitoring", "exit", "expiry", "settlement")
        }
        prefix = f"{result.session_id}:{candidate.standardized_id}:"
        streams = {
            (r.window.dataset, r.window.schema, r.window.stype_in, r.window.symbol)
            for role, entries in by_role.items()
            if role != "settlement"
            for r in entries
        }
        # Without an independently reviewed compatibility contract, one feed cannot
        # initialize another or bridge gaps in its required event history.
        if len(streams) != 1:
            reasons.add("quote_semantics_incompatible")
            incomplete.add(prefix + "quote_stream")
        for role, entries in by_role.items():
            if not entries:
                incomplete.add(prefix + role)
        if not _covers(by_role["entry"], as_of, as_of + 1):
            incomplete.add(prefix + "entry")
        if not any(
            as_of <= r.window.start_ns < last + 1 and r.window.end_ns <= last + 1
            for r in by_role["exit"]
        ):
            incomplete.add(prefix + "exit")
        if not any(r.window.start_ns < as_of <= r.window.end_ns for r in by_role["initialization"]):
            incomplete.add(prefix + "initialization")
        if not _covers(by_role["monitoring"], as_of, last + 1):
            incomplete.add(prefix + "monitoring")
        if not _covers(by_role["expiry"], last, last + 1):
            incomplete.add(prefix + "expiry")
        if not _covers(by_role["settlement"], last, settlement + 1):
            incomplete.add(prefix + "settlement")
        underlying = tuple(
            r for r in applicable if r.role == "underlying_quotes" and r.window.symbol == "SPY"
        )
        if not _covers(underlying, as_of, last + 1):
            incomplete.add(result.session_id + ":underlying_quotes")
    warmup = tuple(
        r
        for r in applicable
        if r.role == "warmup" and r.window.symbol == "SPY" and r.window.end_ns <= as_of
    )
    if not warmup or not _covers(warmup, min(r.window.start_ns for r in warmup), as_of):
        incomplete.add(result.session_id + ":warmup")


def _requirements(
    study: StudyCoverageRequirements,
    results: tuple[VerifiedShortlistResult, ...],
    reasons: set[str],
    incomplete: set[str],
) -> None:
    by_session = {result.session_id: result for result in results}
    semantics = {s.fact_hash: s for s in study.semantics}
    quote_roles = {"initialization", "entry", "monitoring", "exit", "expiry", "underlying_quotes"}
    for item in study.requirements:
        incomplete.update(item.missing_dependencies)
        participants = tuple(by_session[s] for s in item.session_ids if s in by_session)
        if (
            item.preregistration_hash != study.preregistration_hash
            or item.consumer_hash != study.consumer_hash
            or set(item.session_ids) - set(study.session_ids)
            or set(item.window.selection_hashes) != {r.decision_hash for r in participants}
        ):
            reasons.add("coverage_identity_mismatch")
        semantic = semantics.get(item.semantics_hash)
        if semantic is None:
            reasons.add("source_semantics_unverified")
            incomplete.add(item.requirement_id)
            continue
        window = item.window
        if (
            semantic.dataset,
            semantic.schema,
            semantic.stype_in,
            semantic.consumer_id,
            semantic.consumer_hash,
        ) != (
            window.dataset,
            window.schema,
            window.stype_in,
            study.consumer_id,
            study.consumer_hash,
        ):
            reasons.add("coverage_identity_mismatch")
        if not semantic.start_ns <= window.start_ns < window.end_ns <= semantic.end_ns:
            reasons.add("source_coverage_gap")
            incomplete.add(item.requirement_id)
        if not participants or not all(
            item.semantics_hash in result.verification.record_hashes
            and any(
                f.role == "quote_semantics"
                and f.status == "verified"
                and item.semantics_hash in f.visible_hashes
                for f in result.verification.findings
            )
            for result in participants
        ):
            reasons.add("source_semantics_unverified")
            incomplete.add(item.requirement_id)
        if item.role in quote_roles:
            if semantic.observation_kind not in {"event_quote", "interval_quote"}:
                reasons.add("quote_semantics_incompatible")
            if study.observation_requirement == "event_age" and (
                semantic.observation_kind != "event_quote"
                or semantic.initialization != "snapshot_and_updates"
                or window.schema.startswith("cbbo")
            ):
                reasons.add("quote_semantics_incompatible")
        if item.role == "warmup" and semantic.observation_kind != "trade_bar":
            reasons.add("quote_semantics_incompatible")
        if item.role in {"settlement", "reference"} and semantic.observation_kind != "reference":
            reasons.add("quote_semantics_incompatible")
    for result in results:
        if result.status == "selected":
            _phases(result, study, incomplete, reasons)


def build_coverage_manifest(
    results: tuple[VerifiedShortlistResult, ...],
    *,
    requirements: StudyCoverageRequirements | None,
    loaded: LoadedConfig,
) -> CoverageManifest:
    native_limits(loaded)
    canonical, config_hash = hash_loaded_config(loaded.config, loaded.safety_envelope)
    check(config_hash == loaded.config_hash and canonical == loaded.canonical_json)
    limit = loaded.config.options.research_shortlist
    check(type(results) is tuple and len(results) <= limit.max_input_records)
    check(all(type(r) is VerifiedShortlistResult for r in results))
    check(len({r.session_id for r in results}) == len(results))
    check(requirements is None or type(requirements) is StudyCoverageRequirements)
    check(len(canonical_json((results, requirements)).encode()) <= limit.max_input_bytes)
    sessions = tuple(sorted(results, key=lambda r: (r.as_of, r.session_id)))
    research = loaded.config.research
    minimums = (
        ("history_calendar_days", research.history_calendar_days),
        ("minimum_history_bars", research.minimum_history_bars),
        ("walk_forward_folds", research.walk_forward_folds),
        ("minimum_test_bars_per_fold", research.minimum_test_bars_per_fold),
        ("minimum_independent_opportunities", research.minimum_independent_opportunities),
    )
    if requirements is None:
        return CoverageManifest(
            "blocked",
            sessions,
            (),
            (),
            (),
            (),
            (),
            ("coverage_requirements_missing",),
            None,
            minimums,
        )
    study = requirements
    check(
        sum(
            map(
                len,
                (study.requirements, study.semantics, study.contracts, study.session_ids, results),
            )
        )
        <= limit.max_input_records
    )
    reasons: set[str] = set()
    incomplete: set[str] = set()
    missing = tuple(sorted(set(study.session_ids) - {r.session_id for r in results}))
    if missing or {r.session_id for r in results} != set(study.session_ids):
        reasons.add("selection_sessions_incomplete")
    if (
        study.config_hash != config_hash
        or study.shortlist_code_hash != verified_shortlist_code_hash()
        or any(
            r.config_hash != config_hash or r.code_hash != study.shortlist_code_hash
            for r in results
        )
    ):
        reasons.add("coverage_identity_mismatch")
    if study.preregistered_at > study.selection_frozen_at or any(
        r.as_of > study.selection_frozen_at for r in results
    ):
        reasons.add("preregistration_late")
    if any(not study.requested_start_ns <= _ns(r.as_of) < study.requested_end_ns for r in results):
        reasons.add("coverage_identity_mismatch")
    if any(r.status != "selected" for r in results):
        reasons.add("selection_denied")
    if any(r.verification.invalidations for r in results):
        reasons.add("source_audit_invalidated")
    _requirements(study, results, reasons, incomplete)
    requests = union_coverage_windows(tuple(r.window for r in study.requirements))
    by_identity: dict[tuple[str, str], list[CoverageWindow]] = defaultdict(list)
    for item in requests:
        if item.schema in {"cmbp-1", "cbbo-1m"}:
            for previous in by_identity[(item.dataset, item.symbol)]:
                if previous.schema != item.schema and max(previous.start_ns, item.start_ns) < min(
                    previous.end_ns, item.end_ns
                ):
                    reasons.add("duplicate_resolution_request")
            by_identity[(item.dataset, item.symbol)].append(item)
    if study.purpose == "qualification":
        # V1 records declared windows/session IDs, not verified observed history,
        # fold membership or independent opportunities. Neither an old start date
        # nor 750 planned decisions establishes the configured 750-bar minimum.
        # Keep qualification blocked until a reviewed observed-history contract
        # can establish every emitted minimum; engineering pilots remain usable.
        reasons.add("research_history_insufficient")
    if incomplete:
        reasons.add("coverage_obligations_incomplete")
    links = tuple(
        (
            item.requirement_id,
            tuple(
                sorted(
                    content_hash(request)
                    for request in requests
                    if item.requirement_id in request.requirement_ids
                )
            ),
        )
        for item in sorted(study.requirements, key=lambda r: r.requirement_id)
    )
    return CoverageManifest(
        "blocked" if reasons else "requirements_complete",
        sessions,
        requests,
        batch_coverage_requests(requests),
        links,
        missing,
        tuple(sorted(incomplete)),
        tuple(sorted(reasons)),
        content_hash(study),
        minimums,
    )


def plan_options_study_coverage(
    spec: "OptionsStudySpec",
    *,
    shortlists: tuple[VerifiedShortlistResult, ...],
    history: "VerifiedHistoryCoverage",
    loaded: LoadedConfig,
) -> StudyCoverageManifest:
    """V2 adds reverified history/split constraints; v1 qualification stays denied."""
    from trading_bot.research.options_study_coverage import plan_study_coverage

    return plan_study_coverage(spec, shortlists=shortlists, history=history, loaded=loaded)
