"""Reference-screen command refuses unsupported inputs before publication."""

import importlib
import json
from pathlib import Path

from typer.testing import CliRunner

ROOT = Path(__file__).parents[3]


def test_reference_command_bad_inputs_fail_sanitized_without_output(tmp_path):
    module = importlib.import_module("trading_bot.cli.etf_research")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    result = CliRunner().invoke(
        module.app,
        [
            "benchmark-screen-run",
            "--capture-dir",
            str(private),
            "--manifest-hash",
            "a" * 64,
            "--reference-dir",
            str(private),
            "--calendar-hash",
            "b" * 64,
            "--issuer-hash",
            "c" * 64,
            "--report-dir",
            str(private),
            "--config-dir",
            str(ROOT / "configs"),
        ],
    )
    assert result.exit_code == 1, result.stdout
    assert json.loads(result.stdout)["reason"] == "etf_research_input_invalid"
    assert list(private.iterdir()) == []


def test_reference_command_has_no_fill_live_or_calibration_override():
    module = importlib.import_module("trading_bot.cli.etf_research")
    result = CliRunner().invoke(module.app, ["benchmark-screen-run", "--help"])
    assert result.exit_code == 0
    for option in ("--live", "--assumptions-validated", "--capital", "--cost-bps"):
        assert option not in result.stdout


def test_reference_publication_uses_held_directory_and_preregisters_before_results(
    tmp_path, monkeypatch
):
    from tests.unit.research.test_etf_benchmark_screen import inputs

    module = importlib.import_module("trading_bot.cli.etf_research")
    request = inputs()
    monkeypatch.setattr(module, "read_etf_native_bars", lambda *args, **kwargs: request.archive)
    monkeypatch.setattr(
        module, "_read_reference_inputs", lambda *args: (request.calendar, request.issuer)
    )
    private, moved, foreign = tmp_path / "private", tmp_path / "moved", tmp_path / "foreign"
    private.mkdir(mode=0o700)
    foreign.mkdir(mode=0o700)
    (foreign / "unrelated.json").write_bytes(b"unrelated")
    publish = module._publish
    calls = []

    def switched(descriptor, name, body):
        calls.append(json.loads(body)["schema"])
        publish(descriptor, name, body)
        if len(calls) == 1:
            private.rename(moved)
            foreign.rename(private)

    monkeypatch.setattr(module, "_publish", switched)
    result = CliRunner().invoke(
        module.app,
        [
            "benchmark-screen-run",
            "--capture-dir",
            str(private),
            "--manifest-hash",
            "a" * 64,
            "--reference-dir",
            str(private),
            "--calendar-hash",
            "b" * 64,
            "--issuer-hash",
            "c" * 64,
            "--report-dir",
            str(private),
            "--config-dir",
            str(ROOT / "configs"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert calls == ["etf-benchmark-screen-preregistration-v1", "etf-benchmark-screen-report-v1"]
    assert {path.name for path in private.iterdir()} == {"unrelated.json"}
    assert len(list(moved.iterdir())) == 2
    row = json.loads(result.stdout)
    assert row["holdout_evaluated"] is False and row["economic_verdict"] == "ECONOMIC_NO_GO"


def test_latest_signal_reports_also_keep_verified_output_inode(tmp_path, monkeypatch):
    from tests.unit.research.test_etf_latest_vintage import archive

    module = importlib.import_module("trading_bot.cli.etf_research")
    monkeypatch.setattr(module, "read_etf_native_bars", lambda *args, **kwargs: archive())
    private, moved, foreign = tmp_path / "private", tmp_path / "moved", tmp_path / "foreign"
    private.mkdir(mode=0o700)
    foreign.mkdir(mode=0o700)
    publish = module._publish
    calls = []

    def switched(descriptor, name, body):
        calls.append(name)
        publish(descriptor, name, body)
        if len(calls) == 1:
            private.rename(moved)
            foreign.rename(private)

    monkeypatch.setattr(module, "_publish", switched)
    result = CliRunner().invoke(
        module.app,
        [
            "latest-vintage-run",
            "--capture-dir",
            str(private),
            "--manifest-hash",
            "a" * 64,
            "--report-dir",
            str(private),
            "--config-dir",
            str(ROOT / "configs"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert list(private.iterdir()) == []
    assert len(list(moved.iterdir())) == 2
