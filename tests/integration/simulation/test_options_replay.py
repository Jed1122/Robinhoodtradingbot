"""Synthetic-only vertical slice with independently calculated cash flows."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.domain.enums import OrderState
from trading_bot.domain.options import OptionKind
from trading_bot.simulation.options_fixtures import synthetic_options_request
from trading_bot.simulation.options_replay import replay_options
from trading_bot.simulation.options_replay_models import OptionsReplayEvent

D = Decimal
CONFIGS = Path(__file__).parents[3] / "configs"


def request(scenario: str = "completed", capital: str = "2500"):
    loaded = load_config(
        CONFIGS / "base.yaml",
        CONFIGS / "options/simulation.yaml",
        CONFIGS / "safety-envelope.yaml",
        {},
    )
    return synthetic_options_request(loaded, D(capital), scenario)


def test_complete_lifecycle_cash_and_fees_are_exact_and_deterministic() -> None:
    result = replay_options(request())
    assert result == replay_options(request())
    assert result.status == "completed_synthetic_replay"
    assert result.cash == D("2504")  # -10 premium -0.50 fee +15 sale -0.50 fee
    assert result.net_cash_flow == D("4")
    assert result.fees == D("1")
    assert result.position_units == 0
    assert result.trial.reserved_risk == 0
    assert result.trial.consumed_loss == 0
    assert result.entry_state is OrderState.FILLED
    assert result.close_state is OrderState.FILLED
    assert not result.evidence_promotable
    assert not result.production_eligible
    assert result.economic_verdict == "ECONOMIC_NO_GO"


def test_small_capital_denial_is_a_valid_no_trade_outcome() -> None:
    result = replay_options(request(capital="100"))
    assert result.status == "capital_denied"
    assert result.entry_state is OrderState.RISK_REJECTED
    assert result.cash == D("100")
    assert not result.cash_flows
    assert "per_trade_risk" in result.reason_codes


@pytest.mark.parametrize(
    ("scenario", "cash", "units", "state"),
    [
        ("unfilled", "2500", 0, OrderState.SUBMITTED),
        ("unknown", "2500", 0, OrderState.UNKNOWN_REQUIRES_RECONCILIATION),
        ("open", "2489.5", 1, OrderState.FILLED),
        ("unsettled", "2489.5", 0, OrderState.FILLED),
        ("cancel_race", "2489.5", 1, OrderState.FILLED),
    ],
)
def test_incomplete_outcomes_never_force_an_exit_or_release_trial_risk(
    scenario: str,
    cash: str,
    units: int,
    state: OrderState,
) -> None:
    result = replay_options(request(scenario))
    assert result.status == "incomplete_synthetic_replay"
    assert result.cash == D(cash)
    assert result.position_units == units
    assert result.entry_state is state
    assert result.trial.reserved_risk == D("11")


@pytest.mark.parametrize("scenario", ["rejected", "canceled"])
def test_confirmed_unfilled_terminal_orders_release_reserves_without_fictional_fills(
    scenario: str,
) -> None:
    result = replay_options(request(scenario))
    assert result.status == "completed_synthetic_replay"
    assert result.cash == D("2500")
    assert result.position_units == 0
    assert result.trial.reserved_risk == 0
    assert not result.cash_flows


def test_input_ends_after_entry_does_not_generate_a_perfect_exit() -> None:
    original = request()
    result = replay_options(replace(original, events=original.events[:2]))
    assert result.position_units == 1
    assert result.close_state is None
    assert result.status == "incomplete_synthetic_replay"


def test_same_event_fill_future_history_and_real_origin_are_rejected() -> None:
    original = request()
    with pytest.raises(DomainValidationError):
        replace(original, source_kind="historical")
    with pytest.raises((DomainValidationError, RuntimeError)):
        replay_options(replace(original, as_of=original.history.bars[-1].starts_at))
    with pytest.raises(DomainValidationError):
        replace(original, events=(replace(original.events[1], at=original.as_of),))


def test_losing_cash_flows_consume_nonreplenishing_trial_capacity() -> None:
    result = replay_options(request("loss"))
    assert result.net_cash_flow == D("-6")  # -10.50 +4.50
    assert result.cash == D("2494")
    assert result.trial.consumed_loss == D("6")
    assert result.trial.remaining(D("50")) == D("44")


def test_invalid_request_identity_config_history_and_option_kind_are_rejected() -> None:
    r = request()
    with pytest.raises(DomainValidationError):
        replay_options(object())
    with pytest.raises(DomainValidationError):
        replay_options(replace(r, loaded=replace(r.loaded, config_hash="0" * 64)))
    with pytest.raises(DomainValidationError):
        replay_options(replace(r, contract=replace(r.contract, kind=OptionKind.PUT)))
    with pytest.raises(DomainValidationError):
        replay_options(replace(r, history=replace(r.history, bars=r.history.bars[:1])))
    for field in ("loaded", "history", "contract", "initial_quote", "trial"):
        with pytest.raises(DomainValidationError):
            replace(r, **{field: object()})
    with pytest.raises(DomainValidationError):
        replace(r, history=replace(r.history, instrument_id="OTHER"))


def test_event_shapes_idempotency_and_synthetic_provenance_fail_closed() -> None:
    r = request()
    market = r.events[1]
    for change in (
        {"action": "invalid"},
        {"quote": None},
        {"action": "settle"},
        {"quote": replace(market.quote, source="real-data")},
        {"quote": replace(market.quote, received_at=market.at + timedelta(seconds=1))},
    ):
        with pytest.raises(DomainValidationError):
            replace(market, **change)
    with pytest.raises(DomainValidationError):
        replace(r, events=(r.events[0], replace(market, event_id=r.events[0].event_id)))


def test_missing_signal_and_stale_market_event_cannot_create_a_fill() -> None:
    r = request()
    flat_bars = tuple(
        replace(bar, open=D("100"), high=D("101"), low=D("99"), close=D("100"))
        for bar in r.history.bars
    )
    held = replay_options(replace(r, history=replace(r.history, bars=flat_bars)))
    assert "no_momentum_candidate" in held.reason_codes
    market = r.events[1]
    invalid_quote = replace(market.quote, quality_flags=("delayed",))
    result = replay_options(replace(r, events=(r.events[0], replace(market, quote=invalid_quote))))
    assert result.position_units == 0
    assert result.status == "incomplete_synthetic_replay"


def test_close_or_settlement_without_reconciled_position_is_rejected() -> None:
    r = request()
    for action in ("request_close", "settle"):
        event = OptionsReplayEvent("synthetic-invalid", r.as_of + timedelta(seconds=1), action)
        with pytest.raises(DomainValidationError):
            replay_options(replace(r, events=(event,)))


@pytest.mark.parametrize("quote_second", [0, 1])
def test_rewrapped_pre_acceptance_quote_does_not_fill_entry(quote_second: int) -> None:
    r = request()
    observed = r.as_of + timedelta(seconds=quote_second)
    quote = replace(
        r.initial_quote,
        event_at=observed,
        received_at=observed,
        underlying_event_at=observed,
    )
    result = replay_options(replace(r, events=(r.events[0], replace(r.events[1], quote=quote))))
    assert result.position_units == 0
    assert not result.cash_flows
    assert result.status == "incomplete_synthetic_replay"
    assert result.trial.reserved_risk == D("11")


def test_rewrapped_close_decision_quote_does_not_fill_close() -> None:
    r = request()
    observed = r.events[2].at
    quote = replace(
        r.events[3].quote,
        event_at=observed,
        received_at=observed,
        underlying_event_at=observed,
    )
    result = replay_options(replace(r, events=(*r.events[:3], replace(r.events[3], quote=quote))))
    assert result.position_units == 1
    assert result.close_state is OrderState.SUBMITTED
    assert len(result.cash_flows) == 1
    assert result.trial.reserved_risk == D("11")


def test_close_has_its_own_lifetime_after_entry_order_deadline() -> None:
    r = request()
    delay = timedelta(seconds=r.loaded.config.runtime.remainder_order_max_age_seconds)
    delayed = []
    for event in r.events[2:]:
        quote = event.quote
        if quote is not None:
            quote = replace(
                quote,
                event_at=quote.event_at + delay,
                received_at=quote.received_at + delay,
                underlying_event_at=quote.underlying_event_at + delay,
            )
        delayed.append(replace(event, at=event.at + delay, quote=quote))
    result = replay_options(replace(r, events=(*r.events[:2], *delayed)))
    assert result.status == "completed_synthetic_replay"
    assert result.cash == D("2504")
    assert result.trial.reserved_risk == 0


@pytest.mark.parametrize("settled", [False, True])
def test_zero_net_close_still_requires_explicit_settlement(settled: bool) -> None:
    r = request()
    closing = replace(r.events[3], quote=replace(r.events[3].quote, bid=D("0.01"), ask=D("0.02")))
    events = (*r.events[:3], closing, *r.events[4:]) if settled else (*r.events[:3], closing)
    result = replay_options(replace(r, exit_fee=D("1"), close_limit=D("0.01"), events=events))
    assert result.position_units == 0
    assert result.unsettled_receivable == 0
    assert result.cash_flows[-1].amount == 0
    assert result.cash == D("2489.5")
    assert result.trial.episodes[-1].settlement_and_fees_final is settled
    assert result.trial.reserved_risk == (D(0) if settled else D("11.5"))
    assert result.status == (
        "completed_synthetic_replay" if settled else "incomplete_synthetic_replay"
    )


def test_close_creation_outside_eligible_session_is_rejected() -> None:
    r = request()
    closing = replace(r.events[2], at=r.contract.eligible_sessions[0].closes_at)
    with pytest.raises(DomainValidationError, match="eligible option session"):
        replay_options(replace(r, events=(*r.events[:2], closing)))
