"""Original requested-basis reuse preserves bytes, hashes and admission."""

from dataclasses import replace
from datetime import timedelta, timezone
from decimal import ROUND_UP, Inexact, localcontext
from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_prepared import long_source, prepare
from trading_bot.market_data.etf_capital_actions import CapitalDistribution, CapitalSplit
from trading_bot.market_data.etf_capital_features import (
    _capital_feature_source,
    _capital_owned_raw_source,
    capital_split_feature_bars,
)
from trading_bot.market_data.etf_capital_owned import _own_capital_source
from trading_bot.market_data.recording import canonical_json, content_hash


def original_source(dataset):
    owned = _own_capital_source(dataset).dataset
    return _capital_owned_raw_source(
        _capital_feature_source(
            owned.archives[0],
            owned.calendar,
            owned.actions[0],
            as_of_session=owned.start,
        )
    )


def at(source, day, basis=None):
    from trading_bot.research.etf_capital_feature_epoch import _capital_features_epoch_at

    return _capital_features_epoch_at(source, as_of_session=day, basis=basis)


@pytest.mark.parametrize("precision", (3, 64))
def test_same_epoch_and_new_split_epoch_match_all_original_fields_and_bytes(precision):
    dataset = long_source(12)
    days = tuple(row.session_date for row in dataset.calendar.sessions)
    dataset = replace(
        dataset,
        actions=tuple(
            replace(
                action,
                splits=(
                    CapitalSplit(days[4], D(3), "a" * 64),
                    CapitalSplit(days[9], D(2), "b" * 64),
                ),
                distributions=(
                    CapitalDistribution(days[6], days[7], days[10], D("1.25"), "c" * 64),
                ),
            )
            for action in dataset.actions
        ),
    )
    source = original_source(dataset)
    basis = None
    with localcontext() as context:
        context.prec = precision
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        for day in (days[0], days[3], days[4], days[7], days[9], days[-1]):
            basis, actual, encoded = at(source, day, basis)
            expected = capital_split_feature_bars(
                dataset.archives[0], dataset.calendar, dataset.actions[0], as_of_session=day
            )
            assert actual == expected and actual.projection_hash == expected.projection_hash
            assert encoded == tuple(canonical_json(bar).encode() for bar in expected.feature_bars)
    assert actual.feature_bars[0].close == D(
        "16.66666666666666666666666666666666666666666666666666666666666667"
    )
    assert actual.raw_bars[0].close == D(100)


def test_unchanged_basis_derives_only_new_rows_but_split_recomputes_all_originals(monkeypatch):
    import trading_bot.research.etf_capital_feature_epoch as module

    dataset = long_source(12)
    days = tuple(row.session_date for row in dataset.calendar.sessions)
    dataset = replace(
        dataset,
        actions=tuple(
            replace(action, splits=(CapitalSplit(days[8], D(3), "a" * 64),))
            for action in dataset.actions
        ),
    )
    source = original_source(dataset)
    derive = module._capital_split_bar
    calls = []

    def observed(*args, **kwargs):
        calls.append(1)
        return derive(*args, **kwargs)

    monkeypatch.setattr(module, "_capital_split_bar", observed)
    basis, first, _ = at(source, days[5])
    assert len(calls) == 6
    basis, second, _ = at(source, days[6], basis)
    assert len(calls) == 7
    _, third, _ = at(source, days[8], basis)
    assert len(calls) == 16
    assert first.feature_bars[0].close == second.feature_bars[0].close == D(100)
    assert third.feature_bars[0].close == D(
        "33.33333333333333333333333333333333333333333333333333333333333333"
    )


def test_pre_hash_ancestor_is_raw_and_final_feature_digest_remains_date_bound():
    source = original_source(long_source(12))
    days = tuple(row.session_date for row in source.calendar.sessions)
    basis, first, _ = at(source, days[3])
    old_preimage = basis.preimages[0]
    basis, second, _ = at(source, days[4], basis)
    assert basis.preimages[0] == old_preimage
    assert basis.features[0].data_hash == first.raw_bars[0].data_hash
    assert first.feature_bars[0].data_hash != second.feature_bars[0].data_hash
    assert second.feature_bars[0].data_hash == content_hash(
        (
            "capital-split-feature-bar-v2",
            source.archive_hash,
            source.action_hash,
            source.calendar_hash,
            days[4],
            basis.features[0],
        )
    )


def test_basis_cannot_cross_independently_owned_sources():
    dataset = long_source(12)
    first = original_source(dataset)
    second = original_source(dataset)
    days = tuple(row.session_date for row in first.calendar.sessions)
    basis, _, _ = at(first, days[3])
    with pytest.raises(ValueError):
        at(second, days[4], basis)


def test_missing_original_row_cannot_be_hidden_by_a_complete_prior_basis():
    source = original_source(long_source(12))
    days = tuple(row.session_date for row in source.calendar.sessions)
    assert source.raw_rows is not None
    broken = replace(source, raw_rows=source.raw_rows[1:])
    with pytest.raises(ValueError, match="capital_feature_epoch_invalid"):
        at(broken, days[4])


def test_inconsistent_basis_length_cannot_supply_unobserved_feature_rows():
    source = original_source(long_source(12))
    days = tuple(row.session_date for row in source.calendar.sessions)
    basis, _, _ = at(source, days[3])
    inconsistent = replace(
        basis,
        features=(*basis.features, *basis.features),
        preimages=(*basis.preimages, *basis.preimages),
    )
    with pytest.raises(ValueError, match="capital_feature_epoch_invalid"):
        at(source, days[4], inconsistent)


def test_sparse_schedule_does_not_invent_unrequested_invalid_derived_epoch():
    dataset = long_source(3, ancient=True)
    days = tuple(row.session_date for row in dataset.calendar.sessions)
    dataset = replace(
        dataset,
        actions=tuple(
            replace(
                action,
                splits=(
                    CapitalSplit(days[1], D("1e-400"), "a" * 64),
                    CapitalSplit(days[2], D("1e400"), "b" * 64),
                ),
            )
            for action in dataset.actions
        ),
    )
    source = original_source(dataset)
    basis, _, _ = at(source, days[0])
    _, final, _ = at(source, days[2], basis)
    assert final.feature_bars[0].close == D("1e200")
    with pytest.raises(ValueError):
        at(source, days[1], basis)
    assert len(prepare(dataset, (days[0], days[2])).days) == 2
    with pytest.raises(ValueError):
        prepare(dataset, days)


def test_ordered_factor_overflow_cannot_cancel_to_a_bounded_final_product():
    dataset = long_source(5)
    days = tuple(row.session_date for row in dataset.calendar.sessions)
    actions = replace(
        dataset.actions[0],
        splits=tuple(
            CapitalSplit(day, ratio, str(index) * 64)
            for index, (day, ratio) in enumerate(
                zip(days[1:], (D("1e400"), D("1e400"), D("1e-400"), D("1e-400")), strict=True)
            )
        ),
    )
    source = _capital_owned_raw_source(
        _capital_feature_source(
            dataset.archives[0], dataset.calendar, actions, as_of_session=days[0]
        )
    )
    with pytest.raises(ValueError):
        at(source, days[-1])


def test_closed_bar_hash_field_substitution_does_not_replace_other_hash_text():
    from trading_bot.research.etf_capital_feature_epoch import _capital_final_feature

    source = original_source(long_source(2))
    _, projection, _ = at(source, source.calendar.sessions[0].session_date)
    old = projection.raw_bars[0]
    prehash = replace(
        old,
        source=f'repeated {old.data_hash} and escaped "data_hash":"{old.data_hash}"',
    )
    encoded = canonical_json(prehash).encode()
    prefix = canonical_json(("fixture", source.archive_hash)).encode()[:-1] + b","
    final, actual = _capital_final_feature(prehash, encoded, prefix=prefix)
    assert final.data_hash == content_hash(("fixture", source.archive_hash, prehash))
    assert actual == canonical_json(final).encode()
    assert final.source == prehash.source and str(old.data_hash).encode() in actual


@pytest.mark.parametrize("kind", ("missing", "duplicate", "not_bytes", "bad_prefix"))
def test_closed_bar_preimage_rejects_invalid_fragment_or_byte_type(kind):
    from trading_bot.research.etf_capital_feature_epoch import _capital_final_feature

    source = original_source(long_source(2))
    _, projection, _ = at(source, source.calendar.sessions[0].session_date)
    prehash = projection.raw_bars[0]
    encoded = canonical_json(prehash).encode()
    prefix = b'["fixture",'
    needle = b'"data_hash":' + canonical_json(prehash.data_hash).encode()
    if kind == "missing":
        encoded = encoded.replace(needle, b'"other_hash":"none"')
    elif kind == "duplicate":
        encoded += needle
    elif kind == "not_bytes":
        encoded = bytearray(encoded)
    else:
        prefix = bytearray(prefix)
    with pytest.raises(ValueError, match="capital_feature_epoch_invalid"):
        _capital_final_feature(prehash, encoded, prefix=prefix)


def test_closed_bar_preimage_rejects_schema_drift(monkeypatch):
    import trading_bot.research.etf_capital_feature_epoch as module

    source = original_source(long_source(2))
    _, projection, _ = at(source, source.calendar.sessions[0].session_date)
    prehash = projection.raw_bars[0]
    monkeypatch.setattr(module, "_BAR_FIELDS", module._BAR_FIELDS[:-1])
    with pytest.raises(ValueError, match="capital_feature_epoch_invalid"):
        module._capital_final_feature(prehash, canonical_json(prehash).encode(), prefix=b"[")


def test_closed_bar_preimage_rejects_non_owned_timezone():
    from trading_bot.research.etf_capital_feature_epoch import _capital_final_feature

    source = original_source(long_source(2))
    _, projection, _ = at(source, source.calendar.sessions[0].session_date)
    old = projection.raw_bars[0]
    zone = timezone(timedelta(0), "fixture-custom-utc")
    prehash = replace(
        old, starts_at=old.starts_at.astimezone(zone), ends_at=old.ends_at.astimezone(zone)
    )
    with pytest.raises(ValueError, match="capital_feature_epoch_invalid"):
        _capital_final_feature(prehash, canonical_json(prehash).encode(), prefix=b"[")
