"""Private durable report artifacts from exclusively fictional planning inputs."""

import hashlib
import importlib
import json
import os
from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from tests.unit.runtime.test_stock_investment_plan import plan
from trading_bot.runtime.stock_archive_lease import StockArchiveLease


def api():
    try:
        return importlib.import_module("trading_bot.runtime.stock_investment_reports")
    except ModuleNotFoundError:
        pytest.fail("current stock report publisher missing")


@pytest.fixture
def roots(tmp_path):
    output, archive = tmp_path.resolve() / "reports", tmp_path.resolve() / "archive"
    output.mkdir(mode=0o700)
    archive.mkdir(mode=0o700)
    return output, archive


def publish(roots, result=None):
    output, archive = roots
    return api().publish_current_stock_plan(
        plan() if result is None else result, output_dir=output, archive_dir=archive
    )


def read(roots, artifact):
    output, archive = roots
    return api().read_current_stock_plan_report(
        output_dir=output, archive_dir=archive, artifact_file=artifact.file
    )


def test_document_retains_exact_decimals_all_source_clocks_and_component_identities():
    result = plan()
    original = result.rankings.assessments[0]
    precise = Decimal("0.12345678901234567890123456789012345678901234567890")
    decision = replace(original, priority_score=precise)
    rankings = replace(result.rankings, assessments=(decision, *result.rankings.assessments[1:]))
    result = replace(result, rankings=rankings)
    doc = api().current_stock_plan_document(result)
    assert doc["report_evidence_hash"] == result.evidence_hash
    assert doc["plan"]["rankings"]["assessments"][0]["priority_score"] == str(precise)
    assert (
        doc["plan"]["rankings"]["assessments"][0]["source_refs"][0]["received_at"]
        == original.source_refs[0].received_at.isoformat()
    )
    assert doc["plan"]["remaining_execution_checks"] == list(result.remaining_execution_checks)
    assert doc["component_hashes"]["analysis_code_hash"] == result.analysis_code_hash
    assert doc["component_hashes"]["source_config_hash"] == result.source_config_hash
    assert doc["component_hashes"]["acquisition_code_hashes"] == list(
        result.acquisition_code_hashes
    )
    assert doc["component_hashes"]["rankings"] == result.rankings.report_hash
    assert doc["component_hashes"]["allocation"] == result.allocation.evidence_hash
    with localcontext() as ctx:
        ctx.prec = 3
        ctx.capitals = 0
        assert api().current_stock_plan_document(result) == doc


def test_version_two_binds_composed_portfolio_proposal_hash_and_fixed_scope():
    result = plan()
    doc = api().current_stock_plan_document(result)
    assert doc["schema_version"] == 2
    assert (
        doc["component_hashes"]["portfolio_proposals"] == result.portfolio_proposals.evidence_hash
    )
    assert doc["plan"]["portfolio_proposals"]["cash_credited"] is False


def test_reader_preserves_the_version_one_wire_contract(roots):
    # Version one predates portfolio composition. Retained artifacts remain
    # dated research evidence and are never rewritten to the current version.
    document = api().current_stock_plan_document(plan())
    document["schema_version"] = 1
    del document["plan"]["portfolio_proposals"]
    del document["component_hashes"]["portfolio_proposals"]
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    name = hashlib.sha256(body).hexdigest() + ".stock-investment.json"
    target = roots[0] / name
    target.write_bytes(body)
    target.chmod(0o600)
    assert (
        api().read_current_stock_plan_report(
            output_dir=roots[0], archive_dir=roots[1], artifact_file=name
        )
        == document
    )
    assert target.read_bytes() == body


def test_version_downgrade_cannot_hide_new_portfolio_authority(roots):
    artifact = publish(roots)
    document = read(roots, artifact)
    document["schema_version"] = 1
    del document["component_hashes"]["portfolio_proposals"]
    document["plan"]["portfolio_proposals"]["live_authorized"] = True
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    target = roots[0] / (hashlib.sha256(body).hexdigest() + ".stock-investment.json")
    target.write_bytes(body)
    target.chmod(0o600)
    with pytest.raises(ValueError):
        read(roots, replace(artifact, file=target.name))


@pytest.mark.parametrize("field", ("cash_credited", "execution_authorized"))
def test_readdressing_does_not_allow_nested_portfolio_authority(roots, field):
    artifact = publish(roots)
    document = read(roots, artifact)
    document["plan"]["portfolio_proposals"][field] = True
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    target = roots[0] / (hashlib.sha256(body).hexdigest() + ".stock-investment.json")
    target.write_bytes(body)
    target.chmod(0o600)
    with pytest.raises(ValueError):
        read(roots, replace(artifact, file=target.name))


def test_research_only_report_keeps_missing_account_reason_and_never_invents_cash():
    doc = api().current_stock_plan_document(plan(allocation_context=None))
    assert doc["status"] == "research_only" and doc["plan"]["allocation"] is None
    assert "account_context_missing" in doc["plan"]["needs"]
    assert doc["execution_authorized"] is doc["live_authorized"] is False


def test_content_addressed_publish_readback_and_restart_idempotency(roots):
    result = plan()
    first = publish(roots, result)
    output, _ = roots
    raw = (output / first.file).read_bytes()
    assert first.body_sha256 == hashlib.sha256(raw).hexdigest() == first.file[:64]
    assert first.body_sha256 != first.report_evidence_hash == result.evidence_hash
    assert read(roots, first) == api().current_stock_plan_document(result)
    assert publish(roots, result) == first
    assert sorted(x.name for x in output.iterdir()) == [".stock-research.lock", first.file]
    assert (output / first.file).stat().st_mode & 0o777 == 0o600
    assert output.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize(
    "field", ("live_authorized", "execution_authorized", "orders_created", "reservations_created")
)
def test_changed_plan_authority_rejects_before_publication(roots, field):
    result = plan()
    object.__setattr__(result, field, True)
    with pytest.raises(ValueError):
        publish(roots, result)
    assert list(roots[0].iterdir()) == []


def test_changed_nested_decision_authority_rejects(roots):
    result = plan()
    object.__setattr__(result.rankings.long_term[0], "live_authorized", True)
    with pytest.raises(ValueError):
        publish(roots, result)


@pytest.mark.parametrize("kind", ("corrupt", "mode", "hardlink", "symlink"))
def test_existing_artifact_corruption_or_unsafe_metadata_fails_without_repair(roots, kind):
    artifact = publish(roots)
    output, _ = roots
    path = output / artifact.file
    if kind == "corrupt":
        path.write_bytes(b"{}")
    elif kind == "mode":
        path.chmod(0o400)
    elif kind == "hardlink":
        os.link(path, output / ("0" * 64 + ".stock-investment.json"))
    else:
        body = path.read_bytes()
        path.unlink()
        other = output.parent / "elsewhere"
        other.write_bytes(body)
        other.chmod(0o600)
        path.symlink_to(other)
    names = sorted(p.name for p in output.iterdir())
    with pytest.raises(ValueError):
        publish(roots)
    with pytest.raises(ValueError):
        read(roots, artifact)
    assert sorted(p.name for p in output.iterdir()) == names


@pytest.mark.parametrize("kind", ("unknown", "pending", "fifo", "subdirectory"))
def test_unknown_or_unsafe_inventory_denies_without_cleanup(roots, kind):
    output, _ = roots
    name = ".pending-" + "a" * 32 if kind == "pending" else "unexpected"
    path = output / name
    if kind == "fifo":
        os.mkfifo(path, 0o600)
    elif kind == "subdirectory":
        path.mkdir(mode=0o700)
    else:
        path.touch(mode=0o600)
    with pytest.raises(ValueError):
        publish(roots)
    assert path.lstat() and path.name in [p.name for p in output.iterdir()]


@pytest.mark.parametrize(
    "kind", ("equal", "archive_parent", "output_parent", "symlink_root", "public_mode")
)
def test_output_and_source_archive_roots_are_separate_private_and_canonical(roots, kind):
    output, archive = roots
    if kind == "equal":
        archive = output
    elif kind == "archive_parent":
        output = archive / "nested"
        output.mkdir(mode=0o700)
    elif kind == "output_parent":
        archive = output / "nested"
        archive.mkdir(mode=0o700)
    elif kind == "symlink_root":
        link = output.parent / "linked"
        link.symlink_to(output, target_is_directory=True)
        output = link
    else:
        output.chmod(0o755)
    with pytest.raises(ValueError):
        api().publish_current_stock_plan(plan(), output_dir=output, archive_dir=archive)


def test_existing_lease_blocks_publication_and_restart_succeeds(roots):
    with StockArchiveLease(roots[0]), pytest.raises(ValueError):
        publish(roots)
    assert publish(roots).file.endswith(".stock-investment.json")


def test_count_and_byte_caps_cover_transient_growth_while_existing_cache_hit_is_valid(
    roots, monkeypatch
):
    m = api()
    artifact = publish(roots)
    bodylen = (roots[0] / artifact.file).stat().st_size
    monkeypatch.setattr(m, "_MAX_FILES", 2)
    assert publish(roots) == artifact
    with pytest.raises(ValueError):
        publish(roots, replace(plan(), needs=("changed",)))
    monkeypatch.setattr(m, "_MAX_FILES", 1024)
    monkeypatch.setattr(m, "_MAX_BYTES", bodylen)
    assert publish(roots) == artifact
    with pytest.raises(ValueError):
        publish(roots, replace(plan(), needs=("changed",)))


def test_body_size_and_fixed_inventory_limits_are_enforced(roots, monkeypatch):
    m = api()
    assert (m._MAX_FILES, m._MAX_BYTES, m._MAX_BODY) == (1024, 64 * 1024 * 1024, 9_000_000)
    monkeypatch.setattr(m, "_MAX_BODY", 100)
    with pytest.raises(ValueError):
        publish(roots)
    assert list(roots[0].iterdir()) == []


def test_readdressed_modified_authority_document_is_rejected(roots):
    artifact = publish(roots)
    output, _ = roots
    doc = read(roots, artifact)
    doc["plan"]["live_authorized"] = True
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    target = output / (hashlib.sha256(raw).hexdigest() + ".stock-investment.json")
    target.write_bytes(raw)
    target.chmod(0o600)
    with pytest.raises(ValueError):
        read(roots, replace(artifact, file=target.name))


def test_disabled_research_still_has_a_truthful_publishable_report(roots):
    from tests.unit.runtime.test_stock_investment_plan import controls

    result = plan(controls=controls(research_enabled=False))
    artifact = publish(roots, result)
    doc = read(roots, artifact)
    assert doc["plan"]["rankings"] is doc["plan"]["allocation"] is None
    assert doc["component_hashes"]["decisions"] == []
    assert doc["plan"]["needs"] == ["research_disabled"]


@pytest.mark.parametrize("rebound", ("root", "lock"))
def test_publication_rechecks_owned_root_and_lease_after_writing(roots, monkeypatch, rebound):
    m = api()
    original = m._publish
    output, _ = roots

    def displaced(directory, body, suffix):
        result = original(directory, body, suffix)
        if rebound == "root":
            output.rename(output.with_name("retained-reports"))
            output.mkdir(mode=0o700)
        else:
            anchor = output / ".stock-research.lock"
            anchor.unlink()
            anchor.touch(mode=0o600)
        return result

    monkeypatch.setattr(m, "_publish", displaced)
    with pytest.raises(ValueError):
        publish(roots)
    # A completed publication is retained on a later ownership failure. No repair,
    # rollback, or successful-publication receipt is manufactured by this store.
    retained = output.with_name("retained-reports") if rebound == "root" else output
    assert len(list(retained.glob("*.stock-investment.json"))) == 1
