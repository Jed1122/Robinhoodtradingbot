from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from trading_bot.domain import Bar, BarInterval, ConfigHash, DataHash, InstrumentId
from trading_bot.market_data.etf_capital_actions import CapitalDistribution
from trading_bot.market_data.etf_capital_features import CapitalFeatureProjection
from trading_bot.research.etf_capital_signals import (
    CapitalCandidate,
    capital_candidates,
    capital_strategy_signal,
    capital_walk_forward_folds,
)

SYMBOLS = ("SPY", "QQQ", "IWM", "SHY", "IEF")


def projections(values: tuple[Decimal, ...]) -> tuple[CapitalFeatureProjection, ...]:
    outputs = []
    for symbol in SYMBOLS:
        records = []
        for i, close in enumerate(values):
            end = datetime(2019, 1, 1, 21, tzinfo=UTC) + timedelta(days=i)
            records.append(
                Bar(
                    InstrumentId(symbol),
                    BarInterval.ONE_DAY,
                    end - timedelta(hours=6),
                    end,
                    close,
                    close + 1,
                    close - 1,
                    close,
                    Decimal(1000),
                    "alpaca-supplied-daily-session-assumption-v1",
                    DataHash("a" * 64),
                )
            )
        raw = tuple(records)
        feature = tuple(replace(row, source="capital-split-feature-assumption-v2") for row in raw)
        outputs.append(
            CapitalFeatureProjection(
                "a" * 64, "b" * 64, "c" * 64, raw[-1].ends_at.date(), raw, feature, ()
            )
        )
    return tuple(outputs)


def signal(candidate: CapitalCandidate, values: tuple[Decimal, ...]):
    records = projections(values)
    return capital_strategy_signal(
        candidate, records, config_hash=ConfigHash("d" * 64), as_of=records[0].raw_bars[-1].ends_at
    )


def test_grid_is_exact_unique_and_not_mutable() -> None:
    result = capital_candidates()
    assert len(result) == len(set(result)) == 28
    assert [
        sum(c.family == family for c in result)
        for family in ("momentum", "mean_reversion", "rotation")
    ] == [12, 8, 8]
    assert {c.hold_sessions for c in result} == {2, 5, 10, 20}


@pytest.mark.parametrize(
    "args",
    [
        ("momentum", 5, 50, 2),
        ("rotation", 30, 0, 2),
        ("mean_reversion", 5, 0, True),
        ("unknown", 5, 20, 2),
    ],
)
def test_invalid_grid_denies(args) -> None:
    with pytest.raises(ValueError):
        CapitalCandidate(*args)


def test_full_momentum_and_deterministic_tie() -> None:
    result = signal(
        CapitalCandidate("momentum", 20, 100, 5), tuple(Decimal(100 + i) for i in range(750))
    )
    assert result.entry_symbol == "IEF"
    assert result.eligible_symbols == tuple(sorted(SYMBOLS))
    assert result.source_qualified is result.execution_enabled is result.promotion_eligible is False
    assert result.economic_accepted is False


def test_negative_momentum_and_short_warmup_have_no_candidate() -> None:
    candidate = CapitalCandidate("momentum", 5, 20, 2)
    assert signal(candidate, tuple(Decimal(1000 - i) for i in range(750))).entry_symbol is None
    assert signal(candidate, (Decimal(100),) * 199).entry_symbol is None


def test_feature_warmup_does_not_consume_entire_750_session_training_fold() -> None:
    result = signal(
        CapitalCandidate("momentum", 5, 20, 2), tuple(Decimal(100 + i) for i in range(200))
    )
    assert result.entry_symbol == "IEF"


def test_different_historical_session_grids_deny() -> None:
    records = projections((Decimal(100),) * 750)
    spy = records[0]
    raw = (*spy.raw_bars[:50], *spy.raw_bars[51:])
    features = (*spy.feature_bars[:50], *spy.feature_bars[51:])
    with pytest.raises(ValueError):
        capital_strategy_signal(
            CapitalCandidate("rotation", 20, 0, 2),
            (replace(spy, raw_bars=raw, feature_bars=features), *records[1:]),
            config_hash=ConfigHash("d" * 64),
            as_of=raw[-1].ends_at,
        )


def test_rsi_seed_flat_and_oversold_above_sma200() -> None:
    candidate = CapitalCandidate("mean_reversion", 5, 0, 2)
    assert signal(candidate, (Decimal(100),) * 750).entry_symbol is None
    prices = tuple(Decimal(100 + i) for i in range(740)) + tuple(
        Decimal(839 - i) for i in range(1, 11)
    )
    result = signal(candidate, prices)
    assert result.entry_symbol == "IEF"
    assert result.exit_symbols == ()
    rising = signal(candidate, tuple(Decimal(100 + i) for i in range(750)))
    assert rising.entry_symbol is None
    assert rising.exit_symbols == tuple(sorted(SYMBOLS))


def test_rotation_zero_vol_denies_and_precision_is_owned() -> None:
    candidate = CapitalCandidate("rotation", 20, 0, 10)
    assert signal(candidate, (Decimal(100),) * 750).entry_symbol is None
    prices = tuple(Decimal(100 + i + i % 3) for i in range(750))
    expected = signal(candidate, prices)
    with localcontext() as context:
        context.prec = 3
        assert signal(candidate, prices) == expected
    assert expected.entry_symbol == "IEF"


def test_missing_symbol_or_future_bar_denies() -> None:
    records = projections((Decimal(100),) * 750)
    candidate = CapitalCandidate("rotation", 20, 0, 2)
    with pytest.raises(ValueError):
        capital_strategy_signal(
            candidate,
            records[:-1],
            config_hash=ConfigHash("d" * 64),
            as_of=records[0].raw_bars[-1].ends_at,
        )
    with pytest.raises(ValueError):
        capital_strategy_signal(
            candidate,
            records,
            config_hash=ConfigHash("d" * 64),
            as_of=records[0].raw_bars[-1].ends_at - timedelta(seconds=1),
        )


def test_close_scores_do_not_round_into_tie_under_callers_precision() -> None:
    records = projections(tuple(Decimal(100 + i) for i in range(750)))
    spy = records[0]
    raw = (*spy.raw_bars[:-1], replace(spy.raw_bars[-1], close=Decimal("849.00000001")))
    feature = (*spy.feature_bars[:-1], replace(spy.feature_bars[-1], close=Decimal("849.00000001")))
    inputs = (replace(spy, raw_bars=raw, feature_bars=feature), *records[1:])
    kwargs = dict(config_hash=ConfigHash("d" * 64), as_of=raw[-1].ends_at)
    candidate = CapitalCandidate("momentum", 20, 100, 5)
    expected = capital_strategy_signal(candidate, inputs, **kwargs)
    assert expected.entry_symbol == "SPY"
    with localcontext() as context:
        context.prec = 3
        assert capital_strategy_signal(candidate, inputs, **kwargs) == expected


def test_rotation_distribution_cash_is_once_and_not_reinvested() -> None:
    # Falling prices alone deny, but the explicit distribution makes total return positive.
    records = projections(tuple(Decimal(1000 - i) for i in range(750)))
    candidate = CapitalCandidate("rotation", 20, 0, 2)
    kwargs = dict(config_hash=ConfigHash("d" * 64), as_of=records[0].raw_bars[-1].ends_at)
    assert capital_strategy_signal(candidate, records, **kwargs).entry_symbol is None
    spy = records[0]
    day = spy.raw_bars[-1].ends_at.date()
    cash = CapitalDistribution(day, day, day, Decimal(21), "f" * 64)
    with_cash = (replace(spy, distributions=(cash,)), *records[1:])
    result = capital_strategy_signal(candidate, with_cash, **kwargs)
    assert result.entry_symbol == "SPY"
    assert result.eligible_symbols == ("SPY",)


def test_duplicate_distribution_cannot_manufacture_positive_rotation() -> None:
    records = projections(tuple(Decimal(1000 - i) for i in range(200)))
    spy = records[0]
    day = spy.raw_bars[-1].ends_at.date()
    cash = CapitalDistribution(day, day, day, Decimal(11), "f" * 64)
    candidate = CapitalCandidate("rotation", 20, 0, 2)
    kwargs = dict(config_hash=ConfigHash("d" * 64), as_of=spy.raw_bars[-1].ends_at)
    assert (
        capital_strategy_signal(
            candidate, (replace(spy, distributions=(cash,)), *records[1:]), **kwargs
        ).entry_symbol
        is None
    )
    with pytest.raises(ValueError):
        capital_strategy_signal(
            candidate, (replace(spy, distributions=(cash, cash)), *records[1:]), **kwargs
        )


@pytest.mark.parametrize("feature_only", [True, False])
def test_nondaily_feature_or_interpolated_original_denies(feature_only: bool) -> None:
    records = projections(tuple(Decimal(100 + i) for i in range(200)))
    spy = records[0]
    if feature_only:
        changed = replace(
            spy,
            feature_bars=tuple(
                replace(b, interval=BarInterval.ONE_MINUTE) for b in spy.feature_bars
            ),
        )
    else:
        changed = replace(
            spy,
            raw_bars=tuple(replace(b, interpolated=True) for b in spy.raw_bars),
            feature_bars=tuple(replace(b, interpolated=True) for b in spy.feature_bars),
        )
    with pytest.raises(ValueError):
        capital_strategy_signal(
            CapitalCandidate("momentum", 5, 20, 2),
            (changed, *records[1:]),
            config_hash=ConfigHash("d" * 64),
            as_of=spy.raw_bars[-1].ends_at,
        )


def test_calendar_only_fold_boundaries_purge_and_tail() -> None:
    sessions = tuple(date(2016, 1, 1) + timedelta(days=i) for i in range(1423))
    folds = capital_walk_forward_folds(sessions)
    assert len(folds) == 5
    assert folds[0].train_sessions == sessions[:750]
    assert folds[0].selection_sessions == sessions[:730]
    assert folds[0].embargo_sessions == sessions[750:770]
    assert folds[0].test_sessions == sessions[770:896]
    assert folds[-1].train_sessions == sessions[504:1254]
    assert folds[-1].test_sessions == sessions[1274:1400]
    assert folds[-1].exit_only_sessions == sessions[1400:1423]
    with pytest.raises(ValueError):
        capital_walk_forward_folds(sessions[:-1])
    with pytest.raises(ValueError):
        capital_walk_forward_folds((sessions[0], *sessions))
