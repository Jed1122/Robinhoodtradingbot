"""Data-only Docker metadata checks with fictional images and no daemon access."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "sha256:" + "b" * 64
ENV = [
    "PATH=/app/.venv/bin:/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG=C.UTF-8",
    "GPG_KEY=" + "A" * 40,
    "PYTHON_VERSION=3.12.13",
    "PYTHON_SHA256=" + "a" * 64,
    "PYTHONPATH=/app/src",
    "PYTHONDONTWRITEBYTECODE=1",
    "PYTHONUNBUFFERED=1",
    "LIVE_TRADING_ENABLED=false",
    "PREDICTION_LIVE_ENABLED=false",
]


def module():
    source = ROOT / "infra/hybrid/stock_container.py"
    assert source.is_file(), "Stock Engine/image observation verification is not implemented"
    spec = importlib.util.spec_from_file_location("stock_container_fixture", source)
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


def encoded(value):
    return json.dumps(value).encode()


def engine():
    return {"ApiVersion": "1.52", "MinAPIVersion": "1.44", "Os": "linux", "Arch": "amd64"}


def image():
    return {
        "Id": IMAGE,
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {
            "User": "10001:10001",
            "WorkingDir": "/app",
            "Env": ENV.copy(),
            "Volumes": None,
            "ExposedPorts": None,
            "Labels": None,
            "Healthcheck": {
                "Test": [
                    "CMD",
                    "python",
                    "-c",
                    "import urllib.request; "
                    "urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).close()",
                ],
                "Interval": 15000000000,
                "Timeout": 3000000000,
                "StartPeriod": 5000000000,
                "Retries": 3,
            },
        },
    }


def observed_image(value=None):
    verifier = module()
    host = verifier.verify_engine_version(encoded(engine()))
    return verifier.verify_image(encoded(value if value is not None else image()), IMAGE, host)


def test_verified_profiles_retain_only_supported_identity_and_environment():
    verifier = module()
    host = verifier.verify_engine_version(encoded(engine()))
    assert host.api_version == "1.52" and host.architecture == "amd64"
    result = verifier.verify_image(encoded(image()), IMAGE, host)
    assert result.image_digest == IMAGE and result.architecture == host.architecture
    assert result.environment == tuple(ENV)
    assert "GPG_KEY" not in repr(result)
    assert json.loads(result.disabled_healthcheck)["Test"] == ["NONE"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("ApiVersion", "1.51"),
        ("ApiVersion", "1.9"),
        ("ApiVersion", "1.052"),
        ("ApiVersion", 1.52),
        ("MinAPIVersion", "1.53"),
        ("MinAPIVersion", None),
        ("Os", "windows"),
        ("Arch", "fictional"),
    ],
)
def test_engine_requires_explicit_supported_api_range_and_linux(field, value):
    record = engine()
    record[field] = value
    with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
        module().verify_engine_version(encoded(record))


def test_newer_daemon_can_serve_the_fixed_supported_api_without_negotiation():
    record = engine()
    record["ApiVersion"] = "1.53"
    assert module().verify_engine_version(encoded(record)).api_version == "1.52"


@pytest.mark.parametrize(
    "field,value",
    [
        ("Id", "sha256:" + "e" * 64),
        ("Id", "b" * 64),
        ("Os", "windows"),
        ("Architecture", "arm64"),
        ("Config", None),
    ],
)
def test_image_requires_exact_local_id_and_matching_host_platform(field, value):
    record = image()
    record[field] = value
    with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
        observed_image(record)


@pytest.mark.parametrize(
    "field,value",
    [
        ("User", "root"),
        ("WorkingDir", "/unreviewed"),
        ("Volumes", {"/secret": {}}),
        ("ExposedPorts", {"8080/tcp": {}}),
        ("Labels", {"unreviewed": "fictional"}),
        ("OnBuild", ["fictional"]),
        ("Shell", ["/unreviewed"]),
        ("ArgsEscaped", True),
    ],
)
def test_implicit_image_configuration_cannot_expand_worker_policy(field, value):
    record = image()
    record["Config"][field] = value
    with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
        observed_image(record)


@pytest.mark.parametrize(
    "entry",
    [
        "HTTPS_PROXY=fictional-secret",
        "HTTP_PROXY=fictional-secret",
        "http_proxy=fictional-secret",
        "BROKER_TOKEN=fictional-secret",
        "PYTHONHOME=/unreviewed",
        "PYTHONSTARTUP=/unreviewed",
        "CONFIG_ROOT=/unreviewed",
        "LD_PRELOAD=/unreviewed",
        "BARE_KEY",
        "=value",
        "LIVE_TRADING_ENABLED=true",
        "PREDICTION_LIVE_ENABLED=true",
        "PYTHONPATH=/unreviewed",
        "PYTHONDONTWRITEBYTECODE=0",
        "PYTHONUNBUFFERED=0",
        "LANG=en_US.UTF-8",
        "PYTHON_VERSION=3.13.0",
        "PYTHON_SHA256=unknown",
        "GPG_KEY=fictional-secret",
        "PATH=/app/.venv/bin:.:/bin",
        "PATH=/app/.venv/bin::/bin",
        "PATH=/tmp:/bin",
    ],
)
def test_unreviewed_inherited_environment_is_denied_without_disclosure(entry):
    record = image()
    key = entry.partition("=")[0]
    record["Config"]["Env"] = [item for item in ENV if item.partition("=")[0] != key] + [entry]
    with pytest.raises(ValueError, match=r"^stock_container_unavailable$") as error:
        observed_image(record)
    assert "fictional-secret" not in str(error.value)


@pytest.mark.parametrize("change", ["duplicate", "bare", "missing", "not_array", "not_string"])
def test_environment_requires_one_explicit_value_for_each_reviewed_key(change):
    record = image()
    if change == "duplicate":
        record["Config"]["Env"].append("LIVE_TRADING_ENABLED=false")
    elif change == "bare":
        record["Config"]["Env"][0] = "PATH"
    elif change == "missing":
        record["Config"]["Env"].pop()
    elif change == "not_array":
        record["Config"]["Env"] = {}
    else:
        record["Config"]["Env"][0] = False
    with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
        observed_image(record)


@pytest.mark.parametrize(
    "raw",
    [b"", b"[]", b"null", b"{}", b"\xff", b'{"x":NaN}', b'{"x":1,"x":1}', b" " * (1048576 + 1)],
    ids=["empty", "array", "null", "missing", "non_utf8", "nonfinite", "duplicate", "oversize"],
)
def test_both_observations_require_bounded_strict_json_objects(raw):
    verifier = module()
    host = verifier.verify_engine_version(encoded(engine()))
    for call in (
        lambda: verifier.verify_engine_version(raw),
        lambda: verifier.verify_image(raw, IMAGE, host),
    ):
        with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
            call()


def test_inputs_are_not_modified_and_arm64_requires_both_platform_observations():
    verifier = module()
    host_record, image_record = engine(), image()
    host_record["Arch"] = image_record["Architecture"] = "arm64"
    original = copy.deepcopy(image_record)
    host = verifier.verify_engine_version(encoded(host_record))
    assert verifier.verify_image(encoded(image_record), IMAGE, host).architecture == "arm64"
    assert image_record == original


@pytest.mark.parametrize(
    "change", ["missing", "wrong_test", "wrong_timing", "bool_timing", "extra"]
)
def test_inherited_healthcheck_metadata_is_explicit_and_reviewed(change):
    record = image()
    healthcheck = record["Config"]["Healthcheck"]
    if change == "missing":
        del record["Config"]["Healthcheck"]
    elif change == "wrong_test":
        healthcheck["Test"] = ["NONE"]
    elif change == "wrong_timing":
        healthcheck["Interval"] = 1
    elif change == "bool_timing":
        healthcheck["Retries"] = True
    else:
        healthcheck["Unsupported"] = 0
    with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
        observed_image(record)


def test_documented_zero_start_interval_and_absent_empty_maps_are_safe():
    record = image()
    record["Config"]["Healthcheck"]["StartInterval"] = 0
    for key in ("Volumes", "ExposedPorts", "Labels"):
        del record["Config"][key]
    result = observed_image(record)
    assert json.loads(result.disabled_healthcheck)["StartInterval"] == 0


@pytest.mark.parametrize(
    "field", [b'"ignored_number":1e999', b'"ignored_nested":{"number":-1e999}']
)
def test_nonfinite_exponent_overflow_is_denied_even_in_ignored_fields(field):
    verifier = module()
    host = verifier.verify_engine_version(encoded(engine()))
    for record, call in (
        (engine(), verifier.verify_engine_version),
        (image(), lambda raw: verifier.verify_image(raw, IMAGE, host)),
    ):
        raw = encoded(record)[:-1] + b"," + field + b"}"
        with pytest.raises(ValueError, match=r"^stock_container_unavailable$"):
            call(raw)
