"""No retrieved snapshot or valid hash confers unreviewed historical semantics."""

from dataclasses import asdict, replace

import pytest

from tests.unit.market_data._options_source_fixtures import (
    AS_OF,
    END,
    ROOT,
    START,
    arrangement,
    config,
    digest,
    module,
    private_file,
    verify_fixture_bundle,
)
from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401


def test_shipped_rulebook_has_no_blanket_provider_approval(tmp_path):
    bundle, context, _ = arrangement(tmp_path)
    rules_api = module("rules")
    assert rules_api.load_reviewed_rules() == ()
    context = replace(context, rulebook_hash=rules_api.reviewed_rulebook_hash())
    result = module("verify").verify_source_bundle(
        bundle, context=context, loaded=config(), repository_root=ROOT
    )
    assert result.status == "denied"
    assert "historical_availability_unverified" in result.reasons
    assert not result.production_eligible and not result.evidence_promotable


def test_private_fixture_rule_verifies_only_its_exact_synthetic_role(tmp_path):
    bundle, context, rules = arrangement(tmp_path)
    result = verify_fixture_bundle(bundle, context, rules)
    finding = next(item for item in result.findings if item.role == "bar_publication")
    assert finding.status == "verified" and len(finding.visible_hashes) == 1
    assert len(result.record_hashes) == 1 and len(result.visible_claim_hashes) == 1
    assert not result.live_authorized and not result.download_authorized


def test_retrieval_or_hash_does_not_prove_publication(tmp_path):
    bundle, context, rules = arrangement(tmp_path, published=None)
    result = verify_fixture_bundle(bundle, context, rules)
    assert result.status == "denied"
    assert "historical_availability_unverified" in result.reasons


@pytest.mark.parametrize(
    "field", ["config_hash", "code_hash", "rulebook_hash", "start_ns", "end_ns"]
)
def test_copying_evidence_to_other_context_scope_denies(tmp_path, field):
    bundle, context, rules = arrangement(tmp_path)
    value = START + 1 if field == "start_ns" else END + 1 if field == "end_ns" else "0" * 64
    result = verify_fixture_bundle(bundle, replace(context, **{field: value}), rules)
    assert result.status == "denied"
    assert result.reasons == ("source_scope_mismatch",)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "different.source"),
        ("schema", "different-schema"),
        ("coverage_hash", "0" * 64),
        ("era_end_ns", END + 999),
    ],
)
def test_substituted_claim_identity_cannot_reuse_a_rule(tmp_path, field, value):
    bundle, context, rules = arrangement(tmp_path)
    changed = replace(bundle, claims=(replace(bundle.claims[0], **{field: value}),))
    result = verify_fixture_bundle(changed, context, rules)
    assert result.status == "denied"
    assert result.reasons == ("source_scope_mismatch",)


def test_authentic_looking_but_unpinned_document_denies(tmp_path):
    bundle, context, rules = arrangement(tmp_path / "one")
    other = private_file(tmp_path / "two", "official-looking.txt", b"An unreviewed protocol")
    result = verify_fixture_bundle(replace(bundle, references=(other,)), context, rules)
    assert result.status == "denied"
    assert "source_reference_unverified" in result.reasons


def test_future_publication_and_omitted_action_coverage_deny(tmp_path):
    bundle, context, rules = arrangement(tmp_path, role="actions", published=AS_OF + 1)
    result = verify_fixture_bundle(bundle, context, rules)
    assert result.status == "denied" and not result.record_hashes
    result = verify_fixture_bundle(replace(bundle, claims=()), context, rules)
    assert result.status == "denied" and not result.record_hashes


def test_whole_file_future_addition_does_not_change_visible_record_or_claim_hashes(tmp_path):
    before, context, rules = arrangement(tmp_path / "before")
    after, later_context, later_rules = arrangement(tmp_path / "after", future=True)
    first = verify_fixture_bundle(before, context, rules)
    second = verify_fixture_bundle(after, later_context, later_rules)
    assert first.source_hashes != second.source_hashes
    assert first.record_hashes == second.record_hashes
    assert first.visible_claim_hashes == second.visible_claim_hashes


def test_source_mutation_after_claim_hashing_denies(tmp_path):
    bundle, context, rules = arrangement(tmp_path)
    bundle.manifests[0].path.write_bytes(b"changed")
    result = verify_fixture_bundle(bundle, context, rules)
    assert result.status == "denied" and "source_integrity_invalid" in result.reasons


def test_rule_era_end_is_exclusive(tmp_path):
    bundle, context, rules = arrangement(tmp_path)
    rule = replace(rules[0], era_end_ns=END - 1)
    context = replace(context, rulebook_hash=digest([asdict(rule)]))
    result = verify_fixture_bundle(bundle, context, (rule,))
    assert result.status == "denied" and "source_scope_mismatch" in result.reasons


def test_report_is_diagnostic_and_does_not_expose_private_paths(tmp_path):
    bundle, context, rules = arrangement(tmp_path)
    result = verify_fixture_bundle(bundle, context, rules)
    body = module("wire").encode_source_verification(result)
    assert str(tmp_path).encode() not in body
    assert b'"live_authorized":false' in body


def test_retrieval_after_historical_invalidation_does_not_rewrite_visible_hashes(tmp_path):
    before, context, rules = arrangement(tmp_path / "before")
    after, second_context, second_rules = arrangement(tmp_path / "after", invalidation=True)
    first = verify_fixture_bundle(before, context, rules)
    second = verify_fixture_bundle(after, second_context, second_rules)
    assert first.record_hashes == second.record_hashes
    assert first.visible_claim_hashes == second.visible_claim_hashes
    assert first.invalidations == () and len(second.invalidations) == 1
    assert second.invalidations[0].affected_hash in second.record_hashes


def test_loaded_config_identity_is_recomputed_not_trusted(tmp_path):
    bundle, context, rules = arrangement(tmp_path)
    loaded = replace(config(), config_hash="0" * 64)
    result = module("verify")._verify_with_rules(
        bundle,
        context=replace(context, config_hash="0" * 64),
        loaded=loaded,
        repository_root=ROOT,
        rules=rules,
    )
    assert result.status == "denied" and result.reasons == ("source_scope_mismatch",)


def test_verified_source_bytes_are_not_reopened_after_hashing(tmp_path, monkeypatch):
    bundle, context, rules = arrangement(tmp_path)
    api = module("dispatch")
    original = api._read

    def replacing_read(directory, name, maximum):
        encoded = original(directory, name, maximum)
        if name == bundle.manifests[0].path.name:
            bundle.manifests[0].path.write_bytes(b"replaced after hash-bound read")
        return encoded

    monkeypatch.setattr(api, "_read", replacing_read)
    result = verify_fixture_bundle(bundle, context, rules)
    assert result.status == "verified" and len(result.record_hashes) == 1


def test_findings_preserve_unrelated_role_when_a_rule_is_missing(tmp_path):
    bundle, context, rules = arrangement(tmp_path / "bars")
    second, _, _ = arrangement(tmp_path / "actions", role="actions")
    # The shared fabricated protocol document is pinned once, not duplicated.
    combined = replace(
        bundle,
        claims=(*bundle.claims, replace(second.claims[0], rule_id="missing.rule")),
        manifests=bundle.manifests + second.manifests,
    )
    result = verify_fixture_bundle(combined, context, rules)
    assert result.status == "denied"
    findings = {item.role: item.status for item in result.findings}
    assert findings == {"actions": "denied", "bar_publication": "verified"}


def test_unknown_rule_cannot_be_promoted_by_a_claim(tmp_path):
    bundle, context, rules = arrangement(tmp_path)
    bundle = replace(bundle, claims=(replace(bundle.claims[0], rule_id="unreviewed.rule"),))
    result = verify_fixture_bundle(bundle, context, rules)
    assert result.status == "denied" and not result.visible_claim_hashes
    for field in (
        "production_eligible",
        "evidence_promotable",
        "download_authorized",
        "live_authorized",
    ):
        with pytest.raises((TypeError, ValueError), match="init=False"):
            replace(result, **{field: True})
        assert getattr(result, field) is False


def test_visible_fact_identity_is_recomputable_by_downstream_assemblers(tmp_path):
    bundle, context, rules = arrangement(tmp_path)
    result = verify_fixture_bundle(bundle, context, rules)
    expected = digest({"kind": "bar_publication", "identity": "fabricated", "value": "100"})
    assert result.record_hashes == (expected,)
    assert result.findings[0].visible_hashes == (expected,)
