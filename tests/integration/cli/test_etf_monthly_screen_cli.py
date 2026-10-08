"""Private fixture publication before outcomes. No actual licensed inputs."""

import importlib
import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.integration.cli.test_etf_daily_screen_cli import args as old_args
from tests.unit.simulation.test_etf_monthly_screen import inputs

ROOT = Path(__file__).parents[3]


def api():
    return importlib.import_module("trading_bot.cli.etf_monthly_research")


def args(private):
    return ["screen-run", *old_args(private)[1:]]


def fixtures(monkeypatch, module):
    from tests.fixtures.etf.monthly.fixtures import legacy_package
    from trading_bot.code_identity import CodeIdentity

    package = legacy_package()
    monkeypatch.setattr(module, "read_etf_native_bars", lambda *a, **kw: package.archive)
    monkeypatch.setattr(
        module, "_read_reference_inputs", lambda *a: (package.calendar, package.issuer)
    )
    monkeypatch.setattr(
        module,
        "resolve_code_identity",
        lambda *a: CodeIdentity("a" * 64, "b" * 40, False, None, False),
    )
    monkeypatch.setattr(module, "_code_hash", lambda: "c" * 64)

    def projected(study, *a):
        req = inputs()
        return replace(req, protocol=replace(req.protocol, study=study))

    monkeypatch.setattr(module, "make_etf_monthly_request", projected)


def test_absent_invalid_inputs_and_no_overrides_are_sanitized(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    result = CliRunner().invoke(api().app, args(private))
    assert result.exit_code == 1 and list(private.iterdir()) == []
    assert json.loads(result.stdout)["reason"] == "etf_monthly_input_invalid"
    help = CliRunner().invoke(api().app, ["screen-run", "--help"])
    assert help.exit_code == 0
    for option in (
        "--capital",
        "--live",
        "--holdout",
        "--cost-bps",
        "--window",
        "--support",
        "--credentials",
    ):
        assert option not in help.stdout


def test_preregistration_then_single_evaluation_then_private_result(tmp_path, monkeypatch):
    module = api()
    fixtures(monkeypatch, module)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    publish, evaluate = module._publish_report_fd, module.run_etf_monthly_economics
    calls = []

    def publishing(fd, payload):
        calls.append(
            "preregistration"
            if payload["schema"] == "etf-monthly-screen-preregistration-v1"
            else "result"
        )
        return publish(fd, payload)

    def evaluating(request):
        calls.append("evaluation")
        return evaluate(request)

    monkeypatch.setattr(module, "_publish_report_fd", publishing)
    monkeypatch.setattr(module, "run_etf_monthly_economics", evaluating)
    result = CliRunner().invoke(module.app, args(private))
    assert result.exit_code == 0, result.stdout
    assert calls == ["preregistration", "evaluation", "result"]
    documents = {
        json.loads(p.read_bytes())["schema"]: (p, json.loads(p.read_bytes()))
        for p in private.iterdir()
    }
    freeze_path, freeze = documents["etf-monthly-screen-preregistration-v1"]
    _, report = documents["etf-monthly-screen-report-v1"]
    assert report["preregistration_hash"] == freeze_path.name.split(".")[0]
    assert (
        freeze["holdout_exposure"] == "unknown"
        and freeze["development_previously_examined"] is True
    )
    assert report["holdout_evaluated"] is False and report["live_authorized"] is False
    assert (
        report["economic_admitted"]
        is report["source_qualified"]
        is report["cost_qualified"]
        is False
    )
    assert len(report["scores"]) == 24
    for path, _ in documents.values():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600 and path.stat().st_uid == os.getuid()
    assert str(private) not in result.stdout and "102.16" not in result.stdout
    assert json.loads(result.stdout)["disposition"] == "STOP_CANDIDATE"


@pytest.mark.parametrize("stage", ["before", "after"])
def test_failures_cannot_evaluate_without_freeze_or_publish_unfinished_results(
    stage, tmp_path, monkeypatch
):
    module = api()
    fixtures(monkeypatch, module)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)

    def failed(*a, **kw):
        raise ValueError("sensitive details")

    monkeypatch.setattr(
        module, "_publish_report_fd" if stage == "before" else "run_etf_monthly_economics", failed
    )
    if stage == "before":
        monkeypatch.setattr(
            module,
            "run_etf_monthly_economics",
            lambda *a: pytest.fail("evaluation before preregistration"),
        )
    result = CliRunner().invoke(module.app, args(private))
    assert result.exit_code == 1 and "sensitive details" not in result.stdout
    assert len(list(private.iterdir())) == (0 if stage == "before" else 1)


def test_output_descriptor_survives_directory_name_swap(tmp_path, monkeypatch):
    module = api()
    fixtures(monkeypatch, module)
    private, moved, foreign = tmp_path / "private", tmp_path / "moved", tmp_path / "foreign"
    private.mkdir(mode=0o700)
    foreign.mkdir(mode=0o700)
    publish = module._publish_report_fd

    def swapping(fd, payload):
        value = publish(fd, payload)
        if payload["schema"] == "etf-monthly-screen-preregistration-v1":
            private.rename(moved)
            foreign.rename(private)
        return value

    monkeypatch.setattr(module, "_publish_report_fd", swapping)
    result = CliRunner().invoke(module.app, args(private))
    assert result.exit_code == 0, result.stdout
    assert len(list(moved.iterdir())) == 2 and not list(private.iterdir())


def test_dirty_code_and_oversized_publication_deny_without_market_access(tmp_path, monkeypatch):
    from trading_bot.code_identity import CodeIdentity

    module = api()
    fixtures(monkeypatch, module)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    monkeypatch.setattr(
        module, "resolve_code_identity", lambda *a: CodeIdentity("a" * 64, None, True, None, True)
    )
    monkeypatch.setattr(
        module, "read_etf_native_bars", lambda *a, **kw: pytest.fail("dirty source opened inputs")
    )
    result = CliRunner().invoke(module.app, args(private))
    assert result.exit_code == 1 and not list(private.iterdir())
    fd = os.open(private, os.O_RDONLY)
    try:
        with pytest.raises(ValueError):
            module._publish_report_fd(fd, {"payload": "x" * (8 * 1024 * 1024)})
    finally:
        os.close(fd)


def test_executable_change_during_evaluation_preserves_only_preregistration(tmp_path, monkeypatch):
    module = api()
    fixtures(monkeypatch, module)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    evaluate = module.run_etf_monthly_economics

    def changed(request):
        result = evaluate(request)
        monkeypatch.setattr(module, "_code_hash", lambda: "f" * 64)
        return result

    monkeypatch.setattr(module, "run_etf_monthly_economics", changed)
    result = CliRunner().invoke(module.app, args(private))
    assert result.exit_code == 1 and len(list(private.iterdir())) == 1


@pytest.mark.parametrize("unsafe", ["symlink", "permissions", "inside-repo"])
def test_unsafe_output_roots_deny_before_evaluation(unsafe, tmp_path, monkeypatch):
    module = api()
    fixtures(monkeypatch, module)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private
    if unsafe == "symlink":
        output = tmp_path / "link"
        output.symlink_to(private, target_is_directory=True)
    elif unsafe == "permissions":
        private.chmod(0o755)
    else:
        monkeypatch.setattr(module, "_REPOSITORY", tmp_path)
        monkeypatch.setattr(
            module,
            "_load",
            lambda *a: importlib.import_module("trading_bot.config").load_config(
                ROOT / "configs/base.yaml",
                ROOT / "configs/etf/monthly/simulation.yaml",
                ROOT / "configs/safety-envelope.yaml",
                {},
            ),
        )
    monkeypatch.setattr(
        module,
        "run_etf_monthly_economics",
        lambda *a: pytest.fail("unsafe root evaluated outcomes"),
    )
    argv = args(private)
    argv[argv.index("--report-dir") + 1] = str(output)
    result = CliRunner().invoke(module.app, argv)
    assert result.exit_code == 1 and not list(private.iterdir())


def test_publication_cannot_overwrite_conflicting_bytes(tmp_path):
    module = api()
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    fd = os.open(root, os.O_RDONLY)
    try:
        value = {"schema": "fabricated-only", "value": 1}
        digest = module._publish_report_fd(fd, value)
        path = root / (digest + ".etf-report.json")
        path.write_bytes(b"unrelated-preserved-bytes")
        with pytest.raises(ValueError):
            module._publish_report_fd(fd, value)
        assert path.read_bytes() == b"unrelated-preserved-bytes"
    finally:
        os.close(fd)


def test_wrong_output_owner_deny_is_not_masked_by_source_success(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from trading_bot.market_data import bundle_store

    module = api()
    fixtures(monkeypatch, module)
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    original = bundle_store.os.fstat
    monkeypatch.setattr(
        bundle_store.os,
        "fstat",
        lambda fd: SimpleNamespace(st_mode=original(fd).st_mode, st_uid=os.geteuid() + 1),
    )
    result = CliRunner().invoke(module.app, args(root))
    assert result.exit_code == 1 and not list(root.iterdir())
