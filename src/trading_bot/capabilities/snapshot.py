"""Canonical hashes for sanitized JSON capability artifacts."""

import hashlib
import json
import math

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

__all__ = ["JsonValue", "canonical_sha256"]


def canonical_sha256(value: JsonValue) -> str:
    """Hash canonical JSON, sorting object keys while retaining array order."""
    _require_json_value(value)
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require_json_value(value: object) -> None:
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("canonical JSON numbers must be finite")
        return
    if type(value) is list:
        for item in value:
            _require_json_value(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("canonical JSON object keys must be strings")
            _require_json_value(item)
        return
    raise TypeError("canonical hashing accepts JSON values only")
