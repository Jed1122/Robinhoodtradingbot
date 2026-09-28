"""Strict source contracts retain unknowns and expose no trust-token decoder."""

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from tests.unit.market_data._options_source_fixtures import (
    AS_OF,
    END,
    START,
    arrangement,
    config,
    module,
)
from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401


def test_nanosecond_availability_is_not_rounded_into_past():
    assert module("verify").ceil_available_at(1704205800000000001) == datetime(
        2024, 1, 2, 14, 30, 0, 1, tzinfo=UTC
    )
    assert module("verify").ceil_available_at(1704205800000000000) == datetime(
        2024, 1, 2, 14, 30, tzinfo=UTC
    )


@pytest.mark.parametrize("value", [True, 1.0, 0, -1, 2**63])
def test_invalid_native_visibility_timestamp_rejected(value):
    api = module("verify")
    with pytest.raises(ValueError):
        api.ceil_available_at(value)


def test_bundle_codec_roundtrip_cannot_decode_a_trusted_result(tmp_path):
    bundle, _, _ = arrangement(tmp_path)
    wire = module("wire")
    encoded = wire.encode_source_bundle(bundle)
    assert wire.decode_source_bundle(encoded, loaded=config()) == bundle
    assert not hasattr(wire, "decode_source_verification")
    with pytest.raises(FrozenInstanceError):
        bundle.claims = ()


@pytest.mark.parametrize(
    "change",
    [{"verified": True}, {"production_eligible": True}, {"rule_expression": "trust everything"}],
)
def test_unknown_source_authority_fields_deny(tmp_path, change):
    bundle, _, _ = arrangement(tmp_path)
    wire = module("wire")
    value = json.loads(wire.encode_source_bundle(bundle))
    value["claims"][0].update(change)
    with pytest.raises(ValueError):
        wire.decode_source_bundle(json.dumps(value).encode(), loaded=config())


@pytest.mark.parametrize(
    "changes",
    [
        {"role": "unknown"},
        {"era_start_ns": True},
        {"published_at_ns": 1.0},
        {"observed_at": datetime(2024, 1, 1)},
        {"effective_end_ns": START},
        {"raw_hashes": ("bad",)},
        {"raw_hashes": ["a" * 64]},
    ],
)
def test_claim_requires_exact_bounded_immutable_fields(tmp_path, changes):
    bundle, _, _ = arrangement(tmp_path)
    with pytest.raises(ValueError):
        replace(bundle.claims[0], **changes)


def test_rules_cannot_install_executable_or_unknown_verifier(tmp_path):
    _, _, rules = arrangement(tmp_path)
    with pytest.raises(ValueError):
        replace(rules[0], verifier_id="arbitrary-import-or-code")


def test_context_requires_strict_hashes_and_window():
    model = module("models")
    for start, end in ((True, END), (END, START), (START, 2**63)):
        with pytest.raises(ValueError):
            model.VerificationContext(AS_OF, start, end, "a" * 64, "b" * 64, "c" * 64)


def test_claim_publication_cannot_postdate_its_observation(tmp_path):
    bundle, _, _ = arrangement(tmp_path)
    with pytest.raises(ValueError):
        replace(bundle.claims[0], observed_at=datetime(2020, 1, 1, tzinfo=UTC))
