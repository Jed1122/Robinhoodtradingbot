"""Standalone offline native CLI: private inputs and non-promotable reports."""

import hashlib
import importlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.unit.market_data.test_etf_replay_adapter import inputs as inputs
from tests.unit.research.test_etf_costs import evidence
from trading_bot.market_data.etf_native_archive import EtfNativeQuotePagesArchive
from trading_bot.market_data.etf_replay_adapter import native_etf_dataset
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.etf_study import freeze_etf_study


def api():
    try:
        return importlib.import_module("trading_bot.cli.etf_native")
    except ModuleNotFoundError:
        pytest.fail("Standalone native ETF CLI is missing")


def save(root, body, suffix=".json"):
    encoded = body if isinstance(body, bytes) else canonical_json(body).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    path = root / (digest + suffix)
    path.write_bytes(encoded)
    path.chmod(0o600)
    return path


def metadata(**changes):
    return {
        "schema": "etf-native-instrument-v1",
        "instrument": {
            "id": "SPY",
            "symbol": "SPY",
            "asset_class": "equity",
            "provider_status": "unverified-research-input",
            "tradable": True,
            "fractional_eligible": False,
            "price_increment": "0.01",
            "quantity_increment": "1",
            "minimum_quantity": "1",
            "minimum_notional": "1",
            "maximum_quantity": None,
            "correlation_group": "US-equity",
            "observed_at": "2015-12-01T00:00:00.000000Z",
        }
        | changes,
    }


@pytest.fixture
def prepared(tmp_path, monkeypatch, inputs):
    module = api()
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    reports = root / "reports"
    reports.mkdir(mode=0o700)
    quote_archive = EtfNativeQuotePagesArchive(
        "1" * 64,
        replace(inputs["bars"].request, kind="quotes"),
        ("2" * 64,),
        (inputs["quotes"],),
        inputs["bars"].captured_at,
    )
    quote_hash = content_hash((quote_archive.archive_hash,))
    dataset = native_etf_dataset(
        inputs["bars"], inputs["quotes"], inputs["calendar"], inputs["distributions"], quote_hash
    )
    raw_path = save(root, b"Explicit synthetic cost source, never calibration.", ".raw")
    costs = replace(
        evidence(),
        intervals=tuple(replace(row, source_hash=raw_path.stem) for row in evidence().intervals),
    )
    monkeypatch.setattr(module, "_code_hash", lambda: "a" * 64)
    configs = Path(__file__).parents[3] / "configs"
    study = freeze_etf_study(
        module._load(configs),
        code_hash="a" * 64,
        source_plan_hash=dataset.dataset_hash,
        cost_plan_hash=costs.cost_hash,
        holdout_previously_examined=False,
    )
    cost_manifest = save(
        root,
        {
            "schema": "etf-cost-manifest-v1",
            "study_hash": study.study_hash,
            "cost_plan_hash": costs.cost_hash,
            "source_kind": costs.source_kind,
            "starts_at": study.requested_start,
            "ends_at": study.requested_end,
            "intervals": costs.intervals,
            "calibration_hashes": (),
        },
    )
    instrument_file = save(root, metadata())
    monkeypatch.setattr(module, "read_etf_native_bars", lambda *a, **k: inputs["bars"])
    monkeypatch.setattr(module, "read_etf_native_quote_pages", lambda *a, **k: quote_archive)
    monkeypatch.setattr(
        module, "_read_reference_inputs", lambda *a: (inputs["calendar"], inputs["distributions"])
    )
    args = [
        "--capture-dir",
        str(root),
        "--manifest-hash",
        "b" * 64,
        "--quote-capture-dir",
        str(root),
        "--quote-manifest-hash",
        "c" * 64,
        "--reference-dir",
        str(root),
        "--calendar-hash",
        "d" * 64,
        "--issuer-hash",
        "e" * 64,
        "--cost-manifest",
        str(cost_manifest),
        "--instrument-file",
        str(instrument_file),
        "--report-dir",
        str(reports),
        "--config-dir",
        str(configs),
    ]
    return module, args, reports, root, study


def test_native_history_publishes_preregistration_then_exact_nonpromotable_result(
    prepared, monkeypatch
):
    module, args, reports, _, study = prepared
    from trading_bot.simulation import etf_native_history

    original = etf_native_history.run_etf_history

    def audited(request, **kwargs):
        published = [json.loads(path.read_bytes()) for path in reports.iterdir()]
        assert any(row["schema"] == "etf-native-preregistration-v1" for row in published)
        return original(request, **kwargs)

    monkeypatch.setattr(etf_native_history, "run_etf_history", audited)
    result = CliRunner().invoke(module.app, ["history-run", *args])
    assert result.exit_code == 2, result.output
    summary = json.loads(result.output)
    assert summary["study_hash"] == study.study_hash
    assert summary["economic_verdict"] == "ECONOMIC_NO_GO"
    assert summary["execution_enabled"] is False and summary["evidence_promotable"] is False
    assert summary["holdout_evaluated"] is False
    saved = json.loads((reports / (summary["report_hash"] + ".etf-report.json")).read_bytes())
    assert saved["result"]["candidate"]["account"]["orders"] == []
    assert saved["result"]["candidate"]["account"]["cash"] == "500"
    assert "quotes" not in saved and "instrument" not in summary
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in reports.iterdir())


def test_native_economic_report_runs_both_capitals_and_every_scenario(prepared):
    module, args, reports, _, _ = prepared
    result = CliRunner().invoke(module.app, ["economic-report", *args])
    assert result.exit_code == 2, result.output
    summary = json.loads(result.output)
    assert summary["run_count"] == 6 and summary["economic_verdict"] == "ECONOMIC_NO_GO"
    documents = [json.loads(path.read_bytes()) for path in reports.iterdir()]
    runs = [row["result"] for row in documents if row["schema"] == "etf-native-history-report-v1"]
    assert {(r["initial_cash"], r["fill_scenario"]) for r in runs} == {
        (capital, scenario)
        for capital in ("500", "1000")
        for scenario in ("conservative", "base", "optimistic")
    }


def test_fixture_study_composes_real_engine_and_evaluator_without_native_inputs(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    result = CliRunner().invoke(api().app, ["fixture-study", "--report-dir", str(reports)])
    assert result.exit_code == 2, result.output
    summary = json.loads(result.output)
    assert summary["run_count"] == 6 and summary["source_kind"] == "synthetic"
    assert summary["economic_verdict"] == "ECONOMIC_NO_GO"
    assert summary["execution_enabled"] is summary["evidence_promotable"] is False
    histories = [json.loads(path.read_bytes()) for path in reports.iterdir()]
    base = next(
        item["result"]
        for item in histories
        if item["schema"] == "etf-native-history-report-v1"
        and item["result"]["initial_cash"] == "500"
        and item["result"]["fill_scenario"] == "base"
    )
    assert base["candidate"]["account"]["cash"] == "499.63553015"
    assert len(base["candidate"]["account"]["orders"]) == 2


def test_fixture_input_generation_never_evaluates_outcomes_before_preregistration(monkeypatch):
    from tests.unit.simulation.test_etf_history import study
    from trading_bot.simulation import etf_strategy_fixtures
    from trading_bot.simulation.etf_native_fixtures import synthetic_etf_history_request

    def unexpected(*args, **kwargs):
        pytest.fail("Fixture input assembly evaluated a strategy before preregistration")

    monkeypatch.setattr(etf_strategy_fixtures, "run_etf_fixture_strategy", unexpected)
    requests = tuple(
        synthetic_etf_history_request(study(), Decimal(capital), scenario)
        for capital in ("500", "1000")
        for scenario in ("conservative", "base", "optimistic")
    )
    assert len({item.dataset.dataset_hash for item in requests}) == 1
    assert len({item.costs.cost_hash for item in requests}) == 1
    assert len({item.instrument.data_hash for item in requests}) == 1


@pytest.mark.parametrize(
    "case",
    [
        "secret_error",
        "bad_cost_hash",
        "cost_study_mismatch",
        "mismatched_quotes",
        "bad_capital",
        "unsafe_instrument",
        "expected_without_checkpoint",
    ],
)
def test_bad_native_inputs_deny_without_outcome_publication_or_secret_echo(
    prepared, monkeypatch, case
):
    module, args, reports, root, _ = prepared
    if case == "secret_error":

        def denied(*args, **kwargs):
            raise ValueError("private-secret-sentinel")

        monkeypatch.setattr(module, "read_etf_native_bars", denied)
    elif case in ("bad_cost_hash", "cost_study_mismatch"):
        index = args.index("--cost-manifest") + 1
        path = Path(args[index])
        if case == "bad_cost_hash":
            path.write_bytes(path.read_bytes() + b" ")
        else:
            wire = json.loads(path.read_bytes())
            wire["study_hash"] = "0" * 64
            args[index] = str(save(root, wire))
    elif case == "mismatched_quotes":
        args += ["--quote-capture-dir", str(root)]
    elif case == "bad_capital":
        args += ["--capital", "5000"]
    elif case == "unsafe_instrument":
        args[args.index("--instrument-file") + 1] = str(
            save(root, metadata(fractional_eligible=True))
        )
    else:
        args += ["--expected-head", "a" * 64]
    result = CliRunner().invoke(module.app, ["history-run", *args])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["reason"] == "etf_native_input_invalid"
    assert "private-secret-sentinel" not in result.output
    assert list(reports.iterdir()) == []


def test_instrument_requires_private_hash_bound_strict_schema(tmp_path):
    tmp_path.chmod(0o700)
    file = save(tmp_path, metadata())
    result = api()._read_instrument(file)
    assert result.id == "SPY" and result.fractional_eligible is False
    assert result.data_hash == file.stem
    file.chmod(0o644)
    with pytest.raises(ValueError):
        api()._read_instrument(file)
    file.chmod(0o600)
    file.write_bytes(file.read_bytes() + b" ")
    with pytest.raises(ValueError):
        api()._read_instrument(file)


def test_symlinked_reports_fail_before_running_or_writing(prepared):
    module, args, reports, root, _ = prepared
    linked = root / "report-link"
    linked.symlink_to(reports, target_is_directory=True)
    args[args.index("--report-dir") + 1] = str(linked)
    result = CliRunner().invoke(module.app, ["history-run", *args])
    assert result.exit_code == 1
    assert list(reports.iterdir()) == []


def test_help_offers_no_live_or_assumptions_approval_flag():
    result = CliRunner().invoke(api().app, ["history-run", "--help"])
    assert result.exit_code == 0
    assert "--live" not in result.output and "--assumptions-validated" not in result.output


def test_native_checkpoint_prefix_and_resume_publish_same_result_as_uninterrupted(prepared):
    module, args, _, root, _ = prepared
    checkpoints = root / "checkpoints"
    checkpoints.mkdir(mode=0o700)
    first = CliRunner().invoke(
        module.app,
        ["history-run", *args, "--checkpoint-dir", str(checkpoints), "--through-ordinal", "2"],
    )
    assert first.exit_code == 2, first.output
    checkpoint = json.loads(first.output)
    assert checkpoint["source_count"] == 3 and checkpoint["checkpoint_head"]
    resumed = CliRunner().invoke(
        module.app,
        [
            "history-run",
            *args,
            "--checkpoint-dir",
            str(checkpoints),
            "--expected-head",
            checkpoint["checkpoint_head"],
        ],
    )
    full = CliRunner().invoke(module.app, ["history-run", *args])
    assert resumed.exit_code == full.exit_code == 2
    assert json.loads(resumed.output)["result_hash"] == json.loads(full.output)["result_hash"]
    stale = CliRunner().invoke(
        module.app,
        [
            "history-run",
            *args,
            "--checkpoint-dir",
            str(checkpoints),
            "--expected-head",
            checkpoint["checkpoint_head"],
        ],
    )
    assert stale.exit_code == 1


def test_existing_different_report_is_not_overwritten(prepared):
    module, args, reports, _, _ = prepared
    first = CliRunner().invoke(module.app, ["history-run", *args])
    assert first.exit_code == 2
    path = reports / (json.loads(first.output)["report_hash"] + ".etf-report.json")
    path.write_bytes(b"retained-conflicting-report")
    result = CliRunner().invoke(module.app, ["history-run", *args])
    assert result.exit_code == 1
    assert path.read_bytes() == b"retained-conflicting-report"


def test_output_publication_rejects_oversized_artifact_before_writing(tmp_path, monkeypatch):
    module = api()
    tmp_path.chmod(0o700)
    descriptor = module._open_root(tmp_path, module._REPOSITORY)
    monkeypatch.setattr(module, "_MAX_REPORT_BYTES", 16)
    try:
        with pytest.raises(ValueError):
            module._publish(descriptor, {"content": "x" * 17})
    finally:
        module.os.close(descriptor)
    assert list(tmp_path.iterdir()) == []
