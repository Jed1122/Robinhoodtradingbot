"""CI and local defaults must use the same stock/shared test and coverage scope."""

import shlex
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
PRIMARY = [
    "uv",
    "run",
    "pytest",
    "tests",
    "--cov",
    "--cov-branch",
    "--cov-fail-under=80",
    "--cov-report=json:coverage.json",
]
GATE = [
    "uv",
    "run",
    "python",
    "scripts/check_critical_branch_coverage.py",
    "--report",
    "coverage.json",
]


def test_ci_runs_one_stock_suite_then_mandatory_coverage_gates() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["quality"]
    assert job["strategy"]["matrix"]["python-version"] == ["3.12", "3.13", "3.14"]
    commands = [shlex.split(step["run"]) for step in job["steps"] if "run" in step]
    assert [command for command in commands if "pytest" in command] == [PRIMARY]
    assert commands[commands.index(PRIMARY) + 1] == GATE
    for scope in (workflow, job, *job["steps"]):
        assert not scope.get("continue-on-error", False)
        assert "if" not in scope
        assert "COVERAGE_FILE" not in scope.get("env", {})
        assert "working-directory" not in scope
    assert not (ROOT / ".github/workflows/options-research.yml").exists()
    assert "--project research" not in (ROOT / ".github/workflows/ci.yml").read_text()


def test_make_test_runs_same_suite_and_gates() -> None:
    text = (ROOT / "Makefile").read_text()
    target = text.split("\ntest:\n", 1)[1].split("\n\n", 1)[0]
    assert [shlex.split(line.strip()) for line in target.splitlines()] == [PRIMARY, GATE]
    assert "tests/deployment/test_backup_restore.py" not in text


def test_ci_configuration_checks_the_current_stock_composition() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["configuration"]["steps"]
    commands = "\n".join(step["run"] for step in steps if "run" in step)
    assert "infra/digitalocean" not in commands
    assert "docker compose -f compose.stock-research.yml config --quiet" in commands
    assert "infra/hybrid/deploy-remote.sh" in commands
