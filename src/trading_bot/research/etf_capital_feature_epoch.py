"""Invocation-local original basis reuse; no public cache or source authority."""

from dataclasses import dataclass, fields, replace
from datetime import UTC, date, datetime
from hashlib import sha256

from trading_bot.domain import Bar, DataHash
from trading_bot.market_data.etf_capital_actions import CapitalSplit
from trading_bot.market_data.etf_capital_features import (
    CapitalFeatureProjection,
    _capital_split_bar,
    _CapitalFeatureSource,
)
from trading_bot.market_data.recording import canonical_json

_BAR_FIELDS = (
    "instrument_id",
    "interval",
    "starts_at",
    "ends_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
    "data_hash",
    "interpolated",
)


@dataclass(frozen=True, slots=True)
class _CapitalFeatureBasis:
    source: _CapitalFeatureSource
    as_of_session: date
    splits: tuple[CapitalSplit, ...]
    features: tuple[Bar, ...]
    preimages: tuple[bytes, ...]


def _capital_final_feature(
    prehash: Bar, encoded: bytes, *, prefix: bytes
) -> tuple[Bar, bytes]:
    """Use authoritative whole-Bar bytes, replacing one exact hash field only."""
    if (
        type(prehash) is not Bar
        or tuple(field.name for field in fields(Bar)) != _BAR_FIELDS
        or type(encoded) is not bytes
        or type(prefix) is not bytes
        or type(prehash.starts_at) is not datetime
        or type(prehash.ends_at) is not datetime
        or prehash.starts_at.tzinfo is not UTC
        or prehash.ends_at.tzinfo is not UTC
        or type(prehash.instrument_id) is not str
        or type(prehash.source) is not str
        or type(prehash.data_hash) is not str
    ):
        raise ValueError("capital_feature_epoch_invalid")
    prehash.__post_init__()
    needle = b'"data_hash":' + canonical_json(prehash.data_hash).encode()
    if encoded.count(needle) != 1:
        raise ValueError("capital_feature_epoch_invalid")
    digest = sha256(prefix + encoded + b"]").hexdigest()
    final = replace(prehash, data_hash=DataHash(digest))
    replacement = b'"data_hash":' + canonical_json(final.data_hash).encode()
    return final, encoded.replace(needle, replacement, 1)


def _capital_features_epoch_at(
    source: _CapitalFeatureSource,
    *,
    as_of_session: date,
    basis: _CapitalFeatureBasis | None,
) -> tuple[_CapitalFeatureBasis, CapitalFeatureProjection, tuple[bytes, ...]]:
    """Called only after independent ownership/terminal validation in preparation.

    Basis changes recompute every consumed ORIGINAL row. A skipped, unrequested
    derived basis is not newly evaluated; ordered product checks still apply.
    """
    actions = source.actions
    if (
        type(as_of_session) is not date
        or not actions.start <= as_of_session < actions.end
        or source.raw_rows is None
        or actions.splits is None
        or actions.distributions is None
        or (
            basis is not None
            and (
                type(basis) is not _CapitalFeatureBasis
                or basis.source is not source
                or basis.as_of_session > as_of_session
            )
        )
    ):
        raise ValueError("capital_feature_epoch_invalid")
    required = {
        row.session_date
        for row in source.calendar.sessions
        if actions.start <= row.session_date <= as_of_session
    }
    raw = tuple((day, bar) for day, bar in source.raw_rows if day <= as_of_session)
    if as_of_session not in required or {day for day, _ in raw} != required:
        raise ValueError("capital_feature_epoch_invalid")
    splits = tuple(row for row in actions.splits if row.effective_date <= as_of_session)
    prior = basis if basis is not None and basis.splits == splits else None
    if prior is not None and len(prior.features) > len(raw):
        raise ValueError("capital_feature_epoch_invalid")
    features = [] if prior is None else list(prior.features)
    preimages = [] if prior is None else list(prior.preimages)
    for _, original in raw[len(features) :]:
        feature = _capital_split_bar(original, splits=splits, as_of_session=as_of_session)
        features.append(feature)
        preimages.append(canonical_json(feature).encode())
    next_basis = _CapitalFeatureBasis(
        source, as_of_session, splits, tuple(features), tuple(preimages)
    )
    prefix = (
        canonical_json(
            (
                "capital-split-feature-bar-v2",
                source.archive_hash,
                source.action_hash,
                source.calendar_hash,
                as_of_session,
            )
        ).encode()[:-1]
        + b","
    )
    final = tuple(
        _capital_final_feature(feature, encoded, prefix=prefix)
        for feature, encoded in zip(next_basis.features, next_basis.preimages, strict=True)
    )
    projection = CapitalFeatureProjection(
        source.archive_hash,
        source.action_hash,
        source.calendar_hash,
        as_of_session,
        tuple(bar for _, bar in raw),
        tuple(bar for bar, _ in final),
        tuple(row for row in actions.distributions if row.ex_date <= as_of_session),
    )
    return next_basis, projection, tuple(encoded for _, encoded in final)
