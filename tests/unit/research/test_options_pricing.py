"""Independent numerical expectations; fabricated inputs are not market evidence."""

import math
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from tests.unit.domain.test_options import contract
from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.domain.options import ExerciseStyle, OptionKind
from trading_bot.research.options_pricing import (
    CashDividend,
    PricingInput,
    PricingSettings,
    greeks,
    price,
    stress,
)

D = Decimal


def pricing_input(**changes: object) -> PricingInput:
    return replace(
        PricingInput(
            contract(exercise_style=ExerciseStyle.EUROPEAN),
            date(2026, 9, 18),
            D("100"),
            D("0.25"),
            D("0.04"),
            D("0.01"),
            (),
        ),
        **changes,
    )


def settings() -> PricingSettings:
    return PricingSettings(400, 400, D("0.01"), D("0.001"), D("0.0001"), D("0.0001"), D("0.001"))


@pytest.fixture
def backend() -> None:
    ql = pytest.importorskip("QuantLib")
    assert ql.__version__ == "1.43"


def normal(x: float) -> float:
    return (1 + math.erf(x / math.sqrt(2))) / 2


def independent_european(request: PricingInput) -> float:
    s, k, v, r, q = map(
        float,
        (
            request.spot,
            request.contract.strike,
            request.volatility,
            request.risk_free_rate,
            request.dividend_yield,
        ),
    )
    t = (request.contract.expiration - request.valuation_date).days / 365
    d1 = (math.log(s / k) + (r - q + v * v / 2) * t) / (v * math.sqrt(t))
    d2 = d1 - v * math.sqrt(t)
    call = s * math.exp(-q * t) * normal(d1) - k * math.exp(-r * t) * normal(d2)
    return (
        call
        if request.contract.kind is OptionKind.CALL
        else (call - s * math.exp(-q * t) + k * math.exp(-r * t))
    )


@pytest.mark.parametrize("kind", list(OptionKind))
def test_european_matches_independent_formula_and_put_call_parity(
    backend: None, kind: OptionKind
) -> None:
    request = pricing_input(contract=contract(kind=kind, exercise_style=ExerciseStyle.EUROPEAN))
    result = price(request, settings())
    assert abs(float(result) - independent_european(request)) < 1e-10


def test_american_put_early_exercise_and_grid_convergence(backend: None) -> None:
    request = pricing_input(
        contract=contract(kind=OptionKind.PUT),
        spot=D("70"),
        risk_free_rate=D("0.08"),
        dividend_yield=D("0"),
    )
    value = price(request, settings())
    european = price(
        replace(request, contract=replace(request.contract, exercise_style=ExerciseStyle.EUROPEAN)),
        settings(),
    )
    refined = price(request, replace(settings(), time_steps=800, space_steps=800))
    assert value >= D("30") - D("0.00001")
    assert value > european
    assert abs(refined - value) < D("0.01")


def test_discrete_dividend_is_modeled_for_american_and_rejected_for_analytic(backend: None) -> None:
    base = pricing_input(contract=contract(), dividend_yield=D("0"))
    dividend = CashDividend(date(2026, 10, 1), D("2"))
    with_dividend = replace(base, dividends=(dividend,))
    assert price(with_dividend, settings()) < price(base, settings())
    with pytest.raises(DomainValidationError, match="discrete"):
        replace(
            with_dividend, contract=replace(base.contract, exercise_style=ExerciseStyle.EUROPEAN)
        )


def test_greek_units_and_full_repricing_stress(backend: None) -> None:
    request = pricing_input()
    values = greeks(request, settings())
    step = D("0.02")
    independent_delta = (
        price(replace(request, spot=request.spot + step), settings())
        - price(replace(request, spot=request.spot - step), settings())
    ) / (2 * step)
    assert abs(values.delta_per_share - independent_delta) < D("0.00001")
    assert values.gamma_per_share_per_dollar > 0
    assert values.vega_per_vol_point > 0
    assert values.theta_per_calendar_day < 0
    assert values.rho_per_rate_point > 0
    shocked = stress(request, settings(), spot_factor=D("0.9"), volatility_shift=D("0.1"))
    expected = price(replace(request, spot=D("90"), volatility=D("0.35")), settings())
    assert shocked == expected


def test_european_greeks_match_independent_analytical_units(backend: None) -> None:
    request = pricing_input()
    result = greeks(request, settings())
    s, k, v, r, q = 100.0, 100.0, 0.25, 0.04, 0.01
    t = (request.contract.expiration - request.valuation_date).days / 365
    d1 = (math.log(s / k) + (r - q + v * v / 2) * t) / (v * math.sqrt(t))
    d2 = d1 - v * math.sqrt(t)
    density = math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi)
    expected = (
        math.exp(-q * t) * normal(d1),
        math.exp(-q * t) * density / (s * v * math.sqrt(t)),
        s * math.exp(-q * t) * density * math.sqrt(t) / 100,
        k * t * math.exp(-r * t) * normal(d2) / 100,
    )
    actual = (
        result.delta_per_share,
        result.gamma_per_share_per_dollar,
        result.vega_per_vol_point,
        result.rho_per_rate_point,
    )
    for measured, reference in zip(actual, expected, strict=True):
        assert abs(float(measured) - reference) < 1e-5


def test_quantlib_global_evaluation_date_is_restored(backend: None) -> None:
    import QuantLib as ql

    before = ql.Settings.instance().evaluationDate
    price(pricing_input(), settings())
    assert ql.Settings.instance().evaluationDate == before


@pytest.mark.parametrize("field", ["spot_bump", "volatility_bump", "rate_bump"])
def test_sub_resolution_bumps_are_not_silent_zero_greeks(field: str) -> None:
    with pytest.raises(DomainValidationError):
        replace(settings(), **{field: D("1e-30")})


def test_spot_bump_must_be_resolvable_relative_to_spot(backend: None) -> None:
    with pytest.raises(DomainValidationError, match="relative"):
        greeks(pricing_input(spot=D("1000000")), settings())


@pytest.mark.parametrize("years", [2, 10])
def test_unconverged_american_numerics_are_rejected(backend: None, years: int) -> None:
    from datetime import UTC, datetime, timedelta

    expiry = date(2026, 9, 18) + timedelta(days=365 * years)
    last = datetime(expiry.year, expiry.month, expiry.day, 20, tzinfo=UTC)
    request = pricing_input(
        contract=contract(
            expiration=expiry, last_trading_at=last, settlement_at=last + timedelta(days=3)
        ),
        volatility=D("5"),
        risk_free_rate=D("0"),
        dividend_yield=D("0"),
    )
    with pytest.raises(DomainValidationError):
        price(request, replace(settings(), time_steps=25, space_steps=25))


@pytest.mark.parametrize(
    "changes",
    [
        {"spot": 100.0},
        {"spot": D("NaN")},
        {"spot": D("0")},
        {"volatility": D("0")},
        {"volatility": D("5.1")},
        {"risk_free_rate": D("1.1")},
        {"valuation_date": date(2026, 10, 16)},
        {"valuation_date": date(2026, 9, 16)},
        {"dividends": []},
        {"dividends": (CashDividend(date(2026, 11, 1), D("1")),)},
    ],
)
def test_unsupported_inputs_fail_closed(changes: dict[str, object]) -> None:
    with pytest.raises((DomainValidationError, ValueError)):
        pricing_input(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"time_steps": True},
        {"time_steps": 1},
        {"space_steps": 10001},
        {"spot_bump": D("0")},
        {"volatility_bump": D("NaN")},
    ],
)
def test_numerical_work_and_bumps_are_bounded(changes: dict[str, object]) -> None:
    with pytest.raises(DomainValidationError):
        replace(settings(), **changes)
