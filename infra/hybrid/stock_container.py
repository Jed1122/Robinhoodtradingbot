"""Data-only Engine/image policy observations; never contacts a Docker daemon.

Profiles describe supplied metadata, not authenticated provenance or permission to
create/start a container. Native Engine/image verification remains mandatory.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, NoReturn

API_VERSION = "1.55"
_TARGET_API = (1, 55)
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_VERSION = re.compile(r"(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\Z")
_FIXED_ENV = {
    "LANG": "C.UTF-8",
    "PYTHONPATH": "/app/src",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "LIVE_TRADING_ENABLED": "false",
    "PREDICTION_LIVE_ENABLED": "false",
}
_ENV_KEYS = set(_FIXED_ENV) | {"PATH", "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256"}
_BASE_PATHS = {"/usr/local/bin", "/usr/local/sbin", "/usr/bin", "/usr/sbin", "/bin", "/sbin"}
_HEALTH_TEST = [
    "CMD",
    "python",
    "-c",
    "import urllib.request; "
    "urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).close()",
]
_HEALTH_INTEGERS = {
    "Interval": 15000000000,
    "Timeout": 3000000000,
    "StartPeriod": 5000000000,
    "Retries": 3,
}


@dataclass(frozen=True, slots=True)
class EngineProfile:
    api_version: str
    architecture: str


@dataclass(frozen=True, slots=True)
class ImageProfile:
    image_digest: str
    architecture: str
    environment: tuple[str, ...] = field(repr=False)
    disabled_healthcheck: bytes = field(repr=False)


def _deny() -> NoReturn:
    raise ValueError("stock_container_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _constant(_value: str) -> NoReturn:
    _deny()


def _finite_float(value: str) -> float:
    parsed = float(value)
    _require(math.isfinite(parsed))
    return parsed


def _object(raw: bytes) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= 1048576)
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_pairs,
        parse_constant=_constant,
        parse_float=_finite_float,
    )
    _require(type(value) is dict)
    return dict(value)


def _version(value: Any) -> tuple[int, int]:
    _require(type(value) is str)
    match = _VERSION.fullmatch(value)
    if match is None:
        _deny()
    return int(match[1]), int(match[2])


def verify_engine_version(raw: bytes) -> EngineProfile:
    """Require the versioned Linux API profile; no negotiation or daemon call."""
    try:
        record = _object(raw)
        minimum, maximum = _version(record["MinAPIVersion"]), _version(record["ApiVersion"])
        _require(minimum <= _TARGET_API <= maximum)
        _require(record["Os"] == "linux" and record["Arch"] in ("amd64", "arm64"))
        return EngineProfile(API_VERSION, record["Arch"])
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        _deny()


def _environment(value: Any) -> tuple[str, ...]:
    _require(type(value) is list and len(value) == len(_ENV_KEYS))
    entries: dict[str, str] = {}
    for item in value:
        _require(type(item) is str and len(item) <= 1024)
        key, separator, text = item.partition("=")
        _require(separator == "=" and key in _ENV_KEYS and key not in entries)
        _require(text.isascii() and not any(ord(character) < 32 for character in text))
        entries[key] = text
    _require(set(entries) == _ENV_KEYS)
    for key, expected in _FIXED_ENV.items():
        _require(entries[key] == expected)
    _require(re.fullmatch(r"[A-F0-9]{40}", entries["GPG_KEY"]) is not None)
    _require(re.fullmatch(r"3\.12\.(0|[1-9][0-9]{0,2})", entries["PYTHON_VERSION"]) is not None)
    _require(re.fullmatch(r"[a-f0-9]{64}", entries["PYTHON_SHA256"]) is not None)
    paths = entries["PATH"].split(":")
    _require(paths[0] == "/app/.venv/bin" and len(paths) <= 16)
    _require(all(path in _BASE_PATHS for path in paths[1:]))
    _require({"/usr/local/bin", "/usr/bin", "/bin"}.issubset(paths[1:]))
    return tuple(value)


def _empty_metadata(value: Any) -> bool:
    return value is None or (type(value) is dict and len(value) == 0)


def _disabled_healthcheck(value: Any) -> bytes:
    _require(type(value) is dict)
    required = {"Test", *_HEALTH_INTEGERS}
    _require(set(value) in (required, required | {"StartInterval"}))
    _require(type(value["Test"]) is list and value["Test"] == _HEALTH_TEST)
    for key, expected in _HEALTH_INTEGERS.items():
        _require(type(value[key]) is int and value[key] == expected)
    if "StartInterval" in value:
        _require(type(value["StartInterval"]) is int and value["StartInterval"] == 0)
    disabled = {**value, "Test": ["NONE"]}
    return (json.dumps(disabled, sort_keys=True, separators=(",", ":")) + "\n").encode()


def verify_image(raw: bytes, expected_image: str, engine: EngineProfile) -> ImageProfile:
    """Check implicit image effects before any inert probe or worker creation."""
    try:
        _require(type(expected_image) is str and _IMAGE.fullmatch(expected_image) is not None)
        _require(type(engine) is EngineProfile and engine.api_version == API_VERSION)
        _require(engine.architecture in ("amd64", "arm64"))
        record = _object(raw)
        _require(record["Id"] == expected_image and record["Os"] == "linux")
        _require(record["Architecture"] == engine.architecture)
        config = record["Config"]
        _require(type(config) is dict)
        _require(config["User"] == "10001:10001" and config["WorkingDir"] == "/app")
        for key in ("Volumes", "ExposedPorts", "Labels"):
            _require(_empty_metadata(config.get(key)))
        for key in ("OnBuild", "Shell"):
            _require(config.get(key) is None or (type(config[key]) is list and not config[key]))
        _require(config.get("ArgsEscaped", False) is False)
        environment = _environment(config["Env"])
        disabled = _disabled_healthcheck(config["Healthcheck"])
        return ImageProfile(expected_image, engine.architecture, environment, disabled)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        _deny()
