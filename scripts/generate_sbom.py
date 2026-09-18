import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/sbom.cdx.json"))
    args = parser.parse_args()

    lock = Path("uv.lock").read_bytes()
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "components": [],
        "metadata": {
            "properties": [{"name": "uv.lock.sha256", "value": hashlib.sha256(lock).hexdigest()}]
        },
    }
    args.output.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
