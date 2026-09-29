"""Derive complete paired-contract obligations and reuse v1 deterministic unions."""

from pathlib import Path

from trading_bot.config import LoadedConfig
from trading_bot.domain import DataHash
from trading_bot.market_data.options_session_inputs import _ns
from trading_bot.market_data.options_source_models import check
from trading_bot.market_data.recording import content_hash
from trading_bot.research.options_acquisition import build_coverage_manifest
from trading_bot.research.options_acquisition_models import (
    CoverageRequirement,
    CoverageSemantics,
    CoverageWindow,
    StudyCoverageManifest,
    StudyCoverageRequirements,
)
from trading_bot.research.options_shortlist_v2 import (
    VerifiedShortlistResult,
    verified_shortlist_code_hash,
)
from trading_bot.research.options_study_models import OptionsStudySpec, VerifiedHistoryCoverage
from trading_bot.research.options_study_registration import validate_study_registration


def _requirements(
    spec: OptionsStudySpec,
    results: tuple[VerifiedShortlistResult, ...],
) -> tuple[tuple[CoverageRequirement, ...], tuple[str, ...]]:
    items: list[CoverageRequirement] = []
    missing: set[str] = set()
    terms = {content_hash(c): c for c in spec.contracts}
    previous = dict(
        zip(
            (s.session_id for s in spec.decision_sessions),
            spec.initialization_sessions,
            strict=False,
        )
    )

    def semantic(dataset: str | None, schema: str | None, role: str) -> CoverageSemantics | None:
        values = tuple(
            s
            for s in spec.coverage_semantics
            if (dataset is None or s.dataset == dataset)
            and (schema is None or s.schema == schema)
            and (role not in ("reference", "settlement") or s.observation_kind == "reference")
        )
        return values[0] if len(values) == 1 else None

    def add(
        result: VerifiedShortlistResult,
        role: str,
        symbol: str,
        start: int,
        end: int,
        source: CoverageSemantics | None,
    ) -> None:
        ident = f"{result.session_id}:{symbol}:{role}"
        if source is None or start >= end:
            missing.add(ident)
            return
        items.append(
            CoverageRequirement(
                ident,
                role,
                (result.session_id,),
                CoverageWindow(
                    source.dataset,
                    source.schema,
                    symbol,
                    source.stype_in,
                    start,
                    end,
                    (ident,),
                    (result.decision_hash,),
                ),
                source.fact_hash,
                spec.consumer_hash,
                spec.study_hash,
                (),
            )
        )

    for result in results:
        if result.status != "selected":
            missing.add(result.session_id + ":selection")
            continue
        decision = _ns(result.as_of)
        prior = previous.get(result.session_id)
        if prior is None:
            missing.add(result.session_id + ":initialization_calendar")
            continue
        initial = _ns(prior.opens_at)
        for candidate in result.candidates:
            c = terms.get(dict(candidate.selected_input_hashes).get("contract", DataHash("0" * 64)))
            if c is None or c.standardized_id != candidate.standardized_id:
                missing.add(result.session_id + ":" + candidate.standardized_id + ":contract")
                continue
            last, settlement = _ns(c.last_trading_at), _ns(c.settlement_at)
            expiry_sessions = [
                s for s in c.eligible_sessions if s.opens_at < c.last_trading_at <= s.closes_at
            ]
            prior_sessions = [
                s
                for s in c.eligible_sessions
                if expiry_sessions and s.closes_at <= expiry_sessions[-1].opens_at
            ]
            if not prior_sessions or settlement - decision > spec.max_outcome_ns:
                missing.add(
                    result.session_id + ":" + candidate.standardized_id + ":outcome_horizon"
                )
                continue
            quote = semantic("OPRA.PILLAR", "cmbp-1", "entry")
            reference = semantic(None, None, "reference")
            for role, start, end in (
                ("initialization", initial, decision),
                ("entry", decision, decision + 1),
                ("monitoring", decision, last + 1),
                ("exit", _ns(prior_sessions[-1].opens_at), _ns(prior_sessions[-1].closes_at)),
                ("expiry", last, last + 1),
            ):
                add(result, role, c.standardized_id, start, end, quote)
            add(result, "settlement", c.standardized_id, last, settlement + 1, reference)
            add(result, "reference", c.standardized_id, initial, settlement + 1, reference)
            add(
                result,
                "underlying_quotes",
                "SPY",
                initial,
                last + 1,
                semantic("XNAS.ITCH", "mbp-1", "underlying_quotes"),
            )
        add(
            result,
            "warmup",
            "SPY",
            spec.declared_history_start_ns,
            decision,
            semantic("XNAS.ITCH", "ohlcv-1m", "warmup"),
        )
    # Underlying obligations are shared by the paired contracts; their identity
    # remains one requirement and their union covers the longest complete tail.
    unique: dict[str, CoverageRequirement] = {}
    for item in items:
        previous_item = unique.get(item.requirement_id)
        if previous_item is not None:
            from dataclasses import replace

            check(previous_item.role == item.role == "underlying_quotes")
            item = replace(
                item,
                window=replace(
                    item.window,
                    start_ns=min(previous_item.window.start_ns, item.window.start_ns),
                    end_ns=max(previous_item.window.end_ns, item.window.end_ns),
                ),
            )
        unique[item.requirement_id] = item
    return tuple(unique[k] for k in sorted(unique)), tuple(sorted(missing))


def plan_study_coverage(
    spec: OptionsStudySpec,
    *,
    shortlists: tuple[VerifiedShortlistResult, ...],
    history: VerifiedHistoryCoverage,
    loaded: LoadedConfig,
) -> StudyCoverageManifest:
    report = validate_study_registration(
        spec, history=history, loaded=loaded, repository_root=Path(__file__).resolve().parents[3]
    )
    check(type(shortlists) is tuple and all(type(r) is VerifiedShortlistResult for r in shortlists))
    check(len(shortlists) <= loaded.config.options.research_shortlist.max_input_records)
    requirements, missing = _requirements(spec, shortlists)
    declaration = StudyCoverageRequirements(
        spec.study_hash,
        spec.registered_at,
        spec.selection_frozen_at,
        spec.config_hash,
        verified_shortlist_code_hash(),
        "options-historical-study-v1",
        spec.consumer_hash,
        _ns(spec.decision_sessions[0].opens_at),
        _ns(spec.decision_sessions[-1].closes_at),
        tuple(sorted(s.session_id for s in spec.decision_sessions)),
        # Reuse only v1's structural checks/union. V2 independently adds fresh
        # observed-history and split findings below; no v1 qualification is enabled.
        "engineering_pilot",
        "event_age",
        requirements,
        spec.coverage_semantics,
        spec.contracts,
    )
    legacy = build_coverage_manifest(shortlists, requirements=declaration, loaded=loaded)
    reasons = set(legacy.reasons) | set(report.reasons)
    if missing:
        reasons.add("coverage_obligations_incomplete")
    return StudyCoverageManifest(
        status="blocked" if reasons else "requirements_complete",
        sessions=legacy.sessions,
        requests=legacy.requests,
        batches=legacy.batches,
        coverage_links=legacy.coverage_links,
        missing_sessions=legacy.missing_sessions,
        reasons=tuple(sorted(reasons)),
        incomplete_obligations=tuple(sorted(set(legacy.incomplete_obligations) | set(missing))),
        requirements_hash=content_hash(
            {
                "schema": "options-study-coverage-v2",
                "requirements": declaration,
                "history": history.history_hash,
            }
        ),
        research_minimums=legacy.research_minimums,
        study_hash=spec.study_hash,
        history_hash=history.history_hash,
    )
