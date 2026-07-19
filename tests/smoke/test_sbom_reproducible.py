import subprocess
import sys
from pathlib import Path


def test_sbom_is_reproducible() -> None:
    subprocess.run([sys.executable, "scripts/generate_sbom.py"], check=True)
    first = Path("docs/sbom.cdx.json").read_bytes()
    subprocess.run([sys.executable, "scripts/generate_sbom.py"], check=True)
    assert Path("docs/sbom.cdx.json").read_bytes() == first
