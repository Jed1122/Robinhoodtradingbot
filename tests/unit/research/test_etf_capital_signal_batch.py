"""Shared numerical kernel retains literal pre-extraction signal evidence."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from tests.unit.research.test_etf_capital_signals import projections
from trading_bot.domain import BarInterval, ConfigHash
from trading_bot.market_data.etf_capital_actions import CapitalDistribution
from trading_bot.market_data.etf_capital_features import CapitalFeatureProjection
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_signals import capital_candidates, capital_strategy_signal

_CONFIG_HASH = ConfigHash("d" * 64)


def batch(rows, *, as_of=None, config_hash=_CONFIG_HASH):
    from trading_bot.research.etf_capital_signals import _capital_strategy_signals

    return _capital_strategy_signals(
        rows, config_hash=config_hash, as_of=as_of or rows[0].raw_bars[-1].ends_at
    )


def cases():
    return (
        tuple(D(100 + i) for i in range(199)),
        tuple(D(100 + i) for i in range(200)),
        tuple(D(100 + i) for i in range(201)),
        tuple(D(1000 - i) for i in range(200)),
        (D(100),) * 200,
        (
            *tuple(D(100) + D(i) / 10 for i in range(180)),
            *tuple(D(118) - D(i) / 5 for i in range(20)),
        ),
    )


@pytest.mark.parametrize(
    "index,expected",
    [
        (0, "fada1812c18919a9314c59991430862b1234326276c8eda57f6a2678f22064bd"),
        (1, "61ad8fe06c620d7756ec180953871613499fcbb323da7c4f6b75e06ee46363ac"),
        (2, "061c474e8303556b2f48e29da3d00881a650a5a510a6f76e8912f5ef86495dc8"),
        (3, "22a6d423bfdca421f497827f1fafb0c76408605a37fb2f15b2bd648077dde4a2"),
        (4, "49759ae91ae5ad5dc0a11031ee29632636e4f69b369abc8dcb433163603226aa"),
        (5, "23b97be4e9171f3101b1ecceaeeec7df3c1d86ffa975f4e5b980a0165659047a"),
    ],
)
def test_complete_batch_matches_literal_original_public_signal_hashes(index, expected):
    # Literal values captured from unchanged 14d public implementation BEFORE
    # extraction; not recomputed using the new shared kernel as the oracle.
    result = batch(projections(cases()[index]))
    assert content_hash(result) == expected
    assert tuple(row.candidate for row in result) == capital_candidates()
    assert all(
        row.source_qualified
        is row.economic_accepted
        is row.execution_enabled
        is row.promotion_eligible
        is False
        for row in result
    )


def test_one_batch_hashes_each_complete_projection_once(monkeypatch):
    rows = projections(cases()[2])
    actual_property = CapitalFeatureProjection.projection_hash.fget
    calls = []

    def hash_actual_projection(self):
        calls.append(self)
        return actual_property(self)

    monkeypatch.setattr(
        CapitalFeatureProjection, "projection_hash", property(hash_actual_projection)
    )
    result = batch(rows)
    assert len(calls) == 5 and {id(row) for row in calls} == {id(row) for row in rows}
    assert result[0].entry_symbol == "IEF"
    assert result[0].score == D("6.761565836298932384341637010676156583629893238434163701067615700")


def test_batch_equals_all_public_outputs_and_does_not_change_public_order_contract():
    rows = projections(cases()[1])
    expected = tuple(
        capital_strategy_signal(
            candidate, rows, config_hash=ConfigHash("d" * 64), as_of=rows[0].raw_bars[-1].ends_at
        )
        for candidate in capital_candidates()
    )
    assert batch(rows) == expected == batch(tuple(reversed(rows)))


@pytest.mark.parametrize(
    "target", ["flag", "old_interval", "old_interpolation", "duplicates", "grid"]
)
def test_new_batch_revalidates_originals_after_prior_valid_invocation(target):
    rows = projections(cases()[2])
    batch(rows)
    if target == "flag":
        object.__setattr__(rows[0], "source_qualified", True)
    elif target == "old_interval":
        object.__setattr__(rows[0].feature_bars[0], "interval", BarInterval.ONE_MINUTE)
    elif target == "old_interpolation":
        object.__setattr__(rows[0].raw_bars[0], "interpolated", True)
    elif target == "duplicates":
        day = rows[0].as_of_session
        declaration = CapitalDistribution(day, day, day, D(1), "e" * 64)
        object.__setattr__(rows[0], "distributions", (declaration, declaration))
    else:
        object.__setattr__(rows[0], "as_of_session", rows[0].as_of_session + timedelta(days=1))
    with pytest.raises(ValueError):
        batch(rows)


def test_changed_source_metadata_and_asof_bind_new_batch_identities_not_stale_results():
    rows = projections(cases()[1])
    original = batch(rows)
    changed = (replace(rows[0], archive_hash="f" * 64), *rows[1:])
    current = batch(changed)
    later = batch(changed, as_of=rows[0].raw_bars[-1].ends_at + timedelta(seconds=1))
    for old, new, future in zip(original, current, later, strict=True):
        assert old.input_hash != new.input_hash != future.input_hash
        assert old.entry_symbol == new.entry_symbol == future.entry_symbol
        assert old.score == new.score == future.score


@pytest.mark.parametrize("target", ["list", "missing", "duplicate_symbol", "config", "future"])
def test_batch_does_not_offer_a_weaker_input_route(target):
    rows = projections(cases()[1])
    kwargs = {}
    if target == "list":
        rows = list(rows)
    elif target == "missing":
        rows = rows[:-1]
    elif target == "duplicate_symbol":
        rows = (rows[0], rows[0], *rows[2:])
    elif target == "config":
        kwargs["config_hash"] = ConfigHash("z" * 64)
    else:
        kwargs["as_of"] = rows[0].raw_bars[-1].ends_at - timedelta(seconds=1)
    with pytest.raises(ValueError):
        batch(rows, **kwargs)
