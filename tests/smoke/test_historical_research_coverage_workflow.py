"""Contract for combining main and native-research coverage before the safety gate."""

import shlex
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
import yaml
from packaging.specifiers import SpecifierSet
from packaging.utils import parse_wheel_filename

ROOT = Path(__file__).parents[2]
NATIVE_EPISODE = "tests/integration/simulation/test_options_historical_episode.py"
COVERAGE_FLAGS = [
    "--cov=trading_bot",
    "--cov-branch",
    "--cov-fail-under=80",
    "--cov-report=json:coverage.json",
]
HISTORICAL_TESTS = (
    "tests/unit/simulation/test_options_historical_execution.py",
    "tests/unit/simulation/test_options_historical_clock.py",
    "tests/unit/simulation/test_options_historical_policy.py",
    "tests/unit/simulation/test_options_historical_restart.py",
    "tests/unit/simulation/test_options_historical_restart_adversarial.py",
    "tests/integration/simulation/test_options_historical_order_steps.py",
    NATIVE_EPISODE,
)


def _workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())


def _commands(job: dict) -> list[list[str]]:
    return [shlex.split(step["run"]) for step in job["steps"] if "run" in step]


def test_quality_matrix_appends_native_coverage_before_the_existing_critical_gate() -> None:
    job = _workflow("ci.yml")["jobs"]["quality"]
    assert job["strategy"]["matrix"]["python-version"] == ["3.12", "3.13", "3.14"]
    commands = _commands(job)
    primary = ["uv", "run", "pytest", "tests", *COVERAGE_FLAGS]
    gate = [
        "uv",
        "run",
        "python",
        "scripts/check_critical_branch_coverage.py",
        "--report",
        "coverage.json",
    ]
    coverage_sequence = commands[commands.index(primary) : commands.index(gate) + 1]

    assert coverage_sequence == [
        primary,
        [
            "uv",
            "sync",
            "--project",
            "research",
            "--locked",
            "--all-groups",
            "--python",
            "${{ matrix.python-version }}",
        ],
        [
            "PYTHONPATH=src",
            "uv",
            "run",
            "--project",
            "research",
            "--no-sync",
            "pytest",
            NATIVE_EPISODE,
            "--cov=trading_bot",
            "--cov-branch",
            "--cov-append",
            "--cov-fail-under=80",
            "--cov-report=json:coverage.json",
        ],
        gate,
    ]


def test_quality_coverage_steps_share_default_storage_and_cannot_be_optional() -> None:
    workflow = _workflow("ci.yml")
    job = workflow["jobs"]["quality"]
    for scope in (workflow, job, *job["steps"]):
        assert "COVERAGE_FILE" not in scope.get("env", {})
        assert "working-directory" not in scope
        assert "working-directory" not in scope.get("defaults", {}).get("run", {})
    assert not job.get("continue-on-error", False)
    assert "if" not in job
    for step in job["steps"]:
        assert not step.get("continue-on-error", False)
        assert "if" not in step
        assert "COVERAGE_FILE=" not in step.get("run", "")


@pytest.mark.parametrize("test_path", HISTORICAL_TESTS)
def test_research_workflow_mandatorily_selects_historical_tests(test_path: str) -> None:
    job = _workflow("options-research.yml")["jobs"]["options-research"]
    commands = _commands(job)
    pytest_commands = [command for command in commands if "pytest" in command]
    assert len(pytest_commands) == 1
    command = pytest_commands[0]
    assert command[:7] == [
        "PYTHONPATH=src",
        "uv",
        "run",
        "--project",
        "research",
        "--no-sync",
        "pytest",
    ]
    assert test_path in command
    assert (ROOT / test_path).is_file()
    assert not any(token.startswith(("--ignore", "--deselect", "-k", "-m")) for token in command)
    assert "if" not in job
    assert not job.get("continue-on-error", False)
    for step in job["steps"]:
        assert "if" not in step
        assert not step.get("continue-on-error", False)


@pytest.mark.parametrize("package_name", ("quantlib", "duckdb", "databento-dbn", "zstandard"))
def test_locked_native_wheels_support_every_quality_matrix_python(package_name: str) -> None:
    versions = _workflow("ci.yml")["jobs"]["quality"]["strategy"]["matrix"]["python-version"]
    lock = tomllib.loads((ROOT / "research" / "uv.lock").read_text())
    packages = [package for package in lock["package"] if package["name"] == package_name]
    assert len(packages) == 1
    tags = {
        tag
        for wheel in packages[0]["wheels"]
        for tag in parse_wheel_filename(Path(unquote(urlparse(wheel["url"]).path)).name)[3]
        if tag.platform.startswith("manylinux") and tag.platform.endswith("x86_64")
    }
    supported_python = SpecifierSet(lock["requires-python"])
    for version in versions:
        assert version in supported_python
        interpreter = "cp" + version.replace(".", "")
        assert any(
            (tag.interpreter == interpreter and tag.abi == interpreter)
            or (
                tag.abi == "abi3"
                and tag.interpreter.startswith("cp3")
                and int(tag.interpreter[3:]) <= int(version.split(".")[1])
            )
            for tag in tags
        ), f"{package_name} has no locked Linux x86_64 wheel for Python {version}"
