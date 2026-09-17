from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.domain import BarInterval, DataHash, InstrumentId
from trading_bot.market_data.bundle_models import (
    BarSlot,
    BundleError,
    BundleLimits,
    BundlePackage,
    CoverageDeclaration,
    InstrumentMapping,
    MembershipBaseline,
    SnapshotSettings,
    SourceCapture,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
END = NOW + timedelta(days=1)
ID = InstrumentId("SYNTH")


@pytest.mark.parametrize("field", range(5))
@pytest.mark.parametrize("bad", [True, False, 0, -1, 1.5, "100", None])
def test_limits_reject_coerced_or_nonpositive_values(field: int, bad: object) -> None:
    values = [4096, 4096, 8192, 100, 16]
    values[field] = bad  # type: ignore[assignment]
    with pytest.raises(BundleError, match=r"^bundle_limits_invalid$"):
        BundleLimits(*values)


def test_total_limit_cannot_be_smaller_than_an_individual_limit() -> None:
    with pytest.raises(BundleError, match=r"^bundle_limits_invalid$"):
        BundleLimits(4096, 1024, 2048, 100, 16)


def test_valid_limits_preserve_explicit_values_and_immutability() -> None:
    limits = BundleLimits(4096, 4096, 8192, 100, 16)
    assert limits.max_total_bytes == 8192
    with pytest.raises(FrozenInstanceError):
        limits.max_records = 10  # type: ignore[misc]


@pytest.mark.parametrize("bad", ["", " ", "../outside", "a/b", "x" * 129, 1, None])
def test_mapping_rejects_invalid_instrument_labels(bad: object) -> None:
    with pytest.raises(BundleError, match=r"^bundle_value_invalid$"):
        InstrumentMapping(bad, "SYNTH")  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["", "../outside", "x" * 33, 1])
def test_mapping_rejects_invalid_symbols(bad: object) -> None:
    with pytest.raises(BundleError):
        InstrumentMapping(ID, bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [NOW.replace(tzinfo=None), "2026-01-01", None])
def test_slots_reject_non_utc_or_untyped_times(bad: object) -> None:
    with pytest.raises(BundleError):
        BarSlot(bad, END)  # type: ignore[arg-type]


@pytest.mark.parametrize("end", [NOW, NOW - timedelta(seconds=1)])
def test_slots_require_positive_duration(end: datetime) -> None:
    with pytest.raises(BundleError):
        BarSlot(NOW, end)


def test_baseline_cannot_be_effective_after_its_coverage_start() -> None:
    with pytest.raises(BundleError):
        MembershipBaseline(ID, NOW, END, NOW, True)


@pytest.mark.parametrize("bad", [1, "true", None])
def test_baseline_inclusion_is_exact_boolean(bad: object) -> None:
    with pytest.raises(BundleError):
        MembershipBaseline(ID, NOW, NOW, NOW, bad)  # type: ignore[arg-type]


def coverage() -> CoverageDeclaration:
    return CoverageDeclaration(
        ID, "bar", BarInterval.ONE_DAY, NOW, END, "complete", (BarSlot(NOW, END),)
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"interval": None},
        {"record_kind": "baseline"},
        {"state": "trusted"},
        {"state": "gap"},
        {"record_kind": "membership"},
        {"expected_slots": []},
        {"expected_slots": (BarSlot(NOW - timedelta(days=1), END),)},
        {"expected_slots": (BarSlot(NOW, END), BarSlot(NOW, END))},
    ],
)
def test_coverage_rejects_ambiguous_shapes(changes: dict[str, object]) -> None:
    with pytest.raises(BundleError):
        replace(coverage(), **changes)


def test_unknown_coverage_remains_representable_without_inventing_slots() -> None:
    value = replace(coverage(), state="unknown", expected_slots=())
    assert value.state == "unknown"
    assert value.expected_slots == ()


def capture() -> SourceCapture:
    return SourceCapture("fixture", "synthetic", (ID,), ("bar",), NOW, END, END, None, (), b"{}")


@pytest.mark.parametrize(
    "changes",
    [
        {"source_id": "https://secret.example/token"},
        {"origin": "trusted"},
        {"instrument_ids": [ID]},
        {"instrument_ids": (ID, ID)},
        {"record_kinds": ("quote",)},
        {"record_kinds": ("bar", "bar")},
        {"requested_end": NOW},
        {"collected_at": NOW.replace(tzinfo=None)},
        {"limitation_codes": ("Bearer secret",)},
        {"limitation_codes": ["unknown"]},
        {"raw_bytes": bytearray(b"{}")},
    ],
)
def test_capture_rejects_invalid_metadata(changes: dict[str, object]) -> None:
    with pytest.raises(BundleError):
        replace(capture(), **changes)


def test_imported_origin_can_be_retained_as_claim_but_not_reclassified() -> None:
    assert replace(capture(), origin="imported").origin == "imported"


@pytest.mark.parametrize("minimum", [True, 0, 1, 2.5, "2"])
def test_snapshot_settings_require_explicit_integer_history(minimum: object) -> None:
    with pytest.raises(BundleError):
        SnapshotSettings(BarInterval.ONE_DAY, NOW, minimum)  # type: ignore[arg-type]


@pytest.mark.parametrize("interval", ["one_day", None])
def test_snapshot_settings_do_not_coerce_interval(interval: object) -> None:
    with pytest.raises(BundleError):
        SnapshotSettings(interval, NOW, 2)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "blobs",
    [[], (("../outside", b"{}"),), (("a" * 64, "{}"),), (("a" * 64, b"{}"),) * 2],
)
def test_package_requires_immutable_unique_digest_blobs(blobs: object) -> None:
    with pytest.raises(BundleError):
        BundlePackage(b"{}", blobs)  # type: ignore[arg-type]


def test_raw_bodies_are_not_in_default_representations() -> None:
    secret_marker = b"private-payload-marker"
    assert "private-payload-marker" not in repr(replace(capture(), raw_bytes=secret_marker))
    assert "private-payload-marker" not in repr(
        BundlePackage(secret_marker, ((DataHash("a" * 64), secret_marker),))
    )


def test_error_message_and_arguments_contain_only_registered_code() -> None:
    error = BundleError("bundle_json_invalid", record_index=2)
    assert error.args == ("bundle_json_invalid",)
    assert error.code == "bundle_json_invalid"
    assert error.record_index == 2
    with pytest.raises(ValueError, match=r"^bundle_value_invalid$"):
        BundleError("private-payload-marker")
    with pytest.raises(ValueError, match=r"^bundle_value_invalid$"):
        BundleError("bundle_json_invalid", record_index=True)


@pytest.mark.parametrize(
    "changes",
    [
        {"raw_hashes": ["a" * 64]},
        {"cleaned_hashes": ("../outside",)},
        {"point_in_time_universe": 1},
        {"known_gaps": ["unknown"]},
        {"manifest_hash": "../outside"},
        {"corporate_action_coverage": "private prose payload"},
    ],
)
def test_envelope_rejects_mutable_or_untyped_legacy_manifest(changes: dict) -> None:
    from tests.unit.market_data.test_bundle_codec import LIMITS, encoded, wire_envelope
    from trading_bot.market_data.bundle_codec import decode_envelope

    envelope = decode_envelope(encoded(wire_envelope()), limits=LIMITS)
    with pytest.raises(BundleError):
        replace(envelope, manifest=replace(envelope.manifest, **changes))


def test_action_entry_rejects_untyped_effective_date_even_if_legacy_constructor_accepts() -> None:
    from tests.unit.market_data.test_bundle_codec import LIMITS, encoded, wire_envelope
    from trading_bot.market_data.bundle_codec import decode_envelope

    entry = decode_envelope(encoded(wire_envelope()), limits=LIMITS).records[3]
    bad_action = replace(entry.value, effective_date="2026-01-01")
    with pytest.raises(BundleError):
        replace(entry, value=bad_action)
