"""Offline receipt-prefix reports using manufactured private archives only."""

import hashlib
import json
import stat
import subprocess

import pytest
from typer.testing import CliRunner

from trading_bot.cli import etf_observations as cli
from trading_bot.diagnostics import alpaca_observe as observe
from trading_bot.market_data.alpaca_observations import parse_alpaca_observation_frame
from trading_bot.market_data.recording import canonical_json


def publish(root, body, suffix):
    digest = hashlib.sha256(body).hexdigest()
    path = root / (digest + suffix)
    path.write_bytes(body)
    path.chmod(0o600)
    return digest


@pytest.fixture
def archive(tmp_path, monkeypatch):
    repository = tmp_path / "synthetic-repository"
    repository.mkdir()
    (repository / "src").mkdir()
    (repository / "src/identity.py").write_text("# synthetic source\n")
    for args in [
        ("init", "-q"),
        ("add", "src"),
        (
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "Synthetic identity",
        ),
    ]:
        subprocess.run(("git", *args), cwd=repository, check=True, capture_output=True)
    revision = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()
    monkeypatch.setattr(cli, "_REPOSITORY", repository)
    root, reports = tmp_path / "private-input", tmp_path / "private-reports"
    root.mkdir(mode=0o700)
    reports.mkdir(mode=0o700)
    plan = observe.ObservationPlan(
        code_revision="a" * 40,
        config_hash="b" * 64,
        prepared_at_ns=1,
        expires_at_ns=1 + 1800 * 10**9,
        credential_file=tmp_path / "absent/key.json",
        output_root=root,
        repository_root=repository,
        duration_seconds=1,
        max_frames=2,
    )
    publish(root, observe.encode_observation_plan(plan), ".observation-plan.json")
    receipts, observations, total = [], [], 0
    for index, (utc, mono, row) in enumerate(
        [
            (
                2,
                30,
                {
                    "T": "s",
                    "S": "SPY",
                    "t": "2026-10-01T13:59:59Z",
                    "sc": "H",
                    "sm": "Private invented halt",
                    "rc": "T1",
                    "rm": "test",
                    "z": "B",
                },
            ),
            (3, 70, None),
        ]
    ):
        body = json.dumps([] if row is None else [row]).encode()
        body_hash = publish(root, body, ".raw")
        parsed = parse_alpaca_observation_frame(body, frame_index=index, received_at_ns=utc)
        hashes = [o.observation_hash for o in parsed]
        receipt = {
            "schema": "alpaca-observation-receipt-v1",
            "plan_hash": plan.plan_hash,
            "frame_index": index,
            "body_sha256": body_hash,
            "received_at_ns": utc,
            "received_monotonic_ns": mono,
            "previous_receipt_hash": receipts[-1] if receipts else None,
            "observation_hashes": hashes,
        }
        receipts.append(
            publish(root, canonical_json(receipt).encode(), ".observation-receipt.json")
        )
        observations.extend(hashes)
        total += len(body)
    result = {
        "schema": "alpaca-observation-result-v2",
        "plan_hash": plan.plan_hash,
        "started_at_ns": 1,
        "finished_at_ns": 4,
        "receipt_hashes": receipts,
        "total_raw_bytes": total,
        "counts": {"quote": 0, "status": 1, "luld": 0},
        "termination": "frame_limit",
        "predecessor_result_hash": None,
        "segment_gap_before_start": True,
        "initial_control_state_verified": False,
        "transport_continuity_verified": False,
        "source_qualified": False,
        "execution_enabled": False,
        "evidence_promotable": False,
        "collection_started_monotonic_ns": 20,
        "collection_finished_monotonic_ns": 90,
    }
    digest = publish(root, canonical_json(result).encode(), ".observation-result.json")
    return repository, revision, root, reports, digest, receipts, observations


def invoke(archive, *, utc=4, mono=90):
    _, _, root, reports, digest, _, _ = archive
    return CliRunner().invoke(
        cli.app,
        [
            "stream-prefix",
            "--input-root",
            str(root),
            "--result-hash",
            digest,
            "--received-at-ns",
            str(utc),
            "--received-monotonic-ns",
            str(mono),
            "--report-dir",
            str(reports),
        ],
    )


@pytest.mark.parametrize(
    "utc,mono,frames,counts",
    [
        (4, 90, 2, {"quote": 0, "status": 1, "luld": 0}),
        (2, 90, 1, {"quote": 0, "status": 1, "luld": 0}),
        (4, 29, 0, {"quote": 0, "status": 0, "luld": 0}),
    ],
)
def test_prefix_private_report_has_exact_receipt_order_and_dual_cutoffs(
    archive, utc, mono, frames, counts
):
    _, revision, root, reports, digest, receipts, observations = archive
    result = invoke(archive, utc=utc, mono=mono)
    assert result.exit_code == 2, result.output
    output = json.loads(result.stdout)
    body = (reports / (output["artifact_digest"] + ".observation-report.json")).read_bytes()
    assert hashlib.sha256(body).hexdigest() == output["artifact_digest"]
    report = json.loads(body)
    assert report["schema"] == "alpaca-observation-prefix-report-v1"
    assert report["auditor_code_revision"] == revision
    assert report["result_hash"] == digest
    assert report["received_at_ns"] == utc and report["received_monotonic_ns"] == mono
    assert report["receipt_hashes"] == receipts[:frames]
    assert report["observation_hashes"] == (observations if frames else [])
    assert output["counts"] == report["counts"] == counts
    assert report["frame_count"] == frames
    assert report["status"] == ("OBSERVED_UNQUALIFIED" if frames else "BLOCKED_INPUTS")
    for key in ("source_qualified", "execution_enabled", "evidence_promotable", "live_enabled"):
        assert report[key] is False and output[key] is False
    assert "Private invented halt" not in body.decode() + result.stdout
    assert str(root) not in result.stdout and str(reports) not in result.stdout
    assert invoke(archive, utc=utc, mono=mono).stdout == result.stdout
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in reports.iterdir())


@pytest.mark.parametrize("case", ["dirty", "tampered", "nonprivate", "invalid_clock"])
def test_prefix_denies_without_publishing_or_exposing_private_values(archive, case):
    repository, _, root, reports, _, _, _ = archive
    if case == "dirty":
        (repository / "src/identity.py").write_text("# dirty synthetic source\n")
        # Invalid input would fail differently if private reads preceded revision validation.
        root.chmod(0o755)
    elif case == "tampered":
        path = next(root.glob("*.raw"))
        path.write_bytes(b"Private invented credential")
    elif case == "nonprivate":
        root.chmod(0o755)
    result = invoke(archive, utc=-1 if case == "invalid_clock" else 4)
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout) == {
        "status": "denied",
        "reason": "etf_observation_input_invalid",
    }
    assert not list(reports.iterdir())


def test_dirty_prefix_revision_gate_precedes_capture_read(archive, monkeypatch):
    repository = archive[0]
    (repository / "src/identity.py").write_text("# dirty synthetic source\n")

    def forbidden(*args, **kwargs):
        raise AssertionError("private reader was invoked before revision gate")

    monkeypatch.setattr(cli, "read_observation_capture", forbidden, raising=False)
    result = invoke(archive)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["reason"] == "etf_observation_input_invalid"


@pytest.mark.parametrize("invalid", ["SYNTHETIC_PRIVATE_MARKER", "1e3", "\u0661", "9" * 100])
@pytest.mark.parametrize("clock", ["utc", "mono"])
def test_malformed_clock_argument_is_sanitized_before_private_read(archive, invalid, clock):
    result = invoke(archive, **{clock: invalid})
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "status": "denied",
        "reason": "etf_observation_input_invalid",
    }
    assert invalid not in result.output
    assert not list(archive[3].iterdir())
