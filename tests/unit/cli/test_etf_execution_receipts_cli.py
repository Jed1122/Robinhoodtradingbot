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
from trading_bot.diagnostics.etf_fee_attachments import publish_fee_attachment, read_fee_attachment
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


def invoke(root, checkpoint, reports, fee_attachment_hash=None):
    options = []
    if fee_attachment_hash is not None:
        options = ["--fee-attachment-hash", fee_attachment_hash]
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
            *options,
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


class LaterClock:
    def now(self):
        return START + timedelta(days=2)


def terminal_without_fees(sink):
    decision(sink)
    source = sink.retain_source(b"Synthetic broker response without final fees")
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
            "charged_fees": None,
        },
    )
    checkpoint = sink.checkpoint()
    sink.close()
    return checkpoint


def fee_components():
    return {
        "commission": "0",
        "sec": "0.01",
        "taf": "0.02",
        "cat": "0",
        "other": "0",
        "total": "0.03",
    }


def attach_invoke(root, checkpoint, components, source):
    return CliRunner().invoke(
        etf_observations.app,
        [
            "attach-fees",
            "--input-root",
            str(root),
            "--manifest-hash",
            checkpoint,
            "--order-hash",
            "b" * 64,
            "--fee-components-file",
            str(components),
            "--fee-source-file",
            str(source),
        ],
    )


def fee_files(root):
    components = root / "synthetic-components.json"
    source = root / "synthetic-fee-document.txt"
    components.write_text(json.dumps(fee_components()))
    source.write_bytes(b"Synthetic final fee document")
    components.chmod(0o600)
    source.chmod(0o600)
    return components, source


def test_link_costs_attachment_measures_fees_copies_source_and_preserves_clocks(archive):
    repository, _, root, reports, sink = archive
    checkpoint = terminal_without_fees(sink)
    digest = publish_fee_attachment(
        root,
        checkpoint,
        order_hash="b" * 64,
        charged_fees=fee_components(),
        source=b"Synthetic final fee document",
        clock=LaterClock(),
        repository_root=repository,
    )
    result = invoke(root, checkpoint, reports, digest)
    assert result.exit_code == 2, result.output
    assert result.stdout, result.output
    _, report = read_report(result, reports)
    assert report["fee_attachment_hash"] == digest
    assert report["fee_observed_at"] == "2026-10-04T14:00:00.000000Z"
    assert report["charged_order_fee_usd"]["total"]["mean"] == "0.03"
    assert report["order_count"] == report["fill_count"] == 1
    assert report["customer_authenticated"] is report["calibration_verified"] is False
    assert report["execution_enabled"] is report["evidence_promotable"] is False
    source_hash = hashlib.sha256(b"Synthetic final fee document").hexdigest()
    assert source_hash in report["receipt_reference_hashes"]
    assert (reports / (source_hash + ".source")).read_bytes() == b"Synthetic final fee document"
    assert "0.03" not in result.stdout and "2026-10-04" not in result.stdout
    assert invoke(root, checkpoint, reports, digest).stdout == result.stdout


def test_link_costs_attachment_checkpoint_mismatch_denies_before_publication(archive):
    repository, _, root, reports, sink = archive
    prior = sink.checkpoint()
    checkpoint = terminal_without_fees(sink)
    digest = publish_fee_attachment(
        root,
        checkpoint,
        order_hash="b" * 64,
        charged_fees=fee_components(),
        source=b"Synthetic final fee document",
        clock=LaterClock(),
        repository_root=repository,
    )
    result = invoke(root, prior, reports, digest)
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["reason"] == "etf_observation_input_invalid"
    assert list(reports.iterdir()) == []


def test_attach_fees_private_revision_guarded_command_publishes_only_hash(archive, monkeypatch):
    repository, _, root, _, sink = archive
    checkpoint = terminal_without_fees(sink)
    components, source = fee_files(root)
    monkeypatch.setattr(etf_observations, "SystemClock", LaterClock)
    result = attach_invoke(root, checkpoint, components, source)
    assert result.exit_code == 2, result.output
    assert result.stdout, result.output
    output = json.loads(result.stdout)
    assert output["calibration_status"] == "unverified"
    assert output["evidence_promotable"] is output["execution_enabled"] is False
    linked = read_fee_attachment(root, output["fee_attachment_hash"], repository)
    assert linked["fee_observed_at"] == "2026-10-04T14:00:00.000000Z"
    assert linked["cost_input"]["orders"][0]["charged_fees"]["total"] == "0.03"
    assert str(root) not in result.stdout and "0.03" not in result.stdout
    assert "Synthetic" not in result.stdout and "2026-10-04" not in result.stdout
    assert attach_invoke(root, checkpoint, components, source).stdout == result.stdout


@pytest.mark.parametrize("bad", ["component_mode", "source_mode", "duplicate_component"])
def test_attach_fees_unsafe_or_ambiguous_private_input_denies_without_writes(archive, bad):
    _, _, root, _, sink = archive
    checkpoint = terminal_without_fees(sink)
    components, source = fee_files(root)
    if bad == "component_mode":
        components.chmod(0o644)
    elif bad == "source_mode":
        source.chmod(0o644)
    else:
        components.write_text('{"commission":"0","commission":"0"}')
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    result = attach_invoke(root, checkpoint, components, source)
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout) == {
        "status": "denied",
        "reason": "etf_observation_input_invalid",
    }
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}


def test_attach_fees_dirty_source_denies_before_private_reader(archive, monkeypatch):
    repository, _, root, _, sink = archive
    checkpoint = terminal_without_fees(sink)
    components, source = fee_files(root)
    (repository / "src" / "identity.py").write_text("# Changed fixture.\n")

    def forbidden(*args, **kwargs):
        pytest.fail("private fee file opened before committed identity check")

    monkeypatch.setattr(etf_observations, "_read_private_file", forbidden)
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    result = attach_invoke(root, checkpoint, components, source)
    assert result.exit_code == 1, result.output
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}
