"""Unit tests for loss, drawdown, pause, and activity gates."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.config import AppConfig, load_config
from trading_bot.domain import (
    AccountId,
    CheckResult,
    DomainValidationError,
    InstrumentId,
    InvalidDecimal,
    OrderPurpose,
)
from trading_bot.risk import (
    ActivitySnapshot,
    LossDecision,
    LossSnapshot,
    evaluate_activity_limits,
    evaluate_loss_limits,
)

ROOT = Path(__file__).parents[3]
CONFIGS = ROOT / "configs"
OBSERVED_AT = datetime(2026, 7, 15, 16, 0, tzinfo=UTC)
DAY_STARTED_AT = datetime(2026, 7, 15, 0, 0, tzinfo=UTC)
WEEK_STARTED_AT = datetime(2026, 7, 13, 0, 0, tzinfo=UTC)


def settings(mode: str = "paper") -> AppConfig:
    return load_config(
        base_path=CONFIGS / "base.yaml",
        mode_path=CONFIGS / f"{mode}.yaml",
        safety_path=CONFIGS / "safety-envelope.yaml",
        environ={},
    ).config


def loss_snapshot(**overrides: object) -> LossSnapshot:
    values: dict[str, object] = {
        "account_id": AccountId("paper-account"),
        "daily_loss_pct": Decimal("0"),
        "weekly_loss_pct": Decimal("0"),
        "peak_to_trough_drawdown_pct": Decimal("0"),
        "consecutive_loss_count": 0,
        "last_loss_at": None,
        "daily_window_started_at": DAY_STARTED_AT,
        "weekly_window_started_at": WEEK_STARTED_AT,
        "daily_reset_reconciled": True,
        "weekly_reset_reviewed": True,
        "observed_at": OBSERVED_AT,
    }
    values.update(overrides)
    if values["consecutive_loss_count"] and "last_loss_at" not in overrides:
        values["last_loss_at"] = OBSERVED_AT - timedelta(minutes=10)
    return LossSnapshot(**values)  # type: ignore[arg-type]


def activity_snapshot(**overrides: object) -> ActivitySnapshot:
    values: dict[str, object] = {
        "account_id": AccountId("paper-account"),
        "instrument_id": InstrumentId("btc-usd"),
        "new_orders_today": 1,
        "new_orders_for_symbol_today": 0,
        "last_new_order_at": OBSERVED_AT - timedelta(minutes=60),
        "daily_window_started_at": DAY_STARTED_AT,
        "observed_at": OBSERVED_AT,
    }
    values.update(overrides)
    return ActivitySnapshot(**values)  # type: ignore[arg-type]


def evaluate_loss(
    snapshot: LossSnapshot,
    purpose: OrderPurpose = OrderPurpose.ENTRY,
) -> LossDecision:
    return evaluate_loss_limits(
        snapshot=snapshot,
        settings=settings().loss_limits,
        purpose=purpose,
    )


def evaluate_activity(snapshot: ActivitySnapshot, mode: str = "paper") -> CheckResult:
    return evaluate_activity_limits(snapshot, settings=settings(mode).activity)


def test_daily_limit_blocks_new_entries_at_exact_threshold() -> None:
    decision = evaluate_loss(loss_snapshot(daily_loss_pct=Decimal("2")))

    assert not decision.allowed
    assert decision.account_id == AccountId("paper-account")
    assert not decision.new_entries_allowed
    assert decision.cancel_unfilled_entries
    assert not decision.kill_switch_activation_requested
    assert decision.reason_code == "daily_loss_limit_reached"


def test_loss_limits_allow_entry_below_every_threshold() -> None:
    decision = evaluate_loss(
        loss_snapshot(
            daily_loss_pct=Decimal("1.99"),
            weekly_loss_pct=Decimal("4.99"),
            peak_to_trough_drawdown_pct=Decimal("9.99"),
        )
    )

    assert decision.allowed
    assert decision.new_entries_allowed
    assert not decision.cancel_unfilled_entries
    assert decision.reason_code == "within_loss_limits"


def test_weekly_limit_blocks_at_exact_threshold() -> None:
    decision = evaluate_loss(loss_snapshot(weekly_loss_pct=Decimal("5")))

    assert not decision.allowed
    assert decision.cancel_unfilled_entries
    assert decision.reason_code == "weekly_loss_limit_reached"


def test_drawdown_limit_requests_kill_switch_without_liquidation() -> None:
    decision = evaluate_loss(loss_snapshot(peak_to_trough_drawdown_pct=Decimal("10")))

    assert not decision.allowed
    assert decision.cancel_unfilled_entries
    assert decision.kill_switch_activation_requested
    assert decision.reason_code == "drawdown_limit_reached"
    assert not hasattr(decision, "liquidation_requested")


@pytest.mark.parametrize(
    "purpose",
    [OrderPurpose.STRATEGY_EXIT, OrderPurpose.PROTECTIVE_EXIT],
)
def test_exit_purposes_remain_allowed_during_entry_loss_block(
    purpose: OrderPurpose,
) -> None:
    decision = evaluate_loss(
        loss_snapshot(daily_loss_pct=Decimal("2")),
        purpose,
    )

    assert decision.allowed
    assert not decision.new_entries_allowed
    assert decision.cancel_unfilled_entries
    assert not decision.kill_switch_activation_requested


@pytest.mark.parametrize(
    "purpose",
    [OrderPurpose.STRATEGY_EXIT, OrderPurpose.PROTECTIVE_EXIT],
)
def test_drawdown_kill_switch_request_blocks_new_exit_intents(
    purpose: OrderPurpose,
) -> None:
    decision = evaluate_loss(
        loss_snapshot(peak_to_trough_drawdown_pct=Decimal("10")),
        purpose,
    )

    assert not decision.allowed
    assert decision.kill_switch_activation_requested


def test_consecutive_loss_threshold_starts_configured_entry_pause() -> None:
    last_loss_at = OBSERVED_AT - timedelta(minutes=10)
    decision = evaluate_loss(loss_snapshot(consecutive_loss_count=3, last_loss_at=last_loss_at))

    assert not decision.allowed
    assert decision.reason_code == "consecutive_loss_pause_active"
    assert decision.entry_pause_until == last_loss_at + timedelta(minutes=240)


def test_consecutive_loss_pause_allows_at_exact_expiry() -> None:
    last_loss_at = OBSERVED_AT - timedelta(minutes=240)
    decision = evaluate_loss(loss_snapshot(consecutive_loss_count=3, last_loss_at=last_loss_at))

    assert decision.allowed
    assert decision.entry_pause_until is None


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("daily_reset_reconciled", "daily_reset_reconciliation_required"),
        ("weekly_reset_reviewed", "weekly_reset_review_required"),
    ],
)
def test_unattested_loss_window_reset_blocks_entries(field: str, reason: str) -> None:
    decision = evaluate_loss(loss_snapshot(**{field: False}))

    assert not decision.allowed
    assert decision.cancel_unfilled_entries
    assert decision.reason_code == reason


def test_drawdown_reason_has_priority_and_preserves_all_safety_actions() -> None:
    decision = evaluate_loss(
        loss_snapshot(
            daily_loss_pct=Decimal("2"),
            weekly_loss_pct=Decimal("5"),
            peak_to_trough_drawdown_pct=Decimal("10"),
            consecutive_loss_count=3,
        )
    )

    assert decision.reason_code == "drawdown_limit_reached"
    assert decision.cancel_unfilled_entries
    assert decision.kill_switch_activation_requested


def test_daily_activity_limit_blocks_the_next_order_at_exact_count() -> None:
    result = evaluate_activity(activity_snapshot(new_orders_today=3))

    assert not result.allowed
    assert result.code == "daily_order_limit_reached"
    assert result.observed == "3"
    assert result.configured_limit == "3"


def test_micro_live_uses_tighter_canonical_daily_activity_limit() -> None:
    result = evaluate_activity(
        activity_snapshot(new_orders_today=2),
        mode="micro_live",
    )

    assert not result.allowed
    assert result.configured_limit == "2"


def test_symbol_activity_limit_blocks_at_exact_count() -> None:
    result = evaluate_activity(activity_snapshot(new_orders_for_symbol_today=1))

    assert not result.allowed
    assert result.code == "symbol_order_limit_reached"


def test_minimum_order_interval_blocks_until_exact_boundary() -> None:
    too_soon = evaluate_activity(
        activity_snapshot(last_new_order_at=OBSERVED_AT - timedelta(minutes=29, seconds=59))
    )
    at_boundary = evaluate_activity(
        activity_snapshot(last_new_order_at=OBSERVED_AT - timedelta(minutes=30))
    )

    assert not too_soon.allowed
    assert too_soon.code == "minimum_order_interval_active"
    assert at_boundary.allowed
    assert at_boundary.code == "activity_limits"


def test_activity_below_all_limits_is_allowed() -> None:
    snapshot = activity_snapshot()
    result = evaluate_activity(snapshot)

    assert snapshot.account_id == AccountId("paper-account")
    assert snapshot.instrument_id == InstrumentId("btc-usd")
    assert result.allowed
    assert result.reason == "within_limit"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("daily_loss_pct", Decimal("-1")),
        ("account_id", ""),
        ("daily_loss_pct", Decimal("100.01")),
        ("weekly_loss_pct", Decimal("NaN")),
        ("peak_to_trough_drawdown_pct", Decimal("Infinity")),
        ("consecutive_loss_count", True),
        ("daily_reset_reconciled", 1),
        ("weekly_reset_reviewed", 1),
        ("observed_at", OBSERVED_AT.replace(tzinfo=None)),
        ("daily_window_started_at", OBSERVED_AT + timedelta(minutes=1)),
        ("weekly_window_started_at", DAY_STARTED_AT + timedelta(minutes=1)),
        ("last_loss_at", OBSERVED_AT + timedelta(minutes=1)),
    ],
)
def test_loss_snapshot_rejects_unsafe_or_inconsistent_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises((DomainValidationError, InvalidDecimal)):
        loss_snapshot(**{field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"consecutive_loss_count": 1, "last_loss_at": None},
        {"consecutive_loss_count": 0, "last_loss_at": OBSERVED_AT},
    ],
)
def test_loss_snapshot_rejects_inconsistent_consecutive_loss_state(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(DomainValidationError):
        loss_snapshot(**overrides)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("new_orders_today", -1),
        ("account_id", ""),
        ("instrument_id", ""),
        ("new_orders_today", True),
        ("new_orders_for_symbol_today", -1),
        ("new_orders_for_symbol_today", 2),
        ("observed_at", OBSERVED_AT.replace(tzinfo=None)),
        ("daily_window_started_at", DAY_STARTED_AT + timedelta(seconds=1)),
        ("last_new_order_at", OBSERVED_AT + timedelta(seconds=1)),
    ],
)
def test_activity_snapshot_rejects_unsafe_or_inconsistent_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises(DomainValidationError):
        activity_snapshot(**{field: value})


def test_activity_snapshot_requires_a_current_day_order_for_positive_count() -> None:
    with pytest.raises(DomainValidationError):
        activity_snapshot(
            new_orders_today=1,
            last_new_order_at=DAY_STARTED_AT - timedelta(seconds=1),
        )


def test_activity_snapshot_rejects_current_day_timestamp_with_zero_count() -> None:
    with pytest.raises(DomainValidationError):
        activity_snapshot(
            new_orders_today=0,
            new_orders_for_symbol_today=0,
            last_new_order_at=OBSERVED_AT,
        )


def test_activity_without_prior_order_skips_spacing_check() -> None:
    result = evaluate_activity(
        activity_snapshot(
            new_orders_today=0,
            new_orders_for_symbol_today=0,
            last_new_order_at=None,
        )
    )

    assert result.allowed


def test_loss_and_activity_records_are_immutable_and_decision_is_factory_only() -> None:
    losses = loss_snapshot()
    activity = activity_snapshot()

    with pytest.raises(FrozenInstanceError):
        losses.daily_loss_pct = Decimal("1")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        activity.new_orders_today = 0  # type: ignore[misc]
    with pytest.raises(TypeError, match="evaluate_loss_limits"):
        LossDecision()


@pytest.mark.parametrize(
    "overrides",
    [
        {"account_id": ""},
        {"purpose": object()},
        {"reason_code": "unregistered"},
        {"entry_pause_until": OBSERVED_AT},
        {"entry_pause_until": OBSERVED_AT + timedelta(minutes=1)},
        {"allowed": False},
        {"cancel_unfilled_entries": True},
        {"new_entries_allowed": False, "cancel_unfilled_entries": True},
        {"kill_switch_activation_requested": True},
        {
            "allowed": False,
            "new_entries_allowed": False,
            "cancel_unfilled_entries": True,
            "reason_code": "consecutive_loss_pause_active",
        },
    ],
)
def test_internal_loss_decision_factory_rejects_inconsistent_states(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "account_id": AccountId("paper-account"),
        "purpose": OrderPurpose.ENTRY,
        "allowed": True,
        "new_entries_allowed": True,
        "cancel_unfilled_entries": False,
        "kill_switch_activation_requested": False,
        "reason_code": "within_loss_limits",
        "entry_pause_until": None,
        "evaluated_at": OBSERVED_AT,
    }
    values.update(overrides)

    with pytest.raises(DomainValidationError):
        LossDecision._create(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("argument", ["snapshot", "settings", "purpose"])
def test_loss_evaluation_rejects_noncanonical_dependency_types(argument: str) -> None:
    config = settings()
    values: dict[str, object] = {
        "snapshot": loss_snapshot(),
        "settings": config.loss_limits,
        "purpose": OrderPurpose.ENTRY,
    }
    values[argument] = object()

    with pytest.raises(DomainValidationError):
        evaluate_loss_limits(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("argument", ["snapshot", "settings"])
def test_activity_evaluation_rejects_noncanonical_dependency_types(argument: str) -> None:
    config = settings()
    values: dict[str, object] = {
        "snapshot": activity_snapshot(),
        "settings": config.activity,
    }
    values[argument] = object()

    with pytest.raises(DomainValidationError):
        evaluate_activity_limits(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("consecutive_loss_pause_count", 0),
        ("consecutive_loss_pause_count", True),
        ("consecutive_loss_pause_minutes", 0),
        ("consecutive_loss_pause_minutes", True),
    ],
)
def test_loss_evaluation_rejects_invalid_copied_config_values(
    field: str,
    value: object,
) -> None:
    config = settings()
    unsafe = config.loss_limits.model_copy(update={field: value})

    with pytest.raises(DomainValidationError):
        evaluate_loss_limits(
            snapshot=loss_snapshot(),
            settings=unsafe,
            purpose=OrderPurpose.ENTRY,
        )


def test_loss_evaluation_rejects_invalid_copied_limit_ordering() -> None:
    config = settings()
    unsafe = config.loss_limits.model_copy(update={"max_daily_loss_pct": Decimal("6")})

    with pytest.raises(DomainValidationError):
        evaluate_loss_limits(
            snapshot=loss_snapshot(),
            settings=unsafe,
            purpose=OrderPurpose.ENTRY,
        )


def test_loss_evaluation_fails_closed_on_unrepresentable_pause_duration() -> None:
    config = settings()
    unsafe = config.loss_limits.model_copy(update={"consecutive_loss_pause_minutes": 10**20})

    with pytest.raises(DomainValidationError):
        evaluate_loss_limits(
            snapshot=loss_snapshot(consecutive_loss_count=3),
            settings=unsafe,
            purpose=OrderPurpose.ENTRY,
        )


def test_loss_evaluation_fails_closed_on_corrupted_pause_evidence() -> None:
    snapshot = loss_snapshot(consecutive_loss_count=3)
    object.__setattr__(snapshot, "last_loss_at", None)

    with pytest.raises(DomainValidationError, match="last-loss timestamp"):
        evaluate_loss(snapshot)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_new_orders_per_day", -1),
        ("max_new_orders_per_day", True),
        ("max_orders_per_symbol_per_day", -1),
        ("max_orders_per_symbol_per_day", True),
        ("minimum_minutes_between_new_orders", -1),
        ("minimum_minutes_between_new_orders", True),
    ],
)
def test_activity_evaluation_rejects_invalid_copied_config_values(
    field: str,
    value: object,
) -> None:
    config = settings()
    unsafe = config.activity.model_copy(update={field: value})

    with pytest.raises(DomainValidationError):
        evaluate_activity_limits(activity_snapshot(), settings=unsafe)
