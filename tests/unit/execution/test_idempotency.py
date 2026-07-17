"""Unit tests for deterministic internal order idempotency."""

import hashlib
from dataclasses import replace

import pytest

from tests.unit.execution._fixtures import make_intent
from trading_bot.domain import (
    AccountId,
    ConfigHash,
    DomainValidationError,
    OrderIntentId,
    OrderPurpose,
    Side,
)
from trading_bot.execution.idempotency import derive_deduplication_key


def test_deduplication_key_matches_the_canonical_internal_preimage() -> None:
    intent = make_intent()
    canonical = (
        f"{intent.account_id}|{intent.id}|{intent.config_hash}|{intent.purpose.value}"
    ).encode()

    assert derive_deduplication_key(intent) == hashlib.sha256(canonical).hexdigest()


def test_deduplication_key_is_stable_lowercase_sha256() -> None:
    intent = make_intent()

    first = derive_deduplication_key(intent)
    second = derive_deduplication_key(intent)

    assert first == second
    assert len(first) == 64
    assert set(first) <= set("0123456789abcdef")


@pytest.mark.parametrize(
    "changed",
    [
        replace(make_intent(), account_id=AccountId("other-paper-account")),
        replace(
            make_intent(),
            id=OrderIntentId("00000000-0000-4000-8000-000000000009"),
        ),
        replace(make_intent(), config_hash=ConfigHash("c" * 64)),
        replace(
            make_intent(),
            side=Side.SELL,
            purpose=OrderPurpose.PROTECTIVE_EXIT,
            exit_policy_version=None,
        ),
    ],
)
def test_any_canonical_identity_component_changes_the_key(changed: object) -> None:
    assert derive_deduplication_key(changed) != derive_deduplication_key(make_intent())  # type: ignore[arg-type]


def test_deduplication_rejects_noncanonical_intent() -> None:
    with pytest.raises(DomainValidationError, match="intent must be an OrderIntent"):
        derive_deduplication_key(object())  # type: ignore[arg-type]
