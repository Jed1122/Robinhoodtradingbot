"""Offline CLI executes real selection/storage without network or credential capability."""

import json
import os
import socket
import subprocess
import sys
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from tests.unit.research._options_shortlist_fixtures import imported_case, make_case
from trading_bot.cli.options_research import app
from trading_bot.research.options_shortlist_wire import encode_shortlist_input


@pytest.fixture(autouse=True)
def no_network_or_credentials(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("offline capability access denied")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    original = type(os.environ).__getitem__

    def checked(environ, key):
        if str(key).startswith(("DATABENTO", "ROBINHOOD", "ALPACA", "TRADING_BOT__")):
            raise AssertionError("credential or runtime environment access denied")
        return original(environ, key)

    monkeypatch.setattr(type(os.environ), "__getitem__", checked)


def prepare(tmp_path, case=None):
    root = tmp_path.resolve() / "private"
    root.mkdir(mode=0o700)
    path = root / "input.json"
    path.write_bytes(encode_shortlist_input(case or make_case()))
    path.chmod(0o600)
    return root, path


def invoke(root, path):
    return CliRunner().invoke(app, ["options-shortlist", str(path), "--output-dir", str(root)])


def test_reproducible_private_manifest_and_sanitized_summary(tmp_path):
    root, path = prepare(tmp_path)
    first, second = invoke(root, path), invoke(root, path)
    assert first.exit_code == second.exit_code == 0, first.output
    assert first.stdout == second.stdout
    row = json.loads(first.stdout)
    assert set(row) == {
        "status",
        "decision_sessions",
        "candidate_count",
        "denied_sessions",
        "reasons",
        "manifest_hash",
    }
    assert row["status"] == "selected" and row["candidate_count"] == 2
    assert str(root) not in first.stdout and "SPY   " not in first.stdout
    artifact = root / "options-shortlists" / (row["manifest_hash"] + ".json")
    result = json.loads(artifact.read_bytes())["result"]
    assert [c["kind"] for c in result["candidates"]] == ["call", "put"]
    for flag in (
        "production_eligible",
        "evidence_promotable",
        "download_authorized",
        "live_authorized",
    ):
        assert result[flag] is False


@pytest.mark.parametrize(
    "source,reason",
    [("missing", "prior_close_unavailable"), ("imported", "source_evidence_unverified")],
)
def test_valid_unselectable_data_has_explicit_no_candidate_manifest(tmp_path, source, reason):
    case = imported_case() if source == "imported" else replace(make_case(), closes=())
    root, path = prepare(tmp_path, case)
    result = invoke(root, path)
    assert result.exit_code == 0, result.output
    row = json.loads(result.stdout)
    assert row["status"] == "no_candidate"
    assert row["candidate_count"] == 0 and row["denied_sessions"] == 1
    assert row["reasons"] == [reason]


@pytest.mark.parametrize(
    "payload",
    [b"private malformed data", b"{}", b" " * 16777217],
    ids=["malformed", "empty", "oversized"],
)
def test_invalid_input_is_nonzero_sanitized_and_not_published(tmp_path, payload):
    root, path = prepare(tmp_path)
    path.write_bytes(payload)
    result = invoke(root, path)
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "status": "denied",
        "reason": "options_shortlist_input_invalid",
    }
    assert str(path) not in result.stdout
    assert not (root / "options-shortlists").exists()


def test_conflicting_output_and_storage_failures_remain_nonzero(tmp_path, monkeypatch):
    root, path = prepare(tmp_path)
    success = invoke(root, path)
    assert success.exit_code == 0, success.output
    digest = json.loads(success.stdout)["manifest_hash"]
    artifact = root / "options-shortlists" / (digest + ".json")
    artifact.write_bytes(b"preserve this")
    conflict = invoke(root, path)
    assert conflict.exit_code == 1
    assert json.loads(conflict.stdout)["reason"] == "shortlist_storage_conflict"
    assert artifact.read_bytes() == b"preserve this"

    def broken(*args, **kwargs):
        raise OSError("private failure details")

    monkeypatch.setattr(os, "fsync", broken)
    failed = invoke(root, path)
    assert failed.exit_code == 1
    assert "private failure details" not in failed.output


def test_help_has_no_trading_or_acquisition_controls():
    result = CliRunner().invoke(app, ["options-shortlist", "--help"])
    assert result.exit_code == 0
    for forbidden in ("--live", "--provider", "--token", "--download", "--balance", "--quote"):
        assert forbidden not in result.stdout


def test_import_and_invocation_are_guarded_before_composition(tmp_path):
    root, path = prepare(tmp_path)
    fake_credentials = tmp_path.resolve() / "fake-credentials.json"
    fake_credentials.write_text("fabricated secret sentinel")
    program = r"""
import os, pathlib, socket, sys, zoneinfo
repo = pathlib.Path.cwd().resolve()
root, source, forbidden = map(pathlib.Path, sys.argv[1:])
allowed = (repo / "src", repo / "configs", root,
           pathlib.Path(sys.prefix), pathlib.Path(sys.base_prefix))
system_metadata = pathlib.Path("/System/Library/CoreServices/SystemVersion.plist").resolve()
timezone_files = tuple((pathlib.Path(p) / "America/New_York").resolve() for p in zoneinfo.TZPATH)
def deny(*args, **kwargs):
    raise AssertionError("network forbidden")
socket.create_connection = socket.socket.connect = socket.socket.connect_ex = deny
original = type(os.environ).__getitem__
def environment(self, key):
    if str(key).startswith(("DATABENTO", "ROBINHOOD", "ALPACA", "TRADING_BOT__")):
        raise AssertionError("environment forbidden")
    return original(self, key)
type(os.environ).__getitem__ = environment
def audit(event, args):
    if event != "open" or isinstance(args[0], int):
        return
    name = os.fsdecode(args[0])
    flags = args[2]
    if isinstance(flags, int) and flags & os.O_DIRECTORY:
        return
    target = pathlib.Path(name)
    if not target.is_absolute() and target.name == name:
        if (name == "input.json" or name.startswith(".tmp-")
                or (len(name) == 69 and name.endswith(".json"))):
            return
    target = target.resolve()
    if target == system_metadata or target in timezone_files:
        return
    if not any(target.is_relative_to(base) for base in allowed):
        raise AssertionError("filesystem read forbidden")
sys.addaudithook(audit)
for check in (lambda: forbidden.read_bytes(), lambda: os.getenv("DATABENTO_API_KEY"),
              lambda: socket.create_connection(("localhost", 1))):
    try:
        check()
    except AssertionError:
        pass
    else:
        raise AssertionError("guard was not installed")
from typer.testing import CliRunner
from trading_bot.cli.options_research import app
result = CliRunner().invoke(app, ["options-shortlist", str(source), "--output-dir", str(root)])
assert result.exit_code == 0, repr(result.exception)
print(result.stdout, end="")
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(root), str(path), str(fake_credentials)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "selected"
