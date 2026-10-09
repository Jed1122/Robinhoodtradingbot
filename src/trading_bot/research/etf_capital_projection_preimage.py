"""Private original projection framing, not a general or public serializer."""

from collections.abc import Iterable, Iterator
from dataclasses import fields
from datetime import UTC
from hashlib import sha256

from trading_bot.market_data.etf_capital_features import CapitalFeatureProjection
from trading_bot.market_data.recording import canonical_json

_FIELDS = (
    "archive_hash",
    "action_hash",
    "calendar_hash",
    "as_of_session",
    "raw_bars",
    "feature_bars",
    "distributions",
    "limitations",
    "source_qualified",
    "evidence_promotable",
    "execution_enabled",
)


def _array_preimage(values: Iterable[bytes]) -> Iterator[bytes]:
    yield b"["
    first = True
    for value in values:
        if not first:
            yield b","
        first = False
        yield value
    yield b"]"


def _capital_projection_preimage(
    projection: CapitalFeatureProjection, *, raw_json: tuple[bytes, ...]
) -> Iterator[bytes]:
    """Called only with matching private owned raw prefixes after full validation.

    Cached leaves are complete original canonical Bar bytes, never their hashes.
    Public whole-dataclass serialization retains all existing deepcopy behavior.
    """
    if (
        type(projection) is not CapitalFeatureProjection
        or tuple(field.name for field in fields(CapitalFeatureProjection)) != _FIELDS
        or type(raw_json) is not tuple
        or len(raw_json) != len(projection.raw_bars)
        or any(type(value) is not bytes for value in raw_json)
    ):
        raise ValueError("capital_projection_preimage_invalid")
    projection.__post_init__()
    if any(
        bar.starts_at.tzinfo is not UTC or bar.ends_at.tzinfo is not UTC
        for bar in (*projection.raw_bars, *projection.feature_bars)
    ):
        raise ValueError("capital_projection_preimage_invalid")

    yield b'["capital-split-feature-projection-v2",{'
    # Fixed canonical sorted framing for this one closed dataclass schema.
    # Existing canonical_json owns every scalar and full dataclass leaf encoding.
    initial = (
        ("action_hash", projection.action_hash),
        ("archive_hash", projection.archive_hash),
        ("as_of_session", projection.as_of_session),
        ("calendar_hash", projection.calendar_hash),
        ("distributions", projection.distributions),
        ("evidence_promotable", projection.evidence_promotable),
        ("execution_enabled", projection.execution_enabled),
    )
    for index, (name, value) in enumerate(initial):
        if index:
            yield b","
        yield canonical_json(name).encode() + b":" + canonical_json(value).encode()
    yield b',"feature_bars":'
    yield from _array_preimage(canonical_json(bar).encode() for bar in projection.feature_bars)
    yield b',"limitations":' + canonical_json(projection.limitations).encode()
    yield b',"raw_bars":'
    yield from _array_preimage(raw_json)
    yield b',"source_qualified":' + canonical_json(projection.source_qualified).encode()
    yield b"}]"


def _capital_projection_digest(
    projection: CapitalFeatureProjection, *, raw_json: tuple[bytes, ...]
) -> str:
    digest = sha256()
    for chunk in _capital_projection_preimage(projection, raw_json=raw_json):
        digest.update(chunk)
    return digest.hexdigest()
