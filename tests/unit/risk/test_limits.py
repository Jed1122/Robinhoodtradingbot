"""Unit tests for projected exposure limits."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.config import AppConfig, load_config
from trading_bot.domain import (
    AccountId,
    AssetClass,
    DomainValidationError,
    InstrumentId,
    InvalidDecimal,
    OrderIntentId,
)
from trading_bot.portfolio import aggregate_correlated_exposure
from trading_bot.risk import ExposureProjection, evaluate_exposure_limits

ROOT = Path(__file__).parents[3]
CONFIGS = ROOT / "configs"
OBSERVED_AT = datetime(2026, 7, 15, 4, 30, tzinfo=UTC)
EXPECTED_CODES = (
    "total_gross_exposure",
    "open_position_count",
    "position_notional",
    "correlated_group_exposure",
    "total_crypto_exposure",
    "single_crypto_exposure",
    "cash_reserve",
)


def settings(mode: str = "paper") -> AppConfig:
    return load_config(
        base_path=CONFIGS / "base.yaml",
        mode_path=CONFIGS / f"{mode}.yaml",
        safety_path=CONFIGS / "safety-envelope.yaml",
        environ={},
    ).config


def exposure_projection(**overrides: object) -> ExposureProjection:
    values: dict[str, object] = {
        "account_id": AccountId("paper-account"),
        "intent_id": OrderIntentId("paper-intent"),
        "instrument_id": InstrumentId("btc-usd"),
        "asset_class": AssetClass.CRYPTO,
        "correlation_group": "crypto-major",
        "equity": Decimal("100"),
        "authorized_risk_equity": Decimal("100"),
        "cash": Decimal("50"),
        "gross_exposure": Decimal("50"),
        "open_position_count": 3,
        "position_notional": Decimal("10"),
        "correlated_group_exposure": Decimal("20"),
        "crypto_exposure": Decimal("15"),
        "single_crypto_exposure": Decimal("8"),
        "observed_at": OBSERVED_AT,
    }
    values.update(overrides)
    return ExposureProjection(**values)  # type: ignore[arg-type]


def evaluate(projection: ExposureProjection, mode: str = "paper"):  # type: ignore[no-untyped-def]
    config = settings(mode)
    return evaluate_exposure_limits(
        projection,
        portfolio=config.portfolio,
        position_risk=config.position_risk,
        crypto=config.crypto,
    )


def test_safe_projection_allows_all_seven_checks() -> None:
    checks = evaluate(exposure_projection())

    assert tuple(check.code for check in checks) == EXPECTED_CODES
    assert all(check.allowed for check in checks)
    assert all(check.observed is not None for check in checks)
    assert all(check.configured_limit is not None for check in checks)
    assert all(check.observed_at is OBSERVED_AT for check in checks)
    assert all(check.reason == "within_limit" for check in checks)


def test_exact_limit_boundaries_are_allowed() -> None:
    checks = evaluate(
        exposure_projection(
            cash=Decimal("40"),
            gross_exposure=Decimal("60"),
            open_position_count=5,
            position_notional=Decimal("15"),
            correlated_group_exposure=Decimal("25"),
            crypto_exposure=Decimal("20"),
            single_crypto_exposure=Decimal("10"),
        )
    )

    assert all(check.allowed for check in checks)


@pytest.mark.parametrize(
    ("field", "value", "code", "observed", "configured"),
    [
        ("gross_exposure", Decimal("61"), "total_gross_exposure", "61", "60"),
        ("open_position_count", 6, "open_position_count", "6", "5"),
        ("position_notional", Decimal("16"), "position_notional", "16", "15"),
        (
            "correlated_group_exposure",
            Decimal("26"),
            "correlated_group_exposure",
            "26",
            "25",
        ),
        ("crypto_exposure", Decimal("21"), "total_crypto_exposure", "21", "20"),
        (
            "single_crypto_exposure",
            Decimal("11"),
            "single_crypto_exposure",
            "11",
            "10",
        ),
        ("cash", Decimal("39"), "cash_reserve", "39", "40"),
    ],
)
def test_each_exposure_limit_has_stable_denial_evidence(
    field: str,
    value: object,
    code: str,
    observed: str,
    configured: str,
) -> None:
    checks = evaluate(exposure_projection(**{field: value}))
    denied = tuple(check for check in checks if not check.allowed)

    assert len(denied) == 1
    assert denied[0].code == code
    assert denied[0].observed == observed
    assert denied[0].configured_limit == configured
    assert denied[0].reason == "limit_denied"


def test_micro_live_absolute_gross_cap_is_applied() -> None:
    checks = evaluate(
        exposure_projection(gross_exposure=Decimal("21")),
        mode="micro_live",
    )
    gross = checks[0]

    assert not gross.allowed
    assert gross.code == "total_gross_exposure"
    assert gross.configured_limit == "20"


def test_equity_gain_cannot_auto_scale_percentage_exposure_caps() -> None:
    checks = evaluate(
        exposure_projection(
            equity=Decimal("120"),
            authorized_risk_equity=Decimal("100"),
            cash=Decimal("60"),
            position_notional=Decimal("16"),
            correlated_group_exposure=Decimal("26"),
            crypto_exposure=Decimal("21"),
            single_crypto_exposure=Decimal("11"),
        )
    )
    by_code = {check.code: check for check in checks}

    assert not by_code["position_notional"].allowed
    assert by_code["position_notional"].configured_limit == "15"
    assert not by_code["correlated_group_exposure"].allowed
    assert by_code["correlated_group_exposure"].configured_limit == "25"
    assert not by_code["total_crypto_exposure"].allowed
    assert by_code["total_crypto_exposure"].configured_limit == "20"
    assert not by_code["single_crypto_exposure"].allowed
    assert by_code["single_crypto_exposure"].configured_limit == "10"
    assert by_code["cash_reserve"].configured_limit == "48"


def test_check_evidence_uses_canonical_decimal_text() -> None:
    checks = evaluate(
        exposure_projection(
            gross_exposure=Decimal("50.000"),
            position_notional=Decimal("1E+1"),
        )
    )

    assert checks[0].observed == "50"
    assert checks[2].observed == "10"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("equity", Decimal("-1")),
        ("account_id", ""),
        ("intent_id", ""),
        ("instrument_id", ""),
        ("asset_class", "crypto"),
        ("correlation_group", ""),
        ("authorized_risk_equity", Decimal("-1")),
        ("cash", Decimal("NaN")),
        ("gross_exposure", Decimal("Infinity")),
        ("position_notional", Decimal("1E+10000")),
        ("open_position_count", True),
        ("observed_at", datetime(2026, 7, 15, 4, 30)),
    ],
)
def test_exposure_projection_rejects_unsafe_values(field: str, value: object) -> None:
    with pytest.raises((DomainValidationError, InvalidDecimal)):
        exposure_projection(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("position_notional", Decimal("51")),
        ("correlated_group_exposure", Decimal("51")),
        ("crypto_exposure", Decimal("51")),
        ("single_crypto_exposure", Decimal("16")),
        ("cash", Decimal("101")),
    ],
)
def test_exposure_projection_rejects_internally_inconsistent_totals(
    field: str, value: Decimal
) -> None:
    with pytest.raises(DomainValidationError):
        exposure_projection(**{field: value})


def test_correlated_exposure_aggregation_is_exact_and_deterministic() -> None:
    notionals = (Decimal("10.10"), Decimal("2.20"), Decimal("0.70"))

    assert aggregate_correlated_exposure(notionals) == Decimal("13.00")
    assert aggregate_correlated_exposure(notionals) == Decimal("13.00")


def test_correlated_exposure_empty_group_is_zero() -> None:
    assert aggregate_correlated_exposure(()) == Decimal("0")


@pytest.mark.parametrize(
    "notionals",
    [
        [Decimal("1")],
        (Decimal("-1"),),
        (Decimal("NaN"),),
        (1,),
    ],
)
def test_correlated_exposure_rejects_unsafe_inputs(notionals: object) -> None:
    with pytest.raises((DomainValidationError, InvalidDecimal)):
        aggregate_correlated_exposure(notionals)  # type: ignore[arg-type]


def test_exposure_projection_is_immutable() -> None:
    projection = exposure_projection()

    with pytest.raises(FrozenInstanceError):
        projection.gross_exposure = Decimal("1")  # type: ignore[misc]


@pytest.mark.parametrize("argument", ["projection", "portfolio", "position_risk", "crypto"])
def test_limit_evaluation_rejects_noncanonical_dependency_types(argument: str) -> None:
    config = settings()
    values: dict[str, object] = {
        "projection": exposure_projection(),
        "portfolio": config.portfolio,
        "position_risk": config.position_risk,
        "crypto": config.crypto,
    }
    values[argument] = object()

    with pytest.raises(DomainValidationError):
        evaluate_exposure_limits(**values)  # type: ignore[arg-type]
