"""Deterministic synthetic normalization; no acquisition, trust grant, or file I/O."""

from dataclasses import asdict, replace
from datetime import timedelta
from hashlib import sha256
from typing import Literal, cast

from trading_bot.domain import Bar, CorporateAction, DataHash
from trading_bot.market_data.bundle_codec import (
    _array,
    _json,
    _kind,
    _mapping,
    _time,
    _value,
    encode_envelope,
)
from trading_bot.market_data.bundle_models import (
    BundleEnvelope,
    BundleError,
    BundleLimits,
    BundlePackage,
    CoverageDeclaration,
    InstrumentMapping,
    MembershipBaseline,
    NormalizedRecord,
    SourceCapture,
    SourceDescriptor,
    _check,
    _choice,
    _items,
)
from trading_bot.market_data.recording import ResearchDataManifest, content_hash
from trading_bot.market_data.universe import UniverseMembership

_MANDATORY_CODES = (
    "source_authenticity_unverified",
    "source_history_unverified",
    "source_license_unverified",
    "synthetic_data",
)


def _descriptor(capture: SourceCapture) -> SourceDescriptor:
    _check(capture.origin == "synthetic", "bundle_source_unsupported")
    descriptor = SourceDescriptor(
        capture.source_id,
        "synthetic-market-v1",
        "synthetic-normalizer-v1",
        capture.origin,
        capture.instrument_ids,
        capture.record_kinds,
        capture.requested_start,
        capture.requested_end,
        capture.collected_at,
        capture.claimed_published_at,
        capture.limitation_codes,
        len(capture.raw_bytes),
        sha256(capture.raw_bytes).hexdigest(),
        DataHash("0" * 64),
    )
    return replace(descriptor, descriptor_hash=_descriptor_hash(descriptor))


def _descriptor_hash(descriptor: SourceDescriptor) -> DataHash:
    body = asdict(descriptor)
    del body["descriptor_hash"]
    return content_hash({"domain": "source-descriptor-v1", "value": body})


def _raw_rows(body: bytes, limits: BundleLimits) -> list[object]:
    raw = _mapping(
        _json(body, max_bytes=limits.max_blob_bytes, limits=limits), {"schema", "records"}
    )
    _check(raw["schema"] == "synthetic-market-v1", "bundle_source_unsupported")
    return _array(raw["records"])


def _scope(source: SourceDescriptor, row: NormalizedRecord) -> None:
    value = row.value
    valid = value.instrument_id in source.instrument_ids and row.kind in source.record_kinds
    start, end = source.requested_start, source.requested_end
    if isinstance(value, Bar | CoverageDeclaration):
        valid = valid and start <= value.starts_at < value.ends_at <= end
        if isinstance(value, Bar):
            valid = valid and value.source == source.source_id
    elif isinstance(value, UniverseMembership):
        valid = valid and start <= value.effective_at < end
    elif isinstance(value, MembershipBaseline):
        valid = valid and start <= value.coverage_start < end
    elif isinstance(value, CorporateAction):
        # Effective dates are coarse UTC dates, not an inferred intraday event time.
        valid = (
            valid
            and start.date() <= value.effective_date <= (end - timedelta(microseconds=1)).date()
        )
    _check(valid, "bundle_scope_mismatch")


def _normalize(source: SourceDescriptor, rows: list[object]) -> tuple[NormalizedRecord, ...]:
    result: list[NormalizedRecord] = []
    for locator, raw in enumerate(rows):
        try:
            row = _mapping(raw, {"kind", "available_at", "price_basis", "value"})
            kind, available_at, basis = (
                _kind(row["kind"]),
                _time(row["available_at"]),
                row["price_basis"],
            )
            if kind == "bar":
                _choice(basis, ("unadjusted", "adjusted", "unknown"))
            else:
                _check(basis is None)
            value = _value(kind, row["value"], raw_hash=DataHash("0" * 64))
            body = asdict(value)
            body.pop("data_hash", None)
            record_hash = content_hash(
                {
                    "domain": "normalized-record-v1",
                    "kind": kind,
                    "source_hash": source.descriptor_hash,
                    "locator": locator,
                    "available_at": available_at,
                    "price_basis": basis,
                    "normalizer_version": source.normalizer_version,
                    "value": body,
                }
            )
            if isinstance(value, Bar | CorporateAction):
                value = replace(value, data_hash=record_hash)
            record = NormalizedRecord(
                kind,
                source.descriptor_hash,
                locator,
                available_at,
                cast(Literal["unadjusted", "adjusted", "unknown"] | None, basis),
                value,
                record_hash,
            )
            _scope(source, record)
            result.append(record)
            continue
        except BundleError:
            raise
        except (ValueError, TypeError, ArithmeticError):
            pass
        raise BundleError("bundle_value_invalid", record_index=locator)
    return tuple(result)


def _limitations(
    sources: tuple[SourceDescriptor, ...], records: tuple[NormalizedRecord, ...]
) -> tuple[str, ...]:
    codes = set(_MANDATORY_CODES)
    for source in sources:
        codes.update(source.limitation_codes)
    for row in records:
        if isinstance(row.value, CoverageDeclaration) and row.value.state != "complete":
            codes.add("declared_coverage_gap")
        if isinstance(row.value, Bar):
            if row.value.interpolated:
                codes.add("interpolated_data")
            if row.price_basis != "unadjusted":
                codes.add("price_basis_unsupported")
    return tuple(sorted(codes))


def _manifest(
    sources: tuple[SourceDescriptor, ...],
    records: tuple[NormalizedRecord, ...],
    instruments: tuple[InstrumentMapping, ...],
    limitations: tuple[str, ...],
) -> ResearchDataManifest:
    cleaned: list[DataHash] = []
    for mapping in instruments:
        bars = tuple(
            sorted(
                (
                    row.value
                    for row in records
                    if isinstance(row.value, Bar)
                    and row.value.instrument_id == mapping.instrument_id
                ),
                key=lambda bar: (bar.starts_at, bar.ends_at),
            )
        )
        cleaned.append(content_hash({"bars": bars, "symbol": mapping.symbol}))
    return ResearchDataManifest.create(
        raw_hashes=tuple(source.descriptor_hash for source in sources),
        cleaned_hashes=tuple(cleaned),
        corporate_action_coverage="declared_unverified",
        point_in_time_universe=False,
        survivorship_limitations=("source_history_unverified",),
        licensing_limitations=("source_license_unverified",),
        known_gaps=limitations,
    )


def _bundle_hash(envelope: BundleEnvelope) -> DataHash:
    body = asdict(envelope)
    del body["bundle_hash"]
    return content_hash(body)


def assemble_bundle(
    *,
    sources: tuple[SourceCapture, ...],
    instruments: tuple[InstrumentMapping, ...],
    limits: BundleLimits,
) -> BundlePackage:
    _check(type(limits) is BundleLimits, "bundle_limits_invalid")
    _items(sources, SourceCapture)
    _items(instruments, InstrumentMapping)
    _check(bool(sources) and bool(instruments))
    _check(len({item.instrument_id for item in instruments}) == len(instruments))
    _check(len({item.symbol for item in instruments}) == len(instruments))
    _check(
        all(len(source.raw_bytes) <= limits.max_blob_bytes for source in sources),
        "bundle_input_too_large",
    )
    descriptors = tuple(
        sorted(
            (_descriptor(source) for source in sources), key=lambda source: source.descriptor_hash
        )
    )
    _check(len({source.descriptor_hash for source in descriptors}) == len(descriptors))
    ids = {mapping.instrument_id for mapping in instruments}
    _check(
        all(set(source.instrument_ids) <= ids for source in descriptors), "bundle_scope_mismatch"
    )
    blobs = {sha256(source.raw_bytes).hexdigest(): source.raw_bytes for source in sources}
    _check(sum(map(len, blobs.values())) <= limits.max_total_bytes, "bundle_input_too_large")
    raw_rows = {digest: _raw_rows(body, limits) for digest, body in blobs.items()}
    # Replay counts every descriptor's rows, including distinct claims sharing a blob.
    _check(
        2 * sum(len(raw_rows[source.blob_sha256]) for source in descriptors) <= limits.max_records,
        "bundle_input_too_large",
    )
    records = tuple(
        row for source in descriptors for row in _normalize(source, raw_rows[source.blob_sha256])
    )
    limitations = _limitations(descriptors, records)
    envelope = BundleEnvelope(
        "research-bundle-v1",
        instruments,
        descriptors,
        records,
        _manifest(descriptors, records, instruments, limitations),
        "synthetic",
        limitations,
        DataHash("0" * 64),
    )
    encoded = encode_envelope(replace(envelope, bundle_hash=_bundle_hash(envelope)))
    _check(len(encoded) <= limits.max_envelope_bytes, "bundle_input_too_large")
    _check(
        len(encoded) + sum(map(len, blobs.values())) <= limits.max_total_bytes,
        "bundle_input_too_large",
    )
    return BundlePackage(encoded, tuple(sorted(blobs.items())))
