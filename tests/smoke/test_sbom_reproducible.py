import hashlib
import json
import subprocess
import sys
from pathlib import Path


def test_sbom_is_reproducible_without_mutating_tracked_artifact(tmp_path: Path) -> None:
    tracked_artifact = Path("docs/sbom.cdx.json")
    tracked_before = tracked_artifact.read_bytes()
    first_output = tmp_path / "first.json"
    second_output = tmp_path / "second.json"

    subprocess.run(
        [sys.executable, "scripts/generate_sbom.py", "--output", str(first_output)],
        check=True,
    )
    subprocess.run(
        [sys.executable, "scripts/generate_sbom.py", "--output", str(second_output)],
        check=True,
    )

    first_bytes = first_output.read_bytes()
    second_bytes = second_output.read_bytes()
    expected_document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "components": [],
        "metadata": {
            "properties": [
                {
                    "name": "uv.lock.sha256",
                    "value": hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest(),
                }
            ]
        },
    }

    assert first_bytes == second_bytes
    assert json.loads(first_bytes) == expected_document
    assert tracked_artifact.read_bytes() == tracked_before
