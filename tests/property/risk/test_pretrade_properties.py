"""Property tests for fail-closed pretrade invariants."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.unit.risk.test_pretrade import (
    NOW,
    costs,
    reviewed_order,
    valid_harness,
    with_initial,
)
from trading_bot.domain import (
    DomainValidationError,
    InvalidDecimal,
    OrderIntentId,
)
from trading_bot.risk.pretrade import FinalPretradeContext, PretradeCheckCode

BASE = valid_harness()


def denied(
    code: PretradeCheckCode,
    *,
    context: FinalPretradeContext = BASE.context,
) -> bool:
    result = BASE.engine.evaluate_final(context)
    return not {check.code: check for check in result.checks}[code].allowed


@given(elapsed_microseconds=st.integers(min_value=5_000_001, max_value=3_600_000_000))
@settings(max_examples=200)
def test_every_quote_older_than_the_exact_limit_is_denied(
    elapsed_microseconds: int,
) -> None:
    stale_quote = replace(
        BASE.context.initial.quote,
        observed_at=NOW - timedelta(microseconds=elapsed_microseconds),
    )
    context = with_initial(
        BASE.context,
        quote=stale_quote,
        costs=costs(BASE.context.initial.intent, stale_quote),
    )

    assert denied(PretradeCheckCode.MARKET_DATA_FRESHNESS, context=context)


@given(flag=st.sampled_from(("halted", "trading_disabled", "cancel_only")))
def test_every_disabled_market_state_is_denied(flag: str) -> None:
    clock = replace(
        BASE.context.initial.market_clock,
        **{flag: True},  # type: ignore[arg-type]
    )
    context = with_initial(BASE.context, market_clock=clock)

    assert denied(PretradeCheckCode.MARKET_HALT, context=context)


@given(gross=st.decimals(min_value=Decimal("60.01"), max_value=Decimal("100"), places=2))
@settings(max_examples=200)
def test_every_projected_gross_exposure_above_cap_is_denied(gross: Decimal) -> None:
    projection = replace(
        BASE.context.initial.projection,
        cash=Decimal("0"),
        gross_exposure=gross,
    )
    context = with_initial(BASE.context, projection=projection)

    assert denied(PretradeCheckCode.POSITION_CAP, context=context)


@given(cash=st.decimals(min_value=Decimal("0"), max_value=Decimal("39.99"), places=2))
@settings(max_examples=200)
def test_every_projected_cash_value_below_reserve_is_denied(cash: Decimal) -> None:
    context = with_initial(
        BASE.context,
        projection=replace(BASE.context.initial.projection, cash=cash),
    )

    assert denied(PretradeCheckCode.CASH_RESERVE, context=context)


@given(duplicate_count=st.integers(min_value=1, max_value=20))
def test_any_same_purpose_pending_intent_conflict_is_denied(
    duplicate_count: int,
) -> None:
    pending = tuple(
        replace(
            BASE.context.initial.intent,
            id=OrderIntentId(f"duplicate-{index}"),
        )
        for index in range(duplicate_count)
    )
    context = with_initial(BASE.context, local_pending_intents=pending)

    assert denied(PretradeCheckCode.DUPLICATE_ORDER, context=context)


@given(raw_hash=st.binary(min_size=32, max_size=32))
@settings(max_examples=200)
def test_any_rebuilt_review_hash_mismatch_is_denied(raw_hash: bytes) -> None:
    expected = BASE.context.reviewed_order.outbound_payload_sha256
    candidate = raw_hash.hex()
    if candidate == expected:
        candidate = ("0" if candidate[0] != "0" else "1") + candidate[1:]
    context = replace(
        BASE.context,
        reviewed_order=replace(
            BASE.context.reviewed_order,
            outbound_payload_sha256=candidate,
        ),
    )

    assert denied(PretradeCheckCode.REVIEW_MATCH, context=context)


@given(
    invalid_price=st.sampled_from(
        (
            Decimal("-1"),
            Decimal("0"),
            Decimal("NaN"),
            Decimal("Infinity"),
            Decimal("-Infinity"),
        )
    )
)
def test_negative_or_nonfinite_executable_prices_cannot_enter_context(
    invalid_price: Decimal,
) -> None:
    with pytest.raises((DomainValidationError, InvalidDecimal)):
        replace(BASE.context.initial.quote, ask=invalid_price)


@given(slippage=st.decimals(min_value=Decimal("0"), max_value=Decimal("0.50"), places=4))
@settings(max_examples=200)
def test_allowed_final_evaluation_always_contains_exactly_24_allowed_checks(
    slippage: Decimal,
) -> None:
    estimate = costs(
        BASE.context.initial.intent,
        BASE.context.initial.quote,
        slippage_pct=slippage,
        expected_gross_edge_usd=Decimal("1"),
    )
    context = with_initial(BASE.context, costs=estimate)
    context = replace(
        context,
        reviewed_order=reviewed_order(
            context.initial.intent,
            estimated_fees=estimate.fees_usd + estimate.commission_usd,
        ),
    )
    result = BASE.engine.evaluate_final(context)

    assert result.allowed
    assert len(result.checks) == 24
    assert all(check.allowed for check in result.checks)
