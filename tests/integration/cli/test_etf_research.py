"""Runnable offline commands remain broker/network incapable."""

import importlib
import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

ROOT = Path(__file__).parents[3]
runner = CliRunner()


def app():
    try:
        return importlib.import_module("trading_bot.cli.etf_research").app
    except ModuleNotFoundError:
        pytest.fail("Runnable ETF research commands are missing")


def test_account_fixture_command_runs_both_tiers_and_discloses_synthetic_economics():
    for capital in ("500", "1000"):
        result = runner.invoke(
            app(),
            [
                "account-fixture-run",
                "--capital",
                capital,
                "--operating-cost",
                ".25",
                "--config-dir",
                str(ROOT / "configs"),
            ],
        )
        assert result.exit_code == 0, result.stdout
        row = json.loads(result.stdout)
        assert row["cash"] == str(int(capital)) + ".1"
        assert row["trading_pnl"] == "0.1" and row["operating_profit"] == "-0.15"
        assert row["source_kind"] == "synthetic-account-facts-v1"
        assert row["economic_verdict"] == "ECONOMIC_NO_GO"
        assert row["live_authorized"] is False and row["evidence_promotable"] is False


def test_partial_fixture_has_no_forced_exit_or_completed_profit():
    result = runner.invoke(
        app(), ["account-fixture-run", "--scenario", "open", "--config-dir", str(ROOT / "configs")]
    )
    assert result.exit_code == 2
    row = json.loads(result.stdout)
    assert row["shares"] == "0.1" and row["trading_pnl"] is None
    assert row["reserved_trial_risk"] == "10.02"


def test_ledger_command_restarts_exact_partial_account_and_completes(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    args = [
        "account-checkpoint-run",
        "--output-dir",
        str(private),
        "--config-dir",
        str(ROOT / "configs"),
    ]
    first = runner.invoke(app(), [*args, "--through-events", "2"])
    assert first.exit_code == 2, first.stdout
    assert json.loads(first.stdout)["cash"] == "489.99"
    resumed = runner.invoke(app(), args)
    assert resumed.exit_code == 0, resumed.stdout
    assert json.loads(resumed.stdout)["cash"] == "500.1"
    repeated = runner.invoke(app(), args)
    assert repeated.exit_code == 0 and json.loads(repeated.stdout)["cash"] == "500.1"


def test_sqlite_path_binding_is_rejected_before_migration_or_mutation(tmp_path, monkeypatch):
    module = importlib.import_module("trading_bot.cli.etf_research")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)

    def forbidden(*args, **kwargs):
        pytest.fail("an unsupported path-bound SQLite migration was attempted")

    monkeypatch.setattr(module, "_prepare_fixture_ledger", forbidden, raising=False)
    result = runner.invoke(app(), ["account-ledger-run", "--output-dir", str(private)])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["reason"] == "etf_sqlite_path_binding_unsupported"
    assert list(private.iterdir()) == []


def test_checkpoint_publication_stays_in_verified_inode_after_ancestor_replacement(
    tmp_path, monkeypatch
):
    module = importlib.import_module("trading_bot.cli.etf_research")
    private, moved, foreign = tmp_path / "private", tmp_path / "moved", tmp_path / "foreign"
    private.mkdir(mode=0o700)
    foreign.mkdir(mode=0o700)
    sentinel = foreign / "unrelated.sqlite3"
    sentinel.write_bytes(b"unrelated database must not change")
    publish = module._publish

    def replace_parent(descriptor, name, body):
        publish(descriptor, name, body)
        if name == "owner.json":
            private.rename(moved)
            foreign.rename(private)

    monkeypatch.setattr(module, "_publish", replace_parent)
    result = runner.invoke(
        app(),
        [
            "account-checkpoint-run",
            "--output-dir",
            str(private),
            "--through-events",
            "2",
            "--config-dir",
            str(ROOT / "configs"),
        ],
    )
    assert result.exit_code == 2, result.stdout
    assert json.loads(result.stdout)["cash"] == "489.99"
    assert (private / "unrelated.sqlite3").read_bytes() == b"unrelated database must not change"
    assert set(p.name for p in private.iterdir()) == {"unrelated.sqlite3"}
    assert (moved / "etf-account-checkpoints" / "00000002.etf-checkpoint.json").is_file()


def test_corrupt_intermediate_checkpoint_and_missing_prefix_fail_closed(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    args = [
        "account-checkpoint-run",
        "--output-dir",
        str(private),
        "--through-events",
        "2",
        "--config-dir",
        str(ROOT / "configs"),
    ]
    assert runner.invoke(app(), args).exit_code == 2
    first = private / "etf-account-checkpoints" / "00000001.etf-checkpoint.json"
    body = first.read_bytes()
    first.write_bytes(body.replace(b'"state_hash":"', b'"state_hash":"f', 1))
    assert runner.invoke(app(), args).exit_code == 1
    first.unlink()
    assert runner.invoke(app(), args).exit_code == 1


def test_invalid_cost_cannot_create_a_checkpoint(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    result = runner.invoke(
        app(),
        [
            "account-checkpoint-run",
            "--output-dir",
            str(private),
            "--operating-cost",
            "NaN",
            "--config-dir",
            str(ROOT / "configs"),
        ],
    )
    assert result.exit_code == 1 and list(private.iterdir()) == []


def test_unknown_checkpoint_directory_is_not_adopted_or_mutated(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    child = private / "etf-account-checkpoints"
    child.mkdir(mode=0o700)
    other = child / "unrelated.txt"
    other.write_text("owned by a different workflow")
    result = runner.invoke(
        app(),
        [
            "account-checkpoint-run",
            "--output-dir",
            str(private),
            "--config-dir",
            str(ROOT / "configs"),
        ],
    )
    assert result.exit_code == 1
    assert set(path.name for path in child.iterdir()) == {"unrelated.txt"}
    assert other.read_text() == "owned by a different workflow"


@pytest.mark.parametrize("foreign_lock", ["nonempty", "hardlink"])
def test_foreign_lock_is_rejected_before_acquisition(tmp_path, foreign_lock):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    args = [
        "account-checkpoint-run",
        "--output-dir",
        str(private),
        "--through-events",
        "2",
        "--config-dir",
        str(ROOT / "configs"),
    ]
    assert runner.invoke(app(), args).exit_code == 2
    child = private / "etf-account-checkpoints"
    lock = child / "writer.lock"
    if foreign_lock == "nonempty":
        lock.write_bytes(b"owned by another workflow")
    else:
        os.link(lock, private / "unrelated-alias")
    names = set(os.listdir(child))
    assert runner.invoke(app(), args).exit_code == 1
    assert set(os.listdir(child)) == names


def test_unknown_capital_invalid_cost_and_unsafe_output_are_sanitized(tmp_path):
    for args in (
        ["account-fixture-run", "--capital", "1001"],
        ["account-fixture-run", "--operating-cost", "NaN"],
        ["account-checkpoint-run", "--output-dir", str(ROOT)],
        ["account-checkpoint-run", "--output-dir", str(tmp_path / "absent")],
    ):
        result = runner.invoke(app(), [*args, "--config-dir", str(ROOT / "configs")])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["reason"] == "etf_research_input_invalid"
        assert str(tmp_path) not in result.stdout


def test_operator_cannot_bless_data_or_enable_live():
    result = runner.invoke(app(), ["account-fixture-run", "--live"])
    assert result.exit_code != 0


def test_code_identity_binds_common_accounting_dependency(monkeypatch):
    module = importlib.import_module("trading_bot.cli.etf_research")
    original = module._code_hash()
    read = Path.read_bytes

    def changed(path):
        body = read(path)
        return (
            body + b"\n# changed accounting implementation\n"
            if path.name == "lifecycle_accounting.py"
            else body
        )

    monkeypatch.setattr(Path, "read_bytes", changed)
    assert module._code_hash() != original
    result = runner.invoke(app(), ["latest-vintage-run", "--assumptions-validated"])
    assert result.exit_code != 0
