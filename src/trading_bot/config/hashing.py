"""Canonical serialization and SHA-256 binding for configuration."""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from trading_bot.config.models import AppConfig, SafetyEnvelope
from trading_bot.domain import ConfigHash


def _hash_payload(payload: Mapping[str, Any]) -> tuple[bytes, ConfigHash]:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return canonical, ConfigHash(hashlib.sha256(canonical).hexdigest())


def hash_config(config: AppConfig) -> tuple[bytes, ConfigHash]:
    """Hash one resolved app config for non-authorization callers."""

    raw = config.model_dump(mode="json", round_trip=True)
    return _hash_payload(raw)


def hash_loaded_config(
    config: AppConfig, envelope: SafetyEnvelope
) -> tuple[bytes, ConfigHash]:
    """Bind authorization identity to both config and release safety envelope."""

    return _hash_payload(
        {
            "config": config.model_dump(mode="json", round_trip=True),
            "safety_envelope": envelope.model_dump(mode="json", round_trip=True),
        }
    )
