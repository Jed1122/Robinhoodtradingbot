"""Closed parser identifiers are not approval of actual source semantics."""

from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from tests.unit.market_data._options_source_fixtures import (
    ROOT,
    arrangement,
    config,
    digest,
    module,
    verify_fixture_bundle,
)
from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401


def parse(bundle, context, rule):
    return module("dispatch").parse_source_claim(
        bundle.claims[0],
        rule,
        bundle.manifests[0],
        context=context,
        loaded=config(),
        repository_root=ROOT,
    )


def test_unknown_verifier_denies(tmp_path):
    module("dispatch")
    _, _, rules = arrangement(tmp_path)
    with pytest.raises(ValueError, match="options_source_evidence_invalid"):
        replace(rules[0], verifier_id="arbitrary-import-or-code")


def test_synthetic_rule_cannot_approve_native(tmp_path):
    bundle, context, rules = arrangement(tmp_path)
    claim = replace(bundle.claims[0], source_id="OPRA.PILLAR", schema="definition")
    rule = replace(rules[0], source_id=claim.source_id, schema=claim.schema)
    bundle = replace(bundle, claims=(claim,))
    context = replace(context, rulebook_hash=digest([asdict(rule)]))
    with pytest.raises(ValueError, match="options_source_evidence_invalid"):
        parse(bundle, context, rule)
    verification = verify_fixture_bundle(bundle, context, (rule,))
    assert verification.status == "denied" and verification.record_hashes == ()


def test_original_synthetic_claim_hash_unchanged(tmp_path):
    # Literal checkpoint from the pre-dispatch verifier, captured before implementation.
    bundle, context, rules = arrangement(tmp_path)
    facts = parse(bundle, context, rules[0])
    verification = verify_fixture_bundle(bundle, context, rules)
    assert facts.schema == "parsed-source-facts-v1"
    assert tuple(fact for _, fact in facts.record_pairs) == (
        "9e4a8faf6280bbab1775872a09af71834d205e8c0b3a44d63f50664425b75fd9",
    )
    assert verification.status == "verified"
    assert verification.visible_claim_hashes == (
        "51b37f0fd03c8fca1fd4e633b9d3236ad69af86d0be3ccac2545664e1b592161",
    )
    assert bundle.claims[0].coverage_hash == (
        "1996515fd843de6900dccdfde33952b039d656d0f4f6cd0dc6c708806a420314"
    )
    assert bundle.manifests[0].sha256 == (
        "9588657284d2f5a9d8b86fc0ca7a2c4b7bd12f50a068a7f89b3d1eb872181032"
    )
    assert facts.invalidations == ()
    with pytest.raises(FrozenInstanceError):
        facts.record_pairs = ()


@pytest.mark.parametrize("verifier", ["databento-native-v1", "reviewed-reference-v1"])
def test_known_parser_id_is_not_source_approval(tmp_path, verifier):
    bundle, context, rules = arrangement(tmp_path)
    rule = replace(rules[0], verifier_id=verifier)
    context = replace(context, rulebook_hash=digest([asdict(rule)]))
    with pytest.raises(ValueError, match="options_source_evidence_invalid"):
        parse(bundle, context, rule)
    verification = verify_fixture_bundle(bundle, context, (rule,))
    assert verification.status == "denied" and verification.record_hashes == ()
    assert module("rules").load_reviewed_rules() == ()


def test_direct_dispatch_rechecks_artifact_identity(tmp_path):
    bundle, context, rules = arrangement(tmp_path)
    bundle.manifests[0].path.write_bytes(b"substituted")
    with pytest.raises(ValueError):
        parse(bundle, context, rules[0])


def test_direct_dispatch_rejects_mismatched_claim_and_rule(tmp_path):
    bundle, context, rules = arrangement(tmp_path)
    rule = replace(rules[0], role="actions")
    with pytest.raises(ValueError):
        parse(bundle, context, rule)


def test_future_rows_do_not_change_parsed_visible_facts(tmp_path):
    bundle, context, rules = arrangement(tmp_path / "before")
    later, later_context, later_rules = arrangement(tmp_path / "after", future=True)
    assert parse(bundle, context, rules[0]) == parse(later, later_context, later_rules[0])


@pytest.mark.parametrize(
    "pairs",
    [
        [("a" * 64, "b" * 64)],
        (("bad", "b" * 64),),
        (("b" * 64, "a" * 64), ("a" * 64, "b" * 64)),
        (("a" * 64, "b" * 64), ("a" * 64, "c" * 64)),
        (("a" * 64, "b" * 64), ("a" * 64, "b" * 64)),
    ],
)
def test_parsed_facts_require_strict_unique_sorted_envelope_pairs(pairs):
    with pytest.raises(ValueError):
        module("models").ParsedSourceFacts(pairs, ())
