"""Exact-match capability lookup and fail-closed requirements."""

from trading_bot.capabilities.models import (
    CapabilityManifest,
    CapabilityNotFoundError,
    CapabilityRecord,
    EvidenceLevel,
    UnsupportedCapabilityError,
)

__all__ = ["UnsupportedCapabilityError", "require_capability"]


def require_capability(
    manifest: CapabilityManifest,
    *,
    provider: str,
    operation: str,
    minimum: EvidenceLevel,
) -> CapabilityRecord:
    """Require an exact unlocked evidence category for a provider operation."""
    try:
        record = manifest.find(provider=provider, operation=operation)
    except CapabilityNotFoundError:
        raise UnsupportedCapabilityError(provider, operation, minimum) from None
    if not record.satisfies(minimum):
        raise UnsupportedCapabilityError(provider, operation, minimum)
    return record
