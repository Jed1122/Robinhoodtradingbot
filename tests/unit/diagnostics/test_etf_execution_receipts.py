"""Owner-private durable synthetic recording; never broker activity."""

import json
import stat
from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.diagnostics.etf_execution_receipts import (
    EtfExecutionReceiptRecorder,
    read_execution_receipts,
)
from trading_bot.market_data.alpaca_native import parse_timestamp_ns
from trading_bot.market_data.alpaca_observations import parse_alpaca_observation_frame
from trading_bot.research.etf_execution_receipts import EtfReceiptError

START = datetime(2026, 10, 2, 14, tzinfo=UTC)


class Clocks:
    def __init__(self):
        self.tick = -1
        self.regress = False

    def utc(self):
        self.tick += 1
        return START + timedelta(microseconds=self.tick)

    def mono(self):
        return 0 if self.regress else self.tick * 10


def directories(tmp_path):
    root, repository = tmp_path / "private", tmp_path / "repository"
    root.mkdir(mode=0o700)
    repository.mkdir()
    return root, repository


def recorder(root, repository, clocks=None, nonce="a" * 64):
    clocks = clocks or Clocks()
    return EtfExecutionReceiptRecorder(
        root,
        repository,
        code_revision="b" * 40,
        maximum_quote_age_ns=1_000_000_000,
        provenance="synthetic",
        utc_now=clocks.utc,
        monotonic_ns=clocks.mono,
        nonce=nonce,
    )


def record_decision(sink):
    body = json.dumps(
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
    h = sink.retain_source(body)
    sink.record("alpaca_frame", {"frame_index": 0, "body_sha256": h})
    observation = parse_alpaca_observation_frame(
        body,
        frame_index=0,
        received_at_ns=parse_timestamp_ns((START + timedelta(microseconds=1)).isoformat()),
    )[0]
    terms = sink.retain_source(b"synthetic terms")
    sink.record(
        "decision",
        {
            "order_hash": "c" * 64,
            "side": "buy",
            "terms_hash": terms,
            "observation_hash": observation.observation_hash,
        },
    )


def test_checkpoint_survives_close_and_pending_order_remains_incomplete(tmp_path):
    root, repository = directories(tmp_path)
    sink = recorder(root, repository)
    record_decision(sink)
    checkpoint = sink.checkpoint()
    original = (root / (checkpoint + ".source")).read_bytes()
    sink.close()
    result = read_execution_receipts(root, checkpoint, repository)
    assert result["incomplete_order_count"] == 1
    assert result["cost_input"]["orders"] == []
    assert result["execution_enabled"] is False
    assert (root / (checkpoint + ".source")).read_bytes() == original
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in root.iterdir())
    with pytest.raises(EtfReceiptError):
        sink.record("submitted", {})


def test_checkpoint_prefix_is_immutable_and_later_receipts_are_separate(tmp_path):
    root, repository = directories(tmp_path)
    sink = recorder(root, repository)
    first = sink.checkpoint()
    record_decision(sink)
    second = sink.checkpoint()
    assert first != second
    assert read_execution_receipts(root, first, repository)["incomplete_order_count"] == 0
    assert read_execution_receipts(root, second, repository)["incomplete_order_count"] == 1
    sink.close()


def test_restart_uses_distinct_clock_session_and_cannot_reuse_attempt(tmp_path):
    root, repository = directories(tmp_path)
    first = recorder(root, repository)
    checkpoint = first.checkpoint()
    first.close()
    with pytest.raises(EtfReceiptError):
        recorder(root, repository)
    second = recorder(root, repository, nonce="d" * 64)
    assert second.checkpoint() != checkpoint
    second.close()


def test_clock_regression_poisoning_preserves_last_checkpoint(tmp_path):
    root, repository = directories(tmp_path)
    clocks = Clocks()
    sink = recorder(root, repository, clocks)
    record_decision(sink)
    checkpoint = sink.checkpoint()
    clocks.regress = True
    source = sink.retain_source(b"synthetic submission")
    with pytest.raises(EtfReceiptError):
        sink.record("submitted", {"order_hash": "c" * 64, "source_hash": source})
    with pytest.raises(EtfReceiptError):
        sink.checkpoint()
    assert read_execution_receipts(root, checkpoint, repository)["incomplete_order_count"] == 1
    sink.close()


def test_storage_failure_latches_writer_without_retry(monkeypatch, tmp_path):
    import trading_bot.diagnostics.etf_execution_receipts as module

    root, repository = directories(tmp_path)
    sink = recorder(root, repository)
    checkpoint = sink.checkpoint()

    def failed(*args):
        raise OSError("synthetic disk error")

    monkeypatch.setattr(module, "_publish", failed)
    with pytest.raises(EtfReceiptError, match="etf_execution_receipt_invalid"):
        sink.retain_source(b"synthetic source")
    monkeypatch.undo()
    with pytest.raises(EtfReceiptError):
        sink.retain_source(b"synthetic source")
    assert read_execution_receipts(root, checkpoint, repository)["completed_order_count"] == 0
    sink.close()


@pytest.mark.parametrize("bad", ["mode", "inside_repository", "symlink", "missing"])
def test_unsafe_private_paths_are_denied(tmp_path, bad):
    root, repository = directories(tmp_path)
    if bad == "mode":
        root.chmod(0o755)
    elif bad == "inside_repository":
        root = repository / "private"
        root.mkdir(mode=0o700)
    elif bad == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        root = alias
    elif bad == "missing":
        root = tmp_path / "missing"
    with pytest.raises(EtfReceiptError):
        recorder(root, repository)


def test_tampered_receipt_and_unsafe_file_modes_are_denied(tmp_path):
    root, repository = directories(tmp_path)
    sink = recorder(root, repository)
    record_decision(sink)
    checkpoint = sink.checkpoint()
    sink.close()
    manifest = json.loads((root / (checkpoint + ".source")).read_bytes())
    path = root / (manifest["receipt_hashes"][0] + ".source")
    path.chmod(0o644)
    with pytest.raises(EtfReceiptError):
        read_execution_receipts(root, checkpoint, repository)
    path.chmod(0o600)
    # Intentional tampering of a synthetic fixture, never a customer artifact.
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(EtfReceiptError):
        read_execution_receipts(root, checkpoint, repository)


def test_source_body_limit_is_enforced_and_latched(tmp_path):
    root, repository = directories(tmp_path)
    sink = recorder(root, repository)
    with pytest.raises(EtfReceiptError):
        sink.retain_source(b"x" * 1_048_577)
    with pytest.raises(EtfReceiptError):
        sink.checkpoint()
    sink.close()
