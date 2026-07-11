from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from trading_bot.domain import (
    AccountId,
    AccountSnapshot,
    AssetBuyingPower,
    AssetClass,
    AuditEvent,
    AuditEventId,
    Bar,
    BarInterval,
    BrokerHealth,
    BrokerOrder,
    BrokerOrderId,
    BrokerOrderReview,
    CancelReceipt,
    CheckResult,
    ClientOrderId,
    CodeHash,
    ConfigHash,
    CorrelationId,
    DataHash,
    DomainValidationError,
    Fill,
    FillId,
    Instrument,
    InstrumentId,
    MarketClock,
    OrderIntent,
    OrderIntentId,
    OrderPurpose,
    OrderState,
    OrderType,
    PersistedReviewedOrder,
    PortfolioSnapshot,
    Position,
    Quote,
    ReviewId,
    RiskEvaluation,
    Side,
    SpreadEstimate,
    SubmissionAttemptId,
    TimeInForce,
    TimestampSource,
)

NOW = datetime(2026, 7, 11, 12, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _valid_records() -> dict[str, Any]:
    instrument = Instrument(
        id=InstrumentId("btc-usd"),
        symbol="BTC-USD",
        asset_class=AssetClass.CRYPTO,
        provider_status="active",
        tradable=True,
        fractional_eligible=True,
        price_increment=Decimal("0.01"),
        quantity_increment=Decimal("0.00000001"),
        minimum_quantity=Decimal("0.00000001"),
        minimum_notional=Decimal("1"),
        maximum_quantity=Decimal("100"),
        correlation_group="crypto-major",
        observed_at=NOW,
        data_hash=DataHash(HASH_A),
    )
    quote = Quote(
        instrument_id=instrument.id,
        observed_at=NOW,
        bid=Decimal("100"),
        ask=Decimal("101"),
        last=Decimal("100.5"),
        source="fixture",
        data_hash=DataHash(HASH_A),
        freshness_verified=True,
        timestamp_source=TimestampSource.SIMULATED,
    )
    spread = SpreadEstimate(
        instrument_id=instrument.id,
        observed_at=NOW,
        absolute=Decimal("1"),
        percentage=Decimal("0.01"),
        data_hash=DataHash(HASH_A),
    )
    bar = Bar(
        instrument_id=instrument.id,
        interval=BarInterval.FIVE_MINUTE,
        starts_at=NOW,
        ends_at=LATER,
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("10"),
        source="fixture",
        data_hash=DataHash(HASH_A),
    )
    market_clock = MarketClock(
        asset_class=AssetClass.CRYPTO,
        venue="crypto",
        observed_at=NOW,
        is_open=True,
        halted=False,
        trading_disabled=False,
        cancel_only=False,
        next_open_at=None,
        next_close_at=LATER,
    )
    buying_power = AssetBuyingPower(asset_class=AssetClass.CRYPTO, amount=Decimal("100"))
    account = AccountSnapshot(
        account_id=AccountId("account-1"),
        provider_state="active",
        equity=Decimal("100"),
        cash=Decimal("80"),
        buying_power=(buying_power,),
        restricted=False,
        observed_at=NOW,
        data_hash=DataHash(HASH_A),
    )
    position = Position(
        account_id=account.account_id,
        instrument_id=instrument.id,
        asset_class=AssetClass.CRYPTO,
        quantity=Decimal("0.1"),
        average_price=Decimal("90"),
        market_value=Decimal("10"),
        observed_at=NOW,
        data_hash=DataHash(HASH_A),
    )
    portfolio = PortfolioSnapshot(
        account_id=account.account_id,
        positions=(position,),
        cash=Decimal("80"),
        equity=Decimal("100"),
        gross_exposure=Decimal("20"),
        net_exposure=Decimal("20"),
        crypto_exposure=Decimal("20"),
        realized_pnl=Decimal("-1"),
        unrealized_pnl=Decimal("2"),
        observed_at=NOW,
        data_hash=DataHash(HASH_A),
    )
    intent = OrderIntent(
        id=OrderIntentId("intent-1"),
        account_id=account.account_id,
        instrument_id=instrument.id,
        asset_class=AssetClass.CRYPTO,
        side=Side.BUY,
        purpose=OrderPurpose.ENTRY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GOOD_TIL_CANCELED,
        quantity=Decimal("0.1"),
        limit_price=Decimal("100"),
        stop_price=None,
        created_at=NOW,
        expires_at=LATER,
        strategy_version="strategy-v1",
        config_hash=ConfigHash(HASH_B),
        data_hash=DataHash(HASH_A),
        exit_policy_version="exit-policy-v1",
    )
    review = BrokerOrderReview(
        normalized_order=intent,
        source="fixture",
        reviewed_at=NOW,
        expires_at=LATER,
        estimated_notional=Decimal("10"),
        estimated_fees=Decimal("0.01"),
        client_order_id=ClientOrderId("client-1"),
        outbound_payload_sha256=HASH_C,
        broker_review_id="review-at-broker",
    )
    broker_order = BrokerOrder(
        id=BrokerOrderId("broker-order-1"),
        account_id=account.account_id,
        intent_id=intent.id,
        client_order_id=ClientOrderId("client-1"),
        instrument_id=instrument.id,
        side=Side.BUY,
        purpose=OrderPurpose.ENTRY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.GOOD_TIL_CANCELED,
        requested_quantity=Decimal("0.1"),
        filled_quantity=Decimal("0"),
        limit_price=Decimal("100"),
        stop_price=None,
        state=OrderState.SUBMITTED,
        created_at=NOW,
        updated_at=NOW,
        data_hash=DataHash(HASH_A),
    )
    fill = Fill(
        id=FillId("fill-1"),
        broker_order_id=broker_order.id,
        account_id=account.account_id,
        instrument_id=instrument.id,
        side=Side.BUY,
        quantity=Decimal("0.05"),
        price=Decimal("100"),
        fee=Decimal("0.01"),
        occurred_at=NOW,
        data_hash=DataHash(HASH_A),
    )
    cancel_receipt = CancelReceipt(
        broker_order_id=broker_order.id,
        accepted=True,
        ambiguous=False,
        observed_at=NOW,
        reason_code="accepted",
    )
    broker_health = BrokerHealth(
        healthy=True,
        observed_at=NOW,
        latency_ms=Decimal("1.25"),
        reason_codes=(),
    )
    persisted_review = PersistedReviewedOrder(
        review_id=ReviewId("review-1"),
        submission_attempt_id=SubmissionAttemptId("attempt-1"),
        review=review,
        deduplication_key="dedupe-1",
        fencing_token=1,
        live_lease_evidence_hash=HASH_C,
        account_id=account.account_id,
        config_hash=ConfigHash(HASH_B),
    )
    check = CheckResult(
        code="fresh_quote",
        allowed=True,
        observed="1s",
        configured_limit="5s",
        reason="fresh",
        observed_at=NOW,
    )
    risk_evaluation = RiskEvaluation(
        intent_id=intent.id,
        allowed=True,
        checks=(check,),
        evaluated_at=NOW,
        config_hash=ConfigHash(HASH_B),
    )
    audit_event = AuditEvent(
        id=AuditEventId("audit-1"),
        occurred_at=NOW,
        category="risk",
        actor="system",
        reason_code="allowed",
        correlation_id=CorrelationId("correlation-1"),
        config_hash=ConfigHash(HASH_B),
        code_hash=CodeHash(HASH_C),
        data_hash=DataHash(HASH_A),
        details=(("intent_id", intent.id),),
    )
    return {
        "instrument": instrument,
        "quote": quote,
        "spread": spread,
        "bar": bar,
        "market_clock": market_clock,
        "buying_power": buying_power,
        "account": account,
        "position": position,
        "portfolio": portfolio,
        "intent": intent,
        "review": review,
        "broker_order": broker_order,
        "fill": fill,
        "cancel_receipt": cancel_receipt,
        "broker_health": broker_health,
        "persisted_review": persisted_review,
        "check": check,
        "risk_evaluation": risk_evaluation,
        "audit_event": audit_event,
    }


def test_record_fields_are_exact_and_stable() -> None:
    expected_fields = {
        AssetBuyingPower: ("asset_class", "amount"),
        AccountSnapshot: (
            "account_id",
            "provider_state",
            "equity",
            "cash",
            "buying_power",
            "restricted",
            "observed_at",
            "data_hash",
        ),
        Position: (
            "account_id",
            "instrument_id",
            "asset_class",
            "quantity",
            "average_price",
            "market_value",
            "observed_at",
            "data_hash",
        ),
        PortfolioSnapshot: (
            "account_id",
            "positions",
            "cash",
            "equity",
            "gross_exposure",
            "net_exposure",
            "crypto_exposure",
            "realized_pnl",
            "unrealized_pnl",
            "observed_at",
            "data_hash",
        ),
        Instrument: (
            "id",
            "symbol",
            "asset_class",
            "provider_status",
            "tradable",
            "fractional_eligible",
            "price_increment",
            "quantity_increment",
            "minimum_quantity",
            "minimum_notional",
            "maximum_quantity",
            "correlation_group",
            "observed_at",
            "data_hash",
        ),
        Quote: (
            "instrument_id",
            "observed_at",
            "bid",
            "ask",
            "last",
            "source",
            "data_hash",
            "freshness_verified",
            "timestamp_source",
        ),
        SpreadEstimate: (
            "instrument_id",
            "observed_at",
            "absolute",
            "percentage",
            "data_hash",
        ),
        Bar: (
            "instrument_id",
            "interval",
            "starts_at",
            "ends_at",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
            "data_hash",
            "interpolated",
        ),
        MarketClock: (
            "asset_class",
            "venue",
            "observed_at",
            "is_open",
            "halted",
            "trading_disabled",
            "cancel_only",
            "next_open_at",
            "next_close_at",
        ),
        OrderIntent: (
            "id",
            "account_id",
            "instrument_id",
            "asset_class",
            "side",
            "purpose",
            "order_type",
            "time_in_force",
            "quantity",
            "limit_price",
            "stop_price",
            "created_at",
            "expires_at",
            "strategy_version",
            "config_hash",
            "data_hash",
            "exit_policy_version",
        ),
        BrokerOrderReview: (
            "normalized_order",
            "source",
            "reviewed_at",
            "expires_at",
            "estimated_notional",
            "estimated_fees",
            "client_order_id",
            "outbound_payload_sha256",
            "broker_review_id",
        ),
        BrokerOrder: (
            "id",
            "account_id",
            "intent_id",
            "client_order_id",
            "instrument_id",
            "side",
            "purpose",
            "order_type",
            "time_in_force",
            "requested_quantity",
            "filled_quantity",
            "limit_price",
            "stop_price",
            "state",
            "created_at",
            "updated_at",
            "data_hash",
        ),
        Fill: (
            "id",
            "broker_order_id",
            "account_id",
            "instrument_id",
            "side",
            "quantity",
            "price",
            "fee",
            "occurred_at",
            "data_hash",
        ),
        CancelReceipt: (
            "broker_order_id",
            "accepted",
            "ambiguous",
            "observed_at",
            "reason_code",
        ),
        BrokerHealth: ("healthy", "observed_at", "latency_ms", "reason_codes"),
        PersistedReviewedOrder: (
            "review_id",
            "submission_attempt_id",
            "review",
            "deduplication_key",
            "fencing_token",
            "live_lease_evidence_hash",
            "account_id",
            "config_hash",
        ),
        CheckResult: (
            "code",
            "allowed",
            "observed",
            "configured_limit",
            "reason",
            "observed_at",
        ),
        RiskEvaluation: ("intent_id", "allowed", "checks", "evaluated_at", "config_hash"),
        AuditEvent: (
            "id",
            "occurred_at",
            "category",
            "actor",
            "reason_code",
            "correlation_id",
            "config_hash",
            "code_hash",
            "data_hash",
            "details",
        ),
    }

    for record_type, expected in expected_fields.items():
        assert tuple(field.name for field in fields(record_type)) == expected


@pytest.mark.parametrize("record", _valid_records().values(), ids=_valid_records().keys())
def test_domain_records_are_frozen_and_slotted(record: Any) -> None:
    first_field = fields(record)[0].name

    with pytest.raises(FrozenInstanceError):
        setattr(record, first_field, getattr(record, first_field))
    assert "__dict__" not in record.__class__.__slots__


@pytest.mark.parametrize(
    ("record_name", "field_name"),
    [
        ("buying_power", "amount"),
        ("account", "equity"),
        ("account", "cash"),
        ("position", "quantity"),
        ("position", "average_price"),
        ("position", "market_value"),
        ("portfolio", "cash"),
        ("portfolio", "equity"),
        ("portfolio", "gross_exposure"),
        ("portfolio", "net_exposure"),
        ("portfolio", "crypto_exposure"),
        ("portfolio", "realized_pnl"),
        ("portfolio", "unrealized_pnl"),
        ("instrument", "price_increment"),
        ("instrument", "quantity_increment"),
        ("instrument", "minimum_quantity"),
        ("instrument", "minimum_notional"),
        ("instrument", "maximum_quantity"),
        ("quote", "bid"),
        ("quote", "ask"),
        ("quote", "last"),
        ("spread", "absolute"),
        ("spread", "percentage"),
        ("bar", "open"),
        ("bar", "high"),
        ("bar", "low"),
        ("bar", "close"),
        ("bar", "volume"),
        ("intent", "quantity"),
        ("intent", "limit_price"),
        ("review", "estimated_notional"),
        ("review", "estimated_fees"),
        ("broker_order", "requested_quantity"),
        ("broker_order", "filled_quantity"),
        ("broker_order", "limit_price"),
        ("fill", "quantity"),
        ("fill", "price"),
        ("fill", "fee"),
        ("broker_health", "latency_ms"),
    ],
)
@pytest.mark.parametrize("invalid", [Decimal("NaN"), Decimal("Infinity")])
def test_every_decimal_field_rejects_nonfinite_values(
    record_name: str, field_name: str, invalid: Decimal
) -> None:
    record = _valid_records()[record_name]

    with pytest.raises(DomainValidationError):
        replace(record, **{field_name: invalid})


@pytest.mark.parametrize(
    ("record_name", "field_name"),
    [
        ("account", "observed_at"),
        ("position", "observed_at"),
        ("portfolio", "observed_at"),
        ("instrument", "observed_at"),
        ("quote", "observed_at"),
        ("spread", "observed_at"),
        ("bar", "starts_at"),
        ("bar", "ends_at"),
        ("market_clock", "observed_at"),
        ("market_clock", "next_open_at"),
        ("market_clock", "next_close_at"),
        ("intent", "created_at"),
        ("intent", "expires_at"),
        ("review", "reviewed_at"),
        ("review", "expires_at"),
        ("broker_order", "created_at"),
        ("broker_order", "updated_at"),
        ("fill", "occurred_at"),
        ("cancel_receipt", "observed_at"),
        ("broker_health", "observed_at"),
        ("check", "observed_at"),
        ("risk_evaluation", "evaluated_at"),
        ("audit_event", "occurred_at"),
    ],
)
def test_every_datetime_field_rejects_naive_values(record_name: str, field_name: str) -> None:
    record = _valid_records()[record_name]

    with pytest.raises(DomainValidationError):
        replace(record, **{field_name: datetime(2026, 7, 11, 12)})


@pytest.mark.parametrize(
    ("record_name", "field_name"),
    [
        ("account", "buying_power"),
        ("portfolio", "positions"),
        ("broker_health", "reason_codes"),
        ("risk_evaluation", "checks"),
        ("audit_event", "details"),
    ],
)
def test_collection_fields_reject_mutable_lists(record_name: str, field_name: str) -> None:
    record = _valid_records()[record_name]
    mutable_value = list(getattr(record, field_name))

    with pytest.raises(DomainValidationError):
        replace(record, **{field_name: mutable_value})


@pytest.mark.parametrize(
    ("record_name", "field_name"),
    [
        ("account", "data_hash"),
        ("position", "data_hash"),
        ("portfolio", "data_hash"),
        ("instrument", "data_hash"),
        ("quote", "data_hash"),
        ("spread", "data_hash"),
        ("bar", "data_hash"),
        ("intent", "config_hash"),
        ("intent", "data_hash"),
        ("review", "outbound_payload_sha256"),
        ("broker_order", "data_hash"),
        ("fill", "data_hash"),
        ("persisted_review", "live_lease_evidence_hash"),
        ("persisted_review", "config_hash"),
        ("risk_evaluation", "config_hash"),
        ("audit_event", "config_hash"),
        ("audit_event", "code_hash"),
        ("audit_event", "data_hash"),
    ],
)
def test_every_hash_field_rejects_non_sha256_values(record_name: str, field_name: str) -> None:
    record = _valid_records()[record_name]

    with pytest.raises(DomainValidationError):
        replace(record, **{field_name: "not-a-sha256"})


def test_optional_hash_accepts_none() -> None:
    event = replace(_valid_records()["audit_event"], data_hash=None)

    assert event.data_hash is None


def test_account_buying_power_requires_exactly_one_asset_class_value() -> None:
    account = _valid_records()["account"]
    duplicate = replace(account, buying_power=account.buying_power * 2)

    assert account.buying_power_for(AssetClass.CRYPTO) == Decimal("100")
    with pytest.raises(DomainValidationError):
        account.buying_power_for(AssetClass.EQUITY)
    with pytest.raises(DomainValidationError):
        duplicate.buying_power_for(AssetClass.CRYPTO)


@pytest.mark.parametrize(
    ("record_name", "changes"),
    [
        ("quote", {"bid": Decimal("102"), "ask": Decimal("101")}),
        ("bar", {"low": Decimal("101"), "open": Decimal("100")}),
        ("bar", {"starts_at": LATER, "ends_at": NOW}),
        ("instrument", {"price_increment": Decimal("0")}),
        ("instrument", {"maximum_quantity": Decimal("0.000000001")}),
        ("portfolio", {"gross_exposure": Decimal("10"), "net_exposure": Decimal("20")}),
        ("intent", {"quantity": Decimal("0")}),
        ("intent", {"expires_at": NOW}),
        ("review", {"expires_at": NOW}),
        ("broker_order", {"filled_quantity": Decimal("0.2")}),
        ("broker_order", {"updated_at": NOW - timedelta(seconds=1)}),
        ("fill", {"quantity": Decimal("0")}),
        ("cancel_receipt", {"accepted": True, "ambiguous": True}),
        ("broker_health", {"latency_ms": Decimal("-1")}),
        ("persisted_review", {"fencing_token": -1}),
        ("risk_evaluation", {"allowed": False}),
    ],
)
def test_cross_field_and_quantity_invariants(record_name: str, changes: dict[str, Any]) -> None:
    record = _valid_records()[record_name]

    with pytest.raises(DomainValidationError):
        replace(record, **changes)


def test_portfolio_position_account_must_match_snapshot_account() -> None:
    records = _valid_records()
    mismatched_position = replace(records["position"], account_id=AccountId("other"))

    with pytest.raises(DomainValidationError):
        replace(records["portfolio"], positions=(mismatched_position,))


def test_persisted_review_must_match_review_account_and_config() -> None:
    persisted = _valid_records()["persisted_review"]

    with pytest.raises(DomainValidationError):
        replace(persisted, account_id=AccountId("other"))
    with pytest.raises(DomainValidationError):
        replace(persisted, config_hash=ConfigHash(HASH_A))


def test_entry_intent_requires_versioned_exit_policy() -> None:
    intent = _valid_records()["intent"]

    with pytest.raises(DomainValidationError, match="exit policy"):
        replace(intent, purpose=OrderPurpose.ENTRY, exit_policy_version=None)


@pytest.mark.parametrize(
    "purpose",
    [OrderPurpose.STRATEGY_EXIT, OrderPurpose.PROTECTIVE_EXIT],
)
def test_non_entry_intent_may_omit_exit_policy(purpose: OrderPurpose) -> None:
    intent = _valid_records()["intent"]

    updated = replace(intent, purpose=purpose, exit_policy_version=None)

    assert updated.exit_policy_version is None


@pytest.mark.parametrize(
    ("order_type", "limit_price", "stop_price"),
    [
        (OrderType.MARKET, Decimal("100"), None),
        (OrderType.LIMIT, None, None),
        (OrderType.LIMIT, Decimal("100"), Decimal("99")),
        (OrderType.STOP_LOSS, None, None),
        (OrderType.STOP_LOSS, Decimal("100"), Decimal("99")),
        (OrderType.STOP_LIMIT, Decimal("100"), None),
    ],
)
def test_order_intent_price_fields_match_order_type(
    order_type: OrderType, limit_price: Decimal | None, stop_price: Decimal | None
) -> None:
    intent = _valid_records()["intent"]

    with pytest.raises(DomainValidationError):
        replace(
            intent,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
        )


def test_nested_audit_details_must_also_be_immutable_pairs() -> None:
    event = _valid_records()["audit_event"]

    with pytest.raises(DomainValidationError):
        replace(event, details=(("key", "value", "extra"),))
