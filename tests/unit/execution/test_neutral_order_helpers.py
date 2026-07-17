"""Contract tests for broker-neutral order serialization and evidence helpers."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tests.unit.execution._fixtures import DATA_HASH, NOW, make_intent, make_review
from trading_bot.domain import (
    AccountId,
    BrokerOrder,
    BrokerOrderId,
    ClientOrderId,
    DataHash,
    DomainValidationError,
    ExecutionMode,
    InstrumentId,
    OrderId,
    OrderIntent,
    OrderIntentId,
    OrderPurpose,
    OrderState,
    OrderType,
    PersistedReviewedOrder,
    ReviewId,
    Side,
    SubmissionAttemptId,
    TimeInForce,
    canonical_order_intent_payload,
    canonical_order_intent_sha256,
)
from trading_bot.domain.order_matching import broker_order_matches_submission
from trading_bot.execution.idempotency import derive_deduplication_key
from trading_bot.persistence.evidence import (
    canonical_broker_order_response_sha256,
    canonical_review_response_sha256,
)

HASH_C = "c" * 64


def _sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _make_submission(intent: OrderIntent) -> PersistedReviewedOrder:
    return PersistedReviewedOrder(
        review_id=ReviewId("review-1"),
        submission_attempt_id=SubmissionAttemptId("attempt-1"),
        review=make_review(intent),
        deduplication_key=derive_deduplication_key(intent),
        fencing_token=0,
        execution_mode=ExecutionMode.PAPER,
        live_lease_id=None,
        live_lease_evidence_hash=None,
        account_id=intent.account_id,
        config_hash=intent.config_hash,
    )


def _make_broker_order(
    submission: PersistedReviewedOrder,
    **overrides: object,
) -> BrokerOrder:
    intent = submission.review.normalized_order
    values: dict[str, object] = {
        "id": OrderId("local-order-1"),
        "broker_order_id": BrokerOrderId("paper-order-1"),
        "account_id": intent.account_id,
        "intent_id": intent.id,
        "client_order_id": submission.review.client_order_id,
        "instrument_id": intent.instrument_id,
        "side": intent.side,
        "purpose": intent.purpose,
        "order_type": intent.order_type,
        "time_in_force": intent.time_in_force,
        "requested_quantity": intent.quantity,
        "filled_quantity": Decimal("0"),
        "limit_price": intent.limit_price,
        "stop_price": intent.stop_price,
        "state": OrderState.SUBMITTED,
        "created_at": NOW,
        "updated_at": NOW,
        "data_hash": DATA_HASH,
    }
    values.update(overrides)
    return BrokerOrder(**values)  # type: ignore[arg-type]


def test_order_intent_payload_and_hash_use_one_exact_canonical_schema() -> None:
    intent = make_intent(
        quantity=Decimal("0.0100"),
        limit_price=Decimal("100.0000"),
        created_at=datetime(2026, 7, 16, 17, 59, 0, 123456, tzinfo=UTC),
        expires_at=datetime(2026, 7, 16, 18, 5, 0, 654321, tzinfo=UTC),
    )
    expected: dict[str, object] = {
        "account_id": "paper-account",
        "asset_class": "crypto",
        "config_hash": "a" * 64,
        "created_at": "2026-07-16T17:59:00.123456Z",
        "data_hash": "b" * 64,
        "exit_policy_version": "protective-v1",
        "expires_at": "2026-07-16T18:05:00.654321Z",
        "instrument_id": "paper-btc-usd",
        "intent_id": "00000000-0000-4000-8000-000000000008",
        "limit_price": "100",
        "order_type": "limit",
        "purpose": "entry",
        "quantity": "0.01",
        "side": "buy",
        "stop_price": None,
        "strategy_version": "paper-strategy-v1",
        "time_in_force": "good_til_canceled",
    }

    assert canonical_order_intent_payload(intent) == expected
    assert canonical_order_intent_sha256(intent) == _sha256(expected)


def test_review_evidence_hash_uses_validated_fields_and_normalized_intent_digest() -> None:
    intent = make_intent(quantity=Decimal("0.0100"), limit_price=Decimal("100.000"))
    review = make_review(
        intent,
        estimated_notional=Decimal("1.000"),
        estimated_fees=Decimal("0.000"),
    )
    expected = {
        "broker_review_id": "paper-review-1",
        "client_order_id": "00000000-0000-4000-8000-000000000008",
        "estimated_fees": "0",
        "estimated_notional": "1",
        "expires_at": "2026-07-16T18:00:30.000000Z",
        "normalized_intent_sha256": canonical_order_intent_sha256(intent),
        "outbound_payload_sha256": review.outbound_payload_sha256,
        "reviewed_at": "2026-07-16T18:00:00.000000Z",
        "source": "paper",
    }

    assert canonical_review_response_sha256(review) == _sha256(expected)


def test_broker_order_evidence_hash_uses_local_and_provider_identities() -> None:
    submission = _make_submission(make_intent())
    order = _make_broker_order(submission)
    expected = {
        "account_id": "paper-account",
        "broker_order_id": "paper-order-1",
        "client_order_id": "00000000-0000-4000-8000-000000000008",
        "created_at": "2026-07-16T18:00:00.000000Z",
        "data_hash": "b" * 64,
        "filled_quantity": "0",
        "instrument_id": "paper-btc-usd",
        "intent_id": "00000000-0000-4000-8000-000000000008",
        "limit_price": "100",
        "local_order_id": "local-order-1",
        "order_type": "limit",
        "purpose": "entry",
        "requested_quantity": "0.01",
        "side": "buy",
        "state": "submitted",
        "stop_price": None,
        "time_in_force": "good_til_canceled",
        "updated_at": "2026-07-16T18:00:00.000000Z",
    }

    actual = canonical_broker_order_response_sha256(order)

    assert actual == _sha256(expected)
    assert actual != canonical_broker_order_response_sha256(
        replace(order, id=OrderId("local-order-2"))
    )
    assert actual != canonical_broker_order_response_sha256(
        replace(order, broker_order_id=BrokerOrderId("paper-order-2"))
    )


@pytest.mark.parametrize(
    ("helper", "message"),
    [
        (canonical_order_intent_payload, "intent must be an OrderIntent"),
        (canonical_order_intent_sha256, "intent must be an OrderIntent"),
        (canonical_review_response_sha256, "review must be a BrokerOrderReview"),
        (canonical_broker_order_response_sha256, "order must be a BrokerOrder"),
    ],
)
def test_canonical_helpers_reject_noncanonical_records(
    helper: object,
    message: str,
) -> None:
    with pytest.raises(DomainValidationError, match=message):
        helper(object())  # type: ignore[operator]


def test_idempotency_key_separates_exit_purposes_with_identical_identity_fields() -> None:
    strategy_exit = make_intent(
        side=Side.SELL,
        purpose=OrderPurpose.STRATEGY_EXIT,
        exit_policy_version="protective-v1",
    )
    protective_exit = replace(strategy_exit, purpose=OrderPurpose.PROTECTIVE_EXIT)

    assert derive_deduplication_key(strategy_exit) != derive_deduplication_key(protective_exit)


def test_broker_response_matching_accepts_the_exact_reviewed_economic_order() -> None:
    submission = _make_submission(
        make_intent(
            side=Side.SELL,
            purpose=OrderPurpose.STRATEGY_EXIT,
            order_type=OrderType.STOP_LIMIT,
            limit_price=Decimal("100"),
            stop_price=Decimal("90"),
            exit_policy_version="protective-v1",
        )
    )

    assert broker_order_matches_submission(_make_broker_order(submission), submission)


@pytest.mark.parametrize(
    ("case", "overrides"),
    [
        ("intent", {"intent_id": OrderIntentId("other-intent")}),
        ("account", {"account_id": AccountId("other-account")}),
        ("client", {"client_order_id": ClientOrderId("other-client")}),
        ("instrument", {"instrument_id": InstrumentId("other-instrument")}),
        (
            "direction",
            {"side": Side.BUY, "purpose": OrderPurpose.ENTRY},
        ),
        ("purpose", {"purpose": OrderPurpose.PROTECTIVE_EXIT}),
        (
            "order_type",
            {
                "order_type": OrderType.LIMIT,
                "stop_price": None,
            },
        ),
        ("time_in_force", {"time_in_force": TimeInForce.GOOD_FOR_DAY}),
        ("quantity", {"requested_quantity": Decimal("0.02")}),
        ("limit_price", {"limit_price": Decimal("101")}),
        ("stop_price", {"stop_price": Decimal("91")}),
    ],
)
def test_broker_response_matching_rejects_each_identity_or_economic_mismatch(
    case: str,
    overrides: dict[str, object],
) -> None:
    del case
    submission = _make_submission(
        make_intent(
            side=Side.SELL,
            purpose=OrderPurpose.STRATEGY_EXIT,
            order_type=OrderType.STOP_LIMIT,
            limit_price=Decimal("100"),
            stop_price=Decimal("90"),
            exit_policy_version="protective-v1",
        )
    )

    assert not broker_order_matches_submission(
        _make_broker_order(submission, **overrides),
        submission,
    )


def test_broker_response_matching_rejects_noncanonical_inputs() -> None:
    submission = _make_submission(make_intent())
    order = _make_broker_order(submission)

    with pytest.raises(DomainValidationError, match="order must be a BrokerOrder"):
        broker_order_matches_submission(object(), submission)  # type: ignore[arg-type]
    with pytest.raises(
        DomainValidationError,
        match="submission must be a PersistedReviewedOrder",
    ):
        broker_order_matches_submission(order, object())  # type: ignore[arg-type]


def test_evidence_hashes_normalize_equivalent_decimal_representations() -> None:
    intent = make_intent()
    scaled_intent = replace(
        intent,
        quantity=Decimal("0.01000"),
        limit_price=Decimal("100.000"),
    )
    review = make_review(intent)
    scaled_review = replace(
        review,
        normalized_order=scaled_intent,
        estimated_notional=Decimal("1.000"),
        estimated_fees=Decimal("0.000"),
    )
    order = _make_broker_order(_make_submission(intent))
    scaled_order = replace(
        order,
        requested_quantity=Decimal("0.01000"),
        filled_quantity=Decimal("0.000"),
        limit_price=Decimal("100.000"),
    )

    assert canonical_order_intent_sha256(intent) == canonical_order_intent_sha256(scaled_intent)
    assert canonical_review_response_sha256(review) == canonical_review_response_sha256(
        scaled_review
    )
    assert canonical_broker_order_response_sha256(order) == canonical_broker_order_response_sha256(
        scaled_order
    )


def test_broker_evidence_hash_changes_when_response_timestamps_change() -> None:
    submission = _make_submission(make_intent())
    order = _make_broker_order(submission)

    assert canonical_broker_order_response_sha256(order) != canonical_broker_order_response_sha256(
        replace(order, updated_at=NOW + timedelta(microseconds=1))
    )


def test_broker_evidence_hash_changes_when_data_provenance_changes() -> None:
    submission = _make_submission(make_intent())
    order = _make_broker_order(submission)

    assert canonical_broker_order_response_sha256(order) != canonical_broker_order_response_sha256(
        replace(order, data_hash=DataHash(HASH_C))
    )
