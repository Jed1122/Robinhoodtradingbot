"""Study declarations are closed planning inputs, never purchase approval flags."""

import json
from dataclasses import asdict

import pytest

from tests.unit.market_data._options_source_fixtures import config
from tests.unit.research.test_options_acquisition import api, build, fixture_case
from trading_bot.market_data.recording import canonical_json


def test_study_roundtrip_and_path_free_output(tmp_path, monkeypatch):
    value = fixture_case(tmp_path, monkeypatch)
    body = canonical_json({"schema": "options-study-coverage-v1", **asdict(value.study)}).encode()
    assert api("_wire").decode_coverage_requirements(body, loaded=config()) == value.study
    output = api("_wire").encode_coverage_manifest(build(value))
    assert (
        str(tmp_path).encode() not in output
        and json.loads(output)["schema"] == "options-acquisition-manifest-v1"
    )


@pytest.mark.parametrize(
    "field", ["approved", "download_authorized", "prices", "api_key", "estimated_credit_balance"]
)
def test_trust_spending_or_price_fields_are_rejected(tmp_path, monkeypatch, field):
    value = fixture_case(tmp_path, monkeypatch)
    body = {"schema": "options-study-coverage-v1", **asdict(value.study), field: True}
    with pytest.raises(ValueError):
        api("_wire").decode_coverage_requirements(canonical_json(body).encode(), loaded=config())


def test_fractional_or_boolean_nanoseconds_rejected():
    models = api("_models")
    for stamp in (True, 1.1):
        with pytest.raises(ValueError):
            models.CoverageWindow(
                "OPRA.PILLAR", "cmbp-1", "SPY", "raw_symbol", stamp, 10, ("r",), ()
            )
