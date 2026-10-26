"""Frozen offline price-study command; no accounts, provider calls or trade authority.

The actual input handoff is price-only. A successful command does not complete the
economic study, establish an edge or grant live activation. Full paths are private
compressed artifacts and all clocks, source hashes and assumptions are retained.
"""

import argparse
import dataclasses
import gzip
import hashlib
import io
import json
import os
import re
import stat
import uuid
from contextlib import suppress
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading_bot.domain import canonical_decimal_text
from trading_bot.market_data.recording import canonical_json
from trading_bot.runtime.stock_study_inputs import load_stock_study_inputs

FROZEN_MANIFEST_SHA256 = "07c8d3084ec7b199c8bc30944835b6b24aaf9110555a44c4b84a234cdb9dbae3"
_MAX_DOCUMENT_BYTES = 64 * 1024 * 1024


class _StudyEncoder(json.JSONEncoder):
    def default(self, value: Any) -> Any:
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {item.name: getattr(value, item.name) for item in dataclasses.fields(value)}
        if isinstance(value, Decimal):
            return canonical_decimal_text(value)
        if isinstance(value, datetime):
            return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
        if isinstance(value, date):
            return value.isoformat()
        raise TypeError("unsupported study document value")


def compress_study_document(document: dict[str, Any]) -> tuple[bytes, str, int]:
    """Stream canonical JSON to bounded gzip without copying every trace row."""
    encoder = _StudyEncoder(
        ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    output = io.BytesIO()
    digest = hashlib.sha256()
    size = 0
    with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed:
        for text in encoder.iterencode(document):
            chunk = text.encode("utf-8")
            size += len(chunk)
            if size > 512 * 1024 * 1024 or output.tell() > _MAX_DOCUMENT_BYTES:
                raise ValueError("stock_study_full_document_exceeds_limit")
            digest.update(chunk)
            compressed.write(chunk)
    raw = output.getvalue()
    if len(raw) > _MAX_DOCUMENT_BYTES:
        raise ValueError("stock_study_compressed_document_exceeds_limit")
    return raw, digest.hexdigest(), size


def _open_destination(root: Path, *, require_empty: bool = False) -> int:
    descriptor = -1
    try:
        if not isinstance(root, Path) or not root.is_absolute() or root.resolve() != root:
            raise ValueError
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or (require_empty and os.listdir(descriptor))
        ):
            raise ValueError
        return descriptor
    except (OSError, ValueError, TypeError):
        if descriptor >= 0:
            os.close(descriptor)
        raise ValueError("stock_study_publication_destination_invalid") from None


def publish_study_document(root: Path, raw: bytes, *, suffix: str) -> str:
    """Stage and atomically publish once; never expose a partial final artifact."""
    directory = descriptor = -1
    temporary: str | None = None
    linked = False
    name = ""
    try:
        if (
            type(raw) is not bytes
            or not 0 < len(raw) <= _MAX_DOCUMENT_BYTES
            or type(suffix) is not str
            or re.fullmatch(r"\.[a-z][a-z0-9.-]{0,39}", suffix) is None
        ):
            raise ValueError
        directory = _open_destination(root)
        name = hashlib.sha256(raw).hexdigest() + suffix
        temporary = ".pending-" + uuid.uuid4().hex
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
        )
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(descriptor)
        os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        linked = True
        os.unlink(temporary, dir_fd=directory)
        temporary = None
        os.fsync(directory)
        return name
    except (OSError, ValueError, TypeError):
        if linked:
            os.unlink(name, dir_fd=directory)
        raise ValueError("stock_study_publication_invalid") from None
    finally:
        if temporary is not None and directory >= 0:
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=directory)
        if descriptor >= 0:
            os.close(descriptor)
        if directory >= 0:
            os.close(directory)


def _sources() -> tuple[tuple[str, str], ...]:
    package = Path(__file__).resolve().parents[1]
    paths = sorted(package.rglob("*.py"))
    if not 1 <= len(paths) <= 2500:
        raise ValueError("stock_study_source_inventory_invalid")
    return tuple(
        (str(p.relative_to(package)), hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths
    )


def _compact(value: Any, *, key: str = "") -> Any:
    """Omit long path vectors from the summary; full original output is retained."""
    if key in {
        "rows",
        "bars",
        "path",
        "nav",
        "panel_nav",
        "trend_targets",
        "exposure_control_targets",
        "exposure_targets",
        "targets",
        "log_differences",
        "paired_log_differences",
        "log_difference_columns",
        "holdout_log_differences",
    }:
        return {"retained_in_full_artifact": True, "items": len(value)}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _compact(getattr(value, item.name), key=item.name)
            for item in dataclasses.fields(value)
        }
    if type(value) is dict:
        return {k: _compact(v, key=k) for k, v in value.items()}
    if type(value) in (list, tuple):
        return tuple(_compact(v) for v in value)
    return value


def run_bound_stock_price_study(
    *,
    evidence_directory: Path,
    manifest_path: Path,
    expected_manifest_sha256: str,
    expected_protocol_sha256: str,
    output_directory: Path,
) -> dict[str, Any]:
    """Run the single frozen first probe; no parameter search or holdout selection."""
    from trading_bot.research.stock_price_study import (
        PROTOCOL_HASH,
        StockStudyPanel,
        run_stock_price_study,
    )

    if expected_protocol_sha256 != PROTOCOL_HASH:
        raise ValueError("stock_study_protocol_hash_mismatch")
    if expected_manifest_sha256 != FROZEN_MANIFEST_SHA256:
        raise ValueError("stock_study_frozen_manifest_mismatch")
    destination = _open_destination(output_directory, require_empty=True)
    os.close(destination)
    started = datetime.now(UTC)
    sources = _sources()
    inputs = load_stock_study_inputs(
        evidence_directory, manifest_path, expected_manifest_sha256=expected_manifest_sha256
    )
    days = tuple(row.completed_at.date().isoformat() for row in inputs.bars[0])
    if (
        len(days) != 706
        or days[0] != "2024-01-02"
        or days[-1] != "2026-10-23"
        or days[199] != "2024-10-16"
        or days[200] != "2024-10-17"
        or days[437] != "2025-09-30"
        or days[438] != "2025-10-01"
        or inputs.membership_use_not_before != datetime(2024, 2, 15, tzinfo=UTC)
    ):
        raise ValueError("stock_study_frozen_window_mismatch")
    panel = StockStudyPanel(inputs.bars, inputs.opens_at, inputs.membership_use_not_before)
    result = run_stock_price_study(
        panel, training_last_session=437, first_execution_session=200, bootstrap_replicates=5000
    )
    if _sources() != sources:
        raise ValueError("stock_study_sources_changed_during_run")
    # Rebind originals after calculation before publishing any successful result.
    after = load_stock_study_inputs(
        evidence_directory, manifest_path, expected_manifest_sha256=expected_manifest_sha256
    )
    if after.evidence_hash != inputs.evidence_hash:
        raise ValueError("stock_study_inputs_changed_during_run")
    document = {
        "schema": "stock-price-study-run-v1",
        "kind": "retrospective_price_only_cost_ablation",
        "started_at": started,
        "completed_at": datetime.now(UTC),
        "manifest_sha256": inputs.manifest_sha256,
        "input_evidence_hash": inputs.evidence_hash,
        "original_input_sha256s": inputs.original_input_sha256s,
        "source_available_at": inputs.source_available_at,
        "source_sha256s": sources,
        "protocol_sha256": PROTOCOL_HASH,
        "price_currency": None,
        "distributions_taxes_and_operating_costs_evaluated": False,
        "economic_study_complete": False,
        "qualified": False,
        "investment_eligible": False,
        "live_enabled": False,
        "result": result,
    }
    raw, uncompressed_sha256, uncompressed_size = compress_study_document(document)
    full_name = publish_study_document(output_directory, raw, suffix=".study.json.gz")
    brief = {k: v for k, v in document.items() if k != "result"}
    brief["full_artifact"] = full_name
    brief["uncompressed_sha256"] = uncompressed_sha256
    brief["uncompressed_bytes"] = uncompressed_size
    brief["result"] = _compact(document["result"])
    summary_name = publish_study_document(
        output_directory, (canonical_json(brief) + "\n").encode(), suffix=".summary.json"
    )
    return {
        "summary_file": summary_name,
        "full_file": full_name,
        "protocol_sha256": PROTOCOL_HASH,
        "economic_study_complete": False,
        "live_enabled": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-directory", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--output-directory", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = run_bound_stock_price_study(
            evidence_directory=args.evidence_directory,
            manifest_path=args.manifest,
            expected_manifest_sha256=args.manifest_sha256,
            expected_protocol_sha256=args.protocol_sha256,
            output_directory=args.output_directory,
        )
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (ValueError, OSError):
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": "stock_price_study_rejected",
                    "economic_study_complete": False,
                    "live_enabled": False,
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
