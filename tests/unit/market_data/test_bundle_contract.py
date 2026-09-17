"""Independent synthetic-only contract challenges for research bundle v1."""

import json
from dataclasses import replace
from hashlib import sha256

import pytest

from tests.unit.market_data._bundle_fixtures import (
    ID,
    LIMITS,
    fixture_package,
    fixture_rows,
    fixture_sources,
)
from trading_bot.domain import Bar
from trading_bot.market_data.bundle_codec import decode_envelope
from trading_bot.market_data.bundle_models import BundleError, InstrumentMapping
from trading_bot.market_data.bundle_normalize import assemble_bundle
from trading_bot.market_data.bundle_verify import verify_bundle
from trading_bot.market_data.recording import canonical_json, content_hash


def _package_for_rows(rows: list[dict]) -> object:
    return assemble_bundle(
        sources=fixture_sources(rows=rows),
        instruments=(InstrumentMapping(ID, "SYNTH"),),
        limits=LIMITS,
    )


def _rewritten_envelope(package: object, mutation) -> object:
    wire = json.loads(package.envelope_bytes)
    mutation(wire)
    wire["bundle_hash"] = content_hash(
        {key: value for key, value in wire.items() if key != "bundle_hash"}
    )
    return replace(package, envelope_bytes=canonical_json(wire).encode())


def _bar_values(package: object) -> tuple[tuple[str, str, str], ...]:
    envelope = decode_envelope(package.envelope_bytes, limits=LIMITS)
    return tuple(
        (str(row.value.open), str(row.value.close), str(row.value.volume))
        for row in envelope.records
        if isinstance(row.value, Bar)
    )


def test_valid_package_is_deterministic_and_preserves_selected_values() -> None:
    first = fixture_package()
    second = fixture_package()

    assert first == second
    verified = verify_bundle(first, limits=LIMITS)
    assert verified.envelope.bundle_hash == decode_envelope(
        first.envelope_bytes, limits=LIMITS
    ).bundle_hash
    assert _bar_values(first) == (("10", "10", "100"), ("10", "10", "100"))
    assert verified.envelope.classification == "synthetic"
    assert verified.envelope.manifest.point_in_time_universe is False


def test_exact_raw_bytes_not_canonical_values_define_source_identity() -> None:
    source = fixture_sources()[0]
    equivalent = replace(
        source,
        raw_bytes=json.dumps(json.loads(source.raw_bytes), indent=2).encode(),
    )
    changed = assemble_bundle(
        sources=(equivalent,),
        instruments=(InstrumentMapping(ID, "SYNTH"),),
        limits=LIMITS,
    )
    original = fixture_package()

    assert json.loads(equivalent.raw_bytes) == json.loads(source.raw_bytes)
    assert equivalent.raw_bytes != source.raw_bytes
    assert changed.blobs[0][0] == sha256(equivalent.raw_bytes).hexdigest()
    assert changed.blobs[0][0] != original.blobs[0][0]
    assert _bar_values(changed) == _bar_values(original)
    assert decode_envelope(changed.envelope_bytes, limits=LIMITS).bundle_hash != decode_envelope(
        original.envelope_bytes, limits=LIMITS
    ).bundle_hash


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda wire: wire["records"][1]["value"].update(close="11"),
         "bundle_normalization_mismatch"),
        (lambda wire: wire["records"][1].update(locator=999),
         "bundle_normalization_mismatch"),
        (lambda wire: wire["records"][1].update(source_hash="f" * 64),
         "bundle_normalization_mismatch"),
        (lambda wire: wire["manifest"].update(cleaned_hashes=["f" * 64]),
         "bundle_manifest_mismatch"),
    ],
)
def test_outer_rehash_cannot_hide_normalized_locator_source_or_manifest_mutation(
    mutation, code: str
) -> None:
    with pytest.raises(BundleError, match=rf"^{code}$"):
        verify_bundle(_rewritten_envelope(fixture_package(), mutation), limits=LIMITS)


def test_outer_rehash_cannot_hide_raw_body_replacement() -> None:
    package = fixture_package()
    digest, body = package.blobs[0]
    altered = body.replace(b'"close":"10"', b'"close":"11"', 1)
    assert len(altered) == len(body) and altered != body

    with pytest.raises(BundleError, match=r"^bundle_blob_mismatch$"):
        verify_bundle(replace(package, blobs=((digest, altered),)), limits=LIMITS)


def test_rehashing_raw_descriptor_and_outer_layer_still_exposes_replay_mismatch() -> None:
    package = fixture_package()
    _, body = package.blobs[0]
    altered = body.replace(b'"close":"10"', b'"close":"11"', 1)
    digest = sha256(altered).hexdigest()
    wire = json.loads(package.envelope_bytes)
    descriptor = wire["sources"][0]
    descriptor["blob_sha256"] = digest
    descriptor["byte_length"] = len(altered)
    descriptor["descriptor_hash"] = content_hash(
        {
            "domain": "source-descriptor-v1",
            "value": {
                key: value for key, value in descriptor.items() if key != "descriptor_hash"
            },
        }
    )
    wire["bundle_hash"] = content_hash(
        {key: value for key, value in wire.items() if key != "bundle_hash"}
    )
    changed = replace(
        package,
        envelope_bytes=canonical_json(wire).encode(),
        blobs=((digest, altered),),
    )

    with pytest.raises(BundleError, match=r"^bundle_normalization_mismatch$"):
        verify_bundle(changed, limits=LIMITS)


@pytest.mark.parametrize(
    "change",
    [
        {"instrument_ids": ("OTHER",)},
        {"record_kinds": ("coverage",)},
        {"source_id": "other"},
    ],
)
def test_raw_records_are_bound_to_declared_source_scope(change: dict) -> None:
    source = replace(fixture_sources()[0], **change)
    with pytest.raises(BundleError, match=r"^bundle_scope_mismatch$"):
        assemble_bundle(
            sources=(source,),
            instruments=(InstrumentMapping(ID, "SYNTH"),),
            limits=LIMITS,
        )


@pytest.mark.parametrize(
    "encoded,code",
    [
        (b"{", "bundle_json_invalid"),
        (b'{"schema":1}', "bundle_schema_invalid"),
        (b'{"a":1,"a":2}', "bundle_json_invalid"),
        (b'{"value":1.5}', "bundle_json_invalid"),
        (b'{"value":NaN}', "bundle_json_invalid"),
    ],
)
def test_decoder_strictly_rejects_malformed_or_wrongly_typed_json(
    encoded: bytes, code: str
) -> None:
    with pytest.raises(BundleError, match=rf"^{code}$"):
        decode_envelope(encoded, limits=LIMITS)


def test_decoder_enforces_depth_and_envelope_byte_limits() -> None:
    too_deep = (b"[" * (LIMITS.max_json_depth + 1)) + (b"]" * (LIMITS.max_json_depth + 1))
    with pytest.raises(BundleError, match=r"^bundle_input_too_large$"):
        decode_envelope(too_deep, limits=LIMITS)

    package = fixture_package()
    limits = replace(LIMITS, max_envelope_bytes=len(package.envelope_bytes) - 1)
    with pytest.raises(BundleError, match=r"^bundle_input_too_large$"):
        decode_envelope(package.envelope_bytes, limits=limits)


def test_verifier_enforces_blob_total_and_combined_record_limits() -> None:
    package = fixture_package()
    blob_size = len(package.blobs[0][1])
    cases = (
        replace(LIMITS, max_blob_bytes=blob_size - 1),
        replace(
            LIMITS,
            max_envelope_bytes=len(package.envelope_bytes),
            max_blob_bytes=blob_size,
            max_total_bytes=len(package.envelope_bytes) + blob_size - 1,
        ),
        replace(LIMITS, max_records=11),
    )
    for limits in cases:
        with pytest.raises(BundleError, match=r"^bundle_input_too_large$"):
            verify_bundle(package, limits=limits)


def test_synthetic_capture_cannot_be_relabelled_as_imported() -> None:
    source = replace(fixture_sources()[0], origin="imported")
    with pytest.raises(BundleError, match=r"^bundle_source_unsupported$"):
        assemble_bundle(
            sources=(source,),
            instruments=(InstrumentMapping(ID, "SYNTH"),),
            limits=LIMITS,
        )


@pytest.mark.parametrize("state", ["gap", "unknown"])
def test_gap_and_unknown_coverage_are_derived_limitations(state: str) -> None:
    rows = fixture_rows()
    rows[3]["value"].update(state=state, expected_slots=())
    package = _package_for_rows(rows)
    verified = verify_bundle(package, limits=LIMITS)

    assert verified.envelope.records[3].value.state == state
    assert "declared_coverage_gap" in verified.limitation_codes
    assert "declared_coverage_gap" in verified.envelope.manifest.known_gaps
    assert verified.envelope.classification == "synthetic"
