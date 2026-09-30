"""Closed source parsers; parser availability never installs a reviewed source rule."""

import hashlib
import os
from pathlib import Path
from typing import cast

from trading_bot.config import LoadedConfig
from trading_bot.market_data.bundle_codec import _array, _digest, _json, _mapping, _string, _time
from trading_bot.market_data.databento_bar_models import native_limits
from trading_bot.market_data.databento_bar_store import _private_root, _read
from trading_bot.market_data.databento_bar_wire import bounds
from trading_bot.market_data.options_source_models import (
    ParsedSourceFacts,
    PrivateArtifactRef,
    SourceClaim,
    SourceEvidenceError,
    SourceInvalidation,
    SourceRule,
    VerificationContext,
    check,
    instant,
    window,
)
from trading_bot.market_data.recording import content_hash


def _read_source_artifact(
    artifact: PrivateArtifactRef, *, loaded: LoadedConfig, repository_root: Path
) -> bytes:
    """Read one bounded manifest/reference once, binding its exact bytes before parsing."""
    check(type(artifact) is PrivateArtifactRef)
    check(artifact.byte_count <= loaded.config.options.research_shortlist.max_input_bytes)
    parent = _private_root(artifact.path.parent, repository_root)
    try:
        body = _read(parent, artifact.path.name, artifact.byte_count)
    finally:
        os.close(parent)
    check(len(body) == artifact.byte_count and hashlib.sha256(body).hexdigest() == artifact.sha256)
    return body


def _fixture_records(
    claim: SourceClaim,
    rule: SourceRule,
    body: bytes,
    context: VerificationContext,
    loaded: LoadedConfig,
) -> ParsedSourceFacts:
    """Original synthetic protocol, preserving its causal envelope and fact hashes."""
    check(rule.source_id.startswith("synthetic.") and rule.schema == "synthetic-source-records-v1")
    decoded = _json(
        body,
        max_bytes=loaded.config.options.research_shortlist.max_input_bytes,
        limits=bounds(loaded),
    )
    check(type(decoded) is dict)
    keys = {"schema", "source_id", "role", "era_start_ns", "era_end_ns", "records"}
    if "invalidations" in cast(dict[str, object], decoded):
        keys.add("invalidations")
    wire = _mapping(decoded, keys)
    check(
        (wire["schema"], wire["source_id"], wire["role"], wire["era_start_ns"], wire["era_end_ns"])
        == (rule.schema, rule.source_id, rule.role, rule.era_start_ns, rule.era_end_ns)
    )
    items = _array(wire["records"])
    check(len(items) <= loaded.config.options.research_shortlist.max_input_records)
    visible = []
    latest_publication = 0
    for value in items:
        row = _mapping(
            value, {"published_at_ns", "effective_start_ns", "effective_end_ns", "record"}
        )
        published = row["published_at_ns"]
        start, end = cast(int, row["effective_start_ns"]), cast(int, row["effective_end_ns"])
        window(start, end)
        check(type(row["record"]) is dict)
        if published is None:
            continue
        instant(cast(int, published))
        if cast(int, published) > context.as_of_ns:
            continue
        if start <= context.start_ns and context.end_ns <= end:
            visible.append((content_hash(row), content_hash(row["record"])))
            latest_publication = max(latest_publication, cast(int, published))
    check(not visible or latest_publication == claim.published_at_ns)
    invalidations = []
    for value in _array(wire.get("invalidations", [])):
        row = _mapping(value, {"affected_hash", "discovered_at", "reason"})
        invalidation = SourceInvalidation(
            _digest(row["affected_hash"]), _time(row["discovered_at"]), _string(row["reason"])
        )
        check(invalidation.discovered_at <= claim.observed_at)
        invalidations.append(invalidation)
    check(len(invalidations) <= loaded.config.options.research_shortlist.max_input_records)
    return ParsedSourceFacts(tuple(sorted(set(visible))), tuple(invalidations))


def _parse_source_snapshot(
    claim: SourceClaim,
    rule: SourceRule,
    body: bytes,
    *,
    context: VerificationContext,
    loaded: LoadedConfig,
) -> ParsedSourceFacts:
    """Dispatch an already hash-bound snapshot without reopening its mutable path."""
    check(type(claim) is SourceClaim and type(rule) is SourceRule)
    check(type(context) is VerificationContext and type(body) is bytes)
    check(
        (
            claim.rule_id,
            claim.role,
            claim.source_id,
            claim.schema,
            claim.era_start_ns,
            claim.era_end_ns,
        )
        == (
            rule.rule_id,
            rule.role,
            rule.source_id,
            rule.schema,
            rule.era_start_ns,
            rule.era_end_ns,
        )
    )
    check(claim.effective_start_ns <= context.start_ns < context.end_ns <= claim.effective_end_ns)
    if rule.verifier_id == "synthetic-records-v1":
        return _fixture_records(claim, rule, body, context, loaded)
    # Reserved IDs cannot interpret native/reference data before role/era mappings
    # have independently reviewed evidence. No registry, dynamic import or fallback.
    raise SourceEvidenceError()


def parse_source_claim(
    claim: SourceClaim,
    rule: SourceRule,
    artifact: PrivateArtifactRef,
    *,
    context: VerificationContext,
    loaded: LoadedConfig,
    repository_root: Path,
) -> ParsedSourceFacts:
    """Parse a bounded artifact; actual DBN bytes remain behind verified manifests."""
    native_limits(loaded)
    check(type(claim) is SourceClaim and type(artifact) is PrivateArtifactRef)
    check(artifact.sha256 in claim.raw_hashes)
    body = _read_source_artifact(artifact, loaded=loaded, repository_root=repository_root)
    return _parse_source_snapshot(claim, rule, body, context=context, loaded=loaded)
