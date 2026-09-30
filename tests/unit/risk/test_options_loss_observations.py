"""Native event ordering cannot erase a transient loss inside one microsecond."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tests.unit.risk.test_options_loss_history import CLOSE, OPEN, config, next_session, point
from trading_bot.risk import options_loss_history as api


def ns(stamp):
    delta = stamp - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 10**9 + delta.microseconds * 1000


def observation(p, *, nanos=None, ordinal=0):
    return api.OptionsLossObservation(p, ns(p.observed_at) if nanos is None else nanos, ordinal)


def evaluate(*observations, as_of=None):
    return api.evaluate_options_loss_observations(
        config(),
        observations,
        as_of_ns=observations[-1].available_ns if as_of is None else as_of,
    )


@pytest.mark.parametrize("same_nanosecond", [False, True])
def test_transient_loss_latches_before_recovery_in_same_microsecond(same_nanosecond):
    loss = point("loss", "89", at=OPEN + timedelta(microseconds=1))
    recovery = replace(loss, event_id="recovery", liquidation_equity=Decimal("100"))
    result = evaluate(
        observation(point()),
        observation(loss, nanos=ns(OPEN) + 1),
        observation(recovery, nanos=ns(OPEN) + (1 if same_nanosecond else 2), ordinal=1),
    )
    assert result.flow_adjusted_equity == Decimal("100")
    assert result.daily_loss_usd == result.weekly_loss_usd == result.drawdown_loss_usd == 0
    assert result.daily_halt and result.weekly_halt and result.drawdown_halt
    assert not result.production_eligible and not result.economic_evidence


def test_exact_duplicate_is_idempotent_but_order_key_substitution_fails():
    initial = observation(point())
    loss = observation(point("loss", "94", at=OPEN + timedelta(microseconds=1)), nanos=ns(OPEN) + 1)
    assert evaluate(initial, loss, loss) == evaluate(initial, loss)
    for changed in (replace(loss, available_ns=ns(OPEN) + 2), replace(loss, ordinal=1)):
        with pytest.raises(ValueError, match="conflicting duplicate"):
            evaluate(initial, loss, changed)


def test_rounded_close_is_not_verified_close_and_cannot_reset_daily_halt():
    close = point("close", "94", at=CLOSE)
    result = evaluate(
        observation(point()),
        observation(close, nanos=ns(CLOSE) - 1),
        observation(next_session(close, "100")),
    )
    assert result.daily_halt and result.weekly_halt
    assert "risk_history_incomplete" in result.entry_reasons
    assert result.daily_loss_usd is None


def test_exact_close_can_rebase_daily_but_never_clear_weekly_latch():
    close = point("close", "94", at=CLOSE)
    result = evaluate(
        observation(point()), observation(close), observation(next_session(close, "94"))
    )
    assert not result.daily_halt and result.weekly_halt
    assert result.entry_reasons == ("weekly_loss_latched",)


def test_freshness_uses_exact_ns_and_future_evidence_is_denied():
    initial = observation(point())
    at = ns(OPEN) + config().config.freshness.max_account_snapshot_age_seconds * 10**9
    assert "risk_observation_stale" not in evaluate(initial, as_of=int(at)).entry_reasons
    assert "risk_observation_stale" in evaluate(initial, as_of=int(at) + 1).entry_reasons
    with pytest.raises(ValueError, match="precedes"):
        evaluate(initial, as_of=initial.available_ns - 1)


@pytest.mark.parametrize(
    "change",
    [
        {"available_ns": True},
        {"available_ns": -1},
        {"available_ns": 2**64},
        {"ordinal": True},
        {"ordinal": -1},
        {"ordinal": 2**64},
        {"available_ns": ns(OPEN) + 1},
        {"point": object()},
    ],
)
def test_invalid_observation_is_rejected(change):
    with pytest.raises(ValueError):
        replace(observation(point()), **change)


def test_clock_must_advance_and_genesis_is_exact():
    initial = observation(point())
    with pytest.raises(ValueError, match="clock"):
        evaluate(initial, observation(point("second")))
    with pytest.raises(ValueError):
        evaluate(observation(point(at=OPEN + timedelta(microseconds=1)), nanos=ns(OPEN) + 1))
    with pytest.raises(ValueError):
        evaluate(initial, as_of=True)


def test_deposit_cannot_clear_exact_time_loss_latches():
    p = point("loss", "89", at=OPEN + timedelta(microseconds=1))
    deposit = replace(
        p,
        event_id="deposit",
        liquidation_equity=Decimal("1089"),
        cumulative_external_flows=Decimal("1000"),
    )
    result = evaluate(
        observation(point()),
        observation(p, nanos=ns(OPEN) + 1),
        observation(deposit, nanos=ns(OPEN) + 1, ordinal=1),
    )
    assert result.flow_adjusted_equity == Decimal("89")
    assert result.reference_equity == Decimal("100")
    assert result.daily_halt and result.weekly_halt and result.drawdown_halt
