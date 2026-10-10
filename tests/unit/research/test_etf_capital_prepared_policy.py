"""Private prepared-policy equivalence; fabricated inputs, no admission."""

from dataclasses import replace
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.config.test_capital_research import capital_loaded
from tests.unit.research.test_etf_capital_prepared import long_source, prepare
from trading_bot.market_data.etf_capital_dataset import capital_dataset_features
from trading_bot.research.etf_capital_daily_policy import (
    CapitalOpeningPolicy,
    capital_daily_policy,
)
from trading_bot.research.etf_capital_signals import CapitalCandidate, capital_candidates


def policy(prepared, candidate, *, index=-1, opening=None):
    from trading_bot.research.etf_capital_prepared_policy import _capital_prepared_policy

    return _capital_prepared_policy(
        loaded=capital_loaded(),
        prepared=prepared,
        day_index=len(prepared.days) - 1 if index == -1 else index,
        candidate=candidate,
        opening=opening,
    )


@pytest.mark.parametrize("count", (199, 200, 230))
def test_every_candidate_flat_and_held_instruction_matches_original_public_policy(count):
    source = long_source(count)
    dates = tuple(row.session_date for row in source.calendar.sessions)
    value = prepare(source, (dates[-1],))
    original = capital_dataset_features(source, as_of_session=dates[-1])
    for candidate in capital_candidates():
        opening = CapitalOpeningPolicy(candidate, "SPY", dates[-2], D(8))
        for held in (None, opening):
            expected = capital_daily_policy(
                loaded=capital_loaded(),
                candidate=candidate,
                projections=original,
                as_of=value.days[0].as_of,
                opening=held,
            )
            assert policy(value, candidate, opening=held) == expected
            assert not expected.execution_enabled and not expected.evidence_promotable


def test_literal_original_policy_carries_across_new_candidate_and_counts_calendar_sessions():
    source = long_source(230)
    dates = tuple(row.session_date for row in source.calendar.sessions)
    value = prepare(source, (dates[-1],))
    original = CapitalCandidate("momentum", 20, 100, 20)
    opening = CapitalOpeningPolicy(original, "SPY", dates[-19], D("7.25"))
    replacement = CapitalCandidate("mean_reversion", 5, 0, 2)
    result = policy(value, replacement, opening=opening)
    assert (result.action, result.reason, result.candidate, result.stop_distance) == (
        "hold", "opening_policy_retained", original, D("7.25")
    )
    boundary = replace(opening, entry_session=dates[-20])
    assert policy(value, replacement, opening=boundary).reason == "maximum_hold"


def test_known_hold_deadline_precedes_warmup_and_missing_atr():
    source = long_source(199, flat=True)
    dates = tuple(row.session_date for row in source.calendar.sessions)
    value = prepare(source, (dates[-1],))
    candidate = CapitalCandidate("momentum", 20, 100, 2)
    opening = CapitalOpeningPolicy(candidate, "SPY", dates[-2], D(4))
    result = policy(value, candidate, opening=opening)
    assert (result.action, result.reason, result.stop_distance) == ("exit", "maximum_hold", D(4))
    assert all(flag is None for _, flag in value.days[0].below_sma200)


def test_mean_reversion_sma_exit_does_not_depend_on_rsi_exit_signal():
    source = long_source(200, flat=True, last_close=50)
    dates = tuple(row.session_date for row in source.calendar.sessions)
    value = prepare(source, (dates[-1],))
    candidate = CapitalCandidate("mean_reversion", 5, 0, 20)
    signal = next(s for s in value.days[0].signals if s.candidate == candidate)
    # 199 closes100 followed by50: WilderRSI2=0, current close50<SMA99.75.
    assert signal.exit_symbols == ()
    assert dict(value.days[0].below_sma200)["SPY"] is True
    opening = CapitalOpeningPolicy(candidate, "SPY", dates[-1], D(4))
    result = policy(value, candidate, opening=opening)
    assert (result.action, result.reason) == ("exit", "regime_exit")


def test_unknown_held_sma_fact_cannot_silently_mean_no_regime_exit():
    from trading_bot.research.etf_capital_daily_policy import _capital_policy_from_facts

    source = long_source(200, flat=True, last_close=50)
    dates = tuple(row.session_date for row in source.calendar.sessions)
    value = prepare(source, (dates[-1],))
    candidate = CapitalCandidate("mean_reversion", 5, 0, 20)
    signal = next(s for s in value.days[0].signals if s.candidate == candidate)
    opening = CapitalOpeningPolicy(candidate, "SPY", dates[-1], D(4))
    with pytest.raises(ValueError, match="capital_daily_policy_invalid"):
        _capital_policy_from_facts(
            loaded=capital_loaded(), candidate=candidate, signal=signal, opening=opening,
            elapsed=1, history_ready=True, below_sma200=None, entry_distance=None,
        )


@pytest.mark.parametrize("offset", (-1, 1))
def test_opening_session_outside_original_calendar_or_in_future_denies(offset):
    source = long_source(201)
    dates = tuple(row.session_date for row in source.calendar.sessions)
    value = prepare(source, (dates[199],))
    candidate = capital_candidates()[0]
    from datetime import timedelta

    entered = dates[0] - timedelta(days=1) if offset < 0 else dates[200]
    opening = CapitalOpeningPolicy(candidate, "SPY", entered, D(4))
    with pytest.raises(ValueError):
        policy(value, candidate, opening=opening)


def test_untyped_preparation_candidate_and_opening_cannot_create_instructions():
    source = long_source(2)
    value = prepare(source, (source.calendar.sessions[-1].session_date,))
    with pytest.raises(ValueError):
        policy(None, capital_candidates()[0], index=0)
    with pytest.raises(ValueError):
        policy(value, object())
    with pytest.raises(ValueError):
        policy(value, capital_candidates()[0], opening=object())


def test_missing_original_candidate_signal_denies_instead_of_fallback():
    source = long_source(2)
    value = prepare(source, (source.calendar.sessions[-1].session_date,))
    # Defensive private-boundary check; this is not a supported public token.
    damaged = replace(value, days=(replace(value.days[0], signals=()),))
    with pytest.raises(ValueError):
        policy(damaged, capital_candidates()[0])


def test_prepared_config_identity_cannot_be_reused_with_a_different_config():
    source = long_source(2)
    value = prepare(source, (source.calendar.sessions[-1].session_date,))
    with pytest.raises(ValueError):
        policy(replace(value, config_hash="f" * 64), capital_candidates()[0])


def test_split_dividend_preparation_matches_every_public_opening_policy():
    from trading_bot.market_data.etf_capital_actions import CapitalDistribution, CapitalSplit

    source = long_source(230)
    dates = tuple(row.session_date for row in source.calendar.sessions)
    source = replace(
        source,
        actions=tuple(
            replace(
                actions,
                splits=(CapitalSplit(dates[199], D(3), "c" * 64),),
                distributions=(
                    CapitalDistribution(dates[225], dates[226], dates[229], D(1), "d" * 64),
                ),
            )
            for actions in source.actions
        ),
    )
    value = prepare(source, (dates[199], dates[-1]))
    original = capital_dataset_features(source, as_of_session=dates[-1])
    for candidate in capital_candidates():
        opening = CapitalOpeningPolicy(candidate, "SPY", dates[-2], D("2.5"))
        expected = capital_daily_policy(
            loaded=capital_loaded(), candidate=candidate, projections=original,
            as_of=value.days[-1].as_of, opening=opening,
        )
        assert policy(value, candidate, opening=opening) == expected


def test_sma_boundary_uses_public_64_digit_half_even_not_account_context():
    source = long_source(200, flat=True)
    archives = []
    for archive in source.archives:
        page = archive.pages[0]
        records = tuple(
            replace(
                record,
                bar=replace(
                    record.bar,
                    open=D("0." + "9" * 64) if index == 0 else D(1),
                    high=D(1), low=D(".9"),
                    close=D("0." + "9" * 64) if index == 0 else D(1),
                    vwap=D(1),
                ),
            )
            for index, record in enumerate(page.records)
        )
        archives.append(replace(archive, pages=(replace(page, records=records),)))
    source = replace(source, archives=tuple(archives))
    dates = tuple(row.session_date for row in source.calendar.sessions)
    value = prepare(source, (dates[-1],))
    # Under the frozen64-digit sum, mean rounds to1; under2048 it is<1.
    assert dict(value.days[0].below_sma200)["SPY"] is True


def test_zero_atr_does_not_admit_prepared_entry():
    from trading_bot.research.etf_capital_daily_policy import _capital_policy_from_facts

    source = long_source(200)
    value = prepare(source, (source.calendar.sessions[-1].session_date,))
    candidate = capital_candidates()[0]
    signal = value.days[0].signals[0]
    result = _capital_policy_from_facts(
        loaded=capital_loaded(), candidate=candidate, signal=signal, opening=None,
        elapsed=0, history_ready=True, below_sma200=False, entry_distance=D(0),
    )
    assert (result.action, result.reason, result.stop_distance) == ("wait", "zero_atr", None)


def test_prepared_policy_is_independent_of_ambient_decimal_precision():
    source = long_source(200)
    value = prepare(source, (source.calendar.sessions[-1].session_date,))
    candidate = capital_candidates()[0]
    expected = policy(value, candidate)
    assert (expected.action, expected.stop_distance) == ("entry", D(8))
    with localcontext() as context:
        context.prec = 3
        assert policy(value, candidate) == expected


@pytest.mark.parametrize("index", (-2, True, 1, "0"))
def test_invalid_prepared_day_index_denies(index):
    source = long_source(2)
    value = prepare(source, (source.calendar.sessions[-1].session_date,))
    with pytest.raises(ValueError):
        policy(value, capital_candidates()[0], index=index)
