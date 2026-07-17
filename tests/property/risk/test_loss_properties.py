"""Property tests for loss, drawdown, pause, and activity gates."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from trading_bot.config import ActivitySettings, LossLimitSettings
from trading_bot.domain import AccountId, InstrumentId, OrderPurpose
from trading_bot.risk import (
    ActivitySnapshot,
    LossSnapshot,
    evaluate_activity_limits,
    evaluate_loss_limits,
)

OBSERVED_AT = datetime(2026, 7, 15, 16, 0, tzinfo=UTC)
DAY_STARTED_AT = datetime(2026, 7, 15, 0, 0, tzinfo=UTC)
WEEK_STARTED_AT = datetime(2026, 7, 13, 0, 0, tzinfo=UTC)
PERCENT = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("100"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
LOSS_SETTINGS = LossLimitSettings(
    max_daily_loss_pct=Decimal("2"),
    max_weekly_loss_pct=Decimal("5"),
    max_peak_to_trough_drawdown_pct=Decimal("10"),
    consecutive_loss_pause_count=3,
    consecutive_loss_pause_minutes=240,
)
ACTIVITY_SETTINGS = ActivitySettings(
    max_new_orders_per_day=3,
    max_orders_per_symbol_per_day=1,
    minimum_minutes_between_new_orders=30,
    max_order_notional_usd=Decimal("15"),
)


def loss_snapshot(
    *,
    daily_loss_pct: Decimal = Decimal("0"),
    weekly_loss_pct: Decimal = Decimal("0"),
    peak_to_trough_drawdown_pct: Decimal = Decimal("0"),
    consecutive_loss_count: int = 0,
    last_loss_at: datetime | None = None,
    daily_reset_reconciled: bool = True,
    weekly_reset_reviewed: bool = True,
) -> LossSnapshot:
    return LossSnapshot(
        account_id=AccountId("property-account"),
        daily_loss_pct=daily_loss_pct,
        weekly_loss_pct=weekly_loss_pct,
        peak_to_trough_drawdown_pct=peak_to_trough_drawdown_pct,
        consecutive_loss_count=consecutive_loss_count,
        last_loss_at=last_loss_at,
        daily_window_started_at=DAY_STARTED_AT,
        weekly_window_started_at=WEEK_STARTED_AT,
        daily_reset_reconciled=daily_reset_reconciled,
        weekly_reset_reviewed=weekly_reset_reviewed,
        observed_at=OBSERVED_AT,
    )


def activity_snapshot(
    *,
    new_orders_today: int,
    new_orders_for_symbol_today: int,
    last_new_order_at: datetime,
) -> ActivitySnapshot:
    return ActivitySnapshot(
        account_id=AccountId("property-account"),
        instrument_id=InstrumentId("property-instrument"),
        new_orders_today=new_orders_today,
        new_orders_for_symbol_today=new_orders_for_symbol_today,
        last_new_order_at=last_new_order_at,
        daily_window_started_at=DAY_STARTED_AT,
        observed_at=OBSERVED_AT,
    )


@given(loss=st.decimals(min_value=Decimal("2"), max_value=Decimal("100"), places=2))
@settings(max_examples=300)
def test_daily_loss_at_or_above_limit_always_blocks_entries(loss: Decimal) -> None:
    decision = evaluate_loss_limits(
        snapshot=loss_snapshot(daily_loss_pct=loss),
        settings=LOSS_SETTINGS,
        purpose=OrderPurpose.ENTRY,
    )

    assert not decision.allowed
    assert decision.cancel_unfilled_entries
    assert decision.reason_code == "daily_loss_limit_reached"


@given(drawdown=st.decimals(min_value=Decimal("10"), max_value=Decimal("100"), places=2))
@settings(max_examples=300)
def test_drawdown_at_or_above_limit_always_requests_kill_switch(
    drawdown: Decimal,
) -> None:
    decision = evaluate_loss_limits(
        snapshot=loss_snapshot(peak_to_trough_drawdown_pct=drawdown),
        settings=LOSS_SETTINGS,
        purpose=OrderPurpose.ENTRY,
    )

    assert not decision.allowed
    assert decision.kill_switch_activation_requested
    assert decision.reason_code == "drawdown_limit_reached"


@given(
    daily=PERCENT,
    weekly=PERCENT,
    drawdown=PERCENT,
    count=st.integers(min_value=0, max_value=1000),
    minutes_since_loss=st.integers(min_value=0, max_value=10000),
    daily_reconciled=st.booleans(),
    weekly_reviewed=st.booleans(),
    purpose=st.sampled_from((OrderPurpose.STRATEGY_EXIT, OrderPurpose.PROTECTIVE_EXIT)),
)
@settings(deadline=None, max_examples=500)
def test_exit_purposes_follow_entry_block_versus_hard_stop_policy(
    daily: Decimal,
    weekly: Decimal,
    drawdown: Decimal,
    count: int,
    minutes_since_loss: int,
    daily_reconciled: bool,
    weekly_reviewed: bool,
    purpose: OrderPurpose,
) -> None:
    last_loss_at = None if count == 0 else OBSERVED_AT - timedelta(minutes=minutes_since_loss)
    decision = evaluate_loss_limits(
        snapshot=loss_snapshot(
            daily_loss_pct=daily,
            weekly_loss_pct=weekly,
            peak_to_trough_drawdown_pct=drawdown,
            consecutive_loss_count=count,
            last_loss_at=last_loss_at,
            daily_reset_reconciled=daily_reconciled,
            weekly_reset_reviewed=weekly_reviewed,
        ),
        settings=LOSS_SETTINGS,
        purpose=purpose,
    )

    hard_stop = (
        drawdown >= LOSS_SETTINGS.max_peak_to_trough_drawdown_pct
        or not daily_reconciled
        or not weekly_reviewed
    )
    assert decision.allowed is not hard_stop


@given(minutes_since_loss=st.integers(min_value=0, max_value=239))
def test_consecutive_loss_pause_is_active_before_exact_expiry(
    minutes_since_loss: int,
) -> None:
    last_loss_at = OBSERVED_AT - timedelta(minutes=minutes_since_loss)
    decision = evaluate_loss_limits(
        snapshot=loss_snapshot(
            consecutive_loss_count=3,
            last_loss_at=last_loss_at,
        ),
        settings=LOSS_SETTINGS,
        purpose=OrderPurpose.ENTRY,
    )

    assert not decision.allowed
    assert decision.entry_pause_until is not None


@given(count=st.integers(min_value=3, max_value=1000))
def test_daily_order_limit_always_blocks_at_or_above_three(count: int) -> None:
    result = evaluate_activity_limits(
        activity_snapshot(
            new_orders_today=count,
            new_orders_for_symbol_today=0,
            last_new_order_at=OBSERVED_AT - timedelta(minutes=60),
        ),
        settings=ACTIVITY_SETTINGS,
    )

    assert not result.allowed
    assert result.code == "daily_order_limit_reached"


@given(elapsed_microseconds=st.integers(min_value=0, max_value=1_799_999_999))
@settings(max_examples=300)
def test_minimum_order_interval_blocks_every_time_before_boundary(
    elapsed_microseconds: int,
) -> None:
    result = evaluate_activity_limits(
        activity_snapshot(
            new_orders_today=1,
            new_orders_for_symbol_today=0,
            last_new_order_at=OBSERVED_AT - timedelta(microseconds=elapsed_microseconds),
        ),
        settings=ACTIVITY_SETTINGS,
    )

    assert not result.allowed
    assert result.code == "minimum_order_interval_active"
