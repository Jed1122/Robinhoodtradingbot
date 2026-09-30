"""Recompute scoped claims from private bytes; no caller-provided semantic approval."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from trading_bot.config import LoadedConfig
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import DataHash
from trading_bot.market_data.databento_bar_models import native_limits
from trading_bot.market_data.options_source_dispatch import (
    _parse_source_snapshot,
    _read_source_artifact,
)
from trading_bot.market_data.options_source_models import (
    SourceEvidenceBundle,
    SourceFinding,
    SourceInvalidation,
    SourceRole,
    SourceRule,
    SourceVerification,
    VerificationContext,
    check,
    instant,
)
from trading_bot.market_data.options_source_rules import load_reviewed_rules, source_code_hash
from trading_bot.market_data.recording import content_hash


def ceil_available_at(timestamp_ns: int) -> datetime:
    instant(timestamp_ns)
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=(timestamp_ns + 999) // 1000)


def _result(
    context: VerificationContext, bundle: SourceEvidenceBundle, reason: str
) -> SourceVerification:
    roles = sorted({claim.role for claim in bundle.claims}) or ["bar_publication"]
    return SourceVerification(
        context,
        "denied",
        (),
        (),
        (),
        tuple(SourceFinding(role, "denied", (), (reason,)) for role in roles),
        (),
        (reason,),
    )


def _snapshots(
    bundle: SourceEvidenceBundle, loaded: LoadedConfig, repository_root: Path
) -> dict[DataHash, bytes]:
    settings = loaded.config.options.research_shortlist
    check(
        len(bundle.claims) + len(bundle.references) + len(bundle.manifests)
        <= settings.max_input_records
    )
    total = 0
    bodies = {}
    for reference in bundle.references + bundle.manifests:
        total += reference.byte_count
        check(total <= settings.max_input_bytes)
        bodies[reference.sha256] = _read_source_artifact(
            reference, loaded=loaded, repository_root=repository_root
        )
    return bodies


def _verify_with_rules(
    bundle: SourceEvidenceBundle,
    *,
    context: VerificationContext,
    loaded: LoadedConfig,
    repository_root: Path,
    rules: tuple[SourceRule, ...],
) -> SourceVerification:
    """Private deterministic core; only the public wrapper selects installed rules."""
    check(type(bundle) is SourceEvidenceBundle and type(context) is VerificationContext)
    native_limits(loaded)
    check(type(rules) is tuple and all(type(rule) is SourceRule for rule in rules))
    check(len({rule.rule_id for rule in rules}) == len(rules))
    canonical, config_hash = hash_loaded_config(loaded.config, loaded.safety_envelope)
    if (
        loaded.canonical_json != canonical
        or loaded.config_hash != config_hash
        or context.config_hash != config_hash
        or context.code_hash != source_code_hash()
        or context.rulebook_hash != content_hash(rules)
    ):
        return _result(context, bundle, "source_scope_mismatch")
    try:
        bodies = _snapshots(bundle, loaded, repository_root)
    except Exception:
        return _result(context, bundle, "source_integrity_invalid")
    if not bundle.claims:
        return _result(context, bundle, "historical_availability_unverified")
    rules_by_id = {rule.rule_id: rule for rule in rules}
    references = {item.sha256 for item in bundle.references}
    manifests = {item.sha256 for item in bundle.manifests}
    all_records: set[DataHash] = set()
    claim_hashes: set[DataHash] = set()
    invalidations: set[SourceInvalidation] = set()
    role_records: dict[SourceRole, set[DataHash]] = {}
    role_reasons: dict[SourceRole, set[str]] = {}
    for claim in bundle.claims:
        records = role_records.setdefault(claim.role, set())
        denied = role_reasons.setdefault(claim.role, set())
        rule = rules_by_id.get(claim.rule_id)
        if rule is None or claim.published_at_ns is None:
            denied.add("historical_availability_unverified")
            continue
        if (
            (claim.role, claim.source_id, claim.schema, claim.era_start_ns, claim.era_end_ns)
            != (rule.role, rule.source_id, rule.schema, rule.era_start_ns, rule.era_end_ns)
            or not claim.effective_start_ns
            <= context.start_ns
            < context.end_ns
            <= claim.effective_end_ns
            or not set(claim.raw_hashes) <= manifests
        ):
            return _result(context, bundle, "source_scope_mismatch")
        if not set(rule.document_hashes) <= references:
            denied.add("source_reference_unverified")
            continue
        if claim.published_at_ns > context.as_of_ns:
            denied.add("source_future_publication")
            continue
        try:
            parsed = tuple(
                _parse_source_snapshot(
                    claim, rule, bodies[raw_hash], context=context, loaded=loaded
                )
                for raw_hash in claim.raw_hashes
            )
            envelopes = tuple(
                sorted({envelope for facts in parsed for envelope, _ in facts.record_pairs})
            )
            visible = tuple(sorted({fact for facts in parsed for _, fact in facts.record_pairs}))
            for facts in parsed:
                for observation in facts.invalidations:
                    invalidations.add(observation)
                    if observation.affected_hash in visible:
                        since_epoch = observation.discovered_at - datetime(1970, 1, 1, tzinfo=UTC)
                        discovered_ns = (
                            since_epoch.days * 86400 + since_epoch.seconds
                        ) * 10**9 + since_epoch.microseconds * 1000
                        if discovered_ns <= context.as_of_ns:
                            denied.add("source_invalidated")
        except Exception:
            return _result(context, bundle, "source_scope_mismatch")
        if not visible:
            denied.add("historical_availability_unverified")
            continue
        coverage = content_hash(
            {
                "role": claim.role,
                "start_ns": context.start_ns,
                "end_ns": context.end_ns,
                "record_hashes": envelopes,
            }
        )
        if coverage != claim.coverage_hash:
            return _result(context, bundle, "source_scope_mismatch")
        records.update(visible)
        all_records.update(visible)
        causal = asdict(claim)
        del causal["raw_hashes"]
        del causal["observed_at"]
        causal["visible_record_hashes"] = envelopes
        claim_hashes.add(content_hash(causal))
    findings = tuple(
        SourceFinding(
            role,
            "denied" if role_reasons[role] else "verified",
            tuple(sorted(role_records[role])),
            tuple(sorted(role_reasons[role])),
        )
        for role in sorted(role_records)
    )
    reasons = tuple(sorted({reason for finding in findings for reason in finding.reasons}))
    return SourceVerification(
        context,
        "denied" if reasons else "verified",
        tuple(sorted(bodies)),
        tuple(sorted(all_records)),
        tuple(sorted(claim_hashes)),
        findings,
        tuple(
            sorted(
                invalidations,
                key=lambda item: (item.discovered_at, item.affected_hash, item.reason),
            )
        ),
        reasons,
    )


def verify_source_bundle(
    bundle: SourceEvidenceBundle,
    *,
    context: VerificationContext,
    loaded: LoadedConfig,
    repository_root: Path,
) -> SourceVerification:
    return _verify_with_rules(
        bundle,
        context=context,
        loaded=loaded,
        repository_root=repository_root,
        rules=load_reviewed_rules(),
    )
