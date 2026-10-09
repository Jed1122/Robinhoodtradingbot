"""Calendar gaps and literal split-basis arithmetic in offline owner inputs."""

from dataclasses import replace
from datetime import timedelta
from decimal import ROUND_HALF_EVEN, Context, localcontext
from decimal import Decimal as D

import pytest

from tests.unit.simulation.test_etf_capital_daily_owner import action_records, calendar, frames, run


def test_appended_bar_cannot_skip_an_original_declared_calendar_session():
    records = frames(2)
    altered = []
    for p in records[-1].projections:
        raw = replace(
            p.raw_bars[-1],
            starts_at=p.raw_bars[-1].starts_at + timedelta(days=1),
            ends_at=p.raw_bars[-1].ends_at + timedelta(days=1),
        )
        feature = replace(p.feature_bars[-1], starts_at=raw.starts_at, ends_at=raw.ends_at)
        altered.append(
            replace(
                p,
                as_of_session=p.as_of_session + timedelta(days=1),
                raw_bars=(*p.raw_bars[:-1], raw),
                feature_bars=(*p.feature_bars[:-1], feature),
            )
        )
    with pytest.raises(ValueError):
        run(records=(records[0], replace(records[1], projections=tuple(altered))))


def split_records(ratio):
    records = action_records("split")
    original = frames(3, hold=20)[-1]
    with localcontext(Context(prec=64, rounding=ROUND_HALF_EVEN)):
        mark = D(301) / ratio
        projected = []
        for p in original.projections:
            if str(p.raw_bars[-1].instrument_id) != "IEF":
                projected.append(p)
                continue
            adjusted = tuple(
                replace(
                    b,
                    open=b.open / ratio,
                    high=b.high / ratio,
                    low=b.low / ratio,
                    close=b.close / ratio,
                    volume=b.volume * ratio,
                )
                for b in p.feature_bars
            )
            last = replace(
                p.raw_bars[-1],
                open=p.raw_bars[-1].open / ratio,
                high=p.raw_bars[-1].high / ratio,
                low=p.raw_bars[-1].low / ratio,
                close=p.raw_bars[-1].close / ratio,
            )
            projected.append(
                replace(
                    p,
                    raw_bars=(*p.raw_bars[:-1], last),
                    feature_bars=(*adjusted[:-1], replace(adjusted[-1], volume=last.volume)),
                )
            )
        fact = records[-1].original_facts[0]
        fact = replace(
            fact, event=replace(fact.event, ratio=ratio, post_action_mark=mark), mark=mark
        )
    return (
        *records[:-1],
        replace(records[-1], projections=tuple(projected), original_facts=(fact,)),
    )


@pytest.mark.parametrize(
    "ratio,quantity,basis,stop",
    (
        (
            D(3),
            D(".198"),
            D("100.05"),
            D("1.333333333333333333333333333333333333333333333333333333333333333"),
        ),
        (
            D("1.5"),
            D(".099"),
            D("200.10"),
            D("2.666666666666666666666666666666666666666666666666666666666666667"),
        ),
    ),
)
def test_owned_split_uses_the_feature_builders_64_digit_context(ratio, quantity, basis, stop):
    value = run(records=split_records(ratio))
    assert value.account.quantity == quantity
    assert value.account.average_price == basis
    assert value.account.cash == D("80.1801")
    assert value.points[-1].opening.stop_distance == stop


@pytest.mark.parametrize("field,value", (("source_kind", "qualified"), ("limitations", ())))
def test_forged_calendar_metadata_cannot_become_owner_authority(field, value):
    declared = calendar()
    object.__setattr__(declared, field, value)
    records = tuple(
        replace(
            frame,
            projections=tuple(
                replace(p, calendar_hash=declared.archive_hash) for p in frame.projections
            ),
        )
        for frame in frames(2)
    )
    with pytest.raises(ValueError):
        run(records=records, calendar=declared)


@pytest.mark.parametrize("declared", (None, "calendar"))
def test_missing_or_untyped_calendar_denies(declared):
    with pytest.raises(ValueError):
        run(count=2, calendar=declared)


def test_equality_equivalent_calendar_limitation_strings_are_not_canonical_metadata():
    class EqualString(str):
        pass

    declared = calendar()
    object.__setattr__(declared, "limitations", tuple(EqualString(x) for x in declared.limitations))
    with pytest.raises(ValueError):
        run(count=2, calendar=declared)


def test_mismatched_original_calendar_hash_denies():
    with pytest.raises(ValueError):
        run(count=2, calendar=replace(calendar(), source_hash="d" * 64))


def test_unknown_initial_adjusted_feature_basis_is_not_inferred():
    frame = frames(1)[0]
    projection = frame.projections[0]
    altered = replace(
        projection,
        feature_bars=tuple(
            replace(b, open=b.open / 2, high=b.high / 2, low=b.low / 2, close=b.close / 2)
            for b in projection.feature_bars
        ),
    )
    with pytest.raises(ValueError):
        run(records=(replace(frame, projections=(altered, *frame.projections[1:])),))


def test_declared_non_session_gap_is_not_repaired_with_an_invented_bar():
    original = calendar()
    declared = replace(original, sessions=(*original.sessions[:100], *original.sessions[101:]))
    records = tuple(
        replace(
            frame,
            projections=tuple(
                replace(
                    p,
                    calendar_hash=declared.archive_hash,
                    raw_bars=(*p.raw_bars[:100], *p.raw_bars[101:]),
                    feature_bars=(*p.feature_bars[:100], *p.feature_bars[101:]),
                )
                for p in frame.projections
            ),
        )
        for frame in frames(2)
    )
    result = run(records=records, calendar=declared)
    assert len(result.points) == 2
    assert result.account.cash == D(100)
    assert not result.source_qualified


def test_successive_splits_recompute_original_raw_basis_not_rounded_prior_features():
    records = split_records(D(3))
    frame = frames(4, hold=20)[-1]
    previous = {str(p.raw_bars[-1].instrument_id): p for p in records[-1].projections}
    projected = []
    with localcontext(Context(prec=64, rounding=ROUND_HALF_EVEN)):
        for p in frame.projections:
            if str(p.raw_bars[-1].instrument_id) != "IEF":
                projected.append(p)
                continue
            last = replace(
                p.raw_bars[-1],
                open=p.raw_bars[-1].open / 6,
                high=p.raw_bars[-1].high / 6,
                low=p.raw_bars[-1].low / 6,
                close=p.raw_bars[-1].close / 6,
            )
            raw = (*previous["IEF"].raw_bars, last)
            adjusted = []
            for index, b in enumerate(raw):
                factor = D(6) if index < 201 else D(2) if index == 201 else D(1)
                adjusted.append(
                    replace(
                        b,
                        open=b.open / factor,
                        high=b.high / factor,
                        low=b.low / factor,
                        close=b.close / factor,
                        volume=b.volume * factor,
                        source="capital-split-feature-assumption-v2",
                    )
                )
            projected.append(replace(p, raw_bars=raw, feature_bars=tuple(adjusted)))
        old = records[-1].original_facts[0]
        mark = previous["IEF"].raw_bars[-1].close / 2
        event = replace(
            old.event,
            event_id="second-split",
            action_id="second-split-action",
            record_hash="a" * 64,
            ratio=D(2),
            post_action_mark=mark,
            cursor=replace(
                old.event.cursor, sequence=2000, occurred_at=last.starts_at - timedelta(seconds=1)
            ),
        )
        fact = replace(old, event=event, mark=mark)
    result = run(
        records=(*records, replace(frame, projections=tuple(projected), original_facts=(fact,)))
    )
    assert result.account.quantity == D(".396")
    assert result.account.average_price == D("50.025")
    assert result.account.cash == D("80.1801")
    assert result.points[-1].opening.stop_distance == D(
        ".6666666666666666666666666666666666666666666666666666666666666667"
    )
    assert next(p for p in projected if str(p.raw_bars[-1].instrument_id) == "IEF").feature_bars[
        0
    ].close == D("16.66666666666666666666666666666666666666666666666666666666666667")
