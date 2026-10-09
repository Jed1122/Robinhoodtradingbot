"""Literal prior-close policy controls; no authenticated market evidence."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from decimal import localcontext

import pytest

from tests.unit.research.test_etf_capital_feasibility import loaded
from tests.unit.research.test_etf_capital_signals import projections
from trading_bot.research.etf_capital_signals import CapitalCandidate


def decide(*, records=None, candidate=None, opening=None, **changes):
    from trading_bot.research.etf_capital_daily_policy import capital_daily_policy

    records = records or projections(tuple(D(100 + i) for i in range(200)))
    return capital_daily_policy(
        loaded=loaded(),
        candidate=candidate or CapitalCandidate("momentum", 20, 100, 20),
        projections=records,
        as_of=records[0].raw_bars[-1].ends_at,
        opening=opening,
        **changes,
    )


def held(*, symbol="IEF", hold=20, days=0, **changes):
    from trading_bot.research.etf_capital_daily_policy import CapitalOpeningPolicy

    records = projections(tuple(D(100 + i) for i in range(200)))
    return CapitalOpeningPolicy(
        CapitalCandidate("momentum", 20, 100, hold),
        symbol,
        records[0].as_of_session - timedelta(days=days),
        changes.get("stop_distance", D("4")),
    )


def test_entry_uses_complete_signal_and_literal_100_bar_atr():
    value = decide()
    assert (value.action, value.symbol, value.stop_distance) == ("entry", "IEF", D("4"))
    assert not value.execution_enabled and not value.economic_admitted


def test_feature_atr_converts_to_raw_units_without_recounting_splits():
    records = projections(tuple(D(100 + i) for i in range(200)))
    changed = tuple(
        replace(
            p,
            raw_bars=tuple(
                replace(b, open=b.open * 2, high=b.high * 2, low=b.low * 2, close=b.close * 2)
                for b in p.raw_bars
            ),
        )
        for p in records
    )
    assert decide(records=changed).stop_distance == D("8")


@pytest.mark.parametrize("hold", [2, 5, 10, 20])
def test_maximum_hold_counts_entry_session_once(hold):
    before = decide(opening=held(hold=hold, days=hold - 2))
    boundary = decide(opening=held(hold=hold, days=hold - 1))
    assert before.action == "hold"
    assert (boundary.action, boundary.reason) == ("exit", "maximum_hold")


def test_new_fold_candidate_cannot_replace_opening_holding_policy():
    value = decide(
        candidate=CapitalCandidate("mean_reversion", 5, 0, 2),
        opening=held(hold=20, days=2),
    )
    assert value.action == "hold"
    assert value.candidate == CapitalCandidate("momentum", 20, 100, 20)
    assert value.stop_distance == D("4")


def test_momentum_regime_invalidation_schedules_exit_not_reversal():
    records = projections(tuple([D(100 + i) for i in range(199)] + [D("100")]))
    assert decide(records=records, opening=held()).reason == "regime_exit"


def test_mean_reversion_exit_uses_rsi_and_never_new_entry_signal():
    opening = replace(held(), candidate=CapitalCandidate("mean_reversion", 5, 0, 20))
    value = decide(opening=opening)
    assert (value.action, value.reason) == ("exit", "regime_exit")


def test_rotation_exit_when_original_candidate_winner_changes():
    opening = replace(held(symbol="SPY"), candidate=CapitalCandidate("rotation", 20, 0, 20))
    assert decide(opening=opening).action == "exit"


def test_future_opening_and_unknown_symbol_deny():
    with pytest.raises(ValueError):
        decide(opening=replace(held(), entry_session=held().entry_session + timedelta(days=1)))
    with pytest.raises(ValueError):
        decide(opening=held(symbol="BAD"))


def test_missing_warmup_does_not_invent_entry_or_regime_exit():
    value = decide(records=projections(tuple(D(100 + i) for i in range(199))))
    assert (value.action, value.reason) == ("wait", "insufficient_history")


def test_ambient_decimal_precision_does_not_change_policy():
    expected = decide()
    with localcontext() as ctx:
        ctx.prec = 3
        assert decide() == expected


@pytest.mark.parametrize("changes", [{"candidate": object()}, {"opening": object()}])
def test_untyped_policy_inputs_cannot_create_instructions(changes):
    with pytest.raises(ValueError):
        decide(**changes)


def test_flat_complete_history_does_not_create_entry():
    value = decide(records=projections((D("100"),) * 200))
    assert (value.action, value.reason, value.symbol) == ("wait", "no_entry_signal", None)


def test_zero_recent_atr_denies_an_otherwise_admissible_rsi_signal():
    values = (D("10"),) * 89 + tuple(D(200 - i * 10) for i in range(10)) + (D("100"),) * 101
    records = projections(values)
    records = tuple(
        replace(
            p,
            raw_bars=tuple(replace(b, open=b.close, high=b.close, low=b.close) for b in p.raw_bars),
            feature_bars=tuple(
                replace(b, open=b.close, high=b.close, low=b.close) for b in p.feature_bars
            ),
        )
        for p in records
    )
    value = decide(records=records, candidate=CapitalCandidate("mean_reversion", 5, 0, 20))
    assert (value.action, value.reason, value.stop_distance) == ("wait", "zero_atr", None)
