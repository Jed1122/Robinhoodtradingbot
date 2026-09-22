"""Pure four-dimensional evidence assessment; never a live authorization gate."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from trading_bot.capabilities.models import (
    CapabilityManifest,
    CapabilityVerification,
    EvidenceLevel,
    VerificationDimension,
    validated_manifest_copy,
)
from trading_bot.clock import require_utc

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class VerificationContext:
    """Current schema and opaque identity bindings, never account numbers or credentials."""

    now: datetime
    schema_sha256: str
    session_ref: str
    account_ref: str
    runtime_ref: str

    def __post_init__(self) -> None:
        valid = False
        try:
            if type(self.now) is not datetime:
                raise ValueError
            now = require_utc(self.now)
            if not all(
                type(value) is str and _DIGEST.fullmatch(value) is not None
                for value in (
                    self.schema_sha256,
                    self.session_ref,
                    self.account_ref,
                    self.runtime_ref,
                )
            ):
                raise ValueError
            object.__setattr__(self, "now", now)
            valid = True
        except MemoryError:
            raise
        except Exception:
            valid = False
        if not valid:
            raise ValueError("invalid verification context") from None


@dataclass(frozen=True, slots=True)
class DimensionAssessment:
    dimension: VerificationDimension
    reason: str


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    dimensions: tuple[DimensionAssessment, ...]
    operation_reason: str

    @property
    def evidence_complete(self) -> bool:
        complete = False
        try:
            complete = (
                type(self.operation_reason) is str
                and self.operation_reason == "unlocked"
                and type(self.dimensions) is tuple
                and len(self.dimensions) == len(VerificationDimension)
                and all(
                    type(item) is DimensionAssessment
                    and type(item.dimension) is VerificationDimension
                    and type(item.reason) is str
                    and item.reason == "verified"
                    for item in self.dimensions
                )
                and {item.dimension for item in self.dimensions} == set(VerificationDimension)
            )
        except MemoryError:
            raise
        except Exception:
            complete = False
        return complete

    @property
    def production_eligible(self) -> Literal[False]:
        """Evidence is necessary but cannot grant execution authority."""
        return False


def assess_operation(
    manifest: CapabilityManifest,
    *,
    provider: str,
    operation: str,
    context: VerificationContext,
) -> VerificationDecision:
    """Select latest scoped observations without falling back after denial or expiry.

    Legacy evidence levels do not imply verification dimensions. Unrelated operations and
    identities cannot satisfy a dimension. Later schema changes invalidate the affected scope.
    """
    result: VerificationDecision | None = None
    try:
        if type(context) is not VerificationContext:
            raise ValueError
        current = VerificationContext(
            context.now,
            context.schema_sha256,
            context.session_ref,
            context.account_ref,
            context.runtime_ref,
        )
        checked = validated_manifest_copy(manifest)
        record = checked.find(provider=provider, operation=operation)
        witnesses = tuple(
            item
            for item in checked.verifications
            if item.provider == provider and item.operation == operation
        )
        dimensions = tuple(
            DimensionAssessment(dimension, _reason(witnesses, dimension, current))
            for dimension in VerificationDimension
        )
        locked = record.locked_reason is not None or any(
            item.level is EvidenceLevel.UNSUPPORTED for item in record.evidence
        )
        result = VerificationDecision(dimensions, "locked" if locked else "unlocked")
    except MemoryError:
        raise
    except Exception:
        result = None
    return result or VerificationDecision(
        tuple(
            DimensionAssessment(dimension, "invalid_or_missing_operation")
            for dimension in VerificationDimension
        ),
        "invalid_or_missing_operation",
    )


def _reason(
    witnesses: tuple[CapabilityVerification, ...],
    dimension: VerificationDimension,
    context: VerificationContext,
) -> str:
    matches = tuple(
        item
        for item in witnesses
        if item.dimension is dimension
        and (item.session_ref is None or item.session_ref == context.session_ref)
        and (item.account_ref is None or item.account_ref == context.account_ref)
        and (item.runtime_ref is None or item.runtime_ref == context.runtime_ref)
    )
    if not matches:
        return "missing"
    latest = max(matches, key=lambda item: item.evidence.observed_at)
    if latest.synthetic:
        return "synthetic"
    if latest.evidence.observed_at > context.now:
        return "future"
    if latest.valid_until <= context.now:
        return "expired"
    if (
        dimension is not VerificationDimension.PUBLIC
        and latest.evidence.schema_sha256 != context.schema_sha256
    ):
        return "schema_mismatch"
    return latest.status.value
