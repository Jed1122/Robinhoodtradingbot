"""Offline CLI can import synthetic licensed-format bytes but never grant readiness."""

import importlib
import json

import pytest

from tests.integration.market_data.test_databento_definitions import fixture, zstd
from tests.unit.market_data.test_databento_batch import make_batch, no_network  # noqa: F401


def api():
    try:
        return importlib.import_module("trading_bot.cli.databento_import")
    except ModuleNotFoundError:
        pytest.fail("offline definitions import command is not implemented")


def test_import_command_produces_verified_private_artifact_without_trading(tmp_path, capsys):
    source = make_batch(tmp_path, payload=zstd.ZstdCompressor().compress(fixture()))
    target = tmp_path / "staged"
    target.mkdir(mode=0o700)
    result = api().main(
        [
            "stage",
            "--source",
            str(source),
            "--output-root",
            str(target),
            "--parent",
            "SPY.OPT",
            "--start",
            "2023-01-01",
            "--end",
            "2026-01-01",
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert result == 0 and report["record_count"] == 2
    assert report["status"] == "definitions_staged"
    assert report["economic_evidence"] is False
    assert report["production_eligible"] is False
    assert report["network_used"] is False
    assert api().main(["verify", "--manifest", report["manifest"]]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "staged_integrity_verified"


def test_invalid_arguments_do_not_echo_secrets_or_paths(capsys):
    assert api().main(["stage", "--api-key", "DO-NOT-ECHO-TEST-SENTINEL"]) == 2
    captured = capsys.readouterr()
    assert "DO-NOT-ECHO" not in captured.out + captured.err
    assert json.loads(captured.out)["error"] == "databento_command_invalid"
