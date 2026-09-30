"""Immutable study contracts; all source/calendar/bar evidence here is fabricated."""

import importlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.config import load_config
from trading_bot.domain import Bar
from trading_bot.domain.enums import BarInterval
from trading_bot.domain.options import OptionSession
from trading_bot.market_data.options_session_inputs import _ns
from trading_bot.market_data.options_source_models import SourceEvidenceError, SourceRule
from trading_bot.market_data.recording import content_hash


def api(name="registration"):
    try:
        return importlib.import_module("trading_bot.research.options_study_" + name)
    except ModuleNotFoundError:
        pytest.fail("options study registration is not implemented")


def config():
    from tests.unit.market_data._options_source_fixtures import ROOT

    return load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/options/study/simulation.yaml",
        ROOT / "configs/safety-envelope.yaml",
        {},
    )


def session(day):
    opens = datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=15)
    return OptionSession(
        "fixture-" + day.isoformat(), opens, opens + timedelta(hours=5), day, "America/New_York"
    )


def arrangement(tmp_path, monkeypatch, count=750, *, action_changes=None, retained_actions=()):
    import trading_bot.market_data.options_source_verify as verifier
    from tests.unit.market_data import _options_source_fixtures as fixtures

    models = api("models")
    registration = api()
    loaded = config()
    monkeypatch.setattr(fixtures, "config", config)
    # An intentionally irregular synthetic calendar spanning ten years. It is not
    # an assertion about actual SPY sessions or missing provider observations.
    first = date(2010, 1, 1)
    sessions = tuple(session(first + timedelta(days=5 * i)) for i in range(count))
    decision_first = date(2021, 1, 1)
    decisions = tuple(session(decision_first + timedelta(days=i)) for i in range(610))
    observations = tuple(
        models.HistoryObservation(
            Bar(
                "SPY",
                BarInterval.ONE_DAY,
                s.opens_at,
                s.closes_at,
                Decimal("100"),
                Decimal("101"),
                Decimal("99"),
                Decimal("100"),
                Decimal("1000"),
                "synthetic.history",
                content_hash(("native-bar", s.session_id)),
            ),
            s.closes_at + timedelta(microseconds=1),
            s,
            (content_hash(("native", s.session_id)),),
        )
        for s in sessions
    )
    start_ns = _ns(sessions[0].opens_at)
    end_ns = _ns(decisions[0].opens_at)
    actions = {
        "kind": "history-actions-v1",
        "underlying": "SPY",
        "start_ns": start_ns,
        "end_ns": end_ns,
        "adjustment": "unadjusted",
        "actions": retained_actions,
    }
    actions.update(action_changes or {})
    availability = {"kind": "study-availability-v1", "sessions": decisions}
    bundle, verified = fixtures.verified_facts(
        tmp_path / "sources",
        {
            "bar_publication": [
                {"kind": "study-daily-bar-v1", "observation": o} for o in observations
            ],
            "calendar": [
                {
                    "kind": "history-calendar-v1",
                    "start_ns": start_ns,
                    "end_ns": end_ns,
                    "sessions": sessions,
                },
                {"kind": "study-decision-calendar-v1", "sessions": decisions},
            ],
            "actions": [actions],
            "quote_semantics": [availability],
        },
        start_ns=start_ns,
        end_ns=end_ns,
        as_of_ns=end_ns,
    )
    rules = tuple(
        SourceRule(
            c.rule_id,
            c.role,
            c.source_id,
            c.schema,
            c.era_start_ns,
            c.era_end_ns,
            (bundle.references[0].sha256,),
            "synthetic-records-v1",
        )
        for c in bundle.claims
    )
    monkeypatch.setattr(verifier, "load_reviewed_rules", lambda: rules)
    history = models.VerifiedHistoryCoverage(
        observations,
        sessions,
        start_ns,
        end_ns,
        content_hash(actions),
        bundle,
        verified.context,
        actions=retained_actions,
        visible_claim_hashes=verified.visible_claim_hashes,
    )
    folds = tuple(
        models.StudyFold(
            "fold-" + str(i),
            tuple(s.session_id for s in decisions[: 50 + i * 100]),
            tuple(s.session_id for s in decisions[70 + i * 100 : 120 + i * 100]),
        )
        for i in range(5)
    )
    spec = models.OptionsStudySpec(
        purpose="qualification",
        registered_at=datetime(2026, 9, 29, 15, tzinfo=UTC),
        selection_frozen_at=datetime(2026, 9, 29, 16, tzinfo=UTC),
        outcome_access_started_at=None,
        decision_sessions=decisions,
        declared_history_start_ns=start_ns,
        history_hash=history.history_hash,
        source_hashes=verified.source_hashes,
        availability_hash=content_hash(availability),
        config_hash=loaded.config_hash,
        code_hash=registration.study_code_hash(),
        consumer_hash=registration.study_consumer_hash(),
        hypothesis="unvalidated-momentum-20-100-v1",
        shortlist_version="spy-prior-close-atm-30d-v1",
        exit_policy="signal_invalidation_or_prior_session_expiry",
        scenario_hashes=tuple(
            (name, content_hash(name)) for name in ("base", "conservative", "optimistic")
        ),
        cost_hash=content_hash("explicit-fabricated-costs"),
        capital_tiers=tuple(Decimal(n) for n in (100, 500, 1000, 2500, 5000, 10000, 25000, 50000)),
        folds=folds,
        final_session_ids=tuple(s.session_id for s in decisions[560:610]),
        embargo_ns=10 * 86400 * 10**9,
        max_outcome_ns=5 * 86400 * 10**9,
        block_lengths_ns=(5 * 86400 * 10**9, 10 * 86400 * 10**9),
        bootstrap_seed=17,
        execution_seed=23,
        rejection_criteria=(
            "after_cost_lower_bound_positive",
            "canonical_research_minimums",
            "full_policy_feasible",
            "genuine_sources",
            "no_censored_obligations",
        ),
        contracts=(),
        coverage_semantics=(),
        initialization_sessions=(),
    )
    return spec, history, loaded


def report(spec, history, loaded):
    from tests.unit.market_data._options_source_fixtures import ROOT

    return api().validate_study_registration(
        spec, history=history, loaded=loaded, repository_root=ROOT
    )


@pytest.mark.parametrize("count,expected", [(749, True), (750, False)])
def test_counts_observed_daily_bars_not_declared_sessions(tmp_path, monkeypatch, count, expected):
    spec, history, loaded = arrangement(tmp_path, monkeypatch, count)
    result = report(spec, history, loaded)
    assert ("research_history_insufficient" in result.reasons) is expected
    assert result.observed_daily_bars == count
    assert result.production_eligible is False and result.economic_eligible is False


def test_insufficient_and_overlapping_folds_deny(tmp_path, monkeypatch):
    spec, history, loaded = arrangement(tmp_path, monkeypatch)
    assert (
        "study_splits_invalid"
        in report(replace(spec, folds=spec.folds[:4]), history, loaded).reasons
    )
    bad = replace(spec.folds[0], test_session_ids=spec.folds[0].train_session_ids)
    assert (
        "study_splits_invalid"
        in report(replace(spec, folds=(bad, *spec.folds[1:])), history, loaded).reasons
    )


def test_duplicate_observations_and_overlap_do_not_increase_history(tmp_path, monkeypatch):
    _, history, _ = arrangement(tmp_path, monkeypatch)
    with pytest.raises(SourceEvidenceError):
        replace(history, observations=(*history.observations, history.observations[0]))
    with pytest.raises(SourceEvidenceError):
        replace(history, sessions=(*history.sessions, history.sessions[0]))


def test_shortened_declared_history_denies(tmp_path, monkeypatch):
    spec, history, loaded = arrangement(tmp_path, monkeypatch)
    changed = replace(spec, declared_history_start_ns=history.end_ns - 365 * 86400 * 10**9)
    assert "research_history_insufficient" in report(changed, history, loaded).reasons


def test_changed_consumer_or_missing_availability_denies(tmp_path, monkeypatch):
    spec, history, loaded = arrangement(tmp_path, monkeypatch)
    assert (
        "study_identity_mismatch"
        in report(replace(spec, consumer_hash="f" * 64), history, loaded).reasons
    )
    assert (
        "study_availability_unverified"
        in report(replace(spec, availability_hash="f" * 64), history, loaded).reasons
    )


def test_holdout_is_distinct_and_changes_registration_identity(tmp_path, monkeypatch):
    spec, history, loaded = arrangement(tmp_path, monkeypatch)
    bad = replace(spec, final_session_ids=spec.folds[-1].test_session_ids)
    assert bad.study_hash != spec.study_hash
    assert "study_splits_invalid" in report(bad, history, loaded).reasons


def test_late_registration_and_short_embargo_deny(tmp_path, monkeypatch):
    spec, history, loaded = arrangement(tmp_path, monkeypatch)
    late = replace(spec, outcome_access_started_at=spec.registered_at - timedelta(seconds=1))
    assert "preregistration_late" in report(late, history, loaded).reasons
    assert "study_splits_invalid" in report(replace(spec, embargo_ns=1), history, loaded).reasons


def test_freeze_is_private_immutable_and_rechecks_input_bytes(tmp_path, monkeypatch):
    from tests.unit.market_data._options_source_fixtures import ROOT

    spec, history, loaded = arrangement(tmp_path, monkeypatch)
    spec = replace(spec, purpose="engineering_pilot")
    output = tmp_path / "registered"
    output.mkdir(mode=0o700)
    freeze = api().freeze_options_study
    assert report(spec, history, loaded).reasons == ()
    identity = freeze(
        spec, history=history, loaded=loaded, output_root=output, repository_root=ROOT
    )
    assert identity == spec.study_hash
    assert (
        freeze(spec, history=history, loaded=loaded, output_root=output, repository_root=ROOT)
        == identity
    )
    target = output / (identity + ".json")
    assert target.stat().st_mode & 0o777 == 0o600
    assert api("wire").decode_study_spec(target.read_bytes(), loaded=loaded) == spec
    history.source_bundle.manifests[0].path.write_bytes(b"replaced")
    with pytest.raises(SourceEvidenceError):
        freeze(spec, history=history, loaded=loaded, output_root=output, repository_root=ROOT)


def test_pilot_is_not_silently_promoted(tmp_path, monkeypatch):
    spec, history, loaded = arrangement(tmp_path, monkeypatch, 749)
    result = report(replace(spec, purpose="engineering_pilot"), history, loaded)
    assert "research_history_insufficient" in result.reasons
    assert result.economic_eligible is False


def test_synthetic_history_cannot_freeze_a_qualification_study(tmp_path, monkeypatch):
    from tests.unit.market_data._options_source_fixtures import ROOT

    spec, history, loaded = arrangement(tmp_path, monkeypatch)
    result = report(spec, history, loaded)
    assert result.genuine_sources is False
    assert "study_sources_not_genuine" in result.reasons
    output = tmp_path / "disallowed"
    output.mkdir(mode=0o700)
    with pytest.raises(SourceEvidenceError):
        api().freeze_options_study(
            spec, history=history, loaded=loaded, output_root=output, repository_root=ROOT
        )
    assert not tuple(output.iterdir())


@pytest.mark.parametrize(
    "changes",
    [
        {"underlying": "AAPL"},
        {"start_ns": 1},
        {"end_ns": 2**63 - 1},
        {"adjustment": "split_adjusted"},
        {"kind": "unrelated-action-fact"},
    ],
)
def test_unrelated_verified_action_fact_cannot_establish_history(tmp_path, monkeypatch, changes):
    spec, history, loaded = arrangement(tmp_path, monkeypatch, action_changes=changes)
    result = report(spec, history, loaded)
    assert "study_history_unverified" in result.reasons
    assert result.observed_daily_bars == 0


def test_changed_valid_claim_scope_cannot_reuse_frozen_history(tmp_path, monkeypatch):
    from tests.unit.market_data._options_source_fixtures import ROOT
    from trading_bot.market_data.options_source_verify import verify_source_bundle

    spec, history, loaded = arrangement(tmp_path, monkeypatch)
    bundle = history.source_bundle
    changed_bundle = replace(
        bundle,
        claims=(
            replace(bundle.claims[0], effective_start_ns=history.start_ns - 1),
            *bundle.claims[1:],
        ),
    )
    verified = verify_source_bundle(
        changed_bundle, context=history.context, loaded=loaded, repository_root=ROOT
    )
    assert verified.status == "verified"  # Same bytes still satisfy the changed, wider claim.
    changed = replace(history, source_bundle=changed_bundle)
    assert "study_history_unverified" in report(spec, changed, loaded).reasons
    rebound = replace(changed, visible_claim_hashes=verified.visible_claim_hashes)
    assert rebound.history_hash != history.history_hash
    assert "study_identity_mismatch" in report(spec, rebound, loaded).reasons


def test_verified_dividend_cannot_be_omitted_from_history_preimage(tmp_path, monkeypatch):
    from trading_bot.domain import CorporateAction
    from trading_bot.research.options_shortlist_models import ShortlistAction

    action = ShortlistAction(
        CorporateAction(
            "SPY",
            "dividend",
            date(2019, 1, 3),
            datetime(2019, 1, 1, tzinfo=UTC),
            None,
            Decimal("1.00"),
            content_hash("fixture-dividend"),
        ),
        datetime(2019, 1, 1, tzinfo=UTC),
    )
    spec, history, loaded = arrangement(tmp_path, monkeypatch, retained_actions=(action,))
    assert "study_history_unverified" not in report(spec, history, loaded).reasons
    omitted = replace(history, actions=())
    assert omitted.history_hash != history.history_hash
    # Updating the declared hash alone still cannot change source-established facts.
    altered_spec = replace(spec, history_hash=omitted.history_hash)
    assert "study_history_unverified" in report(altered_spec, omitted, loaded).reasons


def test_unreviewed_source_rules_remain_denied(tmp_path, monkeypatch):
    spec, history, loaded = arrangement(tmp_path, monkeypatch)
    import trading_bot.market_data.options_source_verify as verifier

    monkeypatch.setattr(verifier, "load_reviewed_rules", lambda: ())
    result = report(spec, history, loaded)
    assert "study_history_unverified" in result.reasons


def test_v2_missing_selections_preserves_each_missing_session(tmp_path, monkeypatch):
    spec, history, loaded = arrangement(tmp_path, monkeypatch)
    from trading_bot.research import options_acquisition

    value = options_acquisition.plan_options_study_coverage(
        spec,
        shortlists=(),
        history=history,
        loaded=loaded,
    )
    assert value.schema == "options-acquisition-manifest-v2"
    assert set(value.missing_sessions) == {s.session_id for s in spec.decision_sessions}
    assert "selection_sessions_incomplete" in value.reasons
    assert "study_sources_not_genuine" in value.reasons
    assert value.download_authorized is False and value.economic_eligible is False


def test_v2_does_not_erase_history_or_consumer_denials(tmp_path, monkeypatch):
    spec, history, loaded = arrangement(tmp_path, monkeypatch, 749)
    from trading_bot.research import options_acquisition

    value = options_acquisition.plan_options_study_coverage(
        replace(spec, consumer_hash="f" * 64),
        shortlists=(),
        history=history,
        loaded=loaded,
    )
    assert "research_history_insufficient" in value.reasons
    assert "study_identity_mismatch" in value.reasons


def coverage_case(tmp_path, monkeypatch):
    from tests.unit.domain.test_options import contract
    from tests.unit.market_data._options_source_fixtures import ROOT
    from trading_bot.domain.options import OptionKind
    from trading_bot.market_data.options_source_models import SourceFinding
    from trading_bot.market_data.options_source_verify import verify_source_bundle
    from trading_bot.research.options_acquisition_models import CoverageSemantics
    from trading_bot.research.options_shortlist_models import OptionsShortlistCandidate
    from trading_bot.research.options_shortlist_v2 import (
        VerifiedShortlistResult,
        verified_shortlist_code_hash,
    )

    spec, history, loaded = arrangement(tmp_path, monkeypatch)
    decision = spec.decision_sessions[0]
    expiry = spec.decision_sessions[30]
    contracts = tuple(
        contract(
            contract_id="fixture-" + kind.value,
            standardized_id="SPY   210131" + letter + "00100000",
            underlying="SPY",
            deliverable_symbol="SPY",
            kind=kind,
            expiration=expiry.trading_date,
            last_trading_at=expiry.closes_at,
            settlement_at=expiry.closes_at + timedelta(days=2),
            available_at=decision.opens_at - timedelta(days=1),
            eligible_sessions=spec.decision_sessions[:31],
        )
        for kind, letter in ((OptionKind.CALL, "C"), (OptionKind.PUT, "P"))
    )
    semantics = tuple(
        CoverageSemantics(
            dataset,
            schema,
            "raw_symbol",
            1,
            2**63 - 1,
            observation,
            initialization,
            "options-historical-study-v1",
            spec.consumer_hash,
        )
        for dataset, schema, observation, initialization in (
            ("OPRA.PILLAR", "cmbp-1", "event_quote", "snapshot_and_updates"),
            ("XNAS.ITCH", "mbp-1", "event_quote", "snapshot_and_updates"),
            ("XNAS.ITCH", "ohlcv-1m", "trade_bar", "not_applicable"),
            ("SYNTHETIC.REFERENCE", "settlement", "reference", "not_applicable"),
        )
    )
    spec = replace(
        spec,
        contracts=contracts,
        coverage_semantics=semantics,
        initialization_sessions=tuple(
            session(s.trading_date - timedelta(days=1)) for s in spec.decision_sessions
        ),
        max_outcome_ns=45 * 86400 * 10**9,
    )
    verified = verify_source_bundle(
        history.source_bundle, context=history.context, loaded=loaded, repository_root=ROOT
    )
    # Fake upstream verification solely to test pure coverage composition, as in
    # the legacy planner suite; never installed as an actual provider rule.
    semantic_hashes = tuple(sorted(s.fact_hash for s in semantics))
    verified = replace(
        verified,
        findings=(
            *(f for f in verified.findings if f.role != "quote_semantics"),
            SourceFinding("quote_semantics", "verified", semantic_hashes, ()),
        ),
        record_hashes=tuple(sorted(set(verified.record_hashes) | set(semantic_hashes))),
    )
    candidates = tuple(
        OptionsShortlistCandidate(
            decision.session_id,
            decision.opens_at,
            c.kind,
            c.contract_id,
            c.standardized_id,
            c.expiration,
            c.strike,
            history.observations[-1].bar.data_hash,
            (("contract", content_hash(c)),),
        )
        for c in contracts
    )
    result = VerifiedShortlistResult(
        "selected",
        candidates,
        (),
        content_hash("fixture-selection"),
        content_hash("fixture-input"),
        verified,
        decision.session_id,
        decision.opens_at,
        loaded.config_hash,
        verified_shortlist_code_hash(),
        1,
    )
    return spec, history, loaded, result


def test_v2_derives_both_full_contract_tails_and_keeps_missing_sessions(tmp_path, monkeypatch):
    from trading_bot.research.options_acquisition import plan_options_study_coverage

    spec, history, loaded, selected = coverage_case(tmp_path, monkeypatch)
    value = plan_options_study_coverage(
        spec, shortlists=(selected,), history=history, loaded=loaded
    )
    assert value.status == "blocked" and len(value.missing_sessions) == 609
    quotes = [r for r in value.requests if r.schema == "cmbp-1"]
    assert {r.symbol for r in quotes} == {c.standardized_id for c in spec.contracts}
    for item in quotes:
        assert item.start_ns == _ns(spec.initialization_sessions[0].opens_at)
        assert item.end_ns == _ns(spec.contracts[0].last_trading_at) + 1
        assert {p.rsplit(":", 1)[1] for p in item.requirement_ids} == {
            "initialization",
            "entry",
            "monitoring",
            "exit",
            "expiry",
        }
    references = [r for r in value.requests if r.dataset == "SYNTHETIC.REFERENCE"]
    assert len(references) == 2
    assert all(r.end_ns == _ns(spec.contracts[0].settlement_at) + 1 for r in references)
    assert value.sessions[0].candidates == selected.candidates


def test_v2_duplicate_coverage_and_unbounded_outcome_do_not_pass(tmp_path, monkeypatch):
    from trading_bot.research.options_acquisition import plan_options_study_coverage

    spec, history, loaded, selected = coverage_case(tmp_path, monkeypatch)
    with pytest.raises(SourceEvidenceError):
        replace(spec, coverage_semantics=(*spec.coverage_semantics, spec.coverage_semantics[0]))
    with pytest.raises(SourceEvidenceError):
        plan_options_study_coverage(
            spec, shortlists=(selected, selected), history=history, loaded=loaded
        )
    short = replace(spec, max_outcome_ns=1)
    value = plan_options_study_coverage(
        short, shortlists=(selected,), history=history, loaded=loaded
    )
    assert any(s.endswith(":outcome_horizon") for s in value.incomplete_obligations)


def test_initialization_calendar_requires_its_own_source_fact(tmp_path, monkeypatch):
    spec, history, loaded, _ = coverage_case(tmp_path, monkeypatch)
    assert "study_availability_unverified" in report(spec, history, loaded).reasons


@pytest.mark.parametrize("mutation", ["schema", "hash", "unknown", "capital", "seed"])
def test_wire_rejects_changed_or_ambiguous_study(tmp_path, monkeypatch, mutation):
    import json

    from trading_bot.market_data.recording import canonical_json

    spec, _, loaded = arrangement(tmp_path, monkeypatch)
    wire = api("wire")
    value = json.loads(wire.encode_study_spec(spec))
    if mutation == "schema":
        value["schema"] = "options-study-v2"
    elif mutation == "hash":
        value["study_hash"] = "f" * 64
    elif mutation == "unknown":
        value["live_authorized"] = True
    elif mutation == "capital":
        value["capital_tiers"] = [100]
    else:
        value["bootstrap_seed"] = True
    with pytest.raises(SourceEvidenceError):
        wire.decode_study_spec(canonical_json(value).encode(), loaded=loaded)
