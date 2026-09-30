"""The uv interpreter request must match each declared CI job's Python."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    ("workflow", "job_name"),
    [
        ("ci.yml", "quality"),
        ("ci.yml", "bandit"),
        ("ci.yml", "locked-dependencies"),
        ("options-research.yml", "options-research"),
    ],
)
def test_uv_request_is_bound_to_the_job_interpreter(workflow: str, job_name: str) -> None:
    document = yaml.safe_load((ROOT / ".github" / "workflows" / workflow).read_text())
    job = document["jobs"][job_name]
    setup = [
        step for step in job["steps"] if step.get("uses", "").startswith("actions/setup-python@")
    ]
    assert len(setup) == 1
    expected = setup[0]["with"]["python-version"]
    inherited = {**document.get("env", {}), **job.get("env", {})}
    for step in job["steps"]:
        if "uv " in step.get("run", ""):
            effective = {**inherited, **step.get("env", {})}
            assert effective.get("UV_PYTHON") == expected
