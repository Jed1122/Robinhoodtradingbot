"""Explicit source evidence input and diagnostic output. No verification-token decoder."""

from dataclasses import asdict, fields
from pathlib import Path

from trading_bot.config import LoadedConfig
from trading_bot.market_data.bundle_codec import _array, _digest, _json, _mapping, _string, _time
from trading_bot.market_data.databento_bar_wire import bounds
from trading_bot.market_data.options_source_models import (
    PrivateArtifactRef,
    SourceClaim,
    SourceEvidenceBundle,
    SourceEvidenceError,
    SourceVerification,
    check,
)
from trading_bot.market_data.recording import canonical_json


def _reference(value: object) -> PrivateArtifactRef:
    wire = _mapping(value, {"path", "sha256", "byte_count"})
    wire["path"] = Path(_string(wire["path"]))
    return PrivateArtifactRef(**wire)  # type: ignore[arg-type]


def decode_source_bundle(body: bytes, *, loaded: LoadedConfig) -> SourceEvidenceBundle:
    try:
        limits = bounds(loaded)
        maximum = min(
            limits.max_envelope_bytes, loaded.config.options.research_shortlist.max_input_bytes
        )
        wire = _mapping(
            _json(body, max_bytes=maximum, limits=limits),
            {"schema", "claims", "references", "manifests"},
        )
        check(wire["schema"] == "options-source-evidence-v1")
        claims = []
        for item in _array(wire["claims"]):
            row = _mapping(item, {field.name for field in fields(SourceClaim)})
            row["raw_hashes"] = tuple(_digest(value) for value in _array(row["raw_hashes"]))
            row["observed_at"] = _time(row["observed_at"])
            claims.append(SourceClaim(**row))  # type: ignore[arg-type]
        result = SourceEvidenceBundle(
            tuple(claims),
            tuple(_reference(item) for item in _array(wire["references"])),
            tuple(_reference(item) for item in _array(wire["manifests"])),
        )
        check(
            len(result.claims) + len(result.references) + len(result.manifests)
            <= loaded.config.options.research_shortlist.max_input_records
        )
        return result
    except Exception:
        raise SourceEvidenceError() from None


def encode_source_bundle(bundle: SourceEvidenceBundle) -> bytes:
    check(type(bundle) is SourceEvidenceBundle)
    value = {
        "schema": "options-source-evidence-v1",
        "claims": [asdict(item) for item in bundle.claims],
    }
    for name in ("references", "manifests"):
        value[name] = [
            {"path": str(item.path), "sha256": item.sha256, "byte_count": item.byte_count}
            for item in getattr(bundle, name)
        ]
    return canonical_json(value).encode()


def encode_source_verification(result: SourceVerification) -> bytes:
    check(type(result) is SourceVerification)
    return canonical_json({"schema": "options-source-verification-v1", **asdict(result)}).encode()
