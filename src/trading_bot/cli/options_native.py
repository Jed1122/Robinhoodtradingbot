"""Offline native research callbacks with fixed, path-free console summaries."""

import hashlib
from pathlib import Path
from typing import Annotated

import typer

from trading_bot.config import LoadedConfig, load_config
from trading_bot.market_data.bundle_codec import _time
from trading_bot.market_data.databento_bar_models import NativeBarRequest
from trading_bot.market_data.databento_bar_store import stage_bars, verify_bar_stage
from trading_bot.market_data.options_session_inputs import _ns
from trading_bot.market_data.options_source_models import VerificationContext, check
from trading_bot.market_data.options_source_rules import reviewed_rulebook_hash, source_code_hash
from trading_bot.market_data.options_source_verify import verify_source_bundle
from trading_bot.market_data.options_source_wire import decode_source_bundle
from trading_bot.market_data.recording import canonical_json
from trading_bot.research.options_acquisition import build_coverage_manifest
from trading_bot.research.options_acquisition_wire import decode_coverage_requirements
from trading_bot.research.options_native_io import (
    decode_shortlist_index,
    read_native_document,
    write_native_report,
)
from trading_bot.research.options_shortlist_v2 import select_verified_shortlist
from trading_bot.research.options_shortlist_v2_wire import (
    decode_verified_shortlist_input,
    encode_verified_shortlist_result,
)

_ROOT = Path(__file__).resolve().parents[3]


def _load(config_dir: Path) -> LoadedConfig:
    return load_config(
        config_dir / "base.yaml",
        config_dir / "options/native-data/simulation.yaml",
        config_dir / "safety-envelope.yaml",
        {},
    )


def _emit(status: str, reasons: tuple[str, ...], **counts_and_hashes: object) -> None:
    typer.echo(
        canonical_json(
            {
                "status": status,
                "reasons": reasons,
                **counts_and_hashes,
                "production_eligible": False,
                "evidence_promotable": False,
                "download_authorized": False,
                "live_authorized": False,
            }
        )
    )


def _invalid() -> None:
    _emit("denied", ("native_input_or_storage_invalid",))
    raise typer.Exit(1)


def native_bars_import(
    source: Annotated[Path, typer.Argument()],
    start: Annotated[str, typer.Option()],
    end: Annotated[str, typer.Option()],
    output_root: Annotated[Path, typer.Option()],
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Import a private recorded bar batch. Integrity success is not source qualification."""
    try:
        loaded = _load(config_dir)
        path = stage_bars(
            source,
            output_root,
            expected=NativeBarRequest(_ns(_time(start)), _ns(_time(end))),
            loaded=loaded,
            repository_root=_ROOT,
        )
        result = verify_bar_stage(path, loaded=loaded, repository_root=_ROOT)
    except Exception:
        _invalid()
        return
    _emit(
        "integrity_verified",
        (),
        artifact_hash=result.manifest_hash,
        decoded_count=result.profile.decoded_count,
        accepted_count=result.profile.accepted_count,
        rejected_count=result.profile.rejected_count,
        duplicate_count=result.profile.duplicate_count,
    )


def native_source_verify(
    evidence: Annotated[Path, typer.Argument()],
    as_of: Annotated[str, typer.Option()],
    start: Annotated[str, typer.Option()],
    end: Annotated[str, typer.Option()],
    output_root: Annotated[Path, typer.Option()],
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Reverify private source facts against installed reviewed rules only."""
    try:
        loaded = _load(config_dir)
        bundle = decode_source_bundle(
            read_native_document(evidence, loaded=loaded, repository_root=_ROOT), loaded=loaded
        )
        context = VerificationContext(
            _ns(_time(as_of)),
            _ns(_time(start)),
            _ns(_time(end)),
            loaded.config_hash,
            source_code_hash(),
            reviewed_rulebook_hash(),
        )
        result = verify_source_bundle(bundle, context=context, loaded=loaded, repository_root=_ROOT)
        digest = write_native_report(output_root, result, loaded=loaded, repository_root=_ROOT)
    except Exception:
        _invalid()
        return
    _emit(result.status, result.reasons, artifact_hash=digest, finding_count=len(result.findings))
    if result.status != "verified":
        raise typer.Exit(2)


def native_options_shortlist(
    input_path: Annotated[Path, typer.Argument()],
    output_root: Annotated[Path, typer.Option()],
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Recompute a paired research shortlist from exact private native inputs."""
    try:
        loaded = _load(config_dir)
        request = decode_verified_shortlist_input(
            read_native_document(input_path, loaded=loaded, repository_root=_ROOT), loaded=loaded
        )
        result = select_verified_shortlist(request, loaded=loaded, repository_root=_ROOT)
        digest = write_native_report(output_root, result, loaded=loaded, repository_root=_ROOT)
    except Exception:
        _invalid()
        return
    reasons = tuple(sorted(set(result.reasons) | set(result.verification.reasons)))
    _emit(result.status, reasons, artifact_hash=digest, candidate_count=len(result.candidates))
    if result.status != "selected":
        raise typer.Exit(2)


class _ResultMismatch(ValueError):
    """A prior index must be regenerated after any input or installed-rule change."""


def options_coverage_manifest(
    results: Annotated[Path, typer.Argument()],
    output_root: Annotated[Path, typer.Option()],
    requirements: Annotated[Path | None, typer.Option()] = None,
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Recompute indexed inputs before planning explicit, non-authorizing coverage."""
    try:
        loaded = _load(config_dir)
        index = decode_shortlist_index(
            read_native_document(results, loaded=loaded, repository_root=_ROOT), loaded=loaded
        )
        study = (
            None
            if requirements is None
            else decode_coverage_requirements(
                read_native_document(requirements, loaded=loaded, repository_root=_ROOT),
                loaded=loaded,
            )
        )
        selected = []
        # The index already bounds entries and aggregate input bytes. Each
        # recomputation enforces its own record cap; summing per-session source
        # counts would incorrectly reject valid multi-session studies.
        for entry in index:
            body = read_native_document(entry.input.path, loaded=loaded, repository_root=_ROOT)
            check(
                len(body) == entry.input.byte_count
                and hashlib.sha256(body).hexdigest() == entry.input.sha256
            )
            request = decode_verified_shortlist_input(body, loaded=loaded)
            result = select_verified_shortlist(request, loaded=loaded, repository_root=_ROOT)
            if (
                hashlib.sha256(encode_verified_shortlist_result(result)).hexdigest()
                != entry.expected_result_hash
            ):
                raise _ResultMismatch()
            selected.append(result)
        check(len({row.session_id for row in selected}) == len(selected))
        manifest = build_coverage_manifest(tuple(selected), requirements=study, loaded=loaded)
        digest = write_native_report(output_root, manifest, loaded=loaded, repository_root=_ROOT)
    except _ResultMismatch:
        _emit("blocked", ("shortlist_result_identity_mismatch",))
        raise typer.Exit(2) from None
    except Exception:
        _invalid()
        return
    _emit(
        manifest.status,
        manifest.reasons,
        artifact_hash=digest,
        session_count=len(manifest.sessions),
        request_count=len(manifest.requests),
        incomplete_count=len(manifest.incomplete_obligations),
    )
    if manifest.status != "requirements_complete":
        raise typer.Exit(2)
