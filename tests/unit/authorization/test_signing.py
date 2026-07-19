from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from nacl.signing import SigningKey

from trading_bot.authorization import (
    ActivationPayload,
    InvalidAuthorization,
    sign_activation,
    verify_activation,
)
from trading_bot.domain import AccountId, CodeHash, ConfigHash, ExecutionMode

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def valid_payload() -> ActivationPayload:
    return ActivationPayload(
        "authorization-1",
        "nonce-1",
        AccountId("account-1"),
        ExecutionMode.MICRO_LIVE,
        Decimal("100"),
        "1" * 64,
        "2" * 64,
        ConfigHash("3" * 64),
        CodeHash("4" * 64),
        "5" * 64,
        "6" * 64,
        NOW,
        NOW + timedelta(minutes=15),
    )


def test_tampered_artifact_is_rejected() -> None:
    key = SigningKey.generate()
    signed = sign_activation(valid_payload(), key)
    tampered = replace(signed, payload=replace(signed.payload, account_id=AccountId("other")))
    with pytest.raises(InvalidAuthorization, match="signature"):
        verify_activation(tampered, key.verify_key, now=NOW)


def test_valid_artifact_verifies_to_stable_hash() -> None:
    key = SigningKey.generate()
    signed = sign_activation(valid_payload(), key)
    assert verify_activation(signed, key.verify_key, now=NOW) == verify_activation(
        signed, key.verify_key, now=NOW
    )
