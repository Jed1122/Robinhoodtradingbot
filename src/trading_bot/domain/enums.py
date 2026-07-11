"""Canonical broker-neutral domain enumerations."""

from enum import StrEnum


class AssetClass(StrEnum):
    EQUITY = "equity"
    CRYPTO = "crypto"
    PREDICTION = "prediction"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderPurpose(StrEnum):
    ENTRY = "entry"
    STRATEGY_EXIT = "strategy_exit"
    PROTECTIVE_EXIT = "protective_exit"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    STOP_LIMIT = "stop_limit"


class TimeInForce(StrEnum):
    GOOD_FOR_DAY = "good_for_day"
    GOOD_TIL_CANCELED = "good_til_canceled"
    IMMEDIATE_OR_CANCEL = "immediate_or_cancel"


class BarInterval(StrEnum):
    ONE_MINUTE = "one_minute"
    FIVE_MINUTE = "five_minute"
    ONE_HOUR = "one_hour"
    FOUR_HOUR = "four_hour"
    ONE_DAY = "one_day"


class TimestampSource(StrEnum):
    PROVIDER = "provider"
    LOCAL_RECEIPT = "local_receipt"
    SIMULATED = "simulated"


class ExecutionMode(StrEnum):
    BACKTEST = "backtest"
    SIMULATION = "simulation"
    PAPER = "paper"
    SHADOW = "shadow"
    MICRO_LIVE = "micro_live"
    NORMAL_LIVE = "normal_live"


class RuntimeState(StrEnum):
    RUNNING_LIVE = "running_live"
    ENTRY_BLOCKED = "entry_blocked"
    PAUSED = "paused"
    KILL_SWITCH_ACTIVE = "kill_switch_active"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    SHUTTING_DOWN = "shutting_down"


class OrderState(StrEnum):
    PROPOSED = "proposed"
    RISK_REJECTED = "risk_rejected"
    RISK_APPROVED = "risk_approved"
    REVIEW_REQUESTED = "review_requested"
    REVIEWED = "reviewed"
    SUBMISSION_PENDING = "submission_pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCEL_PENDING = "cancel_pending"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNKNOWN_REQUIRES_RECONCILIATION = "unknown_requires_reconciliation"


class OrderEvent(StrEnum):
    RISK_DENY = "risk_deny"
    RISK_ALLOW = "risk_allow"
    EXPIRE = "expire"
    REQUEST_REVIEW = "request_review"
    REVIEW_ACCEPTED = "review_accepted"
    REVIEW_REJECTED = "review_rejected"
    FINAL_RISK_DENY = "final_risk_deny"
    PREPARE_SUBMISSION = "prepare_submission"
    BROKER_ACCEPTED = "broker_accepted"
    BROKER_REJECTED = "broker_rejected"
    BROKER_AMBIGUOUS = "broker_ambiguous"
    PARTIAL_FILL = "partial_fill"
    FILL = "fill"
    REQUEST_CANCEL = "request_cancel"
    CANCEL_CONFIRMED = "cancel_confirmed"
    CANCEL_REJECTED = "cancel_rejected"
    BROKER_EXPIRED = "broker_expired"
    RECONCILE_SUBMITTED = "reconcile_submitted"
    RECONCILE_PARTIAL = "reconcile_partial"
    RECONCILE_FILLED = "reconcile_filled"
    RECONCILE_CANCELED = "reconcile_canceled"
    RECONCILE_REJECTED = "reconcile_rejected"
    RECONCILE_EXPIRED = "reconcile_expired"
