"""Pure observation normalization; no container or configuration load occurs."""

import json

import pytest

from infra.hybrid import stock_release


def observation():
    return {
        "status": "succeeded",
        "schema_version": 1,
        "kind": "stock_research_configuration_identity",
        "config_hash": "c" * 64,
        "scan_interval_seconds": 3600,
        "max_run_seconds": 450,
        "max_daily_calls": 512,
        "max_calls_per_cycle": 32,
        "maximum_source_age_seconds": 7200,
        "live_enabled": False,
    }


def normalize(raw):
    parser = getattr(stock_release, "normalize_configuration_observation", None)
    assert callable(parser), "Pure configuration-observation normalization is missing"
    return parser(raw)


def test_noncanonical_probe_output_has_one_canonical_identity():
    result = normalize(json.dumps(observation(), indent=2).encode())
    assert result == (
        b'{"config_hash":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",'
        b'"kind":"stock_research_configuration_identity","live_enabled":false,'
        b'"max_calls_per_cycle":32,"max_daily_calls":512,"max_run_seconds":450,'
        b'"maximum_source_age_seconds":7200,"scan_interval_seconds":3600,'
        b'"schema_version":1,"status":"succeeded"}\n'
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "blocked"),
        ("status", True),
        ("schema_version", True),
        ("schema_version", 1.0),
        ("schema_version", 0),
        ("schema_version", 2),
        ("kind", "stock_research_release"),
        ("config_hash", ""),
        ("config_hash", "C" * 64),
        ("config_hash", "c" * 63),
        ("config_hash", None),
        ("config_hash", 64),
        ("live_enabled", True),
        ("live_enabled", 0),
        ("live_enabled", "false"),
        ("live_enabled", None),
        ("max_run_seconds", 59),
        ("max_run_seconds", 451),
        ("max_run_seconds", True),
        ("max_run_seconds", 60.0),
        ("max_run_seconds", "60"),
        ("scan_interval_seconds", 899),
        ("scan_interval_seconds", 3601),
        ("scan_interval_seconds", 901),
        ("scan_interval_seconds", True),
        ("scan_interval_seconds", 900.0),
        ("scan_interval_seconds", "900"),
        ("max_daily_calls", 0),
        ("max_daily_calls", 1025),
        ("max_daily_calls", True),
        ("max_daily_calls", 32.0),
        ("max_calls_per_cycle", 0),
        ("max_calls_per_cycle", 33),
        ("max_calls_per_cycle", True),
        ("max_calls_per_cycle", 1.0),
        ("maximum_source_age_seconds", 59),
        ("maximum_source_age_seconds", 86401),
        ("maximum_source_age_seconds", 61),
        ("maximum_source_age_seconds", True),
        ("maximum_source_age_seconds", 60.0),
    ],
)
def test_unknown_unsafe_or_type_equivalent_policy_values_deny(field, value):
    row = observation()
    row[field] = value
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        normalize(json.dumps(row).encode())


@pytest.mark.parametrize("field", observation())
def test_missing_observation_fields_deny(field):
    row = observation()
    del row[field]
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        normalize(json.dumps(row).encode())


def test_extra_observation_fields_deny():
    row = {**observation(), "source_qualified": True}
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        normalize(json.dumps(row).encode())


def test_cycle_budget_cannot_exceed_daily_budget():
    row = {**observation(), "max_calls_per_cycle": 2, "max_daily_calls": 1}
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        normalize(json.dumps(row).encode())


@pytest.mark.parametrize(
    "updates",
    [
        {
            "max_run_seconds": 60,
            "scan_interval_seconds": 900,
            "max_daily_calls": 1,
            "max_calls_per_cycle": 1,
            "maximum_source_age_seconds": 60,
        },
        {"max_daily_calls": 1024, "maximum_source_age_seconds": 86400},
    ],
)
def test_exact_valid_boundaries_remain_available(updates):
    row = {**observation(), **updates}
    assert json.loads(normalize(json.dumps(row).encode())) == row


@pytest.mark.parametrize("raw", [None, "{}", bytearray(b"{}"), 1, b"", b"[]", b"{}", b"\xff"])
def test_invalid_input_type_or_document_deny(raw):
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        normalize(raw)


@pytest.mark.parametrize("token", [b"NaN", b"Infinity", b"-Infinity", b"1e309"])
def test_nonfinite_values_cannot_be_normalized(token):
    raw = (
        json.dumps(observation())
        .encode()
        .replace(b'"max_run_seconds": 450', b'"max_run_seconds": ' + token)
    )
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        normalize(raw)


def test_duplicate_keys_are_not_resolved_by_last_value():
    raw = b'{"live_enabled":true,' + json.dumps(observation()).encode()[1:]
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        normalize(raw)


def test_valid_document_over_byte_limit_denies():
    raw = json.dumps(observation()).encode()
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        normalize(raw + b" " * (4097 - len(raw)))


def test_multiple_json_results_deny():
    raw = json.dumps(observation()).encode()
    with pytest.raises(ValueError, match=r"^stock_release_unavailable$"):
        normalize(raw + b"\n" + raw)
