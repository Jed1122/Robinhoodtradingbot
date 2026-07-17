"""Pure loss, drawdown, consecutive-loss, and activity gates."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final, Self

from trading_bot.clock import require_utc
from trading_bot.config import ActivitySettings, LossLimitSettings
from trading_bot.domain import (
    AccountId,
    CheckResult,
    DomainValidationError,
    InstrumentId,
    OrderPurpose,
    canonical_decimal_text,
    require_bounded_decimal,
)

_MAX_PERCENT: Final = Decimal("100")
_SECONDS_PER_MINUTE: Final = 60
_MICROSECONDS_PER_SECOND: Final = Decimal("1000000")
_LOSS_REASON_CODES: Final = frozenset(
    {
        "consecutive_loss_pause_active",
        "daily_loss_limit_reached",
        "daily_reset_reconciliation_required",
        "drawdown_limit_reached",
        "weekly_loss_limit_reached",
        "weekly_reset_review_required",
        "within_loss_limits",
    }
)
_EXIT_COMPATIBLE_BLOCK_REASONS: Final = frozenset(
    {
        "consecutive_loss_pause_active",
        "daily_loss_limit_reached",
        "weekly_loss_limit_reached",
    }
)
_EXIT_PURPOSES: Final = frozenset(
    {
        OrderPurpose.STRATEGY_EXIT,
        OrderPurpose.PROTECTIVE_EXIT,
    }
)


def _require_exact_bool(value: bool, field_name: str) -> None:
    if type(value) is not bool:
        raise DomainValidationError(f"{field_name} must be a boolean")


def _require_nonempty_identifier(value: str, field_name: str) -> None:
    if type(value) is not str or not value.strip():
        raise DomainValidationError(f"{field_name} must be a nonempty identifier")


def _require_nonnegative_int(value: int, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise DomainValidationError(f"{field_name} must be a nonnegative integer")


def _require_positive_int(value: int, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise DomainValidationError(f"{field_name} must be a positive integer")


def _require_percentage(value: Decimal, field_name: str) -> None:
    require_bounded_decimal(value, field_name, nonnegative=True)
    if value > _MAX_PERCENT:
        raise DomainValidationError(f"{field_name} cannot exceed 100 whole-percent units")


@dataclass(frozen=True, slots=True)
class LossSnapshot:
    """Reconciled loss state plus attestations for the active reset windows."""

    account_id: AccountId
    daily_loss_pct: Decimal
    weekly_loss_pct: Decimal
    peak_to_trough_drawdown_pct: Decimal
    consecutive_loss_count: int
    last_loss_at: datetime | None
    daily_window_started_at: datetime
    weekly_window_started_at: datetime
    daily_reset_reconciled: bool
    weekly_reset_reviewed: bool
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_nonempty_identifier(self.account_id, "account_id")
        _require_percentage(self.daily_loss_pct, "daily_loss_pct")
        _require_percentage(self.weekly_loss_pct, "weekly_loss_pct")
        _require_percentage(
            self.peak_to_trough_drawdown_pct,
            "peak_to_trough_drawdown_pct",
        )
        _require_nonnegative_int(self.consecutive_loss_count, "consecutive_loss_count")
        _require_exact_bool(self.daily_reset_reconciled, "daily_reset_reconciled")
        _require_exact_bool(self.weekly_reset_reviewed, "weekly_reset_reviewed")
        require_utc(self.daily_window_started_at)
        require_utc(self.weekly_window_started_at)
        require_utc(self.observed_at)
        if self.weekly_window_started_at > self.daily_window_started_at:
            raise DomainValidationError(
                "weekly_window_started_at cannot follow daily_window_started_at"
            )
        if self.daily_window_started_at > self.observed_at:
            raise DomainValidationError("daily_window_started_at cannot be in the future")
        if self.last_loss_at is not None:
            require_utc(self.last_loss_at)
            if self.last_loss_at > self.observed_at:
                raise DomainValidationError("last_loss_at cannot be in the future")
        if self.consecutive_loss_count == 0 and self.last_loss_at is not None:
            raise DomainValidationError("zero consecutive losses cannot retain last_loss_at")
        if self.consecutive_loss_count > 0 and self.last_loss_at is None:
            raise DomainValidationError("positive consecutive losses require last_loss_at")


@dataclass(frozen=True, slots=True)
class ActivitySnapshot:
    """Distinct submitted entry-intent counts for one symbol and UTC day.

    Transport retries for one durable intent do not add another count. An ambiguous
    submission still consumes capacity until reconciliation proves its terminal state.
    """

    account_id: AccountId
    instrument_id: InstrumentId
    new_orders_today: int
    new_orders_for_symbol_today: int
    last_new_order_at: datetime | None
    daily_window_started_at: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_nonempty_identifier(self.account_id, "account_id")
        _require_nonempty_identifier(self.instrument_id, "instrument_id")
        _require_nonnegative_int(self.new_orders_today, "new_orders_today")
        _require_nonnegative_int(
            self.new_orders_for_symbol_today,
            "new_orders_for_symbol_today",
        )
        require_utc(self.daily_window_started_at)
        require_utc(self.observed_at)
        expected_window_start = self.observed_at.astimezone(UTC).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        if self.daily_window_started_at != expected_window_start:
            raise DomainValidationError(
                "daily_window_started_at must be the current UTC day boundary"
            )
        if self.new_orders_for_symbol_today > self.new_orders_today:
            raise DomainValidationError(
                "new_orders_for_symbol_today cannot exceed new_orders_today"
            )
        if self.last_new_order_at is not None:
            require_utc(self.last_new_order_at)
            if self.last_new_order_at > self.observed_at:
                raise DomainValidationError("last_new_order_at cannot be in the future")
        if self.new_orders_today > 0 and (
            self.last_new_order_at is None or self.last_new_order_at < self.daily_window_started_at
        ):
            raise DomainValidationError(
                "positive daily order count requires a current-day last_new_order_at"
            )
        if (
            self.new_orders_today == 0
            and self.last_new_order_at is not None
            and self.last_new_order_at >= self.daily_window_started_at
        ):
            raise DomainValidationError(
                "zero daily order count cannot retain a current-day last_new_order_at"
            )


@dataclass(frozen=True, slots=True, init=False)
class LossDecision:
    """Purpose-aware entry block and safety actions from one loss evaluation."""

    account_id: AccountId
    purpose: OrderPurpose
    allowed: bool
    new_entries_allowed: bool
    cancel_unfilled_entries: bool
    kill_switch_activation_requested: bool
    reason_code: str
    entry_pause_until: datetime | None
    evaluated_at: datetime

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("LossDecision must be constructed by evaluate_loss_limits")

    @classmethod
    def _create(
        cls,
        *,
        account_id: AccountId,
        purpose: OrderPurpose,
        allowed: bool,
        new_entries_allowed: bool,
        cancel_unfilled_entries: bool,
        kill_switch_activation_requested: bool,
        reason_code: str,
        entry_pause_until: datetime | None,
        evaluated_at: datetime,
    ) -> Self:
        instance = object.__new__(cls)
        for field_name, value in (
            ("account_id", account_id),
            ("purpose", purpose),
            ("allowed", allowed),
            ("new_entries_allowed", new_entries_allowed),
            ("cancel_unfilled_entries", cancel_unfilled_entries),
            ("kill_switch_activation_requested", kill_switch_activation_requested),
            ("reason_code", reason_code),
            ("entry_pause_until", entry_pause_until),
            ("evaluated_at", evaluated_at),
        ):
            object.__setattr__(instance, field_name, value)
        instance.__post_init__()
        return instance

    def __post_init__(self) -> None:
        _require_nonempty_identifier(self.account_id, "account_id")
        if type(self.purpose) is not OrderPurpose:
            raise DomainValidationError("purpose must be an OrderPurpose")
        _require_exact_bool(self.allowed, "allowed")
        _require_exact_bool(self.new_entries_allowed, "new_entries_allowed")
        _require_exact_bool(self.cancel_unfilled_entries, "cancel_unfilled_entries")
        _require_exact_bool(
            self.kill_switch_activation_requested,
            "kill_switch_activation_requested",
        )
        if self.reason_code not in _LOSS_REASON_CODES:
            raise DomainValidationError("reason_code must be a registered loss reason")
        require_utc(self.evaluated_at)
        if self.entry_pause_until is not None:
            require_utc(self.entry_pause_until)
            if self.entry_pause_until <= self.evaluated_at:
                raise DomainValidationError("entry_pause_until must be in the future")
        expected_allowed = _loss_reason_allows_purpose(self.reason_code, self.purpose)
        if self.allowed is not expected_allowed:
            raise DomainValidationError("allowed must match purpose-aware loss policy")
        if self.cancel_unfilled_entries is self.new_entries_allowed:
            raise DomainValidationError(
                "cancel_unfilled_entries must be the inverse of new_entries_allowed"
            )
        if self.new_entries_allowed != (self.reason_code == "within_loss_limits"):
            raise DomainValidationError("reason_code must match new_entries_allowed")
        if self.kill_switch_activation_requested != (self.reason_code == "drawdown_limit_reached"):
            raise DomainValidationError("kill-switch request must match the drawdown reason")
        if self.reason_code == "consecutive_loss_pause_active" and self.entry_pause_until is None:
            raise DomainValidationError("active consecutive-loss pause requires an expiry")
        if self.reason_code == "within_loss_limits" and self.entry_pause_until is not None:
            raise DomainValidationError("inactive loss limits cannot retain a pause expiry")


def _loss_reason_allows_purpose(reason_code: str, purpose: OrderPurpose) -> bool:
    return reason_code == "within_loss_limits" or (
        purpose in _EXIT_PURPOSES and reason_code in _EXIT_COMPATIBLE_BLOCK_REASONS
    )


def evaluate_loss_limits(
    *,
    snapshot: LossSnapshot,
    settings: LossLimitSettings,
    purpose: OrderPurpose,
) -> LossDecision:
    """Evaluate loss state while preserving non-entry exit purposes."""

    if type(snapshot) is not LossSnapshot:
        raise DomainValidationError("snapshot must be a LossSnapshot")
    if type(settings) is not LossLimitSettings:
        raise DomainValidationError("settings must be LossLimitSettings")
    if type(purpose) is not OrderPurpose:
        raise DomainValidationError("purpose must be an OrderPurpose")

    for field_name, value in (
        ("max_daily_loss_pct", settings.max_daily_loss_pct),
        ("max_weekly_loss_pct", settings.max_weekly_loss_pct),
        (
            "max_peak_to_trough_drawdown_pct",
            settings.max_peak_to_trough_drawdown_pct,
        ),
    ):
        _require_percentage(value, field_name)
    if not (
        settings.max_daily_loss_pct
        <= settings.max_weekly_loss_pct
        <= settings.max_peak_to_trough_drawdown_pct
    ):
        raise DomainValidationError("daily, weekly, and drawdown limits must be ordered")
    _require_positive_int(
        settings.consecutive_loss_pause_count,
        "consecutive_loss_pause_count",
    )
    _require_positive_int(
        settings.consecutive_loss_pause_minutes,
        "consecutive_loss_pause_minutes",
    )

    drawdown_reached = (
        snapshot.peak_to_trough_drawdown_pct >= settings.max_peak_to_trough_drawdown_pct
    )
    weekly_reached = snapshot.weekly_loss_pct >= settings.max_weekly_loss_pct
    daily_reached = snapshot.daily_loss_pct >= settings.max_daily_loss_pct
    pause_until: datetime | None = None
    if snapshot.consecutive_loss_count >= settings.consecutive_loss_pause_count:
        last_loss_at = snapshot.last_loss_at
        if last_loss_at is None:
            raise DomainValidationError("consecutive-loss threshold requires a last-loss timestamp")
        try:
            candidate = last_loss_at + timedelta(minutes=settings.consecutive_loss_pause_minutes)
        except OverflowError:
            raise DomainValidationError(
                "consecutive-loss pause duration is outside the supported UTC range"
            ) from None
        if snapshot.observed_at < candidate:
            pause_until = candidate

    if drawdown_reached:
        reason_code = "drawdown_limit_reached"
    elif not snapshot.weekly_reset_reviewed:
        reason_code = "weekly_reset_review_required"
    elif not snapshot.daily_reset_reconciled:
        reason_code = "daily_reset_reconciliation_required"
    elif weekly_reached:
        reason_code = "weekly_loss_limit_reached"
    elif daily_reached:
        reason_code = "daily_loss_limit_reached"
    elif pause_until is not None:
        reason_code = "consecutive_loss_pause_active"
    else:
        reason_code = "within_loss_limits"

    new_entries_allowed = reason_code == "within_loss_limits"
    return LossDecision._create(
        account_id=snapshot.account_id,
        purpose=purpose,
        allowed=_loss_reason_allows_purpose(reason_code, purpose),
        new_entries_allowed=new_entries_allowed,
        cancel_unfilled_entries=not new_entries_allowed,
        kill_switch_activation_requested=drawdown_reached,
        reason_code=reason_code,
        entry_pause_until=pause_until,
        evaluated_at=snapshot.observed_at,
    )


def _elapsed_seconds(started_at: datetime, ended_at: datetime) -> Decimal:
    elapsed = ended_at - started_at
    microseconds = (elapsed.days * 86400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds
    return Decimal(microseconds) / _MICROSECONDS_PER_SECOND


def evaluate_activity_limits(
    snapshot: ActivitySnapshot,
    *,
    settings: ActivitySettings,
) -> CheckResult:
    """Evaluate whether one additional new order is allowed now."""

    if type(snapshot) is not ActivitySnapshot:
        raise DomainValidationError("snapshot must be an ActivitySnapshot")
    if type(settings) is not ActivitySettings:
        raise DomainValidationError("settings must be ActivitySettings")
    _require_nonnegative_int(
        settings.max_new_orders_per_day,
        "max_new_orders_per_day",
    )
    _require_nonnegative_int(
        settings.max_orders_per_symbol_per_day,
        "max_orders_per_symbol_per_day",
    )
    _require_nonnegative_int(
        settings.minimum_minutes_between_new_orders,
        "minimum_minutes_between_new_orders",
    )

    if snapshot.new_orders_today >= settings.max_new_orders_per_day:
        return CheckResult(
            code="daily_order_limit_reached",
            allowed=False,
            observed=str(snapshot.new_orders_today),
            configured_limit=str(settings.max_new_orders_per_day),
            reason="limit_denied",
            observed_at=snapshot.observed_at,
        )
    if snapshot.new_orders_for_symbol_today >= settings.max_orders_per_symbol_per_day:
        return CheckResult(
            code="symbol_order_limit_reached",
            allowed=False,
            observed=str(snapshot.new_orders_for_symbol_today),
            configured_limit=str(settings.max_orders_per_symbol_per_day),
            reason="limit_denied",
            observed_at=snapshot.observed_at,
        )
    if snapshot.last_new_order_at is not None:
        elapsed_seconds = _elapsed_seconds(
            snapshot.last_new_order_at,
            snapshot.observed_at,
        )
        configured_seconds = Decimal(
            settings.minimum_minutes_between_new_orders * _SECONDS_PER_MINUTE
        )
        if elapsed_seconds < configured_seconds:
            return CheckResult(
                code="minimum_order_interval_active",
                allowed=False,
                observed=canonical_decimal_text(elapsed_seconds),
                configured_limit=canonical_decimal_text(configured_seconds),
                reason="limit_denied",
                observed_at=snapshot.observed_at,
            )
    return CheckResult(
        code="activity_limits",
        allowed=True,
        observed="within_all_limits",
        configured_limit="canonical_activity_settings",
        reason="within_limit",
        observed_at=snapshot.observed_at,
    )


__all__ = [
    "ActivitySnapshot",
    "LossDecision",
    "LossSnapshot",
    "evaluate_activity_limits",
    "evaluate_loss_limits",
]
