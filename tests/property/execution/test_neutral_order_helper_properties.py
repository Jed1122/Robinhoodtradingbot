"""Property invariants for canonical neutral order helpers."""

from dataclasses import replace
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.unit.execution._fixtures import make_intent
from trading_bot.domain import (
    OrderIntentId,
    OrderPurpose,
    Side,
    canonical_order_intent_sha256,
)
from trading_bot.execution.idempotency import derive_deduplication_key


@given(
    quantity=st.integers(min_value=1, max_value=1_000_000),
    limit_price=st.integers(min_value=1, max_value=1_000_000),
    trailing_zeros=st.integers(min_value=1, max_value=12),
)
@settings(deadline=None, max_examples=100)
def test_order_intent_hash_is_invariant_to_decimal_scale(
    quantity: int,
    limit_price: int,
    trailing_zeros: int,
) -> None:
    canonical = make_intent(
        quantity=Decimal(quantity),
        limit_price=Decimal(limit_price),
    )
    suffix = "0" * trailing_zeros
    scaled = replace(
        canonical,
        quantity=Decimal(f"{quantity}.{suffix}"),
        limit_price=Decimal(f"{limit_price}.{suffix}"),
    )

    assert canonical_order_intent_sha256(canonical) == canonical_order_intent_sha256(scaled)


@given(raw_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=40))
@settings(deadline=None, max_examples=100)
def test_idempotency_key_always_separates_strategy_and_protective_exit_purpose(
    raw_id: str,
) -> None:
    strategy_exit = make_intent(
        id=OrderIntentId(raw_id),
        side=Side.SELL,
        purpose=OrderPurpose.STRATEGY_EXIT,
        exit_policy_version="protective-v1",
    )
    protective_exit = replace(strategy_exit, purpose=OrderPurpose.PROTECTIVE_EXIT)

    assert derive_deduplication_key(strategy_exit) != derive_deduplication_key(protective_exit)
