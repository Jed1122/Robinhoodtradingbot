"""Shared loss budgets cannot be refilled by profits or unconfirmed finality."""

from dataclasses import replace
from decimal import Decimal as D

import pytest

from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.risk.trial_losses import TrialEpisode, TrialLossState


def episode(name: str, pnl: str | None, *, final: bool = True) -> TrialEpisode:
    return TrialEpisode(name, D("20"), None if pnl is None else D(pnl), final, final, final)


def test_profits_do_not_refill_consumed_loss() -> None:
    episodes = (
        episode("loss", "-20"),
        episode("profit", "100"),
        episode("pending", "2", final=False),
    )
    book = TrialLossState(episodes)
    assert book.consumed_loss == D("20")
    assert book.reserved_risk == D("20")
    assert book.remaining(D("50")) == D("10")
    assert TrialLossState(tuple(episodes)) == book
    assert TrialLossState((episode("exhausted", "-60"),)).remaining(D("50")) == 0


@pytest.mark.parametrize("flag", ["flat", "orders_terminal", "settlement_and_fees_final"])
def test_each_missing_finality_flag_keeps_the_entire_reservation(flag: str) -> None:
    pending = replace(episode("pending", "-10"), **{flag: False})
    book = TrialLossState((pending,))
    assert not pending.complete
    assert book.consumed_loss == 0
    assert book.reserved_risk == D("20")
    assert book.remaining(D("50")) == D("30")


def test_pending_cash_flow_can_be_unknown_but_completed_cash_flow_cannot() -> None:
    pending = episode("pending", None, final=False)
    assert TrialLossState((pending,)).reserved_risk == D("20")
    with pytest.raises(DomainValidationError):
        episode("complete", None)


@pytest.mark.parametrize("history", [[], (object(),)])
def test_invalid_history_fails_closed(history: object) -> None:
    with pytest.raises(DomainValidationError):
        TrialLossState(history)


def test_duplicate_episode_identity_fails_closed() -> None:
    with pytest.raises(DomainValidationError):
        TrialLossState((episode("same", "-10"), episode("same", "30")))


@pytest.mark.parametrize(
    "changes",
    [{"episode_id": ""}, {"reserved_risk": D("-1")}, {"net_cash_flow": D("NaN")}, {"flat": "yes"}],
)
def test_invalid_episode_fails_closed(changes: dict[str, object]) -> None:
    with pytest.raises(DomainValidationError):
        replace(episode("valid", "1"), **changes)


@pytest.mark.parametrize("ceiling", [D("-1"), D("NaN"), D("Infinity")])
def test_invalid_ceiling_fails_closed(ceiling: D) -> None:
    with pytest.raises(DomainValidationError):
        TrialLossState(()).remaining(ceiling)


def test_legacy_imports_are_identical_aliases() -> None:
    from trading_bot.risk.options_economics import (
        TrialEpisode as LegacyEpisode,
    )
    from trading_bot.risk.options_economics import (
        TrialLossState as LegacyState,
    )

    assert LegacyEpisode is TrialEpisode
    assert LegacyState is TrialLossState
    assert LegacyState((episode("same", "-1"),)).consumed_loss == D("1")
