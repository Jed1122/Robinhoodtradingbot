"""Bounded, date-granularity research prices; never executable market marks.

QuantLib is an optional, separately locked research dependency. Its global evaluation
date is serialized and restored; objects never escape this module. Rates and volatility
are fractions (0.25 = 25%), unlike canonical risk config's whole-percent convention.
The model is flat-curve/constant-volatility Actual/365 with no intraday expiry support.
"""

import importlib
import math
import threading
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from trading_bot.domain.decimal_utils import DomainValidationError, require_bounded_decimal
from trading_bot.domain.options import ExerciseStyle, OptionContract, OptionKind, SettlementTiming

_QL_LOCK = threading.RLock()
_BACKEND_VERSION = "1.43"


@dataclass(frozen=True, slots=True)
class CashDividend:
    ex_date: date
    amount: Decimal

    def __post_init__(self) -> None:
        if type(self.ex_date) is not date:
            raise DomainValidationError("dividend ex-date must be a date")
        require_bounded_decimal(self.amount, "dividend amount", positive=True)


@dataclass(frozen=True, slots=True)
class PricingInput:
    contract: OptionContract
    valuation_date: date
    spot: Decimal
    volatility: Decimal
    risk_free_rate: Decimal
    dividend_yield: Decimal
    dividends: tuple[CashDividend, ...]

    def __post_init__(self) -> None:
        if type(self.contract) is not OptionContract or type(self.valuation_date) is not date:
            raise DomainValidationError("pricing requires a contract and valuation date")
        if not self.contract.available_at.date() <= self.valuation_date < self.contract.expiration:
            raise DomainValidationError("unavailable contract or unsupported expiry-day valuation")
        if self.contract.settlement_timing is not SettlementTiming.PM:
            raise DomainValidationError("AM settlement requires an unsupported time convention")
        for name, value in (
            ("spot", self.spot),
            ("volatility", self.volatility),
            ("risk_free_rate", self.risk_free_rate),
            ("dividend_yield", self.dividend_yield),
        ):
            require_bounded_decimal(value, name)
        # Numerical support domain, not an admission policy or a trading risk limit.
        if not Decimal("0.000001") <= self.spot <= Decimal("1000000000"):
            raise DomainValidationError("spot outside supported numerical domain")
        if not Decimal("0.000001") <= self.contract.strike <= Decimal("1000000000"):
            raise DomainValidationError("strike outside supported numerical domain")
        if not Decimal("0.0001") <= self.volatility <= Decimal("5"):
            raise DomainValidationError("volatility outside supported numerical domain")
        if not -1 <= self.risk_free_rate <= 1 or not 0 <= self.dividend_yield <= 1:
            raise DomainValidationError("rate outside supported numerical domain")
        if (self.contract.expiration - self.valuation_date).days > 3650:
            raise DomainValidationError("maturity exceeds numerical support domain")
        if type(self.dividends) is not tuple or len(self.dividends) > 120:
            raise DomainValidationError("dividend schedule must be a bounded tuple")
        previous = self.valuation_date
        for dividend in self.dividends:
            if type(dividend) is not CashDividend:
                raise DomainValidationError("invalid dividend schedule member")
            if not previous < dividend.ex_date < self.contract.expiration:
                raise DomainValidationError(
                    "dividend dates must be distinct, future and pre-expiry"
                )
            previous = dividend.ex_date
        if self.dividends:
            if self.contract.exercise_style is ExerciseStyle.EUROPEAN:
                raise DomainValidationError("analytical engine does not support discrete dividends")
            if self.dividend_yield != 0:
                raise DomainValidationError("do not combine dividend yield and discrete dividends")
            if sum((item.amount for item in self.dividends), Decimal(0)) >= self.spot:
                raise DomainValidationError("dividend schedule exhausts modeled spot")


@dataclass(frozen=True, slots=True)
class PricingSettings:
    time_steps: int
    space_steps: int
    spot_bump: Decimal
    volatility_bump: Decimal
    rate_bump: Decimal
    absolute_tolerance: Decimal
    relative_tolerance: Decimal

    def __post_init__(self) -> None:
        for grid_size in (self.time_steps, self.space_steps):
            if type(grid_size) is not int or not 25 <= grid_size <= 1000:
                raise DomainValidationError("finite-difference grid outside supported work bound")
        for name, value in (
            ("spot_bump", self.spot_bump),
            ("volatility_bump", self.volatility_bump),
            ("rate_bump", self.rate_bump),
        ):
            require_bounded_decimal(value, name, positive=True)
        if not Decimal("0.0000000001") <= self.spot_bump <= Decimal("100000000"):
            raise DomainValidationError("spot bump outside numerical support domain")
        if any(
            not Decimal("0.00001") <= bump <= Decimal("0.1")
            for bump in (self.volatility_bump, self.rate_bump)
        ):
            raise DomainValidationError("rate or volatility bump outside numerical support domain")
        for tolerance in (self.absolute_tolerance, self.relative_tolerance):
            require_bounded_decimal(tolerance, "convergence tolerance", positive=True)
            if not Decimal("0.00000001") <= tolerance <= Decimal("0.001"):
                raise DomainValidationError("convergence tolerance outside validated bounds")


@dataclass(frozen=True, slots=True)
class OptionGreeks:
    """Per one underlying share, not multiplied by contract or position quantity."""

    delta_per_share: Decimal
    gamma_per_share_per_dollar: Decimal
    vega_per_vol_point: Decimal
    theta_per_calendar_day: Decimal
    rho_per_rate_point: Decimal


def price(request: PricingInput, settings: PricingSettings) -> Decimal:
    """Premium per share; callers apply the exact contract multiplier separately.

    Missing/version-mismatched backends and unsupported assumptions raise; there is no
    fallback model. Dividends must already have passed point-in-time provenance checks.
    """
    if type(request) is not PricingInput or type(settings) is not PricingSettings:
        raise DomainValidationError("invalid pricing request")
    value = _raw_price(request, settings, refinement=1)
    if request.contract.exercise_style is ExerciseStyle.AMERICAN:
        refined = _raw_price(request, settings, refinement=2)
        tolerance = max(settings.absolute_tolerance, settings.relative_tolerance * abs(refined))
        if abs(refined - value) > tolerance:
            raise DomainValidationError("finite-difference price did not converge")
        value = refined
        if (
            request.contract.kind is OptionKind.CALL
            and request.dividend_yield == 0
            and not request.dividends
            and request.risk_free_rate >= 0
        ):
            european = replace(
                request, contract=replace(request.contract, exercise_style=ExerciseStyle.EUROPEAN)
            )
            reference = _raw_price(european, settings, refinement=1)
            if abs(value - reference) > tolerance:
                raise DomainValidationError("American call violates analytical consistency")
        intrinsic = max(
            Decimal(0),
            (request.spot - request.contract.strike)
            * (1 if request.contract.kind is OptionKind.CALL else -1),
        )
        if value + settings.absolute_tolerance < intrinsic:
            raise DomainValidationError("American price violates exercise lower bound")
    years = Decimal((request.contract.expiration - request.valuation_date).days) / 365
    upper = (
        request.spot
        if request.contract.kind is OptionKind.CALL
        else request.contract.strike
        * Decimal(str(math.exp(float(max(Decimal(0), -request.risk_free_rate) * years))))
    )
    if value > upper + settings.absolute_tolerance:
        raise DomainValidationError("research price violates financial upper bound")
    return value


def _raw_price(request: PricingInput, settings: PricingSettings, *, refinement: int) -> Decimal:
    try:
        ql = importlib.import_module("QuantLib")
    except ImportError:
        raise DomainValidationError("locked research pricing backend is unavailable") from None
    if ql.__version__ != _BACKEND_VERSION:
        raise DomainValidationError("unvalidated research pricing backend version")
    with _QL_LOCK:
        saved = ql.Settings.instance().evaluationDate
        try:
            today = ql.Date(
                request.valuation_date.day,
                request.valuation_date.month,
                request.valuation_date.year,
            )
            expiry = ql.Date(
                request.contract.expiration.day,
                request.contract.expiration.month,
                request.contract.expiration.year,
            )
            ql.Settings.instance().evaluationDate = today
            day_count = ql.Actual365Fixed()
            process = ql.BlackScholesMertonProcess(
                ql.QuoteHandle(ql.SimpleQuote(float(request.spot))),
                ql.YieldTermStructureHandle(
                    ql.FlatForward(today, float(request.dividend_yield), day_count)
                ),
                ql.YieldTermStructureHandle(
                    ql.FlatForward(today, float(request.risk_free_rate), day_count)
                ),
                ql.BlackVolTermStructureHandle(
                    ql.BlackConstantVol(
                        today, ql.NullCalendar(), float(request.volatility), day_count
                    )
                ),
            )
            payoff = ql.PlainVanillaPayoff(
                ql.Option.Call if request.contract.kind is OptionKind.CALL else ql.Option.Put,
                float(request.contract.strike),
            )
            if request.contract.exercise_style is ExerciseStyle.EUROPEAN:
                exercise = ql.EuropeanExercise(expiry)
                engine = ql.AnalyticEuropeanEngine(process)
            else:
                exercise = ql.AmericanExercise(today, expiry)
                dividends = ql.DividendVector(
                    [
                        ql.Date(d.ex_date.day, d.ex_date.month, d.ex_date.year)
                        for d in request.dividends
                    ],
                    [float(d.amount) for d in request.dividends],
                )
                engine = ql.FdBlackScholesVanillaEngine(
                    process,
                    dividends,
                    settings.time_steps * refinement,
                    settings.space_steps * refinement,
                )
            option = ql.VanillaOption(payoff, exercise)
            option.setPricingEngine(engine)
            value = float(option.NPV())
            if not math.isfinite(value) or value < 0:
                raise DomainValidationError("invalid numerical pricing result")
            return Decimal(str(value))
        except (RuntimeError, OverflowError, TypeError, ValueError):
            raise DomainValidationError("research pricing backend rejected input") from None
        finally:
            ql.Settings.instance().evaluationDate = saved


def greeks(request: PricingInput, settings: PricingSettings) -> OptionGreeks:
    """Central full-repricing differences, with forward one-calendar-day theta.

    An ex-dividend crossing is not an ordinary theta bump and is explicitly unsupported.
    Spot/vol/rate bumps must keep both sides inside the validated pricing domain.
    """
    if not Decimal("0.0001") <= settings.spot_bump / request.spot <= Decimal("0.01"):
        raise DomainValidationError("spot bump requires a resolvable relative scale")
    tomorrow = request.valuation_date + timedelta(days=1)
    if any(dividend.ex_date == tomorrow for dividend in request.dividends):
        raise DomainValidationError("theta across an ex-dividend date is unsupported")
    base = price(request, settings)

    def bumped(field: str, amount: Decimal) -> Decimal:
        if field == "spot":
            updated = replace(request, spot=request.spot + amount)
        elif field == "volatility":
            updated = replace(request, volatility=request.volatility + amount)
        else:
            updated = replace(request, risk_free_rate=request.risk_free_rate + amount)
        return price(updated, settings)

    up = bumped("spot", settings.spot_bump)
    down = bumped("spot", -settings.spot_bump)
    return OptionGreeks(
        (up - down) / (2 * settings.spot_bump),
        (up - 2 * base + down) / settings.spot_bump**2,
        (
            bumped("volatility", settings.volatility_bump)
            - bumped("volatility", -settings.volatility_bump)
        )
        / (2 * settings.volatility_bump)
        / 100,
        price(replace(request, valuation_date=tomorrow), settings) - base,
        (
            bumped("risk_free_rate", settings.rate_bump)
            - bumped("risk_free_rate", -settings.rate_bump)
        )
        / (2 * settings.rate_bump)
        / 100,
    )


def stress(
    request: PricingInput,
    settings: PricingSettings,
    *,
    spot_factor: Decimal,
    volatility_shift: Decimal,
) -> Decimal:
    """Return a fully repriced premium, not a delta/gamma approximation."""
    require_bounded_decimal(spot_factor, "spot factor", positive=True)
    require_bounded_decimal(volatility_shift, "volatility shift")
    return price(
        replace(
            request,
            spot=request.spot * spot_factor,
            volatility=request.volatility + volatility_shift,
        ),
        settings,
    )
