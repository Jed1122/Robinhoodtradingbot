"""Property tests for conservative position sizing."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from trading_bot.config import ActivitySettings, PositionRiskSettings
from trading_bot.domain import (
    AssetClass,
    DataHash,
    Instrument,
    InstrumentId,
    InvalidDecimal,
)
from trading_bot.portfolio import SizingRequest, size_position

POSITIVE_MONEY = st.decimals(
    min_value=Decimal("0.000001"),
    max_value=Decimal("1000000"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)
PERCENT = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("100"),
    places=4,
    allow_nan=False,
    allow_infinity=False,
)
OBSERVED_AT = datetime(2026, 7, 15, 4, 30, tzinfo=UTC)


def sizing_request(
    *,
    reconciled_equity: Decimal,
    authorized_risk_equity: Decimal,
    risk_pct: Decimal,
    stop_distance_per_unit: Decimal,
    entry_price: Decimal,
    max_position_notional_pct: Decimal,
    max_order_notional: Decimal,
    quantity_increment: Decimal,
    minimum_notional: Decimal,
) -> SizingRequest:
    position_risk = PositionRiskSettings(
        max_risk_per_trade_pct=risk_pct,
        max_position_notional_pct=max_position_notional_pct,
        max_correlated_group_exposure_pct=Decimal("100"),
        minimum_reward_to_initial_risk=Decimal("1"),
        averaging_down_allowed=False,
        pyramiding_allowed=False,
    )
    activity = ActivitySettings(
        max_new_orders_per_day=100,
        max_orders_per_symbol_per_day=100,
        minimum_minutes_between_new_orders=0,
        max_order_notional_usd=max_order_notional,
    )
    instrument = Instrument(
        id=InstrumentId("property-instrument"),
        symbol="PROPERTY",
        asset_class=AssetClass.CRYPTO,
        provider_status="active",
        tradable=True,
        fractional_eligible=True,
        price_increment=Decimal("0.000001"),
        quantity_increment=quantity_increment,
        minimum_quantity=quantity_increment,
        minimum_notional=minimum_notional,
        maximum_quantity=None,
        correlation_group="property",
        observed_at=OBSERVED_AT,
        data_hash=DataHash("a" * 64),
    )
    return SizingRequest.from_config(
        reconciled_equity=reconciled_equity,
        authorized_risk_equity=authorized_risk_equity,
        stop_distance_per_unit=stop_distance_per_unit,
        entry_price=entry_price,
        instrument=instrument,
        position_risk=position_risk,
        activity=activity,
    )


@st.composite
def valid_sizing_requests(draw: st.DrawFn) -> SizingRequest:
    return sizing_request(
        reconciled_equity=draw(POSITIVE_MONEY),
        authorized_risk_equity=draw(POSITIVE_MONEY),
        risk_pct=draw(PERCENT),
        stop_distance_per_unit=draw(POSITIVE_MONEY),
        entry_price=draw(POSITIVE_MONEY),
        max_position_notional_pct=draw(PERCENT),
        max_order_notional=draw(POSITIVE_MONEY),
        quantity_increment=draw(POSITIVE_MONEY),
        minimum_notional=draw(POSITIVE_MONEY),
    )


@given(request=valid_sizing_requests())
@settings(deadline=None, max_examples=500)
def test_approved_sizing_never_exceeds_any_budget(request: SizingRequest) -> None:
    decision = size_position(request)

    if decision.allowed:
        risk_equity = min(request.reconciled_equity, request.authorized_risk_equity)
        risk_cap = risk_equity * request.risk_pct / Decimal("100")
        percentage_notional_cap = risk_equity * request.max_position_notional_pct / Decimal("100")
        assert decision.risk <= risk_cap
        assert decision.notional <= percentage_notional_cap
        assert decision.notional <= request.max_order_notional
        assert decision.quantity % request.quantity_increment == 0
        assert decision.notional >= request.minimum_notional


@given(
    authorized=POSITIVE_MONEY,
    growth=POSITIVE_MONEY,
    risk_pct=PERCENT,
    stop=POSITIVE_MONEY,
    price=POSITIVE_MONEY,
    position_pct=PERCENT,
    order_cap=POSITIVE_MONEY,
    increment=POSITIVE_MONEY,
)
@settings(deadline=None, max_examples=300)
def test_equity_above_authorized_reference_never_increases_size(
    authorized: Decimal,
    growth: Decimal,
    risk_pct: Decimal,
    stop: Decimal,
    price: Decimal,
    position_pct: Decimal,
    order_cap: Decimal,
    increment: Decimal,
) -> None:
    common = {
        "authorized_risk_equity": authorized,
        "risk_pct": risk_pct,
        "stop_distance_per_unit": stop,
        "entry_price": price,
        "max_position_notional_pct": position_pct,
        "max_order_notional": order_cap,
        "quantity_increment": increment,
        "minimum_notional": Decimal("0.000001"),
    }
    baseline = size_position(sizing_request(reconciled_equity=authorized, **common))
    higher = size_position(sizing_request(reconciled_equity=authorized + growth, **common))

    assert higher.risk_budget == baseline.risk_budget
    assert higher.max_notional == baseline.max_notional
    assert higher.quantity == baseline.quantity
    assert higher.allowed is baseline.allowed


@given(request=valid_sizing_requests())
@settings(deadline=None, max_examples=300)
def test_sizing_is_deterministic(request: SizingRequest) -> None:
    assert size_position(request) == size_position(request)


@given(
    price=st.decimals(
        min_value=Decimal("-1000000"),
        max_value=Decimal("0"),
        places=6,
        allow_nan=False,
        allow_infinity=False,
    )
)
@settings(deadline=None, max_examples=200)
def test_nonpositive_entry_price_never_produces_an_allowed_size(price: Decimal) -> None:
    request = sizing_request(
        reconciled_equity=Decimal("100"),
        authorized_risk_equity=Decimal("100"),
        risk_pct=Decimal("0.5"),
        stop_distance_per_unit=Decimal("1"),
        entry_price=price,
        max_position_notional_pct=Decimal("15"),
        max_order_notional=Decimal("15"),
        quantity_increment=Decimal("0.001"),
        minimum_notional=Decimal("1"),
    )

    decision = size_position(request)

    assert not decision.allowed
    assert decision.denial_code == "invalid_stop_or_entry_price"


@given(price=st.sampled_from((Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"))))
def test_nonfinite_entry_price_is_rejected_before_sizing(price: Decimal) -> None:
    with pytest.raises(InvalidDecimal):
        sizing_request(
            reconciled_equity=Decimal("100"),
            authorized_risk_equity=Decimal("100"),
            risk_pct=Decimal("0.5"),
            stop_distance_per_unit=Decimal("1"),
            entry_price=price,
            max_position_notional_pct=Decimal("15"),
            max_order_notional=Decimal("15"),
            quantity_increment=Decimal("0.001"),
            minimum_notional=Decimal("1"),
        )
