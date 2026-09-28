"""Closed source assertions and diagnostic findings; none is an execution capability."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain import ConfigHash, DataHash

type SourceRole = Literal[
    "calendar",
    "bar_publication",
    "actions",
    "definition_state",
    "contract_terms",
    "quote_semantics",
]
ROLES = (
    "actions",
    "bar_publication",
    "calendar",
    "contract_terms",
    "definition_state",
    "quote_semantics",
)
REASONS = frozenset(
    {
        "source_scope_mismatch",
        "historical_availability_unverified",
        "source_reference_unverified",
        "source_integrity_invalid",
        "source_coverage_unverified",
        "source_future_publication",
        "source_invalidated",
    }
)


class SourceEvidenceError(ValueError):
    def __init__(self) -> None:
        super().__init__("options_source_evidence_invalid")


def check(value: bool) -> None:
    if not value:
        raise SourceEvidenceError()


def instant(value: int) -> None:
    check(type(value) is int and 0 < value < 2**63)


def identity(value: str) -> None:
    check(
        type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is not None
    )


def hashes(value: tuple[DataHash, ...], *, nonempty: bool = False) -> None:
    check(type(value) is tuple and len(value) <= 25000 and (bool(value) or not nonempty))
    check(
        all(type(item) is str and re.fullmatch(r"[0-9a-f]{64}", item) is not None for item in value)
    )
    check(value == tuple(sorted(set(value))))


def reasons(value: tuple[str, ...]) -> None:
    check(type(value) is tuple and all(type(item) is str and item in REASONS for item in value))
    check(value == tuple(sorted(set(value))))


def window(start: int, end: int) -> None:
    instant(start)
    instant(end)
    check(start < end)


@dataclass(frozen=True, slots=True)
class SourceClaim:
    role: SourceRole
    source_id: str
    schema: str
    era_start_ns: int
    era_end_ns: int
    raw_hashes: tuple[DataHash, ...]
    observed_at: datetime
    published_at_ns: int | None
    effective_start_ns: int
    effective_end_ns: int
    coverage_hash: DataHash
    rule_id: str

    def __post_init__(self) -> None:
        check(type(self.role) is str and self.role in ROLES)
        for value in (self.source_id, self.schema, self.rule_id):
            identity(value)
        window(self.era_start_ns, self.era_end_ns)
        window(self.effective_start_ns, self.effective_end_ns)
        check(
            self.era_start_ns <= self.effective_start_ns < self.effective_end_ns <= self.era_end_ns
        )
        hashes(self.raw_hashes, nonempty=True)
        hashes((self.coverage_hash,))
        require_utc(self.observed_at)
        if self.published_at_ns is not None:
            instant(self.published_at_ns)
            elapsed = self.observed_at - datetime(1970, 1, 1, tzinfo=UTC)
            observed_ns = (
                elapsed.days * 86400 + elapsed.seconds
            ) * 10**9 + elapsed.microseconds * 1000
            check(self.published_at_ns <= observed_ns)


@dataclass(frozen=True, slots=True)
class PrivateArtifactRef:
    path: Path = field(repr=False)
    sha256: DataHash
    byte_count: int

    def __post_init__(self) -> None:
        check(
            isinstance(self.path, Path) and self.path.is_absolute() and ".." not in self.path.parts
        )
        hashes((self.sha256,))
        check(type(self.byte_count) is int and 0 < self.byte_count <= 16777216)


@dataclass(frozen=True, slots=True)
class SourceEvidenceBundle:
    claims: tuple[SourceClaim, ...]
    references: tuple[PrivateArtifactRef, ...]
    manifests: tuple[PrivateArtifactRef, ...]

    def __post_init__(self) -> None:
        for values, kind in (
            (self.claims, SourceClaim),
            (self.references, PrivateArtifactRef),
            (self.manifests, PrivateArtifactRef),
        ):
            check(type(values) is tuple and len(values) <= 25000)
            check(all(type(item) is kind for item in values))
        check(len(set(self.claims)) == len(self.claims))
        refs = self.references + self.manifests
        check(len({item.path for item in refs}) == len(refs))
        check(len({item.sha256 for item in refs}) == len(refs))


@dataclass(frozen=True, slots=True)
class VerificationContext:
    as_of_ns: int
    start_ns: int
    end_ns: int
    config_hash: ConfigHash
    code_hash: DataHash
    rulebook_hash: DataHash

    def __post_init__(self) -> None:
        instant(self.as_of_ns)
        window(self.start_ns, self.end_ns)
        for value in (self.config_hash, self.code_hash, self.rulebook_hash):
            hashes((DataHash(value),))


@dataclass(frozen=True, slots=True)
class SourceFinding:
    role: SourceRole
    status: Literal["verified", "denied"]
    visible_hashes: tuple[DataHash, ...]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        check(type(self.role) is str and self.role in ROLES)
        check(type(self.status) is str and self.status in ("verified", "denied"))
        hashes(self.visible_hashes)
        reasons(self.reasons)
        check((self.status == "denied") == bool(self.reasons))
        check(self.status != "verified" or bool(self.visible_hashes))


@dataclass(frozen=True, slots=True)
class SourceInvalidation:
    affected_hash: DataHash
    discovered_at: datetime
    reason: str

    def __post_init__(self) -> None:
        hashes((self.affected_hash,))
        require_utc(self.discovered_at)
        reasons((self.reason,))


@dataclass(frozen=True, slots=True)
class SourceVerification:
    context: VerificationContext
    status: Literal["verified", "denied"]
    source_hashes: tuple[DataHash, ...]
    record_hashes: tuple[DataHash, ...]
    visible_claim_hashes: tuple[DataHash, ...]
    findings: tuple[SourceFinding, ...]
    invalidations: tuple[SourceInvalidation, ...]
    reasons: tuple[str, ...]
    production_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    download_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        check(type(self.context) is VerificationContext)
        check(type(self.status) is str and self.status in ("verified", "denied"))
        for values in (self.source_hashes, self.record_hashes, self.visible_claim_hashes):
            hashes(values)
        check(type(self.findings) is tuple and 0 < len(self.findings) <= len(ROLES))
        check(all(type(item) is SourceFinding for item in self.findings))
        check(
            tuple(item.role for item in self.findings)
            == tuple(sorted({item.role for item in self.findings}))
        )
        check(type(self.invalidations) is tuple and len(self.invalidations) <= 25000)
        check(all(type(item) is SourceInvalidation for item in self.invalidations))
        reasons(self.reasons)
        check((self.status == "denied") == bool(self.reasons))
        check(self.status != "verified" or all(item.status == "verified" for item in self.findings))


@dataclass(frozen=True, slots=True)
class SourceRule:
    rule_id: str
    role: SourceRole
    source_id: str
    schema: str
    era_start_ns: int
    era_end_ns: int
    document_hashes: tuple[DataHash, ...]
    verifier_id: Literal["synthetic-records-v1"]

    def __post_init__(self) -> None:
        for value in (self.rule_id, self.source_id, self.schema):
            identity(value)
        check(type(self.role) is str and self.role in ROLES)
        window(self.era_start_ns, self.era_end_ns)
        hashes(self.document_hashes, nonempty=True)
        check(type(self.verifier_id) is str and self.verifier_id == "synthetic-records-v1")
