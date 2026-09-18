"""Independent Decimal expectations; feasibility is not production admission."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.risk.options_economics import (
    OptionsCapitalState,
    TrialEpisode,
    TrialLossState,
    long_option_feasibility,
)

D = Decimal
CONFIGS = Path(__file__).parents[3] / "configs"


def config():
    return load_config(
        CONFIGS / "base.yaml",
        CONFIGS / "options/simulation.yaml",
        CONFIGS / "safety-envelope.yaml",
        {},
    )


def state(capital: str = "100") -> OptionsCapitalState:
    return OptionsCapitalState(D(capital), D(capital), D(capital), D("0"), D("0"), 0, 0)


def test_one_hundred_dollars_does_not_round_half_dollar_risk_up_to_a_contract() -> None:
    result = long_option_feasibility(
        config(),
        state(),
        premium=D("0.25"),
        multiplier=D("100"),
        fee_reserve_per_unit=D("1"),
        trial=TrialLossState(()),
    )
    assert result.per_trade_budget == D("0.50")
    assert result.unit_payoff_risk == D("26")
    assert result.admissible_units == 0
    assert not result.production_eligible
    assert "per_trade_risk" in result.reason_codes


def test_hypothetical_tier_is_feasible_without_relaxing_legacy_notional_cap() -> None:
    result = long_option_feasibility(
        config(),
        state("2500"),
        premium=D("0.10"),
        multiplier=D("100"),
        fee_reserve_per_unit=D("1"),
        trial=TrialLossState(()),
    )
    assert result.admissible_units == 1
    assert result.unit_payoff_risk == D("11")
    assert result.cash_after_reserve == D("2489")
    assert not result.production_eligible
    expensive = long_option_feasibility(
        config(),
        state("50000"),
        premium=D("0.25"),
        multiplier=D("100"),
        fee_reserve_per_unit=D("1"),
        trial=TrialLossState(()),
    )
    assert expensive.admissible_units == 0
    assert "legacy_order_notional" in expensive.reason_codes


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"cash": D("2000")}, "cash_reserve"),
        ({"buying_power": D("10")}, "buying_power"),
        ({"portfolio_risk": D("124")}, "portfolio_payoff_risk"),
        ({"group_risk": D("49"), "portfolio_risk": D("49")}, "underlying_group_risk"),
        ({"open_positions": 1}, "position_count"),
        ({"new_positions_this_session": 1}, "session_activity"),
    ],
)
def test_each_independent_budget_can_deny(change: dict[str, object], reason: str) -> None:
    result = long_option_feasibility(
        config(),
        replace(state("2500"), **change),
        premium=D("0.10"),
        multiplier=D("100"),
        fee_reserve_per_unit=D("1"),
        trial=TrialLossState(()),
    )
    assert result.admissible_units == 0
    assert reason in result.reason_codes


def episode(name: str, pnl: str | None, *, final: bool = True) -> TrialEpisode:
    return TrialEpisode(name, D("20"), None if pnl is None else D(pnl), final, final, final)


def test_profits_do_not_replenish_and_pending_or_unsettled_episodes_keep_reservation() -> None:
    episodes = (
        episode("loss", "-20"),
        episode("profit", "100"),
        episode("pending", "2", final=False),
    )
    restored = TrialLossState(episodes)
    assert restored.consumed_loss == D("20")
    assert restored.reserved_risk == D("20")
    assert restored.remaining(D("50")) == D("10")
    assert TrialLossState(tuple(episodes)) == restored
    result = long_option_feasibility(
        config(),
        state("2500"),
        premium=D("0.10"),
        multiplier=D("100"),
        fee_reserve_per_unit=D("1"),
        trial=restored,
    )
    assert result.admissible_units == 0
    assert "trial_budget" in result.reason_codes


def test_loss_capacity_is_nonnegative_and_duplicate_episodes_fail_closed() -> None:
    book = TrialLossState((episode("a", "-60"),))
    assert book.remaining(D("50")) == 0
    with pytest.raises(DomainValidationError):
        TrialLossState((episode("a", "-10"), episode("a", "-10")))
    with pytest.raises(DomainValidationError):
        episode("a", None)
    with pytest.raises(DomainValidationError):
        replace(state(), cash=D("NaN"))


def test_incomplete_episode_and_invalid_trial_history_fail_closed() -> None:
    pending = episode("pending", None, final=False)
    assert not pending.complete
    assert TrialLossState((pending,)).reserved_risk == D("20")
    for episodes in ([], (object(),)):
        with pytest.raises(DomainValidationError):
            TrialLossState(episodes)
    with pytest.raises(DomainValidationError):
        replace(state(), group_risk=D("1"))
    with pytest.raises(DomainValidationError):
        replace(pending, flat="yes")


def test_feasibility_requires_real_validated_records_and_enabled_offline_profile() -> None:
    arguments = dict(
        premium=D("0.1"), multiplier=D("100"), fee_reserve_per_unit=D("1"), trial=TrialLossState(())
    )
    with pytest.raises(DomainValidationError):
        long_option_feasibility(object(), state(), **arguments)
    with pytest.raises(DomainValidationError):
        long_option_feasibility(config(), object(), **arguments)
    with pytest.raises(DomainValidationError):
        long_option_feasibility(config(), state(), **{**arguments, "trial": object()})
    disabled = load_config(
        CONFIGS / "base.yaml", CONFIGS / "simulation.yaml", CONFIGS / "safety-envelope.yaml", {}
    )
    with pytest.raises(DomainValidationError):
        long_option_feasibility(disabled, state(), **arguments)


def test_zero_configured_unit_cap_denies_even_when_capital_suffices() -> None:
    loaded = load_config(
        CONFIGS / "base.yaml",
        CONFIGS / "options/simulation.yaml",
        CONFIGS / "safety-envelope.yaml",
        {"TRADING_BOT__OPTIONS__MAX_STRUCTURE_UNITS_PER_ENTRY": "0"},
    )
    result = long_option_feasibility(
        loaded,
        state("2500"),
        premium=D("0.1"),
        multiplier=D("100"),
        fee_reserve_per_unit=D("1"),
        trial=TrialLossState(()),
    )
    assert result.admissible_units == 0
    assert "structure_unit_limit" in result.reason_codes
