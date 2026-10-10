"""Private streaming must preserve original whole-dataclass public bytes."""

import hashlib
from dataclasses import fields, make_dataclass, replace
from datetime import timedelta, tzinfo
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.market_data.test_etf_capital_dataset import dataset
from tests.unit.research.test_etf_capital_prepared import long_source, prepare
from trading_bot.market_data.etf_capital_actions import CapitalDistribution, CapitalSplit
from trading_bot.market_data.etf_capital_dataset import capital_dataset_features
from trading_bot.market_data.etf_capital_features import CapitalFeatureProjection
from trading_bot.market_data.recording import canonical_json


def preimage(projection, raw=None):
    from trading_bot.research.etf_capital_projection_preimage import _capital_projection_preimage

    encoded = (
        tuple(canonical_json(bar).encode() for bar in projection.raw_bars) if raw is None else raw
    )
    return b"".join(_capital_projection_preimage(projection, raw_json=encoded))


@pytest.mark.parametrize("kind", ("none", "split", "distribution"))
@pytest.mark.parametrize("precision", (3, 64))
def test_streamed_complete_bytes_match_original_public_projection_preimage(kind, precision):
    source = long_source(12)
    days = tuple(row.session_date for row in source.calendar.sessions)
    source = replace(
        source,
        actions=tuple(
            replace(
                action,
                splits=(CapitalSplit(days[4], D(3), "a" * 64),) if kind == "split" else (),
                distributions=(
                    CapitalDistribution(days[5], days[6], days[8], D("1.25"), "b" * 64),
                )
                if kind == "distribution"
                else (),
            )
            for action in source.actions
        ),
    )
    with localcontext() as context:
        context.prec = precision
        for day in (days[0], days[5], days[-1]):
            for projection in capital_dataset_features(source, as_of_session=day):
                original = canonical_json(
                    ("capital-split-feature-projection-v2", projection)
                ).encode()
                actual = preimage(projection)
                assert actual == original
                assert hashlib.sha256(actual).hexdigest() == projection.projection_hash
                assert b'"source_qualified":false' in actual
                assert b'"evidence_promotable":false' in actual
                assert b'"execution_enabled":false' in actual


def test_reused_raw_bytes_have_the_same_complete_prefix_not_a_digest_substitution():
    source = long_source(12)
    days = tuple(row.session_date for row in source.calendar.sessions)
    full = capital_dataset_features(source, as_of_session=days[-1])
    raw_bytes = tuple(canonical_json(bar).encode() for bar in full[0].raw_bars)
    early = capital_dataset_features(source, as_of_session=days[3])[0]
    assert preimage(early, raw_bytes[:4]) == canonical_json(
        ("capital-split-feature-projection-v2", early)
    ).encode()
    with pytest.raises(ValueError):
        preimage(early, raw_bytes)


def test_preparation_does_not_repeat_public_full_projection_hashing_for_every_prefix(monkeypatch):
    descriptor = CapitalFeatureProjection.projection_hash
    calls = []

    def observed(self):
        calls.append(self.as_of_session)
        return descriptor.fget(self)

    monkeypatch.setattr(CapitalFeatureProjection, "projection_hash", property(observed))
    source = long_source(12)
    days = tuple(row.session_date for row in source.calendar.sessions)
    one = prepare(source, (days[-1],))
    count = len(calls)
    calls.clear()
    many = prepare(source, days)
    assert len(calls) == count
    assert many.days[-1] == one.days[0]


@pytest.mark.parametrize("flag", ("source_qualified", "execution_enabled", "evidence_promotable"))
def test_streaming_cannot_silently_drop_forged_false_markers(flag):
    projection = capital_dataset_features(dataset(), as_of_session=dataset().start)[0]
    object.__setattr__(projection, flag, True)
    with pytest.raises(ValueError):
        preimage(projection)


def test_schema_drift_denies_instead_of_omitting_a_new_projection_field(monkeypatch):
    import trading_bot.research.etf_capital_projection_preimage as module

    future = make_dataclass("FutureProjection", [("new_evidence_flag", bool)])
    original_fields = fields(CapitalFeatureProjection)
    monkeypatch.setattr(module, "fields", lambda _: (*original_fields, *fields(future)))
    projection = capital_dataset_features(dataset(), as_of_session=dataset().start)[0]
    with pytest.raises(ValueError):
        preimage(projection)


def test_private_stream_rejects_public_custom_timezone_copy_semantics():
    class CopyChangingZone(tzinfo):
        def utcoffset(self, value):
            return timedelta(0)

        def dst(self, value):
            return timedelta(0)

        def __deepcopy__(self, memo):
            from datetime import timezone

            return timezone(timedelta(hours=1))

    projection = capital_dataset_features(dataset(), as_of_session=dataset().start)[0]
    raw = projection.raw_bars[0]
    custom = replace(
        raw,
        starts_at=raw.starts_at.replace(tzinfo=CopyChangingZone()),
        ends_at=raw.ends_at.replace(tzinfo=CopyChangingZone()),
    )
    changed = replace(
        projection,
        raw_bars=(custom,),
        feature_bars=(
            replace(
                projection.feature_bars[0],
                starts_at=custom.starts_at,
                ends_at=custom.ends_at,
            ),
        ),
    )
    # Public whole-dataclass serialization remains unchanged, not redirected.
    assert b"+01:00" in canonical_json(changed).encode()
    with pytest.raises(ValueError):
        preimage(changed)
