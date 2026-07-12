"""Evidence-backed capability registry with no transport or account access."""

from trading_bot.capabilities.models import (
    CapabilityEvidence,
    CapabilityManifest,
    CapabilityNotFoundError,
    CapabilityRecord,
    CapabilityValidationError,
    EvidenceLevel,
    InvalidCapabilityEvidence,
    InvalidCapabilityManifest,
    InvalidCapabilityRecord,
    OperationKind,
    UnsupportedCapabilityError,
)
from trading_bot.capabilities.registry import require_capability
from trading_bot.capabilities.snapshot import JsonValue, canonical_sha256

__all__ = [
    "CapabilityEvidence",
    "CapabilityManifest",
    "CapabilityNotFoundError",
    "CapabilityRecord",
    "CapabilityValidationError",
    "EvidenceLevel",
    "InvalidCapabilityEvidence",
    "InvalidCapabilityManifest",
    "InvalidCapabilityRecord",
    "JsonValue",
    "OperationKind",
    "UnsupportedCapabilityError",
    "canonical_sha256",
    "require_capability",
]
