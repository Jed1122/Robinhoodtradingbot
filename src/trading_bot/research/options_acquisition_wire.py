"""Closed local study declarations and private acquisition diagnostics; no transport."""

from dataclasses import asdict, fields

from trading_bot.config import LoadedConfig
from trading_bot.domain import ConfigHash
from trading_bot.market_data.bundle_codec import _array, _digest, _json, _mapping, _string, _time
from trading_bot.market_data.databento_bar_wire import bounds
from trading_bot.market_data.options_data_codec import _contract
from trading_bot.market_data.options_source_models import SourceEvidenceError, check
from trading_bot.market_data.recording import canonical_json
from trading_bot.research.options_acquisition_models import (
    CoverageManifest,
    CoverageRequirement,
    CoverageSemantics,
    CoverageWindow,
    StudyCoverageManifest,
    StudyCoverageRequirements,
)


def _window(value: object) -> CoverageWindow:
    row = _mapping(value, {field.name for field in fields(CoverageWindow)})
    row["requirement_ids"] = tuple(_string(item) for item in _array(row["requirement_ids"]))
    row["selection_hashes"] = tuple(_digest(item) for item in _array(row["selection_hashes"]))
    return CoverageWindow(**row)  # type: ignore[arg-type]


def decode_coverage_requirements(body: bytes, *, loaded: LoadedConfig) -> StudyCoverageRequirements:
    try:
        settings = loaded.config.options.research_shortlist
        row = _mapping(
            _json(body, max_bytes=settings.max_input_bytes, limits=bounds(loaded)),
            {"schema", *(field.name for field in fields(StudyCoverageRequirements))},
        )
        check(row.pop("schema") == "options-study-coverage-v1")
        for key in ("preregistered_at", "selection_frozen_at"):
            row[key] = _time(row[key])
        row["config_hash"] = ConfigHash(_digest(row["config_hash"]))
        row["session_ids"] = tuple(_string(item) for item in _array(row["session_ids"]))
        requirements = []
        for value in _array(row["requirements"]):
            item = _mapping(value, {field.name for field in fields(CoverageRequirement)})
            item["window"] = _window(item["window"])
            for key in ("session_ids", "missing_dependencies"):
                item[key] = tuple(_string(value) for value in _array(item[key]))
            requirements.append(CoverageRequirement(**item))  # type: ignore[arg-type]
        row["requirements"] = tuple(requirements)
        row["semantics"] = tuple(
            CoverageSemantics(**_mapping(value, {f.name for f in fields(CoverageSemantics)}))  # type: ignore[arg-type]
            for value in _array(row["semantics"])
        )
        row["contracts"] = tuple(_contract(value) for value in _array(row["contracts"]))
        result = StudyCoverageRequirements(**row)  # type: ignore[arg-type]
        check(
            sum(
                map(
                    len,
                    (result.requirements, result.semantics, result.contracts, result.session_ids),
                )
            )
            <= settings.max_input_records
        )
        return result
    except Exception:
        raise SourceEvidenceError() from None


def encode_coverage_manifest(manifest: CoverageManifest) -> bytes:
    check(type(manifest) in (CoverageManifest, StudyCoverageManifest))
    return canonical_json({**asdict(manifest), "manifest_hash": manifest.manifest_hash}).encode()
