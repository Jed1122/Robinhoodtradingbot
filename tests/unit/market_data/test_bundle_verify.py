import json
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from hashlib import sha256

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
from trading_bot.market_data.bundle_models import BundleError, InstrumentMapping
from trading_bot.market_data.bundle_normalize import assemble_bundle
from trading_bot.market_data.bundle_verify import VerifiedBundle, verify_bundle
from trading_bot.market_data.recording import content_hash


def package_for(rows):
    return assemble_bundle(
        sources=fixture_sources(rows=rows),
        instruments=(InstrumentMapping(ID, "SYNTH"),),
        limits=LIMITS,
    )


def changed_envelope(package, mutate, *, rehash=True):
    wire = json.loads(package.envelope_bytes)
    mutate(wire)
    if rehash:
        wire["bundle_hash"] = content_hash(
            {key: value for key, value in wire.items() if key != "bundle_hash"}
        )
    return replace(package, envelope_bytes=json.dumps(wire).encode())


def test_complete_fixture_verifies_without_becoming_real_evidence() -> None:
    result = verify_bundle(fixture_package(), limits=LIMITS)
    assert result.envelope.classification == "synthetic"
    assert result.envelope.manifest.point_in_time_universe is False
    assert "source_authenticity_unverified" in result.limitation_codes
    with pytest.raises(FrozenInstanceError):
        result.limitation_codes = ()
    with pytest.raises(TypeError):
        VerifiedBundle()
    assert not hasattr(result, "blobs")
    assert not hasattr(result, "trusted")


def test_raw_byte_tamper_is_detected() -> None:
    package = fixture_package()
    digest, body = package.blobs[0]
    changed = body.replace(b'"close":"10"', b'"close":"99"', 1)
    assert changed != body and len(changed) == len(body)
    with pytest.raises(BundleError, match=r"^bundle_blob_mismatch$"):
        verify_bundle(replace(package, blobs=((digest, changed),)), limits=LIMITS)


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda w: w["sources"][0].update(byte_length=1), "bundle_blob_mismatch"),
        (
            lambda w: w["sources"][0].update(collected_at="2026-01-04T00:00:00.000000Z"),
            "bundle_hash_mismatch",
        ),
        (lambda w: w["records"][1]["value"].update(close="9"), "bundle_normalization_mismatch"),
        (
            lambda w: w["records"][1]["value"].update(data_hash="f" * 64),
            "bundle_normalization_mismatch",
        ),
        (lambda w: w["records"][1].update(locator=99), "bundle_normalization_mismatch"),
        (lambda w: w["records"][1].update(source_hash="f" * 64), "bundle_normalization_mismatch"),
        (lambda w: w["records"].pop(), "bundle_normalization_mismatch"),
        (lambda w: w["records"].append(w["records"][1]), "bundle_normalization_mismatch"),
        (lambda w: w["records"].reverse(), "bundle_normalization_mismatch"),
        (lambda w: w["manifest"].update(manifest_hash="f" * 64), "bundle_manifest_mismatch"),
        (lambda w: w["manifest"].update(point_in_time_universe=True), "bundle_manifest_mismatch"),
        (lambda w: w.update(limitation_codes=[]), "bundle_fixture_mismatch"),
        (lambda w: w.update(classification="imported"), "bundle_fixture_mismatch"),
    ],
)
def test_outer_rehash_does_not_hide_inner_tampering(change, reason) -> None:
    with pytest.raises(BundleError, match=f"^{reason}$"):
        verify_bundle(changed_envelope(fixture_package(), change), limits=LIMITS)


def test_outer_hash_is_required_and_blob_set_is_exact() -> None:
    package = fixture_package()
    with pytest.raises(BundleError, match=r"^bundle_hash_mismatch$"):
        verify_bundle(
            changed_envelope(package, lambda w: w.update(bundle_hash="f" * 64), rehash=False),
            limits=LIMITS,
        )
    for blobs in ((), tuple(sorted((*package.blobs, ("f" * 64, b"{}"))))):
        with pytest.raises(BundleError, match=r"^bundle_blob_mismatch$"):
            verify_bundle(replace(package, blobs=blobs), limits=LIMITS)


def test_correctly_digested_unreferenced_blob_is_rejected_before_raw_parsing() -> None:
    package = fixture_package()
    raw = b"{}"
    blobs = tuple(sorted((*package.blobs, (sha256(raw).hexdigest(), raw))))
    with pytest.raises(BundleError, match=r"^bundle_blob_mismatch$"):
        verify_bundle(replace(package, blobs=blobs), limits=LIMITS)


@pytest.mark.parametrize("change", ["missing", "wrong_slot", "overlap", "unbound_baseline"])
def test_structural_coverage_requires_exact_slots_and_baseline_binding(change: str) -> None:
    rows = fixture_rows()
    if change == "missing":
        rows.pop(1)
    elif change == "wrong_slot":
        rows[3]["value"]["expected_slots"][0]["starts_at"] += timedelta(hours=1)
    elif change == "overlap":
        rows.append(rows[3])
    else:
        rows[0]["value"]["coverage_start"] += timedelta(hours=1)
    with pytest.raises(BundleError, match=r"^bundle_coverage_invalid$"):
        verify_bundle(package_for(rows), limits=LIMITS)


@pytest.mark.parametrize("kind", ["bar", "baseline", "membership", "corporate_action"])
def test_conflicting_or_duplicated_identity_is_rejected(kind: str) -> None:
    rows = fixture_rows()
    if kind == "bar":
        rows.append(rows[1])
    elif kind == "baseline":
        rows.append(rows[0])
    elif kind == "membership":
        value = {
            "instrument_id": ID,
            "effective_at": START,
            "announced_at": START,
            "included": True,
        }
        rows.extend(
            [
                {"kind": kind, "available_at": START, "price_basis": None, "value": value},
                {
                    "kind": kind,
                    "available_at": START,
                    "price_basis": None,
                    "value": {**value, "included": False},
                },
            ]
        )
    else:
        row = {
            "kind": kind,
            "available_at": END,
            "price_basis": None,
            "value": {
                "instrument_id": ID,
                "action_type": "dividend",
                "effective_date": START.date(),
                "announced_at": START,
                "split_ratio": None,
                "cash_amount": "0.25",
            },
        }
        rows.extend([row, row])
    with pytest.raises(BundleError, match=r"^bundle_record_conflict$"):
        verify_bundle(package_for(rows), limits=LIMITS)


def test_adjacent_segments_and_identical_membership_events_are_valid() -> None:
    rows = fixture_rows()
    row = rows[3]
    mid = START + timedelta(days=1)
    rows[3] = {
        **row,
        "value": {
            **row["value"],
            "ends_at": mid,
            "expected_slots": row["value"]["expected_slots"][:1],
        },
    }
    rows.append(
        {
            **row,
            "value": {
                **row["value"],
                "starts_at": mid,
                "expected_slots": row["value"]["expected_slots"][1:],
            },
        }
    )
    event = {
        "kind": "membership",
        "available_at": START,
        "price_basis": None,
        "value": {
            "instrument_id": ID,
            "effective_at": START,
            "announced_at": START,
            "included": True,
        },
    }
    rows.extend([event, event])
    assert len(verify_bundle(package_for(rows), limits=LIMITS).envelope.records) == 9


def test_gap_unknown_and_unavailable_complete_bars_remain_retained_diagnostics() -> None:
    rows = fixture_rows()
    rows[3]["value"].update(state="gap", expected_slots=())
    rows[4]["value"]["state"] = "unknown"
    rows[1]["available_at"] = END + timedelta(days=1)
    result = verify_bundle(package_for(rows), limits=LIMITS)
    assert "declared_coverage_gap" in result.limitation_codes
    assert len(result.envelope.records) == len(rows)


def test_combined_records_are_bounded_before_reconstruction() -> None:
    with pytest.raises(BundleError, match=r"^bundle_input_too_large$"):
        verify_bundle(fixture_package(), limits=replace(LIMITS, max_records=11))


def test_distinct_descriptors_do_not_authorize_duplicate_bars() -> None:
    source = fixture_sources()[0]
    package = assemble_bundle(
        sources=(source, replace(source, limitation_codes=("test_scope",))),
        instruments=(InstrumentMapping(ID, "SYNTH"),),
        limits=LIMITS,
    )
    with pytest.raises(BundleError, match=r"^bundle_record_conflict$"):
        verify_bundle(package, limits=LIMITS)
