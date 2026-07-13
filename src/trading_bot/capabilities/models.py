"""Immutable, fail-closed capability evidence models."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import parse_qsl, unquote_plus, urlsplit

from trading_bot.clock import InvalidTimestamp, require_utc
from trading_bot.domain import AssetClass

_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_SOURCE_URI_SCHEMES = frozenset({"https", "mcp"})
_HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_INVALID_PERCENT_ENCODING = re.compile(r"%(?![0-9A-Fa-f]{2})")
_MAX_URI_DECODE_PASSES = 8
_SENSITIVE_QUERY_TOKENS = frozenset(
    {
        "account",
        "auth",
        "authorization",
        "bearer",
        "cookie",
        "credential",
        "credentials",
        "key",
        "oauth",
        "password",
        "secret",
        "sig",
        "signature",
        "signatures",
        "token",
        "tokens",
    }
)
_SENSITIVE_QUERY_SUFFIXES = (
    "accountid",
    "accountnumber",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "privatekey",
    "secret",
    "signature",
    "token",
)
_JWT_LIKE = re.compile(r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?:access[-_\s]?token|refresh[-_\s]?token|api[-_\s]?key|x[-_\s]?api[-_\s]?key|"
    r"authorization|bearer|cookie|password|private[-_\s]?key|client[-_\s]?secret|"
    r"secret|signature|account[-_\s]?(?:id|number))\s*[:=]",
    re.IGNORECASE,
)
_API_TOKEN_LIKE = re.compile(
    r"\b(?:sk|pk|ghp|gho|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{8,}\b",
    re.IGNORECASE,
)
_ACCOUNT_ID_LIKE = re.compile(r"\bRHC[A-Z0-9]{8,}\b", re.IGNORECASE)


class CapabilityValidationError(ValueError):
    """Base class for invalid committed capability evidence."""


class InvalidCapabilityEvidence(CapabilityValidationError):
    """Raised when evidence is unsafe, ambiguous, or structurally invalid."""


class InvalidCapabilityRecord(CapabilityValidationError):
    """Raised when a provider operation record violates capability invariants."""


class InvalidCapabilityManifest(CapabilityValidationError):
    """Raised when a capability manifest cannot be safely committed or queried."""


class CapabilityNotFoundError(LookupError):
    """Raised when an exact provider and operation key is absent."""

    def __init__(self, provider: str, operation: str) -> None:
        self.provider = provider
        self.operation = operation
        super().__init__("requested capability is not present")


class UnsupportedCapabilityError(RuntimeError):
    """Raised when an operation lacks the exact, unlocked evidence requested."""

    def __init__(
        self,
        provider: str,
        operation: str,
        minimum: "EvidenceLevel",
    ) -> None:
        self.provider = provider
        self.operation = operation
        self.minimum = minimum
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
        if not isinstance(self.level, EvidenceLevel):
            raise InvalidCapabilityEvidence("level must be an EvidenceLevel")
        _require_safe_source_uri(self.source_uri)
        try:
            require_utc(self.observed_at)
        except InvalidTimestamp as exc:
            raise InvalidCapabilityEvidence("observed_at must be aware UTC") from exc
        if self.schema_sha256 is not None and (
            not isinstance(self.schema_sha256, str)
            or _SHA256_HEX.fullmatch(self.schema_sha256) is None
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
    asset_class: AssetClass
    operation_kind: OperationKind
    evidence: tuple[CapabilityEvidence, ...]
    limitations: tuple[str, ...]
    locked_reason: str | None

    def __post_init__(self) -> None:
        _require_nonempty_string(self.provider, "provider", InvalidCapabilityRecord)
        _require_nonempty_string(self.operation, "operation", InvalidCapabilityRecord)
        if not isinstance(self.asset_class, AssetClass):
            raise InvalidCapabilityRecord("asset_class must be an AssetClass")
        if not isinstance(self.operation_kind, OperationKind):
            raise InvalidCapabilityRecord("operation_kind must be an OperationKind")
        _require_exact_tuple(self.evidence, "evidence", InvalidCapabilityRecord)
        if not self.evidence:
            raise InvalidCapabilityRecord("evidence must contain at least one observation")
        if any(not isinstance(item, CapabilityEvidence) for item in self.evidence):
            raise InvalidCapabilityRecord("evidence must contain CapabilityEvidence records")
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
        if not isinstance(required, EvidenceLevel):
            return False
        levels = frozenset(item.level for item in self.evidence)
        if required is EvidenceLevel.UNSUPPORTED:
            return levels == {EvidenceLevel.UNSUPPORTED}
        return self.locked_reason is None and required in levels


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    """Deterministically ordered unique capability records."""

    records: tuple[CapabilityRecord, ...]

    def __post_init__(self) -> None:
        _require_exact_tuple(self.records, "records", InvalidCapabilityManifest)
        if any(not isinstance(item, CapabilityRecord) for item in self.records):
            raise InvalidCapabilityManifest("records must contain CapabilityRecord values")
        keys = tuple((item.provider, item.operation) for item in self.records)
        if len(keys) != len(set(keys)):
            raise InvalidCapabilityManifest(
                "manifest contains a duplicate provider and operation key"
            )
        for item in self.records:
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
            tuple(sorted(self.records, key=lambda item: (item.provider, item.operation))),
        )

    def find(self, *, provider: str, operation: str) -> CapabilityRecord:
        """Find an exact manifest key without fuzzy or prose-based inference."""
        if not _is_nonempty_string(provider) or not _is_nonempty_string(operation):
            raise CapabilityNotFoundError(provider, operation)
        for record in self.records:
            if record.provider == provider and record.operation == operation:
                return record
        raise CapabilityNotFoundError(provider, operation)


def _require_safe_source_uri(value: str) -> None:
    _require_nonempty_string(value, "source_uri", InvalidCapabilityEvidence)
    if (
        value != value.strip()
        or any(character in value for character in "\r\n\t")
        or _INVALID_PERCENT_ENCODING.search(value) is not None
    ):
        raise InvalidCapabilityEvidence("source_uri must be a sanitized URI")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        hostname = parsed.hostname
        username = parsed.username
        password = parsed.password
        query = parse_qsl(parsed.query, keep_blank_values=True)
    except (TypeError, ValueError):
        raise InvalidCapabilityEvidence("source_uri must be a sanitized URI") from None
    if parsed.scheme not in _ALLOWED_SOURCE_URI_SCHEMES:
        raise InvalidCapabilityEvidence("source_uri must use an approved evidence scheme")
    if not parsed.netloc or hostname is None:
        raise InvalidCapabilityEvidence("source_uri must be an absolute URI")
    if not _hostname_is_valid(hostname) or _uri_text_looks_sensitive(hostname):
        raise InvalidCapabilityEvidence("source_uri must use a sanitized hostname")
    if port is not None and not 1 <= port <= 65535:
        raise InvalidCapabilityEvidence("source_uri must use a valid port")
    if username is not None or password is not None:
        raise InvalidCapabilityEvidence("source_uri cannot contain user information")
    for name, query_value in query:
        if _query_name_looks_sensitive(name) or _query_value_looks_sensitive(query_value):
            raise InvalidCapabilityEvidence(
                "source_uri cannot contain secret-bearing query parameters"
            )
    if _uri_text_looks_sensitive(parsed.path) or _uri_text_looks_sensitive(parsed.fragment):
        raise InvalidCapabilityEvidence(
            "source_uri cannot contain secret-bearing path or fragment material"
        )


def _query_value_looks_sensitive(value: str) -> bool:
    return _uri_text_looks_sensitive(value)


def _query_name_looks_sensitive(value: str) -> bool:
    decoded = value
    for _ in range(_MAX_URI_DECODE_PASSES):
        if _decoded_query_name_looks_sensitive(decoded):
            return True
        expanded = unquote_plus(decoded)
        if expanded == decoded:
            return False
        decoded = expanded
    return True


def _decoded_query_name_looks_sensitive(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
    tokens = frozenset(re.findall(r"[a-z0-9]+", value.casefold()))
    return bool(tokens & _SENSITIVE_QUERY_TOKENS) or normalized.endswith(_SENSITIVE_QUERY_SUFFIXES)


def _hostname_is_valid(value: str) -> bool:
    if len(value) > 253:
        return False
    labels = value.split(".")
    return all(_HOST_LABEL.fullmatch(label) is not None for label in labels)


def _uri_text_looks_sensitive(value: str) -> bool:
    decoded = value
    for _ in range(_MAX_URI_DECODE_PASSES):
        if _decoded_uri_text_looks_sensitive(decoded):
            return True
        expanded = unquote_plus(decoded)
        if expanded == decoded:
            return False
        decoded = expanded
    return True


def _decoded_uri_text_looks_sensitive(decoded: str) -> bool:
    normalized = decoded.casefold()
    return (
        any(ord(character) < 32 or ord(character) == 127 for character in decoded)
        or "authorization:" in normalized
        or "bearer " in normalized
        or "-----begin private key-----" in normalized
        or "-----begin encrypted private key-----" in normalized
        or _JWT_LIKE.search(decoded) is not None
        or _SENSITIVE_ASSIGNMENT.search(decoded) is not None
        or _API_TOKEN_LIKE.search(decoded) is not None
        or _ACCOUNT_ID_LIKE.search(decoded) is not None
    )


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


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
    assert isinstance(value, tuple)
    return value


def _require_string_tuple(
    value: object,
    field_name: str,
    error_type: type[CapabilityValidationError],
) -> None:
    items = _require_exact_tuple(value, field_name, error_type)
    if any(not _is_nonempty_string(item) for item in items):
        raise error_type(f"{field_name} must contain only nonempty strings")
