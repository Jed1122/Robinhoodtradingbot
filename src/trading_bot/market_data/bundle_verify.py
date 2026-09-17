"""Replay and consistency checks for synthetic bundles, never source authentication."""

from dataclasses import dataclass
from hashlib import sha256
from itertools import pairwise
from typing import cast

from trading_bot.domain import Bar, CorporateAction
from trading_bot.market_data.bundle_codec import _array, _json, decode_envelope
from trading_bot.market_data.bundle_models import (
    BundleEnvelope,
    BundleLimits,
    BundlePackage,
    CoverageDeclaration,
    MembershipBaseline,
    NormalizedRecord,
    _check,
)
from trading_bot.market_data.bundle_normalize import (
    _bundle_hash,
    _descriptor_hash,
    _limitations,
    _manifest,
    _normalize,
    _raw_rows,
)
from trading_bot.market_data.universe import UniverseMembership


@dataclass(frozen=True, slots=True, init=False)
class VerifiedBundle:
    """Factory output containing immutable decoded records, not a security token."""

    envelope: BundleEnvelope
    limitation_codes: tuple[str, ...]

    def __init__(self) -> None:
        raise TypeError("use_verify_bundle")


def _conflicts(records: tuple[NormalizedRecord, ...]) -> None:
    seen: dict[tuple[object, ...], object] = {}
    for row in records:
        value = row.value
        key: tuple[object, ...]
        if isinstance(value, Bar):
            key = (row.kind, value.instrument_id, value.interval, value.starts_at, value.ends_at)
        elif isinstance(value, CorporateAction):
            key = (row.kind, value.instrument_id, value.action_type, value.effective_date)
        elif isinstance(value, MembershipBaseline):
            key = (row.kind, value.instrument_id, value.coverage_start)
        elif isinstance(value, UniverseMembership):
            key = (row.kind, value.instrument_id, value.effective_at, value.announced_at)
        else:
            continue
        if key in seen:
            _check(
                isinstance(value, UniverseMembership) and value == seen[key],
                "bundle_record_conflict",
            )
        seen[key] = value


def _coverage(records: tuple[NormalizedRecord, ...]) -> None:
    groups: dict[tuple[object, ...], list[CoverageDeclaration]] = {}
    bars = tuple(row.value for row in records if isinstance(row.value, Bar))
    membership_starts: set[tuple[object, ...]] = set()
    for row in records:
        value = row.value
        if not isinstance(value, CoverageDeclaration):
            continue
        key = (value.instrument_id, value.record_kind, value.interval)
        groups.setdefault(key, []).append(value)
        if value.record_kind == "membership":
            membership_starts.add((value.instrument_id, value.starts_at))
        if value.record_kind != "bar" or value.state != "complete":
            continue
        intersecting = tuple(
            bar
            for bar in bars
            if bar.instrument_id == value.instrument_id
            and bar.interval == value.interval
            and bar.starts_at < value.ends_at
            and bar.ends_at > value.starts_at
        )
        # No availability filter: a complete declaration describes retained source rows.
        actual = tuple(sorted((bar.starts_at, bar.ends_at) for bar in intersecting))
        expected = tuple((slot.starts_at, slot.ends_at) for slot in value.expected_slots)
        _check(actual == expected, "bundle_coverage_invalid")
    for segments in groups.values():
        ordered = sorted(segments, key=lambda segment: (segment.starts_at, segment.ends_at))
        _check(
            all(left.ends_at <= right.starts_at for left, right in pairwise(ordered)),
            "bundle_coverage_invalid",
        )
    for row in records:
        if isinstance(row.value, MembershipBaseline):
            _check(
                (row.value.instrument_id, row.value.coverage_start) in membership_starts,
                "bundle_coverage_invalid",
            )


def verify_bundle(package: BundlePackage, *, limits: BundleLimits) -> VerifiedBundle:
    _check(type(limits) is BundleLimits, "bundle_limits_invalid")
    _check(type(package) is BundlePackage)
    _check(len(package.envelope_bytes) <= limits.max_envelope_bytes, "bundle_input_too_large")
    _check(
        all(len(body) <= limits.max_blob_bytes for _, body in package.blobs),
        "bundle_input_too_large",
    )
    _check(
        len(package.envelope_bytes) + sum(len(body) for _, body in package.blobs)
        <= limits.max_total_bytes,
        "bundle_input_too_large",
    )
    # Preflight bounded JSON and combined counts before constructing domain values.
    wire = _json(package.envelope_bytes, max_bytes=limits.max_envelope_bytes, limits=limits)
    _check(type(wire) is dict, "bundle_schema_invalid")
    wire = cast(dict[str, object], wire)
    _check("records" in wire and "sources" in wire, "bundle_schema_invalid")
    normalized_count = len(_array(wire["records"]))
    _check(normalized_count <= limits.max_records, "bundle_input_too_large")
    blobs = dict(package.blobs)
    for digest, body in package.blobs:
        _check(sha256(body).hexdigest() == digest, "bundle_blob_mismatch")
    referenced: set[str] = set()
    ordered_digests: list[str] = []
    for source in _array(wire["sources"]):
        _check(type(source) is dict, "bundle_schema_invalid")
        source = cast(dict[str, object], source)
        candidate = source.get("blob_sha256")
        _check(type(candidate) is str, "bundle_schema_invalid")
        digest = cast(str, candidate)
        _check(digest in blobs, "bundle_blob_mismatch")
        _check(type(source.get("byte_length")) is int, "bundle_value_invalid")
        _check(source["byte_length"] == len(blobs[digest]), "bundle_blob_mismatch")
        referenced.add(digest)
        ordered_digests.append(digest)
    _check(referenced == set(blobs), "bundle_blob_mismatch")
    raw = {digest: _raw_rows(body, limits) for digest, body in package.blobs}
    raw_count = 0
    for digest in ordered_digests:
        raw_count += len(raw[digest])
        _check(normalized_count + raw_count <= limits.max_records, "bundle_input_too_large")
    envelope = decode_envelope(package.envelope_bytes, limits=limits)
    _check(
        all(_descriptor_hash(source) == source.descriptor_hash for source in envelope.sources),
        "bundle_hash_mismatch",
    )
    _check(_bundle_hash(envelope) == envelope.bundle_hash, "bundle_hash_mismatch")
    ordered_sources = tuple(sorted(envelope.sources, key=lambda source: source.descriptor_hash))
    _check(envelope.sources == ordered_sources, "bundle_normalization_mismatch")
    records = tuple(
        row for source in ordered_sources for row in _normalize(source, raw[source.blob_sha256])
    )
    _check(records == envelope.records, "bundle_normalization_mismatch")
    limitations = _limitations(ordered_sources, records)
    _check(
        _manifest(ordered_sources, records, envelope.instruments, limitations) == envelope.manifest,
        "bundle_manifest_mismatch",
    )
    _check(envelope.limitation_codes == limitations, "bundle_fixture_mismatch")
    ids = {item.instrument_id for item in envelope.instruments}
    _check(
        all(set(source.instrument_ids) <= ids for source in ordered_sources),
        "bundle_scope_mismatch",
    )
    _conflicts(records)
    _coverage(records)
    result = object.__new__(VerifiedBundle)
    object.__setattr__(result, "envelope", envelope)
    object.__setattr__(result, "limitation_codes", limitations)
    return result
