import hashlib
import json
from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.market_data._bundle_fixtures import (
    END,
    ID,
    LIMITS,
    START,
    fixture_package,
    fixture_rows,
    fixture_sources,
)
from trading_bot.domain import Bar, CorporateAction
from trading_bot.market_data.bundle_codec import decode_envelope
from trading_bot.market_data.bundle_models import BundleError, InstrumentMapping
from trading_bot.market_data.bundle_normalize import assemble_bundle
from trading_bot.market_data.recording import canonical_json, content_hash


def build(sources=None, *, rows=None, limits=LIMITS):
    return assemble_bundle(
        sources=fixture_sources(rows=rows) if sources is None else sources,
        instruments=(InstrumentMapping(ID, "SYNTH"),),
        limits=limits,
    )


def test_assembly_binds_exact_bytes_and_normalized_domain_values() -> None:
    package = fixture_package()
    assert package == fixture_package()
    envelope = decode_envelope(package.envelope_bytes, limits=LIMITS)
    digest, raw = package.blobs[0]
    assert digest == hashlib.sha256(raw).hexdigest()
    assert digest != content_hash(raw.decode())
    assert envelope.sources[0].blob_sha256 == digest
    assert envelope.sources[0].byte_length == len(raw)
    descriptor_body = asdict(envelope.sources[0])
    del descriptor_body["descriptor_hash"]
    assert envelope.sources[0].descriptor_hash == content_hash(
        {"domain": "source-descriptor-v1", "value": descriptor_body}
    )
    envelope_body = asdict(envelope)
    del envelope_body["bundle_hash"]
    assert envelope.bundle_hash == content_hash(envelope_body)
    assert envelope.manifest.raw_hashes == (envelope.sources[0].descriptor_hash,)
    bars = tuple(row.value for row in envelope.records if isinstance(row.value, Bar))
    assert tuple(str(bar.close) for bar in bars) == ("10", "10")
    assert tuple(bar.ends_at for bar in bars) == (START + timedelta(days=1), END)
    assert envelope.manifest.cleaned_hashes == (content_hash({"bars": bars, "symbol": "SYNTH"}),)
    for row in envelope.records:
        body = asdict(row.value)
        body.pop("data_hash", None)
        expected = content_hash(
            {
                "domain": "normalized-record-v1",
                "kind": row.kind,
                "source_hash": row.source_hash,
                "locator": row.locator,
                "available_at": row.available_at,
                "price_basis": row.price_basis,
                "normalizer_version": "synthetic-normalizer-v1",
                "value": body,
            }
        )
        assert row.record_hash == expected
        if isinstance(row.value, Bar | CorporateAction):
            assert row.value.data_hash == row.record_hash


@pytest.mark.parametrize(
    "change", ["imported", "format", "extra", "data_hash", "float", "duplicate"]
)
def test_source_contract_rejects_guessing_or_pre_normalized_input(change: str) -> None:
    source = fixture_sources()[0]
    data = json.loads(source.raw_bytes)
    if change == "imported":
        source = replace(source, origin="imported")
    elif change == "format":
        data["schema"] = "provider-response"
    elif change == "extra":
        data["auth"] = "private-payload-marker"
    elif change == "data_hash":
        data["records"][1]["value"]["data_hash"] = "a" * 64
    elif change == "float":
        data["records"][1]["value"]["close"] = 10.5
    if change == "duplicate":
        raw = b'{"schema":"synthetic-market-v1","records":[],"records":[]}'
    else:
        raw = json.dumps(data).encode()
    with pytest.raises(BundleError) as caught:
        build((replace(source, raw_bytes=raw),))
    assert "private-payload-marker" not in str(caught.value)
    if change in ("imported", "format"):
        assert caught.value.code == "bundle_source_unsupported"


def test_synthetic_and_unknown_provenance_are_mandatory_classifications() -> None:
    envelope = decode_envelope(fixture_package().envelope_bytes, limits=LIMITS)
    assert envelope.classification == "synthetic"
    assert envelope.manifest.point_in_time_universe is False
    assert envelope.limitation_codes == (
        "source_authenticity_unverified",
        "source_history_unverified",
        "source_license_unverified",
        "synthetic_data",
    )


@pytest.mark.parametrize(
    "change,reason",
    [
        ("interpolated", "interpolated_data"),
        ("adjusted", "price_basis_unsupported"),
        ("unknown", "declared_coverage_gap"),
    ],
)
def test_quality_limitations_survive_normalization(change: str, reason: str) -> None:
    rows = fixture_rows()
    if change == "interpolated":
        rows[1]["value"]["interpolated"] = True
    elif change == "adjusted":
        rows[1]["price_basis"] = "adjusted"
    else:
        rows[3]["value"].update(state="unknown", expected_slots=())
    envelope = decode_envelope(build(rows=rows).envelope_bytes, limits=LIMITS)
    assert reason in envelope.limitation_codes
    assert reason in envelope.manifest.known_gaps


@pytest.mark.parametrize(
    "changes",
    [
        {"instrument_ids": ("DIFFERENT",)},
        {"record_kinds": ("bar",)},
        {"source_id": "different"},
        {"requested_start": START + timedelta(hours=1)},
        {"requested_end": END - timedelta(hours=1)},
    ],
)
def test_normalized_rows_cannot_escape_source_scope(changes: dict) -> None:
    with pytest.raises(BundleError, match=r"^bundle_scope_mismatch$"):
        build((replace(fixture_sources()[0], **changes),))


def test_identical_body_can_be_referenced_by_distinct_descriptors() -> None:
    source = fixture_sources()[0]
    other = replace(source, limitation_codes=("test_scope",))
    first = build((source, other))
    assert first == build((other, source))
    assert len(first.blobs) == 1
    assert len(decode_envelope(first.envelope_bytes, limits=LIMITS).sources) == 2
    # Duplicate bars remain a later verifier denial; assembly is not query verification.


def test_duplicate_descriptors_are_not_silently_collapsed() -> None:
    source = fixture_sources()[0]
    with pytest.raises(BundleError):
        build((source, source))


def test_membership_and_actions_get_their_own_normalized_bindings() -> None:
    rows = fixture_rows()
    rows.extend(
        [
            {
                "kind": "membership",
                "available_at": END,
                "price_basis": None,
                "value": {
                    "instrument_id": ID,
                    "effective_at": START + timedelta(hours=1),
                    "announced_at": END,
                    "included": False,
                },
            },
            {
                "kind": "corporate_action",
                "available_at": END,
                "price_basis": None,
                "value": {
                    "instrument_id": ID,
                    "action_type": "dividend",
                    "effective_date": START.date(),
                    "announced_at": END,
                    "split_ratio": None,
                    "cash_amount": "0.25",
                },
            },
        ]
    )
    envelope = decode_envelope(build(rows=rows).envelope_bytes, limits=LIMITS)
    assert envelope.records[-2].value.included is False
    assert envelope.records[-1].value.cash_amount == Decimal("0.25")


def test_whitespace_changes_raw_identity_not_decoded_market_values() -> None:
    source = fixture_sources()[0]
    spaced = replace(source, raw_bytes=json.dumps(json.loads(source.raw_bytes), indent=2).encode())
    original = decode_envelope(build((source,)).envelope_bytes, limits=LIMITS)
    changed = decode_envelope(build((spaced,)).envelope_bytes, limits=LIMITS)
    assert changed.bundle_hash != original.bundle_hash
    assert changed.records[1].value.close == original.records[1].value.close
    assert changed.records[1].value.data_hash != original.records[1].value.data_hash


def test_byte_and_combined_record_limits_are_checked_before_normalization() -> None:
    source = fixture_sources()[0]
    for limits in (
        replace(LIMITS, max_blob_bytes=len(source.raw_bytes) - 1),
        replace(LIMITS, max_records=11),  # six raw plus six normalized records
        replace(LIMITS, max_envelope_bytes=100),
    ):
        with pytest.raises(BundleError, match=r"^bundle_input_too_large$"):
            build(limits=limits)


def test_reordered_raw_keys_keep_values_but_bind_different_exact_bytes() -> None:
    source = fixture_sources()[0]
    wire = json.loads(source.raw_bytes)
    reordered = {"schema": wire["schema"], "records": wire["records"]}
    body = json.dumps(reordered, separators=(",", ":")).encode()
    assert body != source.raw_bytes
    original = decode_envelope(build((source,)).envelope_bytes, limits=LIMITS)
    changed = decode_envelope(
        build((replace(source, raw_bytes=body),)).envelope_bytes, limits=LIMITS
    )
    assert original.bundle_hash != changed.bundle_hash
    for before, after in zip(original.records, changed.records, strict=True):
        assert before.kind == after.kind
        left, right = asdict(before.value), asdict(after.value)
        left.pop("data_hash", None)
        right.pop("data_hash", None)
        assert left == right


def test_mapping_order_is_preserved_and_legacy_cleaned_hashes_follow_it() -> None:
    first = fixture_sources()[0]
    rows = fixture_rows()
    for row in rows:
        row["value"]["instrument_id"] = "SECOND"
    second = replace(
        first,
        instrument_ids=("SECOND",),
        raw_bytes=canonical_json({"schema": "synthetic-market-v1", "records": rows}).encode(),
    )
    mappings = (InstrumentMapping("SECOND", "SECOND"), InstrumentMapping(ID, "SYNTH"))
    envelope = decode_envelope(
        assemble_bundle(
            sources=(first, second),
            instruments=mappings,
            limits=LIMITS,
        ).envelope_bytes,
        limits=LIMITS,
    )
    assert envelope.instruments == mappings
    for mapping, digest in zip(mappings, envelope.manifest.cleaned_hashes, strict=True):
        bars = tuple(
            row.value
            for row in envelope.records
            if isinstance(row.value, Bar) and row.value.instrument_id == mapping.instrument_id
        )
        assert digest == content_hash({"bars": bars, "symbol": mapping.symbol})
    assert tuple(s.descriptor_hash for s in envelope.sources) == tuple(
        sorted(s.descriptor_hash for s in envelope.sources)
    )


def test_total_bytes_include_envelope_and_all_distinct_blobs() -> None:
    package = fixture_package()
    largest = max(len(package.envelope_bytes), *(len(body) for _, body in package.blobs))
    limits = replace(
        LIMITS, max_envelope_bytes=largest, max_blob_bytes=largest, max_total_bytes=largest
    )
    with pytest.raises(BundleError, match=r"^bundle_input_too_large$"):
        build(limits=limits)


def test_unknown_price_basis_and_declared_gap_are_retained() -> None:
    rows = fixture_rows()
    rows[1]["price_basis"] = "unknown"
    rows[3]["value"].update(state="gap", expected_slots=())
    envelope = decode_envelope(build(rows=rows).envelope_bytes, limits=LIMITS)
    assert "price_basis_unsupported" in envelope.limitation_codes
    assert "declared_coverage_gap" in envelope.limitation_codes
    assert envelope.records[1].price_basis == "unknown"
    assert envelope.records[3].value.state == "gap"


def test_custom_source_limitations_remain_in_manifest_and_envelope() -> None:
    source = replace(fixture_sources()[0], limitation_codes=("custom_fixture_limit",))
    envelope = decode_envelope(build((source,)).envelope_bytes, limits=LIMITS)
    assert "custom_fixture_limit" in envelope.limitation_codes
    assert "custom_fixture_limit" in envelope.manifest.known_gaps


@pytest.mark.parametrize(
    "changes",
    [
        {"effective_at": END},
        {"effective_at": START - timedelta(seconds=1)},
    ],
)
def test_membership_effective_time_must_be_in_source_window(changes: dict) -> None:
    rows = fixture_rows()
    value = {"instrument_id": ID, "effective_at": START, "announced_at": END, "included": False}
    value.update(changes)
    rows.append({"kind": "membership", "available_at": END, "price_basis": None, "value": value})
    with pytest.raises(BundleError, match=r"^bundle_scope_mismatch$"):
        build(rows=rows)


@pytest.mark.parametrize("effective_date", [START.date() - timedelta(days=1), END.date()])
def test_action_effective_date_must_touch_source_window(effective_date) -> None:
    rows = fixture_rows()
    rows.append(
        {
            "kind": "corporate_action",
            "available_at": END,
            "price_basis": None,
            "value": {
                "instrument_id": ID,
                "action_type": "dividend",
                "effective_date": effective_date,
                "announced_at": END,
                "split_ratio": None,
                "cash_amount": "0.25",
            },
        }
    )
    with pytest.raises(BundleError, match=r"^bundle_scope_mismatch$"):
        build(rows=rows)
