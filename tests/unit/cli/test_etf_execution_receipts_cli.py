"""Receipt CLI uses synthetic local inputs, never customer records or transports."""

import hashlib
import json
import stat
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from trading_bot.cli import etf_observations
from trading_bot.diagnostics.etf_execution_receipts import EtfExecutionReceiptRecorder
from trading_bot.market_data.alpaca_native import parse_timestamp_ns
from trading_bot.market_data.alpaca_observations import parse_alpaca_observation_frame
from trading_bot.research.etf_cost_calibration import load_etf_cost_observations

START = datetime(2026, 10, 2, 14, tzinfo=UTC)


@pytest.fixture
def archive(tmp_path, monkeypatch):
    repository = tmp_path / "fixture-repository"
    repository.mkdir()
    (repository / "src").mkdir()
    (repository / "src" / "identity.py").write_text("# Synthetic source identity.\n")

    def git(*args):
        return subprocess.run(
            ("git", *args), cwd=repository, capture_output=True, check=True, text=True
        ).stdout.strip()

    git("init", "--quiet")
    git("add", "src")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "Synthetic identity",
    )
    revision = git("rev-parse", "HEAD")
    monkeypatch.setattr(etf_observations, "_REPOSITORY", repository)
    root, reports = tmp_path / "private-input", tmp_path / "private-reports"
    root.mkdir(mode=0o700)
    reports.mkdir(mode=0o700)
    tick = -1

    def utc():
        nonlocal tick
        tick += 1
        return START + timedelta(microseconds=tick)

    sink = EtfExecutionReceiptRecorder(
        root,
        repository,
        code_revision=revision,
        maximum_quote_age_ns=1_000_000_000,
        utc_now=utc,
        monotonic_ns=lambda: tick * 1000,
        provenance="synthetic",
        nonce="a" * 64,
    )
    yield repository, revision, root, reports, sink
    sink.close()


def decision(sink):
    frame = json.dumps(
        [
            {
                "T": "q",
                "S": "SPY",
                "t": START.isoformat(),
                "z": "B",
                "bp": 100,
                "ap": 100.1,
                "bs": 10,
                "as": 10,
                "bx": "P",
                "ax": "P",
                "c": ["R"],
            }
        ]
    ).encode()
    digest = sink.retain_source(frame)
    sink.record("alpaca_frame", {"frame_index": 0, "body_sha256": digest})
    observation = parse_alpaca_observation_frame(
        frame,
        frame_index=0,
        received_at_ns=parse_timestamp_ns((START + timedelta(microseconds=1)).isoformat()),
    )[0]
    sink.record(
        "decision",
        {
            "order_hash": "b" * 64,
            "side": "buy",
            "terms_hash": sink.retain_source(b"Synthetic terms"),
            "observation_hash": observation.observation_hash,
        },
    )


def invoke(root, checkpoint, reports):
    return CliRunner().invoke(
        etf_observations.app,
        [
            "link-costs",
            "--input-root",
            str(root),
            "--manifest-hash",
            checkpoint,
            "--report-dir",
            str(reports),
        ],
    )


def read_report(result, reports):
    output = json.loads(result.stdout)
    path = reports / (output["artifact_digest"] + ".observation-report.json")
    body = path.read_bytes()
    assert hashlib.sha256(body).hexdigest() == output["artifact_digest"]
    return output, json.loads(body)


def test_link_costs_private_revision_bound_report_is_deterministic_and_blocked(archive):
    repository, revision, root, reports, sink = archive
    checkpoint = sink.checkpoint()
    first = invoke(root, checkpoint, reports)
    assert first.exit_code == 2, first.output
    output, report = read_report(first, reports)
    assert report["status"] == "BLOCKED_INPUTS"
    assert report["calibrator_code_revision"] == revision
    assert report["receipt_checkpoint_hash"] == checkpoint
    assert report["incomplete_order_count"] == 0
    assert report["clock_session_attested"] is False
    assert report["customer_authenticated"] is False
    assert report["execution_enabled"] is False
    assert report["evidence_promotable"] is False
    assert report["calibration_status"] == "unverified"
    assert str(root) not in first.stdout and str(reports) not in first.stdout
    assert invoke(root, checkpoint, reports).stdout == first.stdout
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in reports.iterdir())
    normalized = reports / (output["input_sha256"] + ".cost-input.json")
    assert load_etf_cost_observations(normalized, reports, repository)["order_count"] == 0


def test_link_costs_pending_is_excluded_and_sources_are_copied(archive):
    repository, _, root, reports, sink = archive
    decision(sink)
    result = invoke(root, sink.checkpoint(), reports)
    assert result.exit_code == 2, result.output
    output, report = read_report(result, reports)
    assert report["incomplete_order_count"] == 1
    assert report["order_count"] == report["fill_count"] == 0
    assert report["unfilled_order_count"] == 0
    for digest in report["receipt_reference_hashes"]:
        assert (root / (digest + ".source")).read_bytes() == (
            reports / (digest + ".source")
        ).read_bytes()
    assert (
        load_etf_cost_observations(
            reports / (output["input_sha256"] + ".cost-input.json"),
            reports,
            repository,
        )["status"]
        == "BLOCKED_INPUTS"
    )


def test_link_costs_completed_synthetic_fill_is_never_qualified(archive):
    _, _, root, reports, sink = archive
    decision(sink)
    source = sink.retain_source(b"Synthetic broker response")
    sink.record("submitted", {"order_hash": "b" * 64, "source_hash": source})
    frame = json.dumps(
        [
            {
                "T": "q",
                "S": "SPY",
                "t": (START + timedelta(microseconds=3)).isoformat(),
                "z": "B",
                "bp": 100.1,
                "ap": 100.2,
                "bs": 10,
                "as": 10,
                "bx": "P",
                "ax": "P",
                "c": ["R"],
            }
        ]
    ).encode()
    sink.record("alpaca_frame", {"frame_index": 1, "body_sha256": sink.retain_source(frame)})
    sink.record("acknowledged", {"order_hash": "b" * 64, "source_hash": source})
    sink.record(
        "fill",
        {
            "order_hash": "b" * 64,
            "fill_hash": "c" * 64,
            "quantity": "2",
            "price": "100.2",
            "source_hash": source,
        },
    )
    sink.record(
        "terminal",
        {
            "order_hash": "b" * 64,
            "source_hash": source,
            "state": "filled",
            "charged_fees": {
                "commission": "0",
                "sec": "0",
                "taf": "0",
                "cat": "0.01",
                "other": "0",
                "total": "0.01",
                "source_hash": source,
            },
        },
    )
    result = invoke(root, sink.checkpoint(), reports)
    assert result.exit_code == 2, result.output
    _, report = read_report(result, reports)
    assert report["status"] == "OBSERVED_UNQUALIFIED"
    assert report["executed_notional_usd"] == "200.4"
    assert report["order_count"] == report["fill_count"] == 1
    assert report["charged_order_fee_usd"]["total"]["mean"] == "0.01"
    assert report["economic_verdict"] == "ECONOMIC_NO_GO"
    assert report["customer_authenticated"] is report["clock_session_attested"] is False


def test_invalid_manifest_denies_without_publication(archive):
    _, _, root, reports, _ = archive
    result = invoke(root, "d" * 64, reports)
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "status": "denied",
        "reason": "etf_observation_input_invalid",
    }
    assert list(reports.iterdir()) == []


def test_dirty_source_denies_before_private_input_reader(archive, monkeypatch):
    repository, _, root, reports, sink = archive
    checkpoint = sink.checkpoint()
    (repository / "src" / "identity.py").write_text("# Changed fixture.\n")

    def forbidden(*args):
        pytest.fail("private input opened before committed identity check")

    monkeypatch.setattr(etf_observations, "read_execution_receipts", forbidden)
    result = invoke(root, checkpoint, reports)
    assert result.exit_code == 1
    assert list(reports.iterdir()) == []


def test_source_changed_between_verification_and_copy_denies_report(archive, monkeypatch):
    _, _, root, reports, sink = archive
    decision(sink)
    checkpoint = sink.checkpoint()
    original = etf_observations.read_execution_receipts

    def mutate(*args):
        result = original(*args)
        path = root / (result["reference_hashes"][0] + ".source")
        path.write_bytes(b"Synthetic tampering")
        return result

    monkeypatch.setattr(etf_observations, "read_execution_receipts", mutate)
    result = invoke(root, checkpoint, reports)
    assert result.exit_code == 1
    assert not list(reports.glob("*.observation-report.json"))


def test_unsafe_report_directory_denies(archive):
    _, _, root, reports, sink = archive
    reports.chmod(0o755)
    result = invoke(root, sink.checkpoint(), reports)
    assert result.exit_code == 1
    assert list(reports.iterdir()) == []


def test_link_costs_never_opens_credentials_or_capture_transport(archive, monkeypatch):
    _, _, root, reports, sink = archive

    def forbidden(*args, **kwargs):
        pytest.fail("offline linkage called credential or capture path")

    monkeypatch.setattr(etf_observations, "capture_observations", forbidden)
    monkeypatch.setattr(etf_observations, "_read_private_file", forbidden)
    result = invoke(root, sink.checkpoint(), reports)
    assert result.exit_code == 2, result.output
