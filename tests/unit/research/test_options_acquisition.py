"""Synthetic planning only. No data transport, quotes, prices or purchase capability."""

import importlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.unit.market_data._options_source_fixtures import ROOT, config
from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from tests.unit.research.test_options_shortlist_v2 import arrangement, install_fixture_rules, run
from trading_bot.domain import DataHash
from trading_bot.domain.options import OptionContract
from trading_bot.market_data.options_definition_inputs import assemble_definition_inputs
from trading_bot.market_data.options_session_inputs import _ns
from trading_bot.market_data.options_source_models import SourceFinding, SourceInvalidation
from trading_bot.market_data.recording import content_hash


def api(name=""):
    try:
        return importlib.import_module("trading_bot.research.options_acquisition" + name)
    except ModuleNotFoundError:
        pytest.fail("complete quote coverage planning is not implemented")


def fixture_case(tmp_path, monkeypatch):
    models = api("_models")
    value = arrangement(tmp_path)
    install_fixture_rules(monkeypatch, value)
    result = run(value)
    assert result.status == "selected"
    definitions = assemble_definition_inputs(
        value.request.definitions.path,
        value.request.contracts,
        verification=result.verification,
        as_of=result.as_of,
        loaded=config(),
        repository_root=ROOT,
    )
    contracts = tuple(
        r.value
        for r in definitions.records
        if type(r.value) is OptionContract
        and r.value.contract_id in {c.contract_id for c in result.candidates}
    )
    consumer = content_hash("fabricated-event-consumer-v1")
    prereg = content_hash("fabricated-preregistration-v1")
    decision = _ns(result.as_of)
    last = max(_ns(c.last_trading_at) for c in contracts)
    settlement = max(_ns(c.settlement_at) for c in contracts)
    semantics = tuple(
        models.CoverageSemantics(
            dataset,
            schema,
            "raw_symbol",
            1,
            2**63 - 1,
            kind,
            initialization,
            "synthetic-consumer",
            consumer,
        )
        for dataset, schema, kind, initialization in (
            ("OPRA.PILLAR", "cmbp-1", "event_quote", "snapshot_and_updates"),
            ("XNAS.ITCH", "mbp-1", "event_quote", "snapshot_and_updates"),
            ("XNAS.ITCH", "ohlcv-1m", "trade_bar", "not_applicable"),
            ("SYNTHETIC.REFERENCE", "settlement", "reference", "not_applicable"),
        )
    )
    fact_hashes = tuple(sorted(s.fact_hash for s in semantics))
    verification = replace(
        result.verification,
        findings=(
            *result.verification.findings,
            SourceFinding("quote_semantics", "verified", fact_hashes, ()),
        ),
        record_hashes=tuple(sorted(set(result.verification.record_hashes) | set(fact_hashes))),
    )
    result = replace(result, verification=verification)
    requirements = []

    def add(role, symbol, start, end, semantic):
        ident = f"{role}-{len(requirements)}"
        window = models.CoverageWindow(
            semantic.dataset,
            semantic.schema,
            symbol,
            "raw_symbol",
            start,
            end,
            (ident,),
            (result.decision_hash,),
        )
        requirements.append(
            models.CoverageRequirement(
                ident, role, (result.session_id,), window, semantic.fact_hash, consumer, prereg, ()
            )
        )

    for candidate in result.candidates:
        add("initialization", candidate.standardized_id, decision - 1000, decision, semantics[0])
        add("entry", candidate.standardized_id, decision, decision + 1000, semantics[0])
        add("monitoring", candidate.standardized_id, decision, last + 1, semantics[0])
        add("exit", candidate.standardized_id, last - 1000, last + 1, semantics[0])
        add("expiry", candidate.standardized_id, last, last + 1, semantics[0])
        add("settlement", candidate.standardized_id, last, settlement + 1, semantics[3])
    add("underlying_quotes", "SPY", decision - 1000, last + 1, semantics[1])
    add("warmup", "SPY", decision - 3650 * 86400 * 10**9, decision, semantics[2])
    study = models.StudyCoverageRequirements(
        prereg,
        datetime(2026, 9, 25, tzinfo=UTC),
        datetime(2026, 9, 27, tzinfo=UTC),
        result.config_hash,
        result.code_hash,
        "synthetic-consumer",
        consumer,
        decision,
        decision + 1,
        (result.session_id,),
        "engineering_pilot",
        "event_age",
        tuple(requirements),
        semantics,
        contracts,
    )
    return SimpleNamespace(
        results=(result,), study=study, decision=decision, last=last, settlement=settlement
    )


def build(value, **changes):
    study = replace(value.study, **changes) if changes else value.study
    return api().build_coverage_manifest(value.results, requirements=study, loaded=config())


def test_missing_preregistration_cannot_create_purchase_ready_list(tmp_path, monkeypatch):
    value = fixture_case(tmp_path, monkeypatch)
    result = api().build_coverage_manifest(value.results, requirements=None, loaded=config())
    assert result.status == "blocked" and result.reasons == ("coverage_requirements_missing",)
    assert not result.download_authorized and not result.live_authorized
    assert result.sessions[0].candidates == value.results[0].candidates


def test_complete_pilot_manifest_is_neither_economic_nor_purchase_authorization(
    tmp_path, monkeypatch
):
    result = build(fixture_case(tmp_path, monkeypatch))
    assert result.status == "requirements_complete", result.reasons
    assert not result.reasons and not result.incomplete_obligations
    assert not any(
        (
            result.production_eligible,
            result.evidence_promotable,
            result.download_authorized,
            result.live_authorized,
            result.economic_eligible,
        )
    )
    assert (
        len(result.requests) == 6
    )  # two option streams, two settlement refs, bars, underlying quotes


@pytest.mark.parametrize(
    "role",
    [
        "initialization",
        "entry",
        "monitoring",
        "exit",
        "expiry",
        "settlement",
        "underlying_quotes",
        "warmup",
    ],
)
def test_missing_any_required_phase_blocks_complete_coverage(tmp_path, monkeypatch, role):
    value = fixture_case(tmp_path, monkeypatch)
    result = build(value, requirements=tuple(r for r in value.study.requirements if r.role != role))
    assert result.status == "blocked" and result.incomplete_obligations


def test_one_missing_side_is_not_replaced_or_removed(tmp_path, monkeypatch):
    value = fixture_case(tmp_path, monkeypatch)
    symbol = value.results[0].candidates[0].standardized_id
    result = build(
        value, requirements=tuple(r for r in value.study.requirements if r.window.symbol != symbol)
    )
    assert result.status == "blocked" and len(result.sessions[0].candidates) == 2


def test_unavailable_selected_contract_and_missing_tail_remain_explicit(tmp_path, monkeypatch):
    value = fixture_case(tmp_path, monkeypatch)
    changed = list(value.study.requirements)
    tail = changed[5]
    changed[5] = replace(
        tail, missing_dependencies=("native-definitions-tail", "settlement-reference")
    )
    result = build(value, requirements=tuple(changed))
    assert result.status == "blocked"
    assert result.incomplete_obligations == ("native-definitions-tail", "settlement-reference")
    assert max(r.end_ns for r in result.requests) == value.settlement + 1
    assert result.sessions[0].candidates == value.results[0].candidates


@pytest.mark.parametrize(
    "field", ["config_hash", "shortlist_code_hash", "preregistration_hash", "consumer_hash"]
)
def test_identity_mismatch_blocks(tmp_path, monkeypatch, field):
    value = fixture_case(tmp_path, monkeypatch)
    result = build(value, **{field: DataHash("0" * 64)})
    assert result.status == "blocked" and "coverage_identity_mismatch" in result.reasons


def test_requirements_registered_after_selection_freeze_are_rejected(tmp_path, monkeypatch):
    value = fixture_case(tmp_path, monkeypatch)
    result = build(
        value, preregistered_at=value.study.selection_frozen_at + timedelta(microseconds=1)
    )
    assert result.status == "blocked" and "preregistration_late" in result.reasons


def test_missing_session_and_denied_session_are_preserved(tmp_path, monkeypatch):
    value = fixture_case(tmp_path, monkeypatch)
    result = build(value, session_ids=tuple(sorted((*value.study.session_ids, "missing-session"))))
    assert result.status == "blocked" and result.missing_sessions == ("missing-session",)
    denied = replace(
        value.results[0], status="no_candidate", candidates=(), reasons=("chain_unavailable",)
    )
    value.results = (denied,)
    result = build(value)
    assert result.sessions[0].reasons == ("chain_unavailable",) and result.status == "blocked"


def test_later_audit_invalidates_coverage_without_rewriting_selection(tmp_path, monkeypatch):
    value = fixture_case(tmp_path, monkeypatch)
    original = value.results[0]
    value.results = (
        replace(
            original,
            verification=replace(
                original.verification,
                invalidations=(
                    SourceInvalidation(
                        original.decision_hash,
                        datetime(2026, 9, 27, tzinfo=UTC),
                        "source_invalidated",
                    ),
                ),
            ),
        ),
    )
    result = build(value)
    assert "source_audit_invalidated" in result.reasons
    assert result.sessions[0].candidates == original.candidates


def test_interval_quotes_cannot_satisfy_event_age(tmp_path, monkeypatch):
    value = fixture_case(tmp_path, monkeypatch)
    semantic = replace(
        value.study.semantics[0],
        schema="cbbo-1m",
        observation_kind="interval_quote",
        initialization="interval_observation",
    )
    requirements = tuple(
        replace(r, semantics_hash=semantic.fact_hash, window=replace(r.window, schema="cbbo-1m"))
        if r.window.dataset == "OPRA.PILLAR"
        else r
        for r in value.study.requirements
    )
    original = value.results[0]
    facts = tuple(sorted({semantic.fact_hash, *original.verification.record_hashes}))
    findings = tuple(
        replace(f, visible_hashes=tuple(sorted({semantic.fact_hash, *f.visible_hashes})))
        if f.role == "quote_semantics"
        else f
        for f in original.verification.findings
    )
    value.results = (
        replace(
            original,
            verification=replace(original.verification, record_hashes=facts, findings=findings),
        ),
    )
    result = build(
        value, semantics=(semantic, *value.study.semantics[1:]), requirements=requirements
    )
    assert "quote_semantics_incompatible" in result.reasons and result.status == "blocked"


def test_source_era_does_not_cover_pre_feed_change_events(tmp_path, monkeypatch):
    value = fixture_case(tmp_path, monkeypatch)
    semantic = replace(value.study.semantics[0], start_ns=_ns(datetime(2023, 3, 28, tzinfo=UTC)))
    requirements = tuple(
        replace(r, semantics_hash=semantic.fact_hash) if r.window.dataset == "OPRA.PILLAR" else r
        for r in value.study.requirements
    )
    result = build(
        value, semantics=(semantic, *value.study.semantics[1:]), requirements=requirements
    )
    assert result.status == "blocked" and "source_coverage_gap" in result.reasons


def test_qualification_cannot_relabel_short_pilot_history(tmp_path, monkeypatch):
    value = fixture_case(tmp_path, monkeypatch)
    result = build(value, purpose="qualification")
    assert "research_history_insufficient" in result.reasons and not result.economic_eligible


@pytest.mark.parametrize("planned_sessions", [250, 749, 750])
def test_declared_session_count_cannot_prove_observed_history_bars(
    tmp_path, monkeypatch, planned_sessions
):
    value = fixture_case(tmp_path, monkeypatch)
    session_ids = tuple(
        sorted(
            (
                value.results[0].session_id,
                *(f"planned-{index:04d}" for index in range(planned_sessions - 1)),
            )
        )
    )
    result = build(value, purpose="qualification", session_ids=session_ids)
    # Ten years of declared windows and enough planned folds are not 750 observed bars.
    assert result.status == "blocked"
    assert "research_history_insufficient" in result.reasons


@pytest.mark.parametrize("missing", ["tail", "interior"])
def test_warmup_must_cover_continuously_through_decision(tmp_path, monkeypatch, missing):
    value = fixture_case(tmp_path, monkeypatch)
    warmup = next(r for r in value.study.requirements if r.role == "warmup")
    midpoint = (warmup.window.start_ns + value.decision) // 2
    left = replace(warmup, window=replace(warmup.window, end_ns=midpoint))
    replacements = (left,)
    if missing == "interior":
        right = replace(
            warmup,
            requirement_id="warmup-right",
            window=replace(
                warmup.window,
                start_ns=midpoint + 1,
                requirement_ids=("warmup-right",),
            ),
        )
        replacements += (right,)
    requirements = tuple(r for r in value.study.requirements if r.role != "warmup")
    result = build(value, requirements=(*requirements, *replacements))
    assert result.status == "blocked"
    assert value.results[0].session_id + ":warmup" in result.incomplete_obligations


def test_adjacent_warmup_windows_cover_decision_without_false_gap(tmp_path, monkeypatch):
    value = fixture_case(tmp_path, monkeypatch)
    warmup = next(r for r in value.study.requirements if r.role == "warmup")
    midpoint = (warmup.window.start_ns + value.decision) // 2
    left = replace(warmup, window=replace(warmup.window, end_ns=midpoint))
    right = replace(
        warmup,
        requirement_id="warmup-right",
        window=replace(warmup.window, start_ns=midpoint, requirement_ids=("warmup-right",)),
    )
    requirements = tuple(r for r in value.study.requirements if r.role != "warmup")
    result = build(value, requirements=(*requirements, right, left))
    assert result.status == "requirements_complete"
    assert not result.incomplete_obligations


@pytest.mark.parametrize("role", ["initialization", "entry", "monitoring", "exit", "expiry"])
def test_one_quote_stream_cannot_initialize_or_complete_another(tmp_path, monkeypatch, role):
    value = fixture_case(tmp_path, monkeypatch)
    other = value.study.semantics[1]
    changed = tuple(
        replace(
            r,
            semantics_hash=other.fact_hash,
            window=replace(r.window, dataset=other.dataset, schema=other.schema),
        )
        if r.role == role
        else r
        for r in value.study.requirements
    )
    result = build(value, requirements=changed)
    assert result.status == "blocked"
    assert "quote_semantics_incompatible" in result.reasons
    assert result.sessions[0].candidates == value.results[0].candidates


def test_exact_union_preserves_disjoint_ranges_and_reverse_links():
    models = api("_models")
    windows = (
        models.CoverageWindow(
            "OPRA.PILLAR",
            "cmbp-1",
            "SPY   260120C00400000",
            "raw_symbol",
            10,
            20,
            ("a",),
            (DataHash("a" * 64),),
        ),
        models.CoverageWindow(
            "OPRA.PILLAR",
            "cmbp-1",
            "SPY   260120C00400000",
            "raw_symbol",
            20,
            30,
            ("b",),
            (DataHash("b" * 64),),
        ),
        models.CoverageWindow(
            "OPRA.PILLAR",
            "cmbp-1",
            "SPY   260120C00400000",
            "raw_symbol",
            31,
            40,
            ("c",),
            (DataHash("c" * 64),),
        ),
    )
    result = api().union_coverage_windows(windows)
    assert [(w.start_ns, w.end_ns) for w in result] == [(10, 30), (31, 40)]
    assert result[0].requirement_ids == ("a", "b") and result[0].selection_hashes == (
        DataHash("a" * 64),
        DataHash("b" * 64),
    )
    assert api().union_coverage_windows(tuple(reversed(windows))) == result


def test_101_symbols_are_batched_only_with_identical_windows():
    models = api("_models")
    windows = tuple(
        models.CoverageWindow(
            "OPRA.PILLAR",
            "cmbp-1",
            f"symbol-{index:03d}",
            "raw_symbol",
            10,
            20,
            (f"req-{index}",),
            (DataHash("a" * 64),),
        )
        for index in range(101)
    )
    batches = api().batch_coverage_requests(windows)
    assert [len(batch.symbols) for batch in batches] == [100, 1]
    changed = (*windows[:-1], replace(windows[-1], end_ns=21))
    assert all(len(batch.symbols) <= 100 for batch in api().batch_coverage_requests(changed))


def test_year_end_does_not_cut_required_settlement_tail(tmp_path, monkeypatch):
    value = fixture_case(tmp_path, monkeypatch)
    january_end = _ns(datetime(2024, 1, 5, tzinfo=UTC)) + 1
    requirements = tuple(
        replace(
            r,
            window=replace(r.window, end_ns=january_end),
            missing_dependencies=("january-reference",),
        )
        if r.role == "settlement"
        else r
        for r in value.study.requirements
    )
    result = build(value, requirements=requirements)
    assert max(r.end_ns for r in result.requests) == january_end
    assert result.incomplete_obligations == ("january-reference",)


def test_exit_window_after_expiry_does_not_satisfy_exit_coverage(tmp_path, monkeypatch):
    value = fixture_case(tmp_path, monkeypatch)
    requirements = tuple(
        replace(r, window=replace(r.window, start_ns=value.last + 1, end_ns=value.last + 1000))
        if r.role == "exit"
        else r
        for r in value.study.requirements
    )
    result = build(value, requirements=requirements)
    assert result.status == "blocked"
    assert any(reason.endswith(":exit") for reason in result.incomplete_obligations)


def test_initialization_beginning_at_first_quote_is_not_prior_state(tmp_path, monkeypatch):
    value = fixture_case(tmp_path, monkeypatch)
    requirements = tuple(
        replace(r, window=replace(r.window, start_ns=value.decision, end_ns=value.decision + 1))
        if r.role == "initialization"
        else r
        for r in value.study.requirements
    )
    result = build(value, requirements=requirements)
    assert result.status == "blocked"
    assert any(reason.endswith(":initialization") for reason in result.incomplete_obligations)
