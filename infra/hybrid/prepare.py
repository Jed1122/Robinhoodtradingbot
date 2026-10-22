"""Prepare a reviewed clean source archive, including a freshly built dashboard."""

import argparse
import hashlib
import io
import subprocess
import tarfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
if subprocess.check_output(["git", "status", "--porcelain"], cwd=root):
    raise SystemExit("Refusing dirty source tree")
subprocess.run(["npm", "ci"], cwd=root / "dashboard", check=True)
subprocess.run(["npm", "run", "build"], cwd=root / "dashboard", check=True)
if subprocess.check_output(["git", "status", "--porcelain"], cwd=root):
    raise SystemExit("Build changed tracked source")
source = subprocess.check_output(["git", "archive", "HEAD"], cwd=root)
with (
    tarfile.open(fileobj=io.BytesIO(source)) as original,
    args.output.open("xb") as output,
    tarfile.open(fileobj=output, mode="w") as archive,
):
    for entry in original:
        archive.addfile(entry, original.extractfile(entry) if entry.isfile() else None)
    archive.add(root / "dashboard/dist", arcname="dashboard/dist")
print(hashlib.sha256(args.output.read_bytes()).hexdigest())
