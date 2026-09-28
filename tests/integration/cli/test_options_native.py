"""Credential-free command composition using only fabricated native archives."""

import builtins
import hashlib
import importlib
import json
import os
import socket
import subprocess
from dataclasses import replace
from datetime import timedelta

import pytest
from typer.testing import CliRunner

pytest.importorskip("duckdb")
pytest.importorskip("databento_dbn")

from tests.unit.market_data._options_source_fixtures import ROOT, config
from tests.unit.market_data._options_source_fixtures import private_file as fixture_file
from tests.unit.research.test_options_shortlist_v2 import arrangement, install_fixture_rules
from trading_bot.cli.options_research import app
from trading_bot.market_data.options_source_wire import encode_source_bundle
from trading_bot.research.options_shortlist_models import ShortlistCalendarDay
from trading_bot.research.options_shortlist_v2_wire import encode_verified_shortlist_input


def api():
    try:
        return importlib.import_module("trading_bot.research.options_native_io")
    except ModuleNotFoundError:
        pytest.fail("native private composition is missing")


def private_file(path, body):
    return fixture_file(path.parent, path.name, body)


def setup_case(tmp_path):
    value = arrangement(tmp_path / "case")
    source = private_file(tmp_path / "input.json", encode_verified_shortlist_input(value.request))
    evidence = private_file(tmp_path / "evidence.json", encode_source_bundle(value.request.bundle))
    output = tmp_path / "output"
    output.mkdir(mode=0o700)
    return value, source, evidence, output


def invoke(command, source, output, *extra):
    result = CliRunner().invoke(
        app, [command, str(source.path), "--output-root", str(output), *extra]
    )
    assert str(output.parent) not in result.output
    assert "SPY" not in result.output and "Traceback" not in result.output
    return result


def test_real_source_without_publication_evidence_stays_blocked(tmp_path):
    value, source, _, output = setup_case(tmp_path)
    claims = tuple(replace(c, published_at_ns=None) for c in value.request.bundle.claims)
    request = replace(value.request, bundle=replace(value.request.bundle, claims=claims))
    source = private_file(tmp_path / "unpublished.json", encode_verified_shortlist_input(request))
    result = invoke("native-options-shortlist", source, output)
    assert result.exit_code == 2, result.output
    body = json.loads(result.output)
    assert body["production_eligible"] is False
    assert "historical_availability_unverified" in body["reasons"]


@pytest.mark.parametrize(
    "command", ["native-source-verify", "native-options-shortlist", "options-coverage-manifest"]
)
def test_malformed_private_documents_have_sanitized_errors(tmp_path, command):
    source = private_file(tmp_path / "private-secret-name.json", b'{"private_payload":"SECRET"}')
    output = tmp_path / "out"
    output.mkdir(mode=0o700)
    extra = (
        [
            "--as-of",
            "2023-01-03T14:30:00.000000Z",
            "--start",
            "2023-01-02T14:30:00.000000Z",
            "--end",
            "2023-01-03T14:30:00.000000Z",
        ]
        if command == "native-source-verify"
        else []
    )
    result = invoke(command, source, output, *extra)
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["reasons"] == ["native_input_or_storage_invalid"]
    assert "SECRET" not in result.output and "private-secret-name" not in result.output


def test_offline_composition_cannot_read_credentials_or_send_network(tmp_path, monkeypatch):
    value, source, evidence, output = setup_case(tmp_path)
    install_fixture_rules(monkeypatch, value)
    native = importlib.import_module("trading_bot.cli.options_native")
    original_load = native.load_config
    calls = []

    def load(*args, **kwargs):
        assert args[-1] == {}
        calls.append("empty_environment")
        return original_load(*args, **kwargs)

    def denied(*args, **kwargs):
        raise AssertionError("offline capability forbidden")

    original_import = builtins.__import__

    def imports(name, *args, **kwargs):
        assert not name.startswith(("trading_bot.brokers", "httpx", "requests", "mcp"))
        return original_import(name, *args, **kwargs)

    original_get = os._Environ.__getitem__

    def env_get(self, key):
        assert not any(
            word in key.upper()
            for word in (
                "ROBINHOOD",
                "DATABENTO",
                "ALPACA",
                "TOKEN",
                "SECRET",
                "API_KEY",
                "LIVE_TRADING",
            )
        )
        return original_get(self, key)

    monkeypatch.setattr(native, "load_config", load)
    monkeypatch.setattr(builtins, "__import__", imports)
    monkeypatch.setattr(os._Environ, "__getitem__", env_get)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(os, "system", denied)
    shortlisted = invoke("native-options-shortlist", source, output)
    assert shortlisted.exit_code == 0, shortlisted.output
    verified = invoke(
        "native-source-verify",
        evidence,
        output,
        "--as-of",
        "2023-01-03T14:30:00.000000Z",
        "--start",
        "2023-01-02T14:30:00.000000Z",
        "--end",
        "2023-01-03T14:30:00.000000Z",
    )
    # Verification is scoped to the five submitted roles, not blanket qualification.
    assert verified.exit_code == 0, verified.output
    assert json.loads(verified.output)["finding_count"] == 5
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
                        "expected_result_hash": json.loads(shortlisted.output)["artifact_hash"],
                    }
                ],
            }
        ).encode(),
    )
    coverage = invoke("options-coverage-manifest", index, output)
    assert coverage.exit_code == 2
    assert "coverage_requirements_missing" in json.loads(coverage.output)["reasons"]
    bars_source = tmp_path / "case/bars/download"
    imported = CliRunner().invoke(
        app,
        [
            "native-bars-import",
            str(bars_source),
            "--start",
            "2023-01-02T00:00:00.000000Z",
            "--end",
            "2023-01-04T00:00:00.000000Z",
            "--output-root",
            str(output),
        ],
    )
    assert imported.exit_code == 0, imported.output
    assert len(calls) == 4


def test_saved_result_index_is_recomputed_before_coverage(tmp_path, monkeypatch):
    value, source, _, output = setup_case(tmp_path)
    install_fixture_rules(monkeypatch, value)
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
                        "expected_result_hash": "a" * 64,
                    }
                ],
            }
        ).encode(),
    )
    result = invoke("options-coverage-manifest", index, output)
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reasons"] == ["shortlist_result_identity_mismatch"]
    assert not list(output.rglob("*.json"))


def test_coverage_keeps_individually_bounded_sessions_when_total_records_exceed_limit(tmp_path):
    value, _, _, output = setup_case(tmp_path)
    settings = config().config.options.research_shortlist
    per_session_count = settings.max_input_records // 2 + 1
    padding_count = per_session_count - value.request.record_count
    first_day = value.request.session.calendar_days[0].trading_date
    # Fabricated calendar declarations exercise real record counting without generating
    # thousands of native files. The shipped rulebook still denies these source claims;
    # denied sessions must reach coverage planning just like other bounded diagnostics.
    calendar = (
        *(
            ShortlistCalendarDay(first_day - timedelta(days=offset), None)
            for offset in range(padding_count, 0, -1)
        ),
        *value.request.session.calendar_days,
    )
    entries = []
    for index in range(2):
        request = replace(
            value.request,
            session=replace(
                value.request.session,
                current=replace(
                    value.request.session.current, session_id=f"synthetic-index-session-{index}"
                ),
                calendar_days=calendar,
            ),
        )
        assert request.record_count == per_session_count <= settings.max_input_records
        source = private_file(
            tmp_path / f"input-{index}.json", encode_verified_shortlist_input(request)
        )
        shortlisted = invoke("native-options-shortlist", source, output)
        assert shortlisted.exit_code == 2, shortlisted.output
        summary = json.loads(shortlisted.output)
        assert summary["status"] == "no_candidate"
        assert "source_evidence_unverified" in summary["reasons"]
        entries.append(
            {
                "input": {
                    "path": str(source.path),
                    "sha256": source.sha256,
                    "byte_count": source.byte_count,
                },
                "expected_result_hash": summary["artifact_hash"],
            }
        )
    assert 2 * per_session_count > settings.max_input_records
    index = private_file(
        tmp_path / "index.json",
        json.dumps({"schema": "options-shortlist-index-v1", "entries": entries}).encode(),
    )
    result = invoke("options-coverage-manifest", index, output)
    assert result.exit_code == 2, result.output
    summary = json.loads(result.output)
    assert summary["status"] == "blocked"
    assert summary["reasons"] == ["coverage_requirements_missing"]
    assert summary["session_count"] == 2
    saved = json.loads((output / "manifests" / f"{summary['artifact_hash']}.json").read_bytes())
    assert len(saved["sessions"]) == 2
    assert all(session["input_record_count"] == per_session_count for session in saved["sessions"])
    assert not saved["economic_eligible"]


@pytest.mark.parametrize("change", ["duplicate", "extra", "wrong_hash", "oversized"])
def test_index_rejects_unbounded_duplicate_or_extra_identities(tmp_path, change):
    module = api()
    entry = {
        "input": {"path": str(tmp_path / "input"), "sha256": "b" * 64, "byte_count": 1},
        "expected_result_hash": "a" * 64,
    }
    body = {"schema": "options-shortlist-index-v1", "entries": [entry]}
    if change == "duplicate":
        body["entries"].append(entry)
    elif change == "extra":
        body["trusted"] = True
    elif change == "wrong_hash":
        entry["expected_result_hash"] = "invalid"
    else:
        entry["input"]["byte_count"] = (
            config().config.options.research_shortlist.max_input_bytes + 1
        )
    with pytest.raises(ValueError):
        module.decode_shortlist_index(json.dumps(body).encode(), loaded=config())


@pytest.mark.parametrize("mode", ["public", "hardlink", "symlink"])
def test_private_read_rejects_unsafe_paths(tmp_path, mode):
    module = api()
    source = private_file(tmp_path / "input", b"data")
    if mode == "public":
        source.path.chmod(0o644)
    elif mode == "hardlink":
        os.link(source.path, tmp_path / "alias")
    else:
        (tmp_path / "alias").symlink_to(source.path)
        source = replace(source, path=tmp_path / "alias")
    with pytest.raises(ValueError):
        module.read_native_document(source.path, loaded=config(), repository_root=ROOT)


@pytest.mark.parametrize(
    "failure", [OSError(28, "private disk full"), InterruptedError("private interruption")]
)
def test_report_publication_failure_preserves_existing_reports(tmp_path, monkeypatch, failure):
    module = api()
    value, _, _, output = setup_case(tmp_path)
    install_fixture_rules(monkeypatch, value)
    from tests.unit.research.test_options_shortlist_v2 import run

    report = run(value)
    digest = module.write_native_report(output, report, loaded=config(), repository_root=ROOT)
    path = output / "manifests" / f"{digest}.json"
    original = path.read_bytes()

    def fail(*args):
        raise failure

    monkeypatch.setattr(module, "_publish_checked", fail)
    with pytest.raises(ValueError):
        module.write_native_report(output, report, loaded=config(), repository_root=ROOT)
    assert path.read_bytes() == original
    assert hashlib.sha256(original).hexdigest() == digest
