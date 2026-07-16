"""Conservative, unit-consistent position sizing."""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Final, Self

from trading_bot.config import ActivitySettings, PositionRiskSettings
from trading_bot.domain import (
    DomainValidationError,
    Instrument,
    quantize_down,
    require_bounded_decimal,
)
from trading_bot.domain.decimal_utils import MAX_CANONICAL_DECIMAL_TEXT_LENGTH

_ZERO: Final = Decimal("0")
_PERCENT_DENOMINATOR: Final = Decimal("100")
_ARITHMETIC_PRECISION: Final = MAX_CANONICAL_DECIMAL_TEXT_LENGTH * 4
_DENIAL_CODES: Final = frozenset(
    {
        "below_minimum_notional",
        "final_limit_validation_failed",
        "invalid_stop_or_entry_price",
        "quantity_below_increment",
    }
)


@dataclass(frozen=True, slots=True, init=False)
class SizingRequest:
    """Config-bound quantities needed for one deterministic sizing decision."""

    reconciled_equity: Decimal
    authorized_risk_equity: Decimal
    risk_pct: Decimal
    stop_distance_per_unit: Decimal
    entry_price: Decimal
    max_position_notional_pct: Decimal
    max_order_notional: Decimal
    quantity_increment: Decimal
    minimum_notional: Decimal

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("SizingRequest must be constructed with from_config")

    @classmethod
    def from_config(
        cls,
        *,
        reconciled_equity: Decimal,
        authorized_risk_equity: Decimal,
        stop_distance_per_unit: Decimal,
        entry_price: Decimal,
        instrument: Instrument,
        position_risk: PositionRiskSettings,
        activity: ActivitySettings,
    ) -> Self:
        """Resolve every threshold from canonical config and instrument metadata."""

        if type(instrument) is not Instrument:
            raise DomainValidationError("instrument must be an Instrument")
        if type(position_risk) is not PositionRiskSettings:
            raise DomainValidationError("position_risk must be PositionRiskSettings")
        if type(activity) is not ActivitySettings:
            raise DomainValidationError("activity must be ActivitySettings")

        instance = object.__new__(cls)
        for field_name, value in (
            ("reconciled_equity", reconciled_equity),
            ("authorized_risk_equity", authorized_risk_equity),
            ("risk_pct", position_risk.max_risk_per_trade_pct),
            ("stop_distance_per_unit", stop_distance_per_unit),
            ("entry_price", entry_price),
            ("max_position_notional_pct", position_risk.max_position_notional_pct),
            ("max_order_notional", activity.max_order_notional_usd),
            ("quantity_increment", instrument.quantity_increment),
            ("minimum_notional", instrument.minimum_notional),
        ):
            object.__setattr__(instance, field_name, value)
        instance.__post_init__()
        return instance

    def __post_init__(self) -> None:
        require_bounded_decimal(
            self.reconciled_equity,
            "reconciled_equity",
            nonnegative=True,
        )
        require_bounded_decimal(
            self.authorized_risk_equity,
            "authorized_risk_equity",
            nonnegative=True,
        )
        require_bounded_decimal(self.risk_pct, "risk_pct", nonnegative=True)
        if self.risk_pct > _PERCENT_DENOMINATOR:
            raise DomainValidationError("risk_pct cannot exceed 100 whole-percent units")
        require_bounded_decimal(self.stop_distance_per_unit, "stop_distance_per_unit")
        require_bounded_decimal(self.entry_price, "entry_price")
        require_bounded_decimal(
            self.max_position_notional_pct,
            "max_position_notional_pct",
            nonnegative=True,
        )
        if self.max_position_notional_pct > _PERCENT_DENOMINATOR:
            raise DomainValidationError(
                "max_position_notional_pct cannot exceed 100 whole-percent units"
            )
        require_bounded_decimal(
            self.max_order_notional,
            "max_order_notional",
            nonnegative=True,
        )
        require_bounded_decimal(
            self.quantity_increment,
            "quantity_increment",
            positive=True,
        )
        require_bounded_decimal(
            self.minimum_notional,
            "minimum_notional",
            positive=True,
        )


def _sizing_caps(request: SizingRequest) -> tuple[Decimal, Decimal]:
    risk_equity = min(request.reconciled_equity, request.authorized_risk_equity)
    with localcontext() as context:
        context.prec = max(context.prec, _ARITHMETIC_PRECISION)
        risk_budget = risk_equity * request.risk_pct / _PERCENT_DENOMINATOR
        percentage_notional_cap = (
            risk_equity * request.max_position_notional_pct / _PERCENT_DENOMINATOR
        )
        max_notional = min(percentage_notional_cap, request.max_order_notional)
    return risk_budget, max_notional


@dataclass(frozen=True, slots=True, init=False)
class SizingDecision:
    """A zero-effect denial or a final bounded order size."""

    allowed: bool
    quantity: Decimal
    notional: Decimal
    risk: Decimal
    risk_budget: Decimal
    max_notional: Decimal
    denial_code: str | None

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("SizingDecision must be constructed with validate_final or denied")

    @classmethod
    def _create(
        cls,
        *,
        allowed: bool,
        quantity: Decimal,
        notional: Decimal,
        risk: Decimal,
        risk_budget: Decimal,
        max_notional: Decimal,
        denial_code: str | None,
    ) -> Self:
        instance = object.__new__(cls)
        for field_name, value in (
            ("allowed", allowed),
            ("quantity", quantity),
            ("notional", notional),
            ("risk", risk),
            ("risk_budget", risk_budget),
            ("max_notional", max_notional),
            ("denial_code", denial_code),
        ):
            object.__setattr__(instance, field_name, value)
        instance.__post_init__()
        return instance

    def __post_init__(self) -> None:
        if type(self.allowed) is not bool:
            raise DomainValidationError("allowed must be a boolean")
        for field_name, value in (
            ("quantity", self.quantity),
            ("notional", self.notional),
            ("risk", self.risk),
            ("risk_budget", self.risk_budget),
            ("max_notional", self.max_notional),
        ):
            require_bounded_decimal(
                value,
                field_name,
                nonnegative=True,
            )
        if self.allowed:
            if self.denial_code is not None:
                raise DomainValidationError("allowed sizing cannot have a denial code")
            if self.quantity <= 0:
                raise DomainValidationError("allowed sizing requires positive quantity")
            if self.notional <= 0:
                raise DomainValidationError("allowed sizing requires positive notional")
            if self.risk <= 0:
                raise DomainValidationError("allowed sizing requires positive risk")
            if self.risk > self.risk_budget:
                raise DomainValidationError("allowed sizing risk cannot exceed risk_budget")
            if self.notional > self.max_notional:
                raise DomainValidationError("allowed sizing notional cannot exceed max_notional")
        else:
            if self.denial_code not in _DENIAL_CODES:
                raise DomainValidationError("denied sizing requires a stable denial code")
            if self.quantity != 0 or self.notional != 0 or self.risk != 0:
                raise DomainValidationError("denied sizing cannot retain an economic effect")

    @classmethod
    def denied(
        cls,
        denial_code: str,
        *,
        risk_budget: Decimal,
        max_notional: Decimal,
    ) -> "SizingDecision":
        return cls._create(
            allowed=False,
            quantity=_ZERO,
            notional=_ZERO,
            risk=_ZERO,
            risk_budget=risk_budget,
            max_notional=max_notional,
            denial_code=denial_code,
        )

    @classmethod
    def validate_final(
        cls,
        *,
        quantity: Decimal,
        request: SizingRequest,
    ) -> "SizingDecision":
        """Recompute economic values and reject any quantity outside canonical caps."""

        if type(request) is not SizingRequest:
            raise DomainValidationError("request must be a SizingRequest")
        risk_budget, max_notional = _sizing_caps(request)
        if request.stop_distance_per_unit <= 0 or request.entry_price <= 0:
            return cls.denied(
                "invalid_stop_or_entry_price",
                risk_budget=risk_budget,
                max_notional=max_notional,
            )
        require_bounded_decimal(quantity, "quantity", nonnegative=True)
        if quantity <= 0:
            return cls.denied(
                "quantity_below_increment",
                risk_budget=risk_budget,
                max_notional=max_notional,
            )
        with localcontext() as context:
            context.prec = max(context.prec, _ARITHMETIC_PRECISION)
            notional = quantity * request.entry_price
            risk = quantity * request.stop_distance_per_unit
        if risk > risk_budget or notional > max_notional:
            return cls.denied(
                "final_limit_validation_failed",
                risk_budget=risk_budget,
                max_notional=max_notional,
            )
        if notional < request.minimum_notional:
            return cls.denied(
                "below_minimum_notional",
                risk_budget=risk_budget,
                max_notional=max_notional,
            )
        return cls._create(
            allowed=True,
            quantity=quantity,
            notional=notional,
            risk=risk,
            risk_budget=risk_budget,
            max_notional=max_notional,
            denial_code=None,
        )


def size_position(request: SizingRequest) -> SizingDecision:
    """Size from stop risk and notional caps, always rounding exposure downward."""

    if type(request) is not SizingRequest:
        raise DomainValidationError("request must be a SizingRequest")

    risk_budget, max_notional = _sizing_caps(request)
    with localcontext() as context:
        context.prec = max(context.prec, _ARITHMETIC_PRECISION)
        if request.stop_distance_per_unit <= 0 or request.entry_price <= 0:
            return SizingDecision.denied(
                "invalid_stop_or_entry_price",
                risk_budget=risk_budget,
                max_notional=max_notional,
            )

        risk_quantity = risk_budget / request.stop_distance_per_unit
        notional_quantity = max_notional / request.entry_price
        quantity = quantize_down(
            min(risk_quantity, notional_quantity),
            request.quantity_increment,
        )
        if quantity <= 0:
            return SizingDecision.denied(
                "quantity_below_increment",
                risk_budget=risk_budget,
                max_notional=max_notional,
            )

    return SizingDecision.validate_final(quantity=quantity, request=request)


__all__ = ["SizingDecision", "SizingRequest", "size_position"]
