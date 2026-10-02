"""Standalone, bounded offline native ETF replay/report commands; no transport."""

import hashlib
import os
from dataclasses import fields, replace
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, cast

import typer

from trading_bot.cli.etf_research import (
    _REPOSITORY,
    _code_hash,
    _load,
    _publish_report_fd,
    _read_reference_inputs,
)
from trading_bot.domain import AssetClass, Instrument, InstrumentId
from trading_bot.domain.decimal_utils import _require_sha256_hex, parse_decimal
from trading_bot.market_data.bundle_codec import (
    _array,
    _boolean,
    _decimal,
    _digest,
    _json,
    _mapping,
    _string,
    _time,
)
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.bundle_store import _open_root, _read
from trading_bot.market_data.etf_native_archive import (
    read_etf_native_bars,
    read_etf_native_quote_pages,
)
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.etf_costs import EtfCostEvidence, _cost_interval, load_etf_cost_evidence
from trading_bot.research.etf_study import freeze_etf_study
from trading_bot.simulation.etf_native_models import SCENARIOS, EtfHistoryRequest, EtfHistoryResult

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False, add_completion=False)
_MAX_REPORT_BYTES = 32 * 1048576
_LIMITS = BundleLimits(1048576, 1048576, 8388608, 10000, 16)
_ERRORS = (ValueError, TypeError, ArithmeticError, OSError, RuntimeError, AttributeError, KeyError)


def _require(value: bool) -> None:
    if not value:
        raise ValueError("etf_native_input_invalid")


def _invalid() -> None:
    typer.echo(canonical_json({"status": "denied", "reason": "etf_native_input_invalid"}))
    raise typer.Exit(1)


def _private_json(path: Path, maximum: int = 1048576) -> object:
    _require(path.is_absolute() and ".." not in path.parts and path.suffix == ".json")
    _require_sha256_hex(path.stem, "private input")
    descriptor = _open_root(path.parent, _REPOSITORY)
    try:
        body = _read(descriptor, path.name, maximum)
    finally:
        os.close(descriptor)
    _require(hashlib.sha256(body).hexdigest() == path.stem)
    return _json(body, max_bytes=maximum, limits=_LIMITS)


def _read_instrument(path: Path) -> Instrument:
    """Explicit integer-only input, not observed brokerage/fractional authority."""
    wrapper = _mapping(_private_json(path, 16384), {"schema", "instrument"})
    _require(wrapper["schema"] == "etf-native-instrument-v1")
    row = _mapping(
        wrapper["instrument"], {field.name for field in fields(Instrument)} - {"data_hash"}
    )
    _require(row["id"] == row["symbol"] == "SPY" and row["asset_class"] == "equity")
    _require(row["provider_status"] == "unverified-research-input")
    _require(row["correlation_group"] == "US-equity" and row["fractional_eligible"] is False)
    instrument = Instrument(
        InstrumentId("SPY"),
        "SPY",
        AssetClass.EQUITY,
        "unverified-research-input",
        _boolean(row["tradable"]),
        False,
        _decimal(row["price_increment"]),
        _decimal(row["quantity_increment"]),
        _decimal(row["minimum_quantity"]),
        _decimal(row["minimum_notional"]),
        None if row["maximum_quantity"] is None else _decimal(row["maximum_quantity"]),
        "US-equity",
        _time(row["observed_at"]),
        _digest(path.stem),
    )
    _require(instrument.quantity_increment >= 1 and instrument.minimum_quantity >= 1)
    return instrument


def _cost_preview(path: Path) -> EtfCostEvidence:
    """Read syntax to freeze identity; the unchanged source loader must validate it."""
    row = _mapping(
        _private_json(path),
        {
            "schema",
            "study_hash",
            "cost_plan_hash",
            "source_kind",
            "starts_at",
            "ends_at",
            "intervals",
            "calibration_hashes",
        },
    )
    _require(row["schema"] == "etf-cost-manifest-v1")
    preview = EtfCostEvidence(
        tuple(_cost_interval(item) for item in _array(row["intervals"])),
        cast(Literal["synthetic", "recorded"], _string(row["source_kind"])),
        tuple(_digest(item) for item in _array(row["calibration_hashes"])),
    )
    _require(preview.cost_hash == row["cost_plan_hash"])
    return preview


def _native_request(
    capture_dir: Path,
    manifest_hash: str,
    quote_capture_dir: list[Path],
    quote_manifest_hash: list[str],
    reference_dir: Path,
    calendar_hash: str,
    issuer_hash: str,
    cost_manifest: Path,
    instrument_file: Path,
    config_dir: Path,
) -> EtfHistoryRequest:
    from trading_bot.market_data.etf_replay_adapter import native_etf_dataset

    _require(0 < len(quote_capture_dir) == len(quote_manifest_hash) <= 128)
    bars = read_etf_native_bars(capture_dir, manifest_hash, repository_root=_REPOSITORY)
    archives = []
    total = 0
    for root, digest in zip(quote_capture_dir, quote_manifest_hash, strict=True):
        source = read_etf_native_quote_pages(root, digest, repository_root=_REPOSITORY)
        total += source.record_count
        _require(total <= 128000)
        archives.append(source)
    _require(len({archive.archive_hash for archive in archives}) == len(archives))
    quotes = tuple(
        sorted(
            (row for archive in archives for page in archive.pages for row in page),
            key=lambda row: row.timestamp_ns,
        )
    )
    calendar, distributions = _read_reference_inputs(reference_dir, calendar_hash, issuer_hash)
    dataset = native_etf_dataset(
        bars,
        quotes,
        calendar,
        distributions,
        content_hash(tuple(archive.archive_hash for archive in archives)),
    )
    instrument = _read_instrument(instrument_file)
    preview = _cost_preview(cost_manifest)
    study = freeze_etf_study(
        _load(config_dir),
        code_hash=_code_hash(),
        source_plan_hash=dataset.dataset_hash,
        cost_plan_hash=preview.cost_hash,
        holdout_previously_examined=False,
    )
    costs = load_etf_cost_evidence(cost_manifest, cost_manifest.parent, study)
    _require(costs == preview)
    return EtfHistoryRequest(study, dataset, costs, Decimal("500"), "base", instrument)


def _publish(descriptor: int, report: dict[str, object]) -> str:
    _require(len(canonical_json(report).encode()) <= _MAX_REPORT_BYTES)
    return _publish_report_fd(descriptor, report)


def _preregister(descriptor: int, requests: tuple[EtfHistoryRequest, ...]) -> str:
    _require(bool(requests))
    return _publish(
        descriptor,
        {
            "schema": "etf-native-preregistration-v1",
            "study": requests[0].study,
            "dataset_hash": requests[0].dataset.dataset_hash,
            "cost_hash": requests[0].costs.cost_hash,
            "instrument_hash": content_hash(requests[0].instrument),
            "schedule": requests[0].schedule,
            "request_hashes": tuple(r.input_hash for r in requests),
            "source_kind": requests[0].dataset.source_kind,
            "instrument_metadata_verified": False,
            "lifecycle_assumptions_verified": False,
            "economic_verdict": "NOT_EVALUATED",
            "holdout_evaluated": False,
            "execution_enabled": False,
            "evidence_promotable": False,
            "live_authorized": False,
        },
    )


def _history_document(result: EtfHistoryResult, preregistration_hash: str) -> dict[str, object]:
    return {
        "schema": "etf-native-history-report-v1",
        "preregistration_hash": preregistration_hash,
        "result": result,
        "result_hash": result.result_hash,
        "economic_verdict": "ECONOMIC_NO_GO",
        "holdout_evaluated": False,
        "execution_enabled": False,
        "evidence_promotable": False,
        "live_authorized": False,
    }


def _summary(report_hash: str, request: EtfHistoryRequest, **extra: object) -> None:
    typer.echo(
        canonical_json(
            {
                "report_hash": report_hash,
                "study_hash": request.study.study_hash,
                "source_kind": request.dataset.source_kind,
                "economic_verdict": "ECONOMIC_NO_GO",
                "holdout_evaluated": False,
                "execution_enabled": False,
                "evidence_promotable": False,
                "live_authorized": False,
                **extra,
            }
        )
    )


def _run_economics(requests: tuple[EtfHistoryRequest, ...], report_dir: Path) -> None:
    from trading_bot.research.etf_full_economics import evaluate_etf_economics
    from trading_bot.simulation.etf_native_history import run_etf_history

    descriptor = _open_root(report_dir, _REPOSITORY)
    try:
        preregistration = _preregister(descriptor, requests)
        results = tuple(run_etf_history(request) for request in requests)
        history_hashes = tuple(
            _publish(descriptor, _history_document(result, preregistration)) for result in results
        )
        report = evaluate_etf_economics(requests[0].study, results, requests[0].costs)
        digest = _publish(
            descriptor,
            {
                "schema": "etf-native-economic-report-v1",
                "preregistration_hash": preregistration,
                "history_report_hashes": history_hashes,
                "report": report,
                "economic_report_hash": report.report_hash,
                "economic_verdict": "ECONOMIC_NO_GO",
                "execution_enabled": False,
                "evidence_promotable": False,
                "live_authorized": False,
                "holdout_evaluated": False,
            },
        )
    finally:
        os.close(descriptor)
    _summary(digest, requests[0], run_count=len(results))


@app.command("history-run")
def history_run(
    capture_dir: Annotated[Path, typer.Option()],
    manifest_hash: Annotated[str, typer.Option()],
    quote_capture_dir: Annotated[list[Path], typer.Option()],
    quote_manifest_hash: Annotated[list[str], typer.Option()],
    reference_dir: Annotated[Path, typer.Option()],
    calendar_hash: Annotated[str, typer.Option()],
    issuer_hash: Annotated[str, typer.Option()],
    cost_manifest: Annotated[Path, typer.Option()],
    instrument_file: Annotated[Path, typer.Option()],
    report_dir: Annotated[Path, typer.Option()],
    capital: Annotated[str, typer.Option()] = "500",
    scenario: Annotated[str, typer.Option()] = "base",
    checkpoint_dir: Annotated[Path | None, typer.Option()] = None,
    through_ordinal: Annotated[int | None, typer.Option()] = None,
    expected_head: Annotated[str | None, typer.Option()] = None,
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Replay saved development observations; missing semantics remain blocking."""
    descriptor = -1
    try:
        _require(capital in ("500", "1000") and scenario in SCENARIOS)
        _require(expected_head is None or checkpoint_dir is not None)
        _require(through_ordinal is None or through_ordinal >= 0)
        if expected_head is not None:
            _require_sha256_hex(expected_head, "expected checkpoint head")
        request = replace(
            _native_request(
                capture_dir,
                manifest_hash,
                quote_capture_dir,
                quote_manifest_hash,
                reference_dir,
                calendar_hash,
                issuer_hash,
                cost_manifest,
                instrument_file,
                config_dir,
            ),
            initial_cash=parse_decimal(capital),
            fill_scenario=scenario,
        )
        descriptor = _open_root(report_dir, _REPOSITORY)
        preregistration = _preregister(descriptor, (request,))
        head = None
        if checkpoint_dir is None:
            from trading_bot.simulation.etf_native_history import run_etf_history

            result = run_etf_history(request, through_ordinal=through_ordinal)
        else:
            from trading_bot.persistence.etf_native_checkpoint import advance_etf_native_checkpoint

            checkpoint = advance_etf_native_checkpoint(
                checkpoint_dir,
                request,
                repository_root=_REPOSITORY,
                through_ordinal=through_ordinal,
                expected_head=expected_head,
            )
            result, head = checkpoint.result, checkpoint.head_hash
        digest = _publish(descriptor, _history_document(result, preregistration))
    except _ERRORS:
        _invalid()
        return
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    _summary(
        digest,
        request,
        source_count=result.source_count,
        result_hash=result.result_hash,
        checkpoint_head=head,
    )
    raise typer.Exit(2)


@app.command("economic-report")
def economic_report(
    capture_dir: Annotated[Path, typer.Option()],
    manifest_hash: Annotated[str, typer.Option()],
    quote_capture_dir: Annotated[list[Path], typer.Option()],
    quote_manifest_hash: Annotated[list[str], typer.Option()],
    reference_dir: Annotated[Path, typer.Option()],
    calendar_hash: Annotated[str, typer.Option()],
    issuer_hash: Annotated[str, typer.Option()],
    cost_manifest: Annotated[Path, typer.Option()],
    instrument_file: Annotated[Path, typer.Option()],
    report_dir: Annotated[Path, typer.Option()],
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Run both fixed cash tiers and all three frozen scenarios, then evaluate."""
    try:
        base = _native_request(
            capture_dir,
            manifest_hash,
            quote_capture_dir,
            quote_manifest_hash,
            reference_dir,
            calendar_hash,
            issuer_hash,
            cost_manifest,
            instrument_file,
            config_dir,
        )
        requests = tuple(
            replace(base, initial_cash=cash, fill_scenario=scenario)
            for cash in base.study.capital_tiers
            for scenario in SCENARIOS
        )
        _run_economics(requests, report_dir)
    except _ERRORS:
        _invalid()
        return
    raise typer.Exit(2)


@app.command("fixture-study")
def fixture_study(
    report_dir: Annotated[Path, typer.Option()],
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Run six explicitly fictional inputs through the real offline stack."""
    try:
        from trading_bot.simulation.etf_native_fixtures import synthetic_etf_history_request

        policy = _load(config_dir)
        provisional = freeze_etf_study(
            policy,
            code_hash=_code_hash(),
            source_plan_hash=content_hash("fixture-input-assembly"),
            cost_plan_hash=content_hash("fixture-cost-assembly"),
            holdout_previously_examined=False,
        )
        assembled = synthetic_etf_history_request(provisional, Decimal("500"))
        study = freeze_etf_study(
            policy,
            code_hash=provisional.code_hash,
            source_plan_hash=assembled.dataset.dataset_hash,
            cost_plan_hash=assembled.costs.cost_hash,
            holdout_previously_examined=False,
        )
        requests = tuple(
            replace(assembled, study=study, initial_cash=cash, fill_scenario=scenario)
            for cash in study.capital_tiers
            for scenario in SCENARIOS
        )
        _run_economics(requests, report_dir)
    except _ERRORS:
        _invalid()
        return
    raise typer.Exit(2)


if __name__ == "__main__":
    app()
