"""Private fabricated pipeline stability; no genuine economic evidence is produced."""

import hashlib
import json
import stat
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("databento_dbn")

from tests.integration.cli.test_options_native import invoke, private_file, setup_case
from tests.unit.market_data._options_source_fixtures import verified_facts
from tests.unit.research.test_options_acquisition import fixture_case
from tests.unit.research.test_options_shortlist_v2 import install_fixture_rules, run
from trading_bot.market_data.options_source_models import SourceRule
from trading_bot.market_data.recording import canonical_json
from trading_bot.research.options_shortlist_v2_wire import encode_verified_shortlist_input


def test_native_pipeline_repeats_exact_private_artifacts(tmp_path, monkeypatch):
    value, source, _, output = setup_case(tmp_path)
    install_fixture_rules(monkeypatch, value)
    first = invoke("native-options-shortlist", source, output)
    second = invoke("native-options-shortlist", source, output)
    assert first.exit_code == second.exit_code == 0, first.output
    assert first.output == second.output
    row = json.loads(first.output)
    assert row["candidate_count"] == 2
    assert not row["production_eligible"] and not row["live_authorized"]
    path = output / "manifests" / f"{row['artifact_hash']}.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row["artifact_hash"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    saved = json.loads(path.read_bytes())
    assert len(saved["candidates"]) == 2
    assert str(tmp_path) not in path.read_text()


def test_complete_fabricated_pipeline_reverifies_quote_semantics_before_coverage(
    tmp_path, monkeypatch
):
    study_case = fixture_case(tmp_path / "study", monkeypatch)
    value, _, _, output = setup_case(tmp_path)
    facts = {}
    for ref in value.request.bundle.manifests:
        if ref in (value.request.bars, value.request.definitions):
            continue
        body = json.loads(ref.path.read_bytes())
        facts.setdefault(body["role"], []).extend(row["record"] for row in body["records"])
    facts["quote_semantics"] = [
        {"kind": "coverage_semantics", "semantics": asdict(s)} for s in study_case.study.semantics
    ]
    context = value.verification.context
    bundle, verification = verified_facts(
        tmp_path / "all-proofs",
        facts,
        start_ns=context.start_ns,
        end_ns=context.end_ns,
        as_of_ns=context.as_of_ns,
        manifests=(value.request.bars, value.request.definitions),
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
    request = replace(
        value.request,
        bundle=bundle,
        session=replace(value.request.session, claim_hashes=verification.visible_claim_hashes),
        contracts=replace(
            value.request.contracts,
            references=tuple(
                r
                for r in bundle.manifests
                if r not in (value.request.bars, value.request.definitions)
            ),
            claim_hashes=verification.visible_claim_hashes,
        ),
    )
    complete = SimpleNamespace(request=request, rules=rules)
    install_fixture_rules(monkeypatch, complete)
    result = run(complete)
    assert result.status == "selected"
    study = replace(
        study_case.study,
        requirements=tuple(
            replace(r, window=replace(r.window, selection_hashes=(result.decision_hash,)))
            for r in study_case.study.requirements
        ),
    )
    source = private_file(
        tmp_path / "complete-input.json", encode_verified_shortlist_input(request)
    )
    short = invoke("native-options-shortlist", source, output)
    assert short.exit_code == 0, short.output
    index = private_file(
        tmp_path / "index.json",
        json.dumps(
            {
                "schema": "options-shortlist-index-v1",
                "entries": [
                    {
                        "input": {
                            "path": str(source.path),
                            "sha256": source.sha256,
                            "byte_count": source.byte_count,
                        },
                        "expected_result_hash": json.loads(short.output)["artifact_hash"],
                    }
                ],
            }
        ).encode(),
    )
    requirements = private_file(
        tmp_path / "study.json",
        canonical_json({"schema": "options-study-coverage-v1", **asdict(study)}).encode(),
    )
    coverage = invoke(
        "options-coverage-manifest", index, output, "--requirements", str(requirements.path)
    )
    assert coverage.exit_code == 0, coverage.output
    row = json.loads(coverage.output)
    assert row["status"] == "requirements_complete"
    assert not row["download_authorized"] and not row["live_authorized"]
    saved = json.loads((output / "manifests" / f"{row['artifact_hash']}.json").read_bytes())
    assert saved["economic_eligible"] is False
    assert len(saved["sessions"][0]["candidates"]) == 2
