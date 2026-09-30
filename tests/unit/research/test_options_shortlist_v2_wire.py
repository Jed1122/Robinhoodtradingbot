"""Closed v2 request codec; no trusted-result or quote/outcome input channel."""

import json

import pytest

from tests.unit.market_data._options_source_fixtures import config
from tests.unit.research.test_options_shortlist_v2 import (
    api,
    arrangement,
    install_fixture_rules,
    run,
)


def test_exact_input_roundtrip(tmp_path):
    value = arrangement(tmp_path)
    wire = api("_wire")
    encoded = wire.encode_verified_shortlist_input(value.request)
    assert wire.decode_verified_shortlist_input(encoded, loaded=config()) == value.request
    assert json.loads(encoded)["schema"] == "options-shortlist-input-v2"


@pytest.mark.parametrize(
    "field", ["verification", "verified", "quotes", "returns", "live_authorized"]
)
def test_extra_trust_and_outcome_fields_are_rejected(tmp_path, field):
    value = arrangement(tmp_path)
    wire = api("_wire")
    encoded = json.loads(wire.encode_verified_shortlist_input(value.request))
    encoded[field] = True
    with pytest.raises(ValueError):
        wire.decode_verified_shortlist_input(json.dumps(encoded).encode(), loaded=config())


def test_result_is_path_free_diagnostic_not_a_trusted_input(tmp_path, monkeypatch):
    value = arrangement(tmp_path)
    install_fixture_rules(monkeypatch, value)
    wire = api("_wire")
    encoded = wire.encode_verified_shortlist_result(run(value))
    assert str(tmp_path).encode() not in encoded
    assert json.loads(encoded)["schema"] == "options-shortlist-result-v2"
    with pytest.raises(ValueError):
        wire.decode_verified_shortlist_input(encoded, loaded=config())


def test_input_bytes_limit_is_enforced_before_json_decode():
    wire = api("_wire")
    with pytest.raises(ValueError):
        wire.decode_verified_shortlist_input(
            b" " * (config().config.options.research_shortlist.max_input_bytes + 1), loaded=config()
        )
