"""Immutable, fail-closed capability evidence models."""

import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import cast
from urllib.parse import urlsplit

from trading_bot.capabilities.sanitization import text_contains_sensitive_material
from trading_bot.clock import require_utc
from trading_bot.domain import AssetClass

_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_SOURCE_URI_SCHEMES = frozenset({"https", "mcp"})
_ALLOWED_HTTPS_HOSTS = frozenset({"robinhood.com", "docs.robinhood.com"})
_ALLOWED_MCP_HOST = "robinhood-trading"
_HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_PATH_SEGMENT = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._~-]{0,127})?\Z")
_DECLARED_OPERATION = re.compile(
    r"(?:cancel|create|exercise|get|mark|place|preview|review|run|search|update)"
    r"(?:_[a-z0-9]+)*\Z"
)


class CapabilityValidationError(ValueError):
    """Base class for invalid committed capability evidence."""


class InvalidCapabilityEvidence(CapabilityValidationError):
    """Raised when evidence is unsafe, ambiguous, or structurally invalid."""


class InvalidCapabilityRecord(CapabilityValidationError):
    """Raised when a provider operation record violates capability invariants."""


class InvalidCapabilityManifest(CapabilityValidationError):
    """Raised when a capability manifest cannot be safely committed or queried."""


class InvalidCapabilityVerification(CapabilityValidationError):
    """A scoped verification observation is malformed or contradictory."""


class CapabilityNotFoundError(LookupError):
    """Raised when an exact provider and operation key is absent."""

    def __init__(self, provider: str, operation: str) -> None:
        self.provider = _safe_error_text(provider, "<invalid-provider>")
        self.operation = _safe_error_text(operation, "<invalid-operation>")
        super().__init__("requested capability is not present")


class UnsupportedCapabilityError(RuntimeError):
    """Raised when an operation lacks the exact, unlocked evidence requested."""

    def __init__(
        self,
        provider: str,
        operation: str,
        minimum: "EvidenceLevel",
    ) -> None:
        self.provider = _safe_error_text(provider, "<invalid-provider>")
        self.operation = _safe_error_text(operation, "<invalid-operation>")
        self.minimum = minimum if type(minimum) is EvidenceLevel else EvidenceLevel.UNSUPPORTED
        super().__init__("requested capability does not have the required exact evidence")


class EvidenceLevel(StrEnum):
    """Independent evidence categories; members do not imply one another."""

    DOCUMENTED = "documented"
    SCHEMA_DECLARED = "schema-declared"
    AUTHENTICATED_READ_VERIFIED = "authenticated-read-verified"
    AUTHENTICATED_WRITE_REVIEWED = "authenticated-write-reviewed"
    UNSUPPORTED = "unsupported"


class OperationKind(StrEnum):
    """Reviewed protocol categories used without interpreting provider prose."""

    DISCOVER = "discover"
    READ = "read"
    REVIEW = "review"
    PLACE = "place"
    CANCEL = "cancel"


class CapabilityAssetClass(StrEnum):
    """Metadata-only extension; never accepted by the legacy order validator."""

    OPTIONS = "options"


class VerificationDimension(StrEnum):
    PUBLIC = "public"
    SESSION = "session"
    ACCOUNT = "account"
    RUNTIME = "runtime"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    DENIED = "denied"
    UNKNOWN = "unknown"


def _safe_error_text(value: object, fallback: str) -> str:
    if type(value) is str and not text_contains_sensitive_material(value):
        return value
    return fallback


_AUTHENTICATED_LEVELS = frozenset(
    {
        EvidenceLevel.AUTHENTICATED_READ_VERIFIED,
        EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED,
    }
)
_DIGEST_LEVELS = frozenset(
    {
        EvidenceLevel.SCHEMA_DECLARED,
        EvidenceLevel.AUTHENTICATED_READ_VERIFIED,
        EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED,
    }
)


@dataclass(frozen=True, slots=True)
class CapabilityEvidence:
    """One sanitized observation supporting exactly one evidence category."""

    level: EvidenceLevel
    source_uri: str
    observed_at: datetime
    schema_sha256: str | None
    authenticated: bool
    contains_account_data: bool
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.level) is not EvidenceLevel:
            raise InvalidCapabilityEvidence("level must be an EvidenceLevel")
        _require_safe_source_uri(self.source_uri)
        canonical_timestamp: datetime | None = None
        if type(self.observed_at) is datetime:
            with suppress(Exception):
                canonical_timestamp = require_utc(self.observed_at)
        if canonical_timestamp is None:
            raise InvalidCapabilityEvidence("observed_at must be aware UTC") from None
        object.__setattr__(self, "observed_at", canonical_timestamp)
        if self.schema_sha256 is not None and (
            type(self.schema_sha256) is not str or _SHA256_HEX.fullmatch(self.schema_sha256) is None
        ):
            raise InvalidCapabilityEvidence("schema_sha256 must be a lowercase SHA-256 hex digest")
        if self.level in _DIGEST_LEVELS and self.schema_sha256 is None:
            raise InvalidCapabilityEvidence("schema_sha256 is required for this evidence level")
        if type(self.authenticated) is not bool:
            raise InvalidCapabilityEvidence("authenticated must be a boolean")
        if self.level in _AUTHENTICATED_LEVELS:
            if not self.authenticated:
                raise InvalidCapabilityEvidence(
                    "authenticated evidence requires authenticated=True"
                )
        elif self.authenticated:
            raise InvalidCapabilityEvidence("this evidence category must remain unauthenticated")
        if type(self.contains_account_data) is not bool:
            raise InvalidCapabilityEvidence("contains_account_data must be a boolean")
        if self.contains_account_data:
            raise InvalidCapabilityEvidence("committed evidence cannot contain account data")
        _require_string_tuple(self.notes, "notes", InvalidCapabilityEvidence)


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    """Evidence and lock state for one exact provider operation."""

    provider: str
    operation: str
    asset_class: AssetClass | CapabilityAssetClass
    operation_kind: OperationKind
    evidence: tuple[CapabilityEvidence, ...]
    limitations: tuple[str, ...]
    locked_reason: str | None

    def __post_init__(self) -> None:
        _require_nonempty_string(self.provider, "provider", InvalidCapabilityRecord)
        if not _is_operation_identifier(self.operation):
            raise InvalidCapabilityRecord("operation must be a bounded identifier")
        if type(self.asset_class) not in {AssetClass, CapabilityAssetClass}:
            raise InvalidCapabilityRecord("asset_class must be an AssetClass")
        if type(self.operation_kind) is not OperationKind:
            raise InvalidCapabilityRecord("operation_kind must be an OperationKind")
        _require_exact_tuple(self.evidence, "evidence", InvalidCapabilityRecord)
        if not self.evidence:
            raise InvalidCapabilityRecord("evidence must contain at least one observation")
        if any(type(item) is not CapabilityEvidence for item in self.evidence):
            raise InvalidCapabilityRecord("evidence must contain CapabilityEvidence records")
        validated_evidence: list[CapabilityEvidence] = []
        for item in self.evidence:
            rebuilt = _rebuild_evidence(item)
            if rebuilt is None:
                raise InvalidCapabilityRecord(
                    "evidence contains an invalid CapabilityEvidence value"
                ) from None
            validated_evidence.append(rebuilt)
        object.__setattr__(self, "evidence", tuple(validated_evidence))
        _require_string_tuple(self.limitations, "limitations", InvalidCapabilityRecord)
        if self.locked_reason is not None:
            _require_nonempty_string(
                self.locked_reason,
                "locked_reason",
                InvalidCapabilityRecord,
            )
        levels = frozenset(item.level for item in self.evidence)
        if EvidenceLevel.UNSUPPORTED in levels and len(levels) != 1:
            raise InvalidCapabilityRecord("evidence cannot mix unsupported and positive categories")
        if levels == {EvidenceLevel.UNSUPPORTED} and self.locked_reason is None:
            raise InvalidCapabilityRecord("unsupported records require a nonempty locked_reason")

    def satisfies(self, required: EvidenceLevel) -> bool:
        """Return whether this unlocked record contains the exact category requested."""
        if type(self) is not CapabilityRecord or type(required) is not EvidenceLevel:
            return False
        validated = _rebuild_record(self)
        if validated is None:
            return False
        levels = frozenset(item.level for item in validated.evidence)
        if required is EvidenceLevel.UNSUPPORTED:
            return levels == {EvidenceLevel.UNSUPPORTED}
        return (
            validated.asset_class is not CapabilityAssetClass.OPTIONS
            and validated.locked_reason is None
            and required in levels
        )


@dataclass(frozen=True, slots=True)
class CapabilityVerification:
    """One expiring, operation-scoped witness; refs are opaque local commitments.

    Evidence history is retained, including denials. No witness grants trading authority.
    Synthetic witnesses are always ineligible, regardless of their stated status.
    """

    provider: str
    operation: str
    dimension: VerificationDimension
    status: VerificationStatus
    evidence: CapabilityEvidence
    valid_until: datetime
    session_ref: str | None
    account_ref: str | None
    runtime_ref: str | None
    synthetic: bool

    def __post_init__(self) -> None:
        valid = False
        try:
            _require_nonempty_string(self.provider, "provider", InvalidCapabilityVerification)
            if not _is_operation_identifier(self.operation):
                raise ValueError
            if (
                type(self.dimension) is not VerificationDimension
                or type(self.status) is not VerificationStatus
            ):
                raise ValueError
            evidence = _rebuild_evidence(self.evidence)
            if (
                evidence is None
                or type(self.valid_until) is not datetime
                or type(self.synthetic) is not bool
            ):
                raise ValueError
            expiry = require_utc(self.valid_until)
            if expiry <= evidence.observed_at:
                raise ValueError
            required_refs = {
                VerificationDimension.PUBLIC: (False, False, False),
                VerificationDimension.SESSION: (True, False, False),
                VerificationDimension.ACCOUNT: (False, True, False),
                VerificationDimension.RUNTIME: (False, True, True),
            }[self.dimension]
            for value, required in zip(
                (self.session_ref, self.account_ref, self.runtime_ref), required_refs, strict=True
            ):
                if required:
                    if type(value) is not str or _SHA256_HEX.fullmatch(value) is None:
                        raise ValueError
                elif value is not None:
                    raise ValueError
            allowed_levels = {
                VerificationDimension.PUBLIC: {EvidenceLevel.DOCUMENTED},
                VerificationDimension.SESSION: {EvidenceLevel.SCHEMA_DECLARED},
                VerificationDimension.ACCOUNT: {EvidenceLevel.AUTHENTICATED_READ_VERIFIED},
                VerificationDimension.RUNTIME: _AUTHENTICATED_LEVELS,
            }[self.dimension]
            if evidence.level not in allowed_levels and (
                self.status is VerificationStatus.VERIFIED
                or evidence.level is not EvidenceLevel.UNSUPPORTED
            ):
                raise ValueError
            if (
                self.dimension is not VerificationDimension.PUBLIC
                and evidence.schema_sha256 is None
            ):
                raise ValueError
            object.__setattr__(self, "evidence", evidence)
            object.__setattr__(self, "valid_until", expiry)
            valid = True
        except MemoryError:
            raise
        except Exception:
            valid = False
        if not valid:
            raise InvalidCapabilityVerification("capability verification is invalid") from None


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    """Deterministically ordered unique capability records."""

    records: tuple[CapabilityRecord, ...]
    verifications: tuple[CapabilityVerification, ...] = ()

    def __post_init__(self) -> None:
        _require_exact_tuple(self.records, "records", InvalidCapabilityManifest)
        if any(type(item) is not CapabilityRecord for item in self.records):
            raise InvalidCapabilityManifest("records must contain CapabilityRecord values")
        validated_records: list[CapabilityRecord] = []
        for item in self.records:
            rebuilt = _rebuild_record(item)
            if rebuilt is None:
                raise InvalidCapabilityManifest(
                    "records contain an invalid CapabilityRecord value"
                ) from None
            validated_records.append(rebuilt)
        records = tuple(validated_records)
        keys = tuple((item.provider, item.operation) for item in records)
        if len(keys) != len(set(keys)):
            raise InvalidCapabilityManifest(
                "manifest contains a duplicate provider and operation key"
            )
        for item in records:
            if (
                item.asset_class is AssetClass.PREDICTION
                and item.operation_kind is OperationKind.PLACE
                and any(
                    evidence.level is not EvidenceLevel.UNSUPPORTED for evidence in item.evidence
                )
            ):
                raise InvalidCapabilityManifest(
                    "positive prediction placement evidence is prohibited"
                )
        object.__setattr__(
            self,
            "records",
            tuple(sorted(records, key=lambda item: (item.provider, item.operation))),
        )
        _require_exact_tuple(self.verifications, "verifications", InvalidCapabilityManifest)
        witnesses: list[CapabilityVerification] = []
        witness_keys: set[tuple[object, ...]] = set()
        by_key = {(item.provider, item.operation): item for item in records}
        for raw in self.verifications:
            witness = _rebuild_verification(raw)
            if witness is None:
                raise InvalidCapabilityManifest("capability verification is invalid")
            record = by_key.get((witness.provider, witness.operation))
            if record is None:
                raise InvalidCapabilityManifest("verification has no operation record")
            key = (
                witness.provider,
                witness.operation,
                witness.dimension,
                witness.session_ref,
                witness.account_ref,
                witness.runtime_ref,
                witness.evidence.observed_at,
            )
            if key in witness_keys:
                raise InvalidCapabilityManifest("verification history is ambiguous")
            if (
                witness.dimension is VerificationDimension.RUNTIME
                and witness.status is VerificationStatus.VERIFIED
                and record.operation_kind
                in {OperationKind.REVIEW, OperationKind.PLACE, OperationKind.CANCEL}
                and witness.evidence.level is not EvidenceLevel.AUTHENTICATED_WRITE_REVIEWED
            ):
                raise InvalidCapabilityManifest(
                    "write runtime requires operation-specific write evidence"
                )
            witness_keys.add(key)
            witnesses.append(witness)
        object.__setattr__(
            self,
            "verifications",
            tuple(
                sorted(
                    witnesses,
                    key=lambda item: (
                        item.provider,
                        item.operation,
                        item.dimension.value,
                        item.session_ref or "",
                        item.account_ref or "",
                        item.runtime_ref or "",
                        item.evidence.observed_at,
                    ),
                )
            ),
        )

    def find(self, *, provider: str, operation: str) -> CapabilityRecord:
        """Find an exact manifest key without fuzzy or prose-based inference."""
        if not _is_nonempty_string(provider) or not _is_operation_identifier(operation):
            raise CapabilityNotFoundError(provider, operation)
        validated = _rebuild_manifest(self)
        if validated is None:
            raise InvalidCapabilityManifest("capability manifest is invalid") from None
        for record in validated.records:
            if record.provider == provider and record.operation == operation:
                return record
        raise CapabilityNotFoundError(provider, operation)


def validated_manifest_copy(value: object) -> CapabilityManifest:
    """Return a fully reconstructed exact manifest or fail without nested context."""
    rebuilt = _rebuild_manifest(value)
    if rebuilt is None:
        raise InvalidCapabilityManifest("capability manifest is invalid") from None
    return rebuilt


def _rebuild_evidence(value: object) -> CapabilityEvidence | None:
    if type(value) is not CapabilityEvidence:
        return None
    rebuilt: CapabilityEvidence | None = None
    try:
        rebuilt = CapabilityEvidence(
            level=value.level,
            source_uri=value.source_uri,
            observed_at=value.observed_at,
            schema_sha256=value.schema_sha256,
            authenticated=value.authenticated,
            contains_account_data=value.contains_account_data,
            notes=value.notes,
        )
    except MemoryError:
        raise
    except Exception:
        rebuilt = None
    return rebuilt


def _rebuild_record(value: object) -> CapabilityRecord | None:
    if type(value) is not CapabilityRecord:
        return None
    rebuilt: CapabilityRecord | None = None
    try:
        rebuilt = CapabilityRecord(
            provider=value.provider,
            operation=value.operation,
            asset_class=value.asset_class,
            operation_kind=value.operation_kind,
            evidence=value.evidence,
            limitations=value.limitations,
            locked_reason=value.locked_reason,
        )
    except MemoryError:
        raise
    except Exception:
        rebuilt = None
    return rebuilt


def _rebuild_manifest(value: object) -> CapabilityManifest | None:
    if type(value) is not CapabilityManifest:
        return None
    rebuilt: CapabilityManifest | None = None
    try:
        if type(value.records) is not tuple:
            raise TypeError
        rebuilt = CapabilityManifest(records=value.records, verifications=value.verifications)
    except MemoryError:
        raise
    except Exception:
        rebuilt = None
    return rebuilt


def _rebuild_verification(value: object) -> CapabilityVerification | None:
    if type(value) is not CapabilityVerification:
        return None
    rebuilt: CapabilityVerification | None = None
    try:
        rebuilt = CapabilityVerification(
            provider=value.provider,
            operation=value.operation,
            dimension=value.dimension,
            status=value.status,
            evidence=value.evidence,
            valid_until=value.valid_until,
            session_ref=value.session_ref,
            account_ref=value.account_ref,
            runtime_ref=value.runtime_ref,
            synthetic=value.synthetic,
        )
    except MemoryError:
        raise
    except Exception:
        rebuilt = None
    return rebuilt


def _require_safe_source_uri(value: str) -> None:
    _require_nonempty_string(value, "source_uri", InvalidCapabilityEvidence)
    if (
        value != value.strip()
        or any(character.isspace() for character in value)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or "%" in value
        or "?" in value
        or "#" in value
    ):
        raise InvalidCapabilityEvidence("source_uri must be a sanitized URI")
    parsed = None
    port = None
    hostname = None
    username = None
    password = None
    try:
        parsed = urlsplit(value)
        port = parsed.port
        hostname = parsed.hostname
        username = parsed.username
        password = parsed.password
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        raise InvalidCapabilityEvidence("source_uri must be a sanitized URI")
    if parsed.scheme not in _ALLOWED_SOURCE_URI_SCHEMES:
        raise InvalidCapabilityEvidence("source_uri must use an approved evidence scheme")
    if not parsed.netloc or hostname is None:
        raise InvalidCapabilityEvidence("source_uri must be an absolute URI")
    if not _hostname_is_valid(hostname):
        raise InvalidCapabilityEvidence("source_uri must use a sanitized hostname")
    if username is not None or password is not None:
        raise InvalidCapabilityEvidence("source_uri cannot contain user information")
    if port is not None or parsed.netloc != hostname:
        raise InvalidCapabilityEvidence("source_uri must use a canonical authority")
    if parsed.scheme == "https" and hostname not in _ALLOWED_HTTPS_HOSTS:
        raise InvalidCapabilityEvidence("source_uri must use an official HTTPS authority")
    if parsed.scheme == "mcp" and hostname != _ALLOWED_MCP_HOST:
        raise InvalidCapabilityEvidence("source_uri must use the approved MCP authority")
    if parsed.query or parsed.fragment:
        raise InvalidCapabilityEvidence("source_uri cannot contain a query or fragment")
    if not _path_is_valid(parsed.path):
        raise InvalidCapabilityEvidence("source_uri must use a sanitized canonical path")


def _hostname_is_valid(value: str) -> bool:
    if len(value) > 253:
        return False
    labels = value.split(".")
    return all(_HOST_LABEL.fullmatch(label) is not None for label in labels)


def _path_is_valid(value: str) -> bool:
    if value == "":
        return True
    if not value.startswith("/") or len(value) > 2048:
        return False
    segments = value.split("/")[1:]
    if segments and segments[-1] == "":
        segments.pop()
    return all(_PATH_SEGMENT.fullmatch(segment) is not None for segment in segments)


def _is_nonempty_string(value: object) -> bool:
    return (
        type(value) is str and bool(value.strip()) and not text_contains_sensitive_material(value)
    )


def _is_operation_identifier(value: object) -> bool:
    return _is_nonempty_string(value) or (
        type(value) is str and _DECLARED_OPERATION.fullmatch(value) is not None
    )


def _require_nonempty_string(
    value: object,
    field_name: str,
    error_type: type[CapabilityValidationError],
) -> None:
    if not _is_nonempty_string(value):
        raise error_type(f"{field_name} must be a nonempty string")


def _require_exact_tuple(
    value: object,
    field_name: str,
    error_type: type[CapabilityValidationError],
) -> tuple[object, ...]:
    if type(value) is not tuple:
        raise error_type(f"{field_name} must be an exact immutable tuple")
    return cast(tuple[object, ...], value)


def _require_string_tuple(
    value: object,
    field_name: str,
    error_type: type[CapabilityValidationError],
) -> None:
    items = _require_exact_tuple(value, field_name, error_type)
    if any(not _is_nonempty_string(item) for item in items):
        raise error_type(f"{field_name} must contain only nonempty strings")
