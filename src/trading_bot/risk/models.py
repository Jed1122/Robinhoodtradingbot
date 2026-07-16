"""Immutable inputs for pure risk-limit evaluation."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_bot.clock import require_utc
from trading_bot.domain import DomainValidationError, require_bounded_decimal


@dataclass(frozen=True, slots=True)
class ExposureProjection:
    """Projected post-order exposure values at one UTC observation time."""

    equity: Decimal
    authorized_risk_equity: Decimal
    cash: Decimal
    gross_exposure: Decimal
    open_position_count: int
    position_notional: Decimal
    correlated_group_exposure: Decimal
    crypto_exposure: Decimal
    single_crypto_exposure: Decimal
    observed_at: datetime

    def __post_init__(self) -> None:
        for field_name, value in (
            ("equity", self.equity),
            ("authorized_risk_equity", self.authorized_risk_equity),
            ("cash", self.cash),
            ("gross_exposure", self.gross_exposure),
            ("position_notional", self.position_notional),
            ("correlated_group_exposure", self.correlated_group_exposure),
            ("crypto_exposure", self.crypto_exposure),
            ("single_crypto_exposure", self.single_crypto_exposure),
        ):
            require_bounded_decimal(
                value,
                field_name,
                nonnegative=True,
            )
        if type(self.open_position_count) is not int or self.open_position_count < 0:
            raise DomainValidationError("open_position_count must be a nonnegative integer")
        if self.cash > self.equity:
            raise DomainValidationError("cash cannot exceed equity")
        if self.position_notional > self.gross_exposure:
            raise DomainValidationError("position_notional cannot exceed gross_exposure")
        if self.correlated_group_exposure > self.gross_exposure:
            raise DomainValidationError("correlated_group_exposure cannot exceed gross_exposure")
        if self.crypto_exposure > self.gross_exposure:
            raise DomainValidationError("crypto_exposure cannot exceed gross_exposure")
        if self.single_crypto_exposure > self.crypto_exposure:
            raise DomainValidationError("single_crypto_exposure cannot exceed crypto_exposure")
        require_utc(self.observed_at)


__all__ = ["ExposureProjection"]
