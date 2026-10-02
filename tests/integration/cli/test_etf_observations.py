"""Standalone private observations CLI; all inputs are manufactured."""

import hashlib
import json
import subprocess

import pytest
from typer.testing import CliRunner

from trading_bot.cli import etf_observations
from trading_bot.diagnostics.alpaca_observe import ObservationPlan, encode_observation_plan
from trading_bot.market_data.recording import canonical_json


@pytest.fixture
def auditor_repository(tmp_path, monkeypatch):
    repository = tmp_path / "synthetic-auditor-repository"
    repository.mkdir()

    def git(*arguments):
        return subprocess.run(
            ("git", *arguments), cwd=repository, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "--quiet")
    source = repository / "src"
    source.mkdir()
    tracked = source / "auditor.py"
    tracked.write_text("# Manufactured source identity fixture.\n")
    git("add", "src")
    git(
        "-c",
        "user.name=Fixture Auditor",
        "-c",
        "user.email=fixture-auditor@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "Manufactured auditor source",
    )
    revision = git("rev-parse", "HEAD")
    monkeypatch.setattr(etf_observations, "_REPOSITORY", repository)
    return repository, revision


def _empty_observation_archive(root, repository):
    plan = ObservationPlan(
        code_revision="a" * 40,
        config_hash="b" * 64,
        prepared_at_ns=1,
        expires_at_ns=1 + 1800 * 10**9,
        credential_file=root.parent / "absent-credentials" / "unused.json",
        output_root=root,
        repository_root=repository,
        duration_seconds=1,
        max_frames=1,
    )
    path = root / (plan.plan_hash + ".observation-plan.json")
    path.write_bytes(encode_observation_plan(plan))
    path.chmod(0o600)
    body = canonical_json(
        {
            "schema": "alpaca-observation-result-v1",
            "plan_hash": plan.plan_hash,
            "started_at_ns": 2,
            "finished_at_ns": 3,
            "receipt_hashes": [],
            "total_raw_bytes": 0,
            "counts": {"quote": 0, "status": 0, "luld": 0},
            "termination": "capture_failed",
            "predecessor_result_hash": None,
            "segment_gap_before_start": True,
            "initial_control_state_verified": False,
            "transport_continuity_verified": False,
            "source_qualified": False,
            "execution_enabled": False,
            "evidence_promotable": False,
        }
    ).encode()
    digest = hashlib.sha256(body).hexdigest()
    path = root / (digest + ".observation-result.json")
    path.write_bytes(body)
    path.chmod(0o600)
    return digest


def test_calibration_missing_orders_writes_revision_bound_blocked_private_report(
    tmp_path, auditor_repository
):
    repository, revision = auditor_repository
    inputs = tmp_path / "inputs"
    inputs.mkdir(mode=0o700)
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    input_file = inputs / "observations.json"
    input_file.write_text(
        json.dumps(
            {
                "schema": "etf-cost-observations-v1",
                "provenance": "synthetic",
                "execution_broker": "robinhood",
                "market_data_source": "alpaca-sip",
                "orders": [],
            }
        )
    )
    input_file.chmod(0o600)
    result = CliRunner().invoke(
        etf_observations.app,
        [
            "calibrate-costs",
            "--input-file",
            str(input_file),
            "--input-root",
            str(inputs),
            "--report-dir",
            str(reports),
        ],
    )
    assert result.exit_code == 2, result.output
    response = json.loads(result.output)
    assert response["status"] == "BLOCKED_INPUTS"
    assert response["evidence_promotable"] is False
    path = reports / (response["artifact_digest"] + ".observation-report.json")
    body = path.read_bytes()
    assert hashlib.sha256(body).hexdigest() == response["artifact_digest"]
    report = json.loads(body)
    assert response["report_hash"] == report["report_hash"]
    assert response["report_hash"] != response["artifact_digest"]
    unhashed_report = {key: value for key, value in report.items() if key != "report_hash"}
    expected_report_hash = hashlib.sha256(canonical_json(unhashed_report).encode()).hexdigest()
    assert expected_report_hash == report["report_hash"]
    assert report["calibrator_code_revision"] == revision
    unbound_report = {
        key: value for key, value in unhashed_report.items() if key != "calibrator_code_revision"
    }
    draft_report_hash = hashlib.sha256(canonical_json(unbound_report).encode()).hexdigest()
    assert draft_report_hash != report["report_hash"]
    assert report["charged_order_fee_usd"]["total"] is None
    assert report["execution_enabled"] is False
    assert report["economic_verdict"] == "ECONOMIC_NO_GO"
    assert path.stat().st_mode & 0o777 == 0o600
    assert str(inputs) not in result.output
    assert str(repository) not in result.output


def test_untrusted_input_is_sanitized_and_does_not_publish(tmp_path, auditor_repository):
    inputs = tmp_path / "inputs"
    inputs.mkdir(mode=0o700)
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    path = inputs / "synthetic-secret-file.json"
    path.write_text('{"token":"synthetic-secret-value"}')
    path.chmod(0o600)
    result = CliRunner().invoke(
        etf_observations.app,
        [
            "calibrate-costs",
            "--input-file",
            str(path),
            "--input-root",
            str(inputs),
            "--report-dir",
            str(reports),
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "status": "denied",
        "reason": "etf_observation_input_invalid",
    }
    assert "synthetic-secret" not in result.output
    assert list(reports.iterdir()) == []


@pytest.mark.parametrize("dirty_kind", ["tracked", "relevant_untracked"])
def test_calibration_dirty_source_denies_before_loading_inputs(
    tmp_path, monkeypatch, auditor_repository, dirty_kind
):
    repository, _ = auditor_repository
    if dirty_kind == "tracked":
        (repository / "src/auditor.py").write_text("# Dirty manufactured source.\n")
    else:
        (repository / "src/untracked.py").write_text("# Untracked manufactured source.\n")

    def forbidden(*args, **kwargs):
        raise AssertionError("dirty calibrator tried to load execution inputs")

    monkeypatch.setattr(etf_observations, "load_etf_cost_observations", forbidden)
    inputs = tmp_path / "inputs"
    inputs.mkdir(mode=0o700)
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    result = CliRunner().invoke(
        etf_observations.app,
        [
            "calibrate-costs",
            "--input-file",
            str(inputs / "absent.json"),
            "--input-root",
            str(inputs),
            "--report-dir",
            str(reports),
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "status": "denied",
        "reason": "etf_observation_input_invalid",
    }
    assert list(reports.iterdir()) == []
    assert str(repository) not in result.output


def test_audit_missing_archive_denies_without_authentication(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline audit tried opening a credential")

    monkeypatch.setattr(etf_observations, "capture_observations", forbidden)
    monkeypatch.setattr(etf_observations, "_revision", lambda: "a" * 40)
    inputs = tmp_path / "inputs"
    inputs.mkdir(mode=0o700)
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    result = CliRunner().invoke(
        etf_observations.app,
        [
            "audit",
            "--input-root",
            str(inputs),
            "--result-hash",
            "a" * 64,
            "--report-dir",
            str(reports),
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "denied"
    assert list(reports.iterdir()) == []


@pytest.mark.parametrize("dirty_kind", ["tracked", "relevant_untracked"])
def test_audit_dirty_source_denies_before_reading_archive(
    tmp_path, monkeypatch, auditor_repository, dirty_kind
):
    repository, _ = auditor_repository
    if dirty_kind == "tracked":
        (repository / "src/auditor.py").write_text("# Dirty manufactured source.\n")
    else:
        (repository / "src/untracked.py").write_text("# Untracked manufactured source.\n")

    def forbidden(*args, **kwargs):
        raise AssertionError("dirty audit tried to process an archive")

    monkeypatch.setattr(etf_observations, "audit_observation_capture", forbidden)
    inputs = tmp_path / "inputs"
    inputs.mkdir(mode=0o700)
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    result = CliRunner().invoke(
        etf_observations.app,
        [
            "audit",
            "--input-root",
            str(inputs),
            "--result-hash",
            "a" * 64,
            "--report-dir",
            str(reports),
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "status": "denied",
        "reason": "etf_observation_input_invalid",
    }
    assert list(reports.iterdir()) == []
    assert str(repository) not in result.output


def test_audit_report_records_clean_auditor_revision_and_full_artifact_digest(
    tmp_path, auditor_repository
):
    repository, revision = auditor_repository
    inputs = tmp_path / "inputs"
    inputs.mkdir(mode=0o700)
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    result_hash = _empty_observation_archive(inputs, repository)
    result = CliRunner().invoke(
        etf_observations.app,
        [
            "audit",
            "--input-root",
            str(inputs),
            "--result-hash",
            result_hash,
            "--report-dir",
            str(reports),
        ],
    )
    assert result.exit_code == 2, result.output
    response = json.loads(result.output)
    path = reports / (response["artifact_digest"] + ".observation-report.json")
    body = path.read_bytes()
    assert hashlib.sha256(body).hexdigest() == response["artifact_digest"]
    assert response["report_hash"] == response["artifact_digest"]
    report = json.loads(body)
    assert report["auditor_code_revision"] == revision
    assert report["auditor_code_revision"] != "a" * 40
    assert report["result_hash"] == result_hash
    assert report["status"] == "BLOCKED_INPUTS"
    for flag in ("source_qualified", "execution_enabled", "evidence_promotable"):
        assert report[flag] is False
    assert path.stat().st_mode & 0o777 == 0o600
    assert str(repository) not in result.output


def test_capture_wrong_hash_is_rejected_before_keys(tmp_path, monkeypatch):
    from trading_bot.clock import SystemClock
    from trading_bot.diagnostics.alpaca_observe import (
        encode_observation_plan,
        prepare_observation_capture,
    )

    inputs = tmp_path / "inputs"
    inputs.mkdir(mode=0o700)
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    plan = prepare_observation_capture(
        etf_observations._loaded(etf_observations._REPOSITORY / "configs"),
        clock=SystemClock(),
        code_revision="a" * 40,
        credential_file=keys / "missing.json",
        output_root=inputs,
        repository_root=etf_observations._REPOSITORY,
    )
    path = inputs / "plan.json"
    path.write_bytes(encode_observation_plan(plan))
    path.chmod(0o600)
    monkeypatch.setattr(etf_observations, "_revision", lambda: "a" * 40)
    result = CliRunner().invoke(
        etf_observations.app,
        [
            "capture",
            "--manifest-file",
            str(path),
            "--approved-plan-hash",
            "b" * 64,
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "denied"
    assert not list(inputs.glob("*.attempt"))
