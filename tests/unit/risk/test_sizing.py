"""Unit tests for conservative position sizing."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.config import AppConfig, load_config
from trading_bot.domain import (
    AssetClass,
    DataHash,
    DomainValidationError,
    Instrument,
    InstrumentId,
    InvalidDecimal,
)
from trading_bot.portfolio import SizingDecision, SizingRequest, size_position

ROOT = Path(__file__).parents[3]
CONFIGS = ROOT / "configs"
OBSERVED_AT = datetime(2026, 7, 15, 4, 30, tzinfo=UTC)


def settings(mode: str = "paper") -> AppConfig:
    return load_config(
        base_path=CONFIGS / "base.yaml",
        mode_path=CONFIGS / f"{mode}.yaml",
        safety_path=CONFIGS / "safety-envelope.yaml",
        environ={},
    ).config


def instrument(**overrides: object) -> Instrument:
    values: dict[str, object] = {
        "id": InstrumentId("btc-usd"),
        "symbol": "BTC-USD",
        "asset_class": AssetClass.CRYPTO,
        "provider_status": "active",
        "tradable": True,
        "fractional_eligible": True,
        "price_increment": Decimal("0.01"),
        "quantity_increment": Decimal("0.001"),
        "minimum_quantity": Decimal("0.001"),
        "minimum_notional": Decimal("1"),
        "maximum_quantity": Decimal("100"),
        "correlation_group": "crypto-major",
        "observed_at": OBSERVED_AT,
        "data_hash": DataHash("a" * 64),
    }
    values.update(overrides)
    return Instrument(**values)  # type: ignore[arg-type]


def test_request_factory_resolves_canonical_config_and_instrument_values() -> None:
    config = settings("micro_live")

    request = SizingRequest.from_config(
        reconciled_equity=Decimal("100"),
        authorized_risk_equity=Decimal("100"),
        stop_distance_per_unit=Decimal("1"),
        entry_price=Decimal("10"),
        instrument=instrument(),
        position_risk=config.position_risk,
        activity=config.activity,
    )

    assert request.risk_pct == config.position_risk.max_risk_per_trade_pct
    assert request.max_position_notional_pct == config.position_risk.max_position_notional_pct
    assert request.max_order_notional == Decimal("5")
    assert request.quantity_increment == Decimal("0.001")
    assert request.minimum_notional == Decimal("1")


def test_request_cannot_be_constructed_without_canonical_factory() -> None:
    with pytest.raises(TypeError, match="from_config"):
        SizingRequest()


@pytest.mark.parametrize("argument", ["instrument", "position_risk", "activity"])
def test_request_factory_rejects_noncanonical_dependency_types(argument: str) -> None:
    config = settings()
    values: dict[str, object] = {
        "reconciled_equity": Decimal("100"),
        "authorized_risk_equity": Decimal("100"),
        "stop_distance_per_unit": Decimal("1"),
        "entry_price": Decimal("10"),
        "instrument": instrument(),
        "position_risk": config.position_risk,
        "activity": config.activity,
    }
    values[argument] = object()

    with pytest.raises(DomainValidationError):
        SizingRequest.from_config(**values)  # type: ignore[arg-type]


def sizing_request(**overrides: Decimal) -> SizingRequest:
    values: dict[str, Decimal] = {
        "reconciled_equity": Decimal("100"),
        "authorized_risk_equity": Decimal("100"),
        "stop_distance_per_unit": Decimal("1"),
        "entry_price": Decimal("10"),
    }
    for field_name in tuple(values):
        if field_name in overrides:
            values[field_name] = overrides.pop(field_name)

    config = settings()
    position_risk = config.position_risk.model_copy(
        update={
            "max_risk_per_trade_pct": overrides.pop(
                "risk_pct", config.position_risk.max_risk_per_trade_pct
            ),
            "max_position_notional_pct": overrides.pop(
                "max_position_notional_pct",
                config.position_risk.max_position_notional_pct,
            ),
        }
    )
    activity = config.activity.model_copy(
        update={
            "max_order_notional_usd": overrides.pop(
                "max_order_notional", config.activity.max_order_notional_usd
            )
        }
    )
    resolved_instrument = instrument(
        quantity_increment=overrides.pop("quantity_increment", Decimal("0.001")),
        minimum_notional=overrides.pop("minimum_notional", Decimal("1")),
    )
    if overrides:
        raise AssertionError(f"unsupported sizing override fields: {sorted(overrides)}")
    return SizingRequest.from_config(
        **values,
        instrument=resolved_instrument,
        position_risk=position_risk,
        activity=activity,
    )


def test_position_size_uses_smaller_risk_quantity_cap() -> None:
    decision = size_position(sizing_request())

    assert decision.allowed
    assert decision.quantity == Decimal("0.500")
    assert decision.notional == Decimal("5.000")
    assert decision.risk == Decimal("0.500")
    assert decision.risk_budget == Decimal("0.50")
    assert decision.max_notional == Decimal("15")
    assert decision.denial_code is None


def test_position_size_uses_smaller_percentage_notional_cap() -> None:
    decision = size_position(
        sizing_request(
            risk_pct=Decimal("50"),
            max_order_notional=Decimal("100"),
        )
    )

    assert decision.allowed
    assert decision.quantity == Decimal("1.500")
    assert decision.notional == Decimal("15.000")
    assert decision.max_notional == Decimal("15")


def test_absolute_order_notional_cap_cannot_be_bypassed() -> None:
    decision = size_position(
        sizing_request(
            risk_pct=Decimal("50"),
            stop_distance_per_unit=Decimal("0.10"),
            max_position_notional_pct=Decimal("100"),
            max_order_notional=Decimal("5"),
        )
    )

    assert decision.allowed
    assert decision.quantity == Decimal("0.500")
    assert decision.notional == Decimal("5.000")
    assert decision.max_notional == Decimal("5")


@pytest.mark.parametrize("reconciled_equity", ["120", "500", "1000"])
def test_authorized_reference_prevents_gain_or_deposit_based_auto_scaling(
    reconciled_equity: str,
) -> None:
    baseline = size_position(sizing_request())
    higher = size_position(sizing_request(reconciled_equity=Decimal(reconciled_equity)))

    assert higher.risk_budget == baseline.risk_budget
    assert higher.risk_budget == Decimal("0.50")
    assert higher.quantity == baseline.quantity


def test_reconciled_loss_reduces_risk_immediately() -> None:
    baseline = size_position(sizing_request())
    lower = size_position(sizing_request(reconciled_equity=Decimal("80")))

    assert lower.allowed
    assert lower.risk_budget == Decimal("0.40")
    assert lower.quantity < baseline.quantity


def test_quantity_is_rounded_down_to_broker_increment() -> None:
    decision = size_position(
        sizing_request(
            risk_pct=Decimal("1"),
            stop_distance_per_unit=Decimal("3"),
            quantity_increment=Decimal("0.01"),
        )
    )

    assert decision.allowed
    assert decision.quantity == Decimal("0.33")
    assert decision.risk == Decimal("0.99")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stop_distance_per_unit", Decimal("0")),
        ("stop_distance_per_unit", Decimal("-0.01")),
        ("entry_price", Decimal("0")),
        ("entry_price", Decimal("-1")),
    ],
)
def test_invalid_stop_or_entry_price_is_denied(field: str, value: Decimal) -> None:
    decision = size_position(sizing_request(**{field: value}))

    assert not decision.allowed
    assert decision.denial_code == "invalid_stop_or_entry_price"
    assert decision.quantity == Decimal("0")
    assert decision.notional == Decimal("0")
    assert decision.risk == Decimal("0")


def test_zero_sized_order_is_denied() -> None:
    decision = size_position(sizing_request(risk_pct=Decimal("0")))

    assert not decision.allowed
    assert decision.denial_code == "quantity_below_increment"


def test_order_below_broker_minimum_notional_is_denied() -> None:
    decision = size_position(sizing_request(minimum_notional=Decimal("5.001")))

    assert not decision.allowed
    assert decision.denial_code == "below_minimum_notional"
    assert decision.quantity == Decimal("0")
    assert decision.notional == Decimal("0")
    assert decision.risk == Decimal("0")


def test_order_at_broker_minimum_notional_is_allowed() -> None:
    decision = size_position(sizing_request(minimum_notional=Decimal("5")))

    assert decision.allowed
    assert decision.notional == Decimal("5.000")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reconciled_equity", Decimal("-1")),
        ("authorized_risk_equity", Decimal("-1")),
        ("risk_pct", Decimal("-0.01")),
        ("risk_pct", Decimal("100.01")),
        ("max_position_notional_pct", Decimal("100.01")),
        ("max_order_notional", Decimal("-1")),
        ("quantity_increment", Decimal("0")),
        ("minimum_notional", Decimal("0")),
        ("minimum_notional", Decimal("-1")),
    ],
)
def test_request_rejects_values_outside_structural_bounds(field: str, value: Decimal) -> None:
    with pytest.raises((DomainValidationError, InvalidDecimal)):
        sizing_request(**{field: value})


@pytest.mark.parametrize(
    "value",
    [
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1E+512"),
        Decimal("1E+10000"),
    ],
)
def test_request_rejects_unsafe_decimal_representations(value: Decimal) -> None:
    with pytest.raises(InvalidDecimal):
        sizing_request(entry_price=value)


def test_request_rejects_non_decimal_without_coercion() -> None:
    with pytest.raises(InvalidDecimal):
        sizing_request(entry_price=10)  # type: ignore[arg-type]


def test_sizing_records_are_immutable() -> None:
    request = sizing_request()
    decision = size_position(request)

    with pytest.raises(FrozenInstanceError):
        request.entry_price = Decimal("11")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        decision.quantity = Decimal("1")  # type: ignore[misc]


def test_size_position_rejects_non_request_without_rendering_it() -> None:
    with pytest.raises(DomainValidationError, match="request must be a SizingRequest"):
        size_position(object())  # type: ignore[arg-type]


def test_denied_decision_keeps_zero_economic_effect() -> None:
    decision = SizingDecision.denied(
        "quantity_below_increment",
        risk_budget=Decimal("1"),
        max_notional=Decimal("1"),
    )

    assert not decision.allowed
    assert decision.quantity == decision.notional == decision.risk == 0


def test_sizing_decision_cannot_be_constructed_without_validation_factory() -> None:
    with pytest.raises(TypeError, match="validate_final"):
        SizingDecision(
            allowed=True,
            quantity=Decimal("1"),
            notional=Decimal("0.01"),
            risk=Decimal("0.01"),
            risk_budget=Decimal("1"),
            max_notional=Decimal("1"),
            denial_code=None,
        )


@pytest.mark.parametrize("denial_code", ["unregistered_code", None])
def test_denied_factory_rejects_unregistered_codes(denial_code: str | None) -> None:
    with pytest.raises(DomainValidationError):
        SizingDecision.denied(
            denial_code,  # type: ignore[arg-type]
            risk_budget=Decimal("1"),
            max_notional=Decimal("1"),
        )


def test_final_validation_factory_denies_quantity_above_computed_caps() -> None:
    decision = SizingDecision.validate_final(
        quantity=Decimal("100"),
        request=sizing_request(),
    )

    assert not decision.allowed
    assert decision.denial_code == "final_limit_validation_failed"
    assert decision.quantity == decision.notional == decision.risk == 0


def test_final_validation_factory_rejects_noncanonical_request() -> None:
    with pytest.raises(DomainValidationError):
        SizingDecision.validate_final(
            quantity=Decimal("1"),
            request=object(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"allowed": 1},
        {"denial_code": "quantity_below_increment"},
        {"quantity": Decimal("0")},
        {"notional": Decimal("0")},
        {"risk": Decimal("0")},
        {"risk": Decimal("1.01")},
        {"notional": Decimal("10.01")},
        {
            "allowed": False,
            "quantity": Decimal("1"),
            "notional": Decimal("0"),
            "risk": Decimal("0"),
            "denial_code": "quantity_below_increment",
        },
    ],
)
def test_internal_decision_factory_defensively_rejects_inconsistent_states(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "allowed": True,
        "quantity": Decimal("1"),
        "notional": Decimal("10"),
        "risk": Decimal("1"),
        "risk_budget": Decimal("1"),
        "max_notional": Decimal("10"),
        "denial_code": None,
    }
    values.update(overrides)

    with pytest.raises(DomainValidationError):
        SizingDecision._create(**values)  # type: ignore[arg-type]


def test_final_validation_factory_denies_invalid_price_or_zero_quantity() -> None:
    invalid_price = SizingDecision.validate_final(
        quantity=Decimal("1"),
        request=sizing_request(entry_price=Decimal("0")),
    )
    zero_quantity = SizingDecision.validate_final(
        quantity=Decimal("0"),
        request=sizing_request(),
    )

    assert invalid_price.denial_code == "invalid_stop_or_entry_price"
    assert zero_quantity.denial_code == "quantity_below_increment"


def test_final_revalidation_denies_an_upward_quantization_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "trading_bot.portfolio.sizing.quantize_down",
        lambda value, increment: Decimal("1000"),
    )

    decision = size_position(sizing_request())

    assert not decision.allowed
    assert decision.denial_code == "final_limit_validation_failed"
