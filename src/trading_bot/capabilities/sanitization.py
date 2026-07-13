"""Dependency-neutral sanitization shared by capability evidence and schema capture."""

from __future__ import annotations

import re
import unicodedata
from itertools import pairwise
from urllib.parse import parse_qsl, unquote, urlsplit

_JWT_LIKE = re.compile(r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
_API_TOKEN_LIKE = re.compile(
    r"(?:sk|pk|ghp|gho|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{8,}",
    re.IGNORECASE,
)
_ACCOUNT_ID_LIKE = re.compile(r"RHC[A-Z0-9]{8,}", re.IGNORECASE)
_UUID_LIKE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_BARE_LONG_NUMERIC_ID = re.compile(r"(?<![0-9])[0-9]{8,}(?![0-9])")
_HIGH_ENTROPY_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])")
_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
_PEM_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE)
_BEARER_OR_HEADER_ASSIGNMENT = re.compile(
    r"(?:authorization|proxy-authorization|[a-z0-9-]*header|cookie|set-cookie)\s*[:=]"
    r"\s*(?:bearer\s+)?\S+",
    re.IGNORECASE,
)
_BEARER_MATERIAL = re.compile(r"\bbearer\s+[A-Za-z0-9._~-]+", re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    r"(?:x-api-key|api[_-]?key|access[_-]?token|refresh[_-]?token|signature|signatures|sig|"
    r"account[_-]?(?:id|number|uuid))\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_ASSIGNMENT_OPERATOR = re.compile(r"[:=]")
_CAMEL_NAME_TOKEN = re.compile(r"[A-Z]+(?=[A-Z][a-z]|[0-9]|\Z)|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")

_SENSITIVE_SINGLE_NAME_TOKENS = frozenset(
    {
        "account",
        "accounts",
        "acct",
        "auth",
        "authorization",
        "bearer",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "header",
        "headers",
        "oauth",
        "passphrase",
        "password",
        "passwords",
        "secret",
        "secrets",
        "sig",
        "signature",
        "signatures",
        "token",
        "tokens",
    }
)
_SENSITIVE_KEY_PREFIXES = frozenset(
    {"api", "access", "client", "consumer", "private", "secret", "signing"}
)
_SENSITIVE_SESSION_SUFFIXES = frozenset({"id", "key", "token", "cookie"})
_BENIGN_COMPOUND_NAMES = frozenset(
    {
        "accountingreference",
        "authorizationstatus",
        "oauthscope",
        "postcode",
        "zipcode",
        "codepoint",
        "referenceprice",
        "identifierformat",
    }
)

_MAX_INSPECTION_TEXT_LENGTH = 65_536
_MAX_PERCENT_DECODE_ROUNDS = 3
_MAX_CANDIDATE_NAME_LENGTH = 256
_MAX_ASSIGNMENT_NAME_LENGTH = 128
_MAX_QUERY_FIELDS = 128

_COMPACT_SENSITIVE_BASE_GRAMMAR = (
    r"(?:"
    r"x?api(?:key|keys|secret|secrets)|"
    r"(?:private|signing|client|consumer|secret)(?:key|keys)|"
    r"access(?:key|keys)(?:id|ids)?|"
    r"secretaccess(?:key|keys)|"
    r"(?:access|client|consumer)(?:secret|secrets)|"
    r"oauth(?:client|consumer)(?:secret|secrets)|"
    r"(?:access|refresh|auth|authorization|oauth|bearer)(?:token|tokens)|"
    r"session(?:id|ids|key|keys|token|tokens|cookie|cookies)|"
    r"account(?:id|ids|identifier|identifiers|number|numbers|uuid|uuids|reference|references|no|nos)|"
    r"acct(?:id|ids|identifier|identifiers|number|numbers|uuid|uuids|reference|references|no|nos)|"
    r"(?:authorization|oauth|auth|verification|mfa|recovery|otp)(?:code|codes)|"
    r"(?:auth|authorization)(?:header|headers)"
    r")"
)
_COMPACT_STRONG_NAME_GRAMMAR = re.compile(
    rf"(?:[a-z][a-z0-9]{{0,{_MAX_CANDIDATE_NAME_LENGTH - 1}}})?"
    rf"{_COMPACT_SENSITIVE_BASE_GRAMMAR}\Z",
    re.IGNORECASE,
)
_COMPACT_CREDENTIAL_VALUE_SUFFIXES = (
    "material",
    "values",
    "value",
    "bytes",
    "data",
    "pem",
)


def has_unsafe_freeform_characters(value: str) -> bool:
    """Reject invisible formatting and unsafe controls while allowing ordinary prose."""
    return type(value) is not str or any(
        (unicodedata.category(character) == "Cc" and character not in {"\t", "\n", "\r"})
        or unicodedata.category(character) == "Cf"
        or unicodedata.bidirectional(character)
        in {"LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI"}
        for character in value
    )


def text_contains_sensitive_material(value: str) -> bool:
    """Return whether bounded public evidence text is unsafe to store or render."""
    if (
        type(value) is not str
        or len(value) > _MAX_INSPECTION_TEXT_LENGTH
        or has_unsafe_freeform_characters(value)
    ):
        return True
    try:
        candidates = decoded_candidates(value)
    except (UnicodeError, ValueError):
        return True
    for candidate in candidates:
        if (
            _PEM_PRIVATE_KEY.search(candidate)
            or _BEARER_MATERIAL.search(candidate)
            or _JWT_LIKE.search(candidate)
            or _API_TOKEN_LIKE.search(candidate)
            or _ACCOUNT_ID_LIKE.search(candidate)
            or _UUID_LIKE.search(candidate)
            or _BARE_LONG_NUMERIC_ID.search(candidate)
            or _HIGH_ENTROPY_TOKEN.search(candidate)
            or _BEARER_OR_HEADER_ASSIGNMENT.search(candidate)
            or _SECRET_ASSIGNMENT.search(candidate)
            or _has_sensitive_assignment(candidate)
        ):
            return True
        try:
            parsed = urlsplit(candidate)
        except ValueError:
            return True
        if parsed.username is not None or parsed.password is not None:
            return True
        for component in (parsed.query, parsed.fragment):
            if not component:
                continue
            try:
                pairs = parse_qsl(
                    component,
                    keep_blank_values=True,
                    max_num_fields=_MAX_QUERY_FIELDS,
                )
            except ValueError:
                return True
            if any(name_is_sensitive(name) and bool(item) for name, item in pairs):
                return True
        if path_has_sensitive_value_pair(parsed.path) or path_has_sensitive_value_pair(
            parsed.fragment
        ):
            return True
    return False


def decoded_candidates(value: str) -> tuple[str, ...]:
    """Return each bounded percent-decoding stage or reject malformed/unsafe text."""
    if type(value) is not str or len(value) > _MAX_INSPECTION_TEXT_LENGTH:
        raise ValueError
    if has_unsafe_freeform_characters(value):
        raise ValueError
    candidates = [value]
    decoded = value
    for _ in range(_MAX_PERCENT_DECODE_ROUNDS):
        next_value = unquote(decoded, errors="strict")
        if next_value == decoded:
            break
        if has_unsafe_freeform_characters(next_value):
            raise ValueError
        candidates.append(next_value)
        decoded = next_value
    if _PERCENT_ESCAPE.search(decoded) or "%" in decoded:
        raise ValueError
    return tuple(candidates)


def name_is_sensitive(value: str) -> bool:
    """Classify one bounded candidate name using the shared reviewed taxonomy."""
    if type(value) is not str or len(value) > _MAX_CANDIDATE_NAME_LENGTH:
        return True
    try:
        decoded = decoded_candidates(value)[-1]
    except (UnicodeError, ValueError):
        return True
    if candidate_name_has_unsafe_characters(value):
        return True
    components = tuple(component for component in re.split(r"[^A-Za-z0-9]+", decoded) if component)
    tokens = tuple(
        token.casefold()
        for component in components
        for token in _CAMEL_NAME_TOKEN.findall(component)
    )
    normalized = "".join(tokens)
    if normalized in _BENIGN_COMPOUND_NAMES:
        return False
    if _compact_stem_is_sensitive(normalized):
        return True
    if any(_compact_component_is_sensitive(component) for component in components):
        return True
    if len(tokens) == 1 and tokens[0] in _SENSITIVE_SINGLE_NAME_TOKENS:
        return True
    if any(
        token
        in {
            "bearer",
            "cookie",
            "cookies",
            "credential",
            "credentials",
            "header",
            "headers",
            "passphrase",
            "password",
            "passwords",
            "secret",
            "secrets",
            "sig",
            "signature",
            "signatures",
            "token",
            "tokens",
        }
        for token in tokens
    ):
        return True
    return any(
        (left in _SENSITIVE_KEY_PREFIXES and right in {"key", "keys"})
        or (left == "session" and right.removesuffix("s") in _SENSITIVE_SESSION_SUFFIXES)
        for left, right in pairwise(tokens)
    )


def candidate_name_has_unsafe_characters(value: str) -> bool:
    """Reject unbounded, non-ASCII, malformed, control, or formatted names."""
    if type(value) is not str or len(value) > _MAX_CANDIDATE_NAME_LENGTH:
        return True
    try:
        decoded = decoded_candidates(value)[-1]
    except (UnicodeError, ValueError):
        return True
    return not decoded.isascii() or any(
        ord(character) < 32 or ord(character) == 127 for character in decoded
    )


def path_has_sensitive_value_pair(value: str) -> bool:
    """Detect a sensitive path name immediately followed by a nonempty value."""
    segments = tuple(
        part
        for segment in value.split("/")
        for part in segment.replace("~1", "/").replace("~0", "~").split("/")
        if part
    )
    return segments_have_sensitive_value_pair(segments)


def segments_have_sensitive_value_pair(segments: tuple[str, ...]) -> bool:
    """Detect sensitive/value adjacency across already-decoded path segments."""
    flattened = tuple(part for segment in segments for part in segment.split("/") if part)
    return any(name_is_sensitive(left) and bool(right) for left, right in pairwise(flattened))


def _has_sensitive_assignment(value: str) -> bool:
    for match in _ASSIGNMENT_OPERATOR.finditer(value):
        name, overlong = _assignment_name_before(value, match.start())
        has_value = _assignment_has_value_after(value, match.end())
        if overlong and has_value:
            return True
        if name is None or not has_value:
            continue
        if name_is_sensitive(name):
            return True
    return False


def _assignment_name_before(value: str, operator_index: int) -> tuple[str | None, bool]:
    index = operator_index - 1
    while index >= 0 and value[index].isspace():
        index -= 1
    while index >= 0 and value[index] in "'\"`]}>)":
        index -= 1
    if index < 0 or not _is_assignment_name_character(value[index]):
        return None, False
    end = index + 1
    inspected = 0
    while index >= 0 and _is_assignment_name_character(value[index]):
        inspected += 1
        if inspected > _MAX_ASSIGNMENT_NAME_LENGTH:
            return None, True
        index -= 1
    return value[index + 1 : end], False


def _assignment_has_value_after(value: str, operator_end: int) -> bool:
    index = operator_end
    while index < len(value) and value[index].isspace():
        index += 1
    return index < len(value)


def _is_assignment_name_character(value: str) -> bool:
    return value.isalnum() or value in "_-.~%[]"


def _compact_component_is_sensitive(value: str) -> bool:
    normalized = value.casefold()
    stems = [normalized]
    stems.extend(
        normalized[: -len(suffix)]
        for suffix in _COMPACT_CREDENTIAL_VALUE_SUFFIXES
        if normalized.endswith(suffix) and len(normalized) > len(suffix)
    )
    return any(_compact_stem_is_sensitive(stem) for stem in stems)


def _compact_stem_is_sensitive(value: str) -> bool:
    if value in _BENIGN_COMPOUND_NAMES:
        return False
    if _COMPACT_STRONG_NAME_GRAMMAR.fullmatch(value) is not None:
        return True
    if value in _SENSITIVE_SINGLE_NAME_TOKENS:
        return True
    return any(
        value.endswith(lexeme) and _is_bounded_compact_namespace(value[: -len(lexeme)])
        for lexeme in _SENSITIVE_SINGLE_NAME_TOKENS
    )


def _is_bounded_compact_namespace(value: str) -> bool:
    return 0 < len(value) <= _MAX_CANDIDATE_NAME_LENGTH and value[0].isalpha() and value.isalnum()


__all__ = [
    "candidate_name_has_unsafe_characters",
    "decoded_candidates",
    "has_unsafe_freeform_characters",
    "name_is_sensitive",
    "path_has_sensitive_value_pair",
    "segments_have_sensitive_value_pair",
    "text_contains_sensitive_material",
]
