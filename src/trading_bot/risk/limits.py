"""Pure evaluation of config-owned projected exposure limits."""

from decimal import Decimal, localcontext
from typing import Final

from trading_bot.config import CryptoSettings, PortfolioSettings, PositionRiskSettings
from trading_bot.domain import (
    CheckResult,
    DomainValidationError,
    canonical_decimal_text,
    require_bounded_decimal,
)
from trading_bot.domain.decimal_utils import MAX_CANONICAL_DECIMAL_TEXT_LENGTH
from trading_bot.risk.models import ExposureProjection

_PERCENT_DENOMINATOR: Final = Decimal("100")
_ARITHMETIC_PRECISION: Final = MAX_CANONICAL_DECIMAL_TEXT_LENGTH * 4


def _evidence_text(value: Decimal | int) -> str:
    if type(value) is int:
        return str(value)
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    raise DomainValidationError("exposure evidence must be an exact Decimal or integer")


def _check(
    *,
    code: str,
    observed: Decimal | int,
    configured_limit: Decimal | int,
    allowed: bool,
    projection: ExposureProjection,
) -> CheckResult:
    return CheckResult(
        code=code,
        allowed=allowed,
        observed=_evidence_text(observed),
        configured_limit=_evidence_text(configured_limit),
        reason="within_limit" if allowed else "limit_denied",
        observed_at=projection.observed_at,
    )


def evaluate_exposure_limits(
    projection: ExposureProjection,
    *,
    portfolio: PortfolioSettings,
    position_risk: PositionRiskSettings,
    crypto: CryptoSettings,
) -> tuple[CheckResult, ...]:
    """Evaluate every projected exposure against the canonical config graph."""

    if type(projection) is not ExposureProjection:
        raise DomainValidationError("projection must be an ExposureProjection")
    if type(portfolio) is not PortfolioSettings:
        raise DomainValidationError("portfolio must be PortfolioSettings")
    if type(position_risk) is not PositionRiskSettings:
        raise DomainValidationError("position_risk must be PositionRiskSettings")
    if type(crypto) is not CryptoSettings:
        raise DomainValidationError("crypto must be CryptoSettings")

    for field_name, value in (
        ("max_total_gross_exposure_pct", portfolio.max_total_gross_exposure_pct),
        ("max_gross_exposure_usd", portfolio.max_gross_exposure_usd),
        ("min_cash_reserve_pct", portfolio.min_cash_reserve_pct),
        ("max_position_notional_pct", position_risk.max_position_notional_pct),
        (
            "max_correlated_group_exposure_pct",
            position_risk.max_correlated_group_exposure_pct,
        ),
        ("max_total_crypto_exposure_pct", crypto.max_total_crypto_exposure_pct),
        ("max_single_crypto_exposure_pct", crypto.max_single_crypto_exposure_pct),
    ):
        require_bounded_decimal(value, field_name, nonnegative=True)

    with localcontext() as context:
        context.prec = max(context.prec, _ARITHMETIC_PRECISION)
        risk_equity = min(projection.equity, projection.authorized_risk_equity)
        percentage_gross_cap = (
            risk_equity * portfolio.max_total_gross_exposure_pct / _PERCENT_DENOMINATOR
        )
        gross_cap = min(percentage_gross_cap, portfolio.max_gross_exposure_usd)
        position_cap = risk_equity * position_risk.max_position_notional_pct / _PERCENT_DENOMINATOR
        correlation_cap = (
            risk_equity * position_risk.max_correlated_group_exposure_pct / _PERCENT_DENOMINATOR
        )
        total_crypto_cap = risk_equity * crypto.max_total_crypto_exposure_pct / _PERCENT_DENOMINATOR
        single_crypto_cap = (
            risk_equity * crypto.max_single_crypto_exposure_pct / _PERCENT_DENOMINATOR
        )
        cash_reserve = projection.equity * portfolio.min_cash_reserve_pct / _PERCENT_DENOMINATOR

    return (
        _check(
            code="total_gross_exposure",
            observed=projection.gross_exposure,
            configured_limit=gross_cap,
            allowed=projection.gross_exposure <= gross_cap,
            projection=projection,
        ),
        _check(
            code="open_position_count",
            observed=projection.open_position_count,
            configured_limit=portfolio.max_open_positions,
            allowed=projection.open_position_count <= portfolio.max_open_positions,
            projection=projection,
        ),
        _check(
            code="position_notional",
            observed=projection.position_notional,
            configured_limit=position_cap,
            allowed=projection.position_notional <= position_cap,
            projection=projection,
        ),
        _check(
            code="correlated_group_exposure",
            observed=projection.correlated_group_exposure,
            configured_limit=correlation_cap,
            allowed=projection.correlated_group_exposure <= correlation_cap,
            projection=projection,
        ),
        _check(
            code="total_crypto_exposure",
            observed=projection.crypto_exposure,
            configured_limit=total_crypto_cap,
            allowed=projection.crypto_exposure <= total_crypto_cap,
            projection=projection,
        ),
        _check(
            code="single_crypto_exposure",
            observed=projection.single_crypto_exposure,
            configured_limit=single_crypto_cap,
            allowed=projection.single_crypto_exposure <= single_crypto_cap,
            projection=projection,
        ),
        _check(
            code="cash_reserve",
            observed=projection.cash,
            configured_limit=cash_reserve,
            allowed=projection.cash >= cash_reserve,
            projection=projection,
        ),
    )


__all__ = ["evaluate_exposure_limits"]
