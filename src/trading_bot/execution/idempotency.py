"""Deterministic internal idempotency keys for one persisted intent."""

import hashlib

from trading_bot.domain import DomainValidationError, OrderIntent


def derive_deduplication_key(intent: OrderIntent) -> str:
    """Hash the canonical internal submission identity without changing client IDs."""

    if type(intent) is not OrderIntent:
        raise DomainValidationError("intent must be an OrderIntent")
    canonical = (
        f"{intent.account_id}|{intent.id}|{intent.config_hash}|{intent.purpose.value}"
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


__all__ = ["derive_deduplication_key"]
