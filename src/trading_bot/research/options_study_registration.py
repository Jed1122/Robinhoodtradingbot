"""Offline preregistration with reverified observed history and purged split checks."""

import hashlib
import os
from pathlib import Path

from trading_bot.config import LoadedConfig
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import DataHash
from trading_bot.market_data.databento_bar_models import native_limits
from trading_bot.market_data.databento_bar_store import _private_root, _publish_checked
from trading_bot.market_data.options_session_inputs import _fact, _ns
from trading_bot.market_data.options_source_models import SourceEvidenceError, check
from trading_bot.market_data.options_source_verify import verify_source_bundle
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.options_study_models import (
    OptionsStudySpec,
    StudyRegistrationReport,
    VerifiedHistoryCoverage,
)

DAY_NS = 86400 * 10**9


def study_code_hash() -> DataHash:
    """Installed source identity, including later consumer additions; not a git assertion."""
    root = Path(__file__).resolve().parents[1]
    return content_hash(
        tuple(
            (str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest())
            for path in sorted(root.rglob("*.py"))
        )
    )


def study_consumer_hash() -> DataHash:
    return content_hash({"consumer": "options-historical-study-v1", "code_hash": study_code_hash()})


def study_settings(loaded: LoadedConfig) -> None:
    native_limits(loaded)
    canonical, digest = hash_loaded_config(loaded.config, loaded.safety_envelope)
    check(canonical == loaded.canonical_json and digest == loaded.config_hash)
    check(loaded.config.options.research_study.enabled)


def _splits_valid(spec: OptionsStudySpec, loaded: LoadedConfig) -> bool:
    research = loaded.config.research
    sessions = {s.session_id: s for s in spec.decision_sessions}
    if (
        len(spec.folds) < research.walk_forward_folds
        or spec.embargo_ns < spec.max_outcome_ns
        or min(spec.block_lengths_ns) < spec.max_outcome_ns
    ):
        return False
    tests: set[str] = set()
    previous_end = 0
    for fold in spec.folds:
        train, test = fold.train_session_ids, fold.test_session_ids
        if (
            len(test) < research.minimum_test_bars_per_fold
            or set(train) & set(test)
            or set(test) & tests
            or (set(train) | set(test)) - sessions.keys()
        ):
            return False
        for ids in (train, test):
            if tuple(sorted(ids, key=lambda ident: sessions[ident].opens_at)) != ids:
                return False
        first_test = _ns(sessions[test[0]].opens_at)
        # Purge the entire modeled obligation horizon, not merely the entry date.
        if (
            _ns(sessions[train[-1]].closes_at) + spec.max_outcome_ns + spec.embargo_ns > first_test
            or previous_end + spec.embargo_ns > first_test
        ):
            return False
        previous_end = _ns(sessions[test[-1]].closes_at) + spec.max_outcome_ns
        tests.update(test)
    final = spec.final_session_ids
    if (
        len(final) < research.minimum_test_bars_per_fold
        or set(final) - sessions.keys()
        or set(final) & {i for f in spec.folds for i in (*f.train_session_ids, *f.test_session_ids)}
    ):
        return False
    if tuple(sorted(final, key=lambda ident: sessions[ident].opens_at)) != final:
        return False
    return previous_end + spec.embargo_ns <= _ns(sessions[final[0]].opens_at)


def validate_study_registration(
    spec: OptionsStudySpec,
    *,
    history: VerifiedHistoryCoverage,
    loaded: LoadedConfig,
    repository_root: Path,
) -> StudyRegistrationReport:
    study_settings(loaded)
    check(type(spec) is OptionsStudySpec and type(history) is VerifiedHistoryCoverage)
    limit = loaded.config.options.research_shortlist
    check(len(canonical_json((spec, history.observations)).encode()) <= limit.max_input_bytes)
    check(
        len(spec.decision_sessions)
        + len(history.observations)
        + sum(len(f.train_session_ids) + len(f.test_session_ids) for f in spec.folds)
        <= limit.max_input_records
    )
    reasons: set[str] = set()
    if (
        spec.config_hash != loaded.config_hash
        or spec.code_hash != study_code_hash()
        or spec.consumer_hash != study_consumer_hash()
        or spec.history_hash != history.history_hash
        or spec.exit_policy != loaded.config.options.research_study.exit_policy
        or spec.shortlist_version != loaded.config.options.research_shortlist.version
    ):
        reasons.add("study_identity_mismatch")
    if spec.registered_at > spec.selection_frozen_at or (
        spec.outcome_access_started_at is not None
        and spec.selection_frozen_at >= spec.outcome_access_started_at
    ):
        reasons.add("preregistration_late")
    verified = verify_source_bundle(
        history.source_bundle,
        context=history.context,
        loaded=loaded,
        repository_root=repository_root,
    )
    calendar = {
        "kind": "history-calendar-v1",
        "start_ns": history.start_ns,
        "end_ns": history.end_ns,
        "sessions": history.sessions,
    }
    history_ok = (
        verified.status == "verified"
        and _fact(verified, "calendar", calendar)
        and history.actions_coverage_hash in verified.record_hashes
        and any(
            f.role == "actions"
            and f.status == "verified"
            and history.actions_coverage_hash in f.visible_hashes
            for f in verified.findings
        )
        and all(
            _fact(
                verified,
                "bar_publication",
                {
                    "kind": "study-daily-bar-v1",
                    "observation": o,
                },
            )
            for o in history.observations
        )
    )
    if not history_ok:
        reasons.add("study_history_unverified")
    if (
        not _fact(
            verified,
            "calendar",
            {"kind": "study-decision-calendar-v1", "sessions": spec.decision_sessions},
        )
        or spec.source_hashes != verified.source_hashes
        or not any(
            f.role == "quote_semantics"
            and f.status == "verified"
            and spec.availability_hash in f.visible_hashes
            for f in verified.findings
        )
    ):
        reasons.add("study_availability_unverified")
    if spec.initialization_sessions and not _fact(
        verified,
        "calendar",
        {
            "kind": "study-initialization-calendar-v1",
            "sessions": spec.initialization_sessions,
        },
    ):
        reasons.add("study_availability_unverified")
    first = _ns(spec.decision_sessions[0].opens_at)
    count = len(history.observations) if history_ok else 0
    days = (history.end_ns - history.start_ns) // DAY_NS if history_ok else 0
    research = loaded.config.research
    if (
        count < research.minimum_history_bars
        or days < research.history_calendar_days
        or history.end_ns != first
        or spec.declared_history_start_ns != history.start_ns
        or (first - spec.declared_history_start_ns) // DAY_NS < research.history_calendar_days
    ):
        reasons.add("research_history_insufficient")
    if not _splits_valid(spec, loaded):
        reasons.add("study_splits_invalid")
    genuine = history_ok and all(
        not c.source_id.startswith("synthetic.") for c in history.source_bundle.claims
    )
    return StudyRegistrationReport(
        spec.study_hash, history.history_hash, count, days, genuine, tuple(sorted(reasons))
    )


def freeze_options_study(
    spec: OptionsStudySpec,
    *,
    history: VerifiedHistoryCoverage,
    loaded: LoadedConfig,
    output_root: Path,
    repository_root: Path,
) -> DataHash:
    """Immutable declaration, not proof that outside callers never inspected outcomes.

    The study consumer must additionally enforce a freeze-before-open journal. Known
    late registration denies here; absence of an access timestamp is not a certificate.
    """
    from trading_bot.research.options_study_wire import encode_study_spec

    try:
        report = validate_study_registration(
            spec, history=history, loaded=loaded, repository_root=repository_root
        )
        allowed = {"research_history_insufficient", "study_splits_invalid"}
        check(
            not report.reasons
            or (spec.purpose == "engineering_pilot" and set(report.reasons) <= allowed)
        )
        parent = _private_root(output_root, repository_root)
        try:
            _publish_checked(parent, spec.study_hash + ".json", encode_study_spec(spec))
        finally:
            os.close(parent)
        return spec.study_hash
    except Exception:
        raise SourceEvidenceError() from None
