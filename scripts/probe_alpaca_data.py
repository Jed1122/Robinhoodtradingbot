"""Prepare an offline diagnostic; capture requires a separately approved exact scope."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from trading_bot.clock import SystemClock
from trading_bot.config import LoadedConfig, load_config
from trading_bot.diagnostics.alpaca_probe import (
    MAX_MANIFEST_BYTES,
    ProbeError,
    ProbeReceipt,
    _check,
    _digest,
    _parse_time,
    _path,
    capture_probe,
    decode_manifest,
    encode_manifest,
    manifest_sha256,
    prepare_probe,
)
from trading_bot.diagnostics.alpaca_probe_io import _publish_private_file, _read_private_file

ROOT = Path(__file__).resolve().parents[1]
_CHECKS = (
    "zero_cost_plan",
    "contractual_entitlement",
    "technical_access",
    "retention_rights",
    "original_bytes",
    "identity",
    "numeric_shape",
    "requested_history",
    "expected_slot_coverage",
    "interpolation_semantics",
    "event_session_timing",
    "historical_availability_revisions",
    "corporate_action_coverage",
    "historical_universe_evidence",
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse normally echoes invalid values, which may include operator mistakes/secrets.
        raise ProbeError("probe_manifest_invalid")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__, allow_abbrev=False)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true", help="Prepare offline (the default).")
    modes.add_argument(
        "--capture", action="store_true", help="Run an explicitly approved scope once."
    )
    parser.add_argument("--manifest-file", type=Path, required=True)
    parser.add_argument("--approved-manifest-sha256")
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--quarantine-root", type=Path)
    parser.add_argument("--requested-end")
    return parser


def _git(*arguments: str) -> str:
    binary = shutil.which("git", path=os.defpath)
    _check(binary is not None, "probe_scope_mismatch")
    # Fixed local read-only Git arguments, never a shell.
    result = subprocess.run(
        [str(binary), "-c", "core.fsmonitor=false", "-C", str(ROOT), *arguments],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
        shell=False,
        env={
            "PATH": os.defpath,
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        },
    )
    return result.stdout.strip()


def _identity(*, require_clean: bool) -> str:
    revision = _git("rev-parse", "HEAD")
    _check(_digest(revision, 40), "probe_scope_mismatch")
    _check(Path(_git("rev-parse", "--show-toplevel")).resolve() == ROOT, "probe_scope_mismatch")
    if require_clean:
        _check(not _git("status", "--porcelain", "--untracked-files=no"), "probe_scope_mismatch")
        _git(
            "ls-files",
            "--error-unmatch",
            "--",
            "scripts/probe_alpaca_data.py",
            "src/trading_bot/diagnostics/alpaca_probe.py",
            "src/trading_bot/diagnostics/alpaca_probe_io.py",
        )
    return revision


def _summary(
    *,
    now: datetime,
    status: str,
    code: str,
    loaded: LoadedConfig | None,
    digest: str | None,
    receipts: tuple[ProbeReceipt, ...],
) -> dict[str, object]:
    checks = {name: {"status": "not_checked", "evidence": "not_collected"} for name in _CHECKS}
    for name in (
        "contractual_entitlement",
        "retention_rights",
        "historical_availability_revisions",
    ):
        checks[name] = {"status": "unresolved", "evidence": "separate_primary_review_required"}
    checks["zero_cost_plan"]["evidence"] = "operator_handoff_not_authenticated"
    if len(receipts) == 2:
        for name in ("technical_access", "original_bytes"):
            checks[name] = {"status": "observed_pass", "evidence": "two_private_sample_receipts"}
    attempted_failure = code in {
        "probe_access_denied",
        "probe_rate_limited",
        "probe_http_failed",
        "probe_timeout",
        "probe_response_invalid",
        "probe_response_too_large",
        "probe_secret_echo",
    }
    if attempted_failure:
        checks["technical_access"] = {"status": "observed_fail", "evidence": code}
    return {
        "assessment_at": now.isoformat(),
        "status": status,
        "reason_code": code,
        "manifest_sha256": digest,
        "disposition": (
            "INSUFFICIENT_SOURCE_EVIDENCE"
            if receipts or attempted_failure
            else "BLOCKED_PREREQUISITES"
        ),
        "checks": checks,
        # Failure can follow a successfully published first sample; do not invent zero retention.
        "sample_count": len(receipts) if status != "blocked" else None,
        "minimum_history_bars": loaded.config.research.minimum_history_bars if loaded else None,
        "history_calendar_days": loaded.config.research.history_calendar_days if loaded else None,
        "sample_body_sha256": (
            [receipt.body_sha256 for receipt in receipts] if status != "blocked" else None
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """No implicit capture, credential discovery, endpoint override or trading operation."""
    clock = SystemClock()
    code, status, result_code = "probe_manifest_invalid", "blocked", 2
    loaded: LoadedConfig | None = None
    digest: str | None = None
    receipts: tuple[ProbeReceipt, ...] = ()
    try:
        args = _parser().parse_args(argv)
        if args.capture:
            _check(_digest(args.approved_manifest_sha256), "probe_scope_mismatch")
            _check(
                args.credential_file is None
                and args.quarantine_root is None
                and args.requested_end is None,
                "probe_scope_mismatch",
            )
        else:
            _check(args.approved_manifest_sha256 is None)
            _check(
                args.credential_file is not None
                and args.quarantine_root is not None
                and args.requested_end is not None
            )
        revision = _identity(require_clean=args.capture)
        loaded = load_config(
            ROOT / "configs/base.yaml",
            ROOT / "configs/backtest.yaml",
            ROOT / "configs/safety-envelope.yaml",
            environ={},
        )
        if args.capture:
            body = _read_private_file(
                args.manifest_file,
                repository_root=ROOT,
                max_bytes=MAX_MANIFEST_BYTES,
                code="probe_manifest_invalid",
            )
            manifest = decode_manifest(body)
            digest = manifest_sha256(manifest)
            _check(manifest.repository_root == ROOT, "probe_scope_mismatch")
            receipts = asyncio.run(
                capture_probe(
                    manifest,
                    approved_manifest_sha256=args.approved_manifest_sha256,
                    loaded=loaded,
                    active_code_revision=revision,
                    clock=clock,
                )
            )
            code, status, result_code = "probe_sample_retained", "capture_completed", 0
        else:
            manifest = prepare_probe(
                loaded,
                clock=clock,
                code_revision=revision,
                requested_end=_parse_time(args.requested_end),
                credential_file=args.credential_file,
                quarantine_root=args.quarantine_root,
                repository_root=ROOT,
            )
            _check(_path(args.manifest_file), "probe_path_invalid")
            _check(args.manifest_file != manifest.credential_file, "probe_path_invalid")
            # Refuse all existing entries without reading their content (including key mistakes).
            _check(
                not args.manifest_file.exists() and not args.manifest_file.is_symlink(),
                "probe_storage_failed",
            )
            _publish_private_file(
                args.manifest_file, encode_manifest(manifest), repository_root=ROOT
            )
            digest = manifest_sha256(manifest)
            code, status, result_code = "probe_prepared_offline", "prepared_offline", 0
    except ProbeError as error:
        code = error.code
    except Exception:
        # No argv, path, provider body, subprocess output or exception object escapes here.
        code = "probe_manifest_invalid"
    print(
        json.dumps(
            _summary(
                now=clock.now(),
                status=status,
                code=code,
                loaded=loaded,
                digest=digest,
                receipts=receipts,
            ),
            sort_keys=True,
            allow_nan=False,
        )
    )
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
