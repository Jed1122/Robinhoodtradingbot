from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from trading_bot.clock import Clock, InvalidTimestamp, SystemClock, require_utc
from trading_bot.domain import (
    AccountId,
    AssetClass,
    AuditEventId,
    AuthorizationId,
    BarInterval,
    BrokerOrderId,
    ClientOrderId,
    CodeHash,
    ConfigHash,
    ConfigVersionId,
    CorrelationId,
    DataHash,
    EvidenceId,
    ExecutionMode,
    FillId,
    InstrumentId,
    InvalidDecimal,
    LeaseId,
    OrderEvent,
    OrderIntentId,
    OrderPurpose,
    OrderState,
    OrderTransitionId,
    OrderType,
    ReconciliationId,
    ReviewId,
    RunId,
    RuntimeState,
    Side,
    SubmissionAttemptId,
    TimeInForce,
    TimestampSource,
    new_order_intent_id,
    parse_decimal,
    quantize_down,
)


def test_enums_have_exact_canonical_members() -> None:
    expected_members = {
        AssetClass: ("EQUITY", "CRYPTO", "PREDICTION"),
        Side: ("BUY", "SELL"),
        OrderPurpose: ("ENTRY", "STRATEGY_EXIT", "PROTECTIVE_EXIT"),
        OrderType: ("MARKET", "LIMIT", "STOP_LOSS", "STOP_LIMIT"),
        TimeInForce: ("GOOD_FOR_DAY", "GOOD_TIL_CANCELED", "IMMEDIATE_OR_CANCEL"),
        BarInterval: ("ONE_MINUTE", "FIVE_MINUTE", "ONE_HOUR", "FOUR_HOUR", "ONE_DAY"),
        TimestampSource: ("PROVIDER", "LOCAL_RECEIPT", "SIMULATED"),
        ExecutionMode: (
            "BACKTEST",
            "SIMULATION",
            "PAPER",
            "SHADOW",
            "MICRO_LIVE",
            "NORMAL_LIVE",
        ),
        RuntimeState: (
            "RUNNING_LIVE",
            "ENTRY_BLOCKED",
            "PAUSED",
            "KILL_SWITCH_ACTIVE",
            "RECONCILIATION_REQUIRED",
            "SHUTTING_DOWN",
        ),
        OrderState: (
            "PROPOSED",
            "RISK_REJECTED",
            "RISK_APPROVED",
            "REVIEW_REQUESTED",
            "REVIEWED",
            "SUBMISSION_PENDING",
            "SUBMITTED",
            "PARTIALLY_FILLED",
            "FILLED",
            "CANCEL_PENDING",
            "CANCELED",
            "REJECTED",
            "EXPIRED",
            "UNKNOWN_REQUIRES_RECONCILIATION",
        ),
        OrderEvent: (
            "RISK_DENY",
            "RISK_ALLOW",
            "EXPIRE",
            "REQUEST_REVIEW",
            "REVIEW_ACCEPTED",
            "REVIEW_REJECTED",
            "FINAL_RISK_DENY",
            "PREPARE_SUBMISSION",
            "BROKER_ACCEPTED",
            "BROKER_REJECTED",
            "BROKER_AMBIGUOUS",
            "PARTIAL_FILL",
            "FILL",
            "REQUEST_CANCEL",
            "CANCEL_CONFIRMED",
            "CANCEL_REJECTED",
            "BROKER_EXPIRED",
            "RECONCILIATION_DRIFT",
            "RECONCILE_SUBMITTED",
            "RECONCILE_PARTIAL",
            "RECONCILE_FILLED",
            "RECONCILE_CANCELED",
            "RECONCILE_REJECTED",
            "RECONCILE_EXPIRED",
        ),
    }

    for enum_type, expected in expected_members.items():
        assert tuple(enum_type.__members__) == expected


def test_identifiers_are_distinct_newtypes_over_strings() -> None:
    identifier_types: tuple[Any, ...] = (
        AccountId,
        InstrumentId,
        OrderIntentId,
        ClientOrderId,
        ReviewId,
        SubmissionAttemptId,
        BrokerOrderId,
        FillId,
        OrderTransitionId,
        RunId,
        AuthorizationId,
        ReconciliationId,
        LeaseId,
        AuditEventId,
        EvidenceId,
        ConfigVersionId,
        CorrelationId,
        ConfigHash,
        DataHash,
        CodeHash,
    )

    assert len({id(identifier_type) for identifier_type in identifier_types}) == len(
        identifier_types
    )
    assert all(identifier_type.__supertype__ is str for identifier_type in identifier_types)


def test_new_order_intent_id_is_uuid4_and_unique() -> None:
    first = new_order_intent_id()
    second = new_order_intent_id()

    assert first != second
    assert UUID(first).version == 4
    assert UUID(second).version == 4


def test_parse_decimal_accepts_finite_decimal_text() -> None:
    assert parse_decimal("123.4500") == Decimal("123.4500")


@pytest.mark.parametrize("raw", ["NaN", "sNaN", "Infinity", "-Infinity", "invalid"])
def test_parse_decimal_rejects_nonfinite_or_malformed_values(raw: str) -> None:
    with pytest.raises(InvalidDecimal):
        parse_decimal(raw)


def test_quantize_down_never_increases_exposure() -> None:
    assert quantize_down(Decimal("1.239"), Decimal("0.01")) == Decimal("1.23")


@pytest.mark.parametrize(
    ("value", "increment"),
    [
        (Decimal("NaN"), Decimal("0.01")),
        (Decimal("Infinity"), Decimal("0.01")),
        (Decimal("1"), Decimal("NaN")),
        (Decimal("1"), Decimal("0")),
        (Decimal("1"), Decimal("-0.01")),
    ],
)
def test_quantize_down_rejects_nonfinite_or_nonpositive_inputs(
    value: Decimal, increment: Decimal
) -> None:
    with pytest.raises(InvalidDecimal):
        quantize_down(value, increment)


def test_system_clock_is_aware_utc() -> None:
    clock: Clock = SystemClock()

    now = clock.now()

    assert now.tzinfo is UTC
    assert now.utcoffset() == timedelta(0)


def test_require_utc_returns_datetime_with_canonical_utc_timezone() -> None:
    value = datetime(2026, 7, 11, tzinfo=timezone(timedelta(0), name="zero"))

    result = require_utc(value)

    assert result == value
    assert result.tzinfo is UTC


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 7, 11),
        datetime(2026, 7, 11, tzinfo=timezone(timedelta(hours=-4))),
    ],
)
def test_require_utc_rejects_naive_or_non_utc_datetimes(value: datetime) -> None:
    with pytest.raises(InvalidTimestamp):
        require_utc(value)
