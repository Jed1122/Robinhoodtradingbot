"""Offline capital budgets and fee-aware sizing; no execution authority."""

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Context, Decimal, localcontext

from trading_bot.config import ActivitySettings, LoadedConfig
from trading_bot.config.capital_research import CapitalResearchAppConfig
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import (
    AssetClass,
    ConfigHash,
    DomainValidationError,
    Instrument,
    quantize_down,
    require_bounded_decimal,
)
from trading_bot.portfolio import SizingDecision, SizingRequest, size_position

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_CONTEXT = Context(prec=2048, rounding=ROUND_DOWN)


def _config(loaded: LoadedConfig) -> CapitalResearchAppConfig:
    with localcontext(_CONTEXT):
        return _restore_config(loaded)


def _restore_config(loaded: LoadedConfig) -> CapitalResearchAppConfig:
    if type(loaded) is not LoadedConfig:
        raise DomainValidationError("capital research requires canonical LoadedConfig")
    if type(loaded.config) is not CapitalResearchAppConfig:
        raise DomainValidationError("capital research profile required")
    if hash_loaded_config(loaded.config, loaded.safety_envelope) != (
        loaded.canonical_json,
        loaded.config_hash,
    ):
        raise DomainValidationError("capital research configuration identity changed")
    restored = restore_loaded_config(loaded.canonical_json, loaded.config_hash)
    if type(restored.config) is not CapitalResearchAppConfig:
        raise DomainValidationError("capital research profile required")
    return restored.config


@dataclass(frozen=True, slots=True)
class CapitalBudget:
    equity: Decimal
    max_notional: Decimal
    planned_risk_budget: Decimal
    cash_floor: Decimal
    daily_loss_budget: Decimal


def capital_budgets(loaded: LoadedConfig, equity: Decimal) -> CapitalBudget:
    """Current-equity research limits, not enlarged production order limits."""
    config = _config(loaded)
    require_bounded_decimal(equity, "equity", positive=True)
    policy = config.capital_research
    with localcontext(_CONTEXT):
        return CapitalBudget(
            equity,
            equity
            * min(
                policy.position_risk.max_position_notional_pct,
                policy.position_risk.max_correlated_group_exposure_pct,
            )
            / _HUNDRED,
            equity * policy.position_risk.max_risk_per_trade_pct / _HUNDRED,
            equity * policy.min_cash_reserve_pct / _HUNDRED,
            equity * policy.loss_limits.max_daily_loss_pct / _HUNDRED,
        )


@dataclass(frozen=True, slots=True)
class CapitalEntryDecision:
    allowed: bool
    quantity: Decimal
    notional: Decimal
    planned_risk_with_fees: Decimal
    cash_reservation: Decimal
    denial_code: str | None
    config_hash: ConfigHash
    execution_enabled: bool = field(default=False, init=False)
    evidence_promotable: bool = field(default=False, init=False)


def size_capital_entry(
    *,
    loaded: LoadedConfig,
    instrument: Instrument,
    equity: Decimal,
    settled_cash: Decimal,
    entry_price: Decimal,
    stop_distance: Decimal,
    fee_bound: Decimal | None,
    position_open: bool,
    daily_loss: Decimal,
) -> CapitalEntryDecision:
    """Size assumed instrument terms through the shared sizing implementation.

    Fees bound the whole episode and remain reserved. Stop risk is planned risk,
    not a guaranteed loss cap. This result cannot authorize a brokerage order.
    Cash-floor arithmetic assumes equity outside the new position remains cash;
    the caller must separately model unsettled obligations in a replay account.
    """
    config = _config(loaded)
    budget = capital_budgets(loaded, equity)
    if type(instrument) is not Instrument or type(position_open) is not bool:
        raise DomainValidationError("invalid capital sizing dependency type")
    instrument.__post_init__()
    for name, value in (
        ("settled_cash", settled_cash),
        ("daily_loss", daily_loss),
    ):
        require_bounded_decimal(value, name, nonnegative=True)
    for name, value in (
        ("entry_price", entry_price),
        ("stop_distance", stop_distance),
        ("quantity_increment", instrument.quantity_increment),
        ("minimum_quantity", instrument.minimum_quantity),
        ("minimum_notional", instrument.minimum_notional),
    ):
        require_bounded_decimal(value, name, positive=True)
    if instrument.maximum_quantity is not None:
        require_bounded_decimal(instrument.maximum_quantity, "maximum_quantity", positive=True)
    if settled_cash > equity:
        raise DomainValidationError("settled cash cannot exceed unleveraged research equity")
    if fee_bound is not None:
        require_bounded_decimal(fee_bound, "fee_bound", nonnegative=True)

    def deny(code: str) -> CapitalEntryDecision:
        return CapitalEntryDecision(False, _ZERO, _ZERO, _ZERO, _ZERO, code, loaded.config_hash)

    if position_open:
        return deny("position_already_open")
    if daily_loss >= budget.daily_loss_budget:
        return deny("daily_loss_breaker")
    if (
        instrument.asset_class is not AssetClass.EQUITY
        or instrument.symbol not in config.capital_research.universe
        or not instrument.tradable
        or instrument.provider_status != "active"
    ):
        return deny("unsupported_instrument")
    if fee_bound is None:
        return deny("unknown_fee_bound")

    with localcontext(_CONTEXT):
        if not instrument.fractional_eligible and instrument.quantity_increment % 1 != 0:
            return deny("inconsistent_whole_share_terms")
        if fee_bound >= budget.planned_risk_budget:
            return deny("fee_exhausts_planned_risk")
        available = min(settled_cash, equity - budget.cash_floor) - fee_bound
        if available <= 0:
            return deny("insufficient_cash")
        # Isolated research request; never mutate the canonical production graph.
        activity = ActivitySettings.model_validate(
            {**config.activity.model_dump(), "max_order_notional_usd": budget.max_notional}
        )
        request = SizingRequest.from_config(
            reconciled_equity=equity,
            authorized_risk_equity=equity,
            stop_distance_per_unit=stop_distance,
            entry_price=entry_price,
            instrument=instrument,
            position_risk=config.capital_research.position_risk,
            activity=activity,
        )
        initial = size_position(request)
        if not initial.allowed:
            return deny(initial.denial_code or "shared_sizing_denied")
        quantity = quantize_down(
            min(
                initial.quantity,
                (budget.planned_risk_budget - fee_bound) / stop_distance,
                available / entry_price,
                instrument.maximum_quantity
                if instrument.maximum_quantity is not None
                else initial.quantity,
            ),
            instrument.quantity_increment,
        )
        if quantity < instrument.minimum_quantity:
            return deny("below_minimum_quantity")
        final = SizingDecision.validate_final(quantity=quantity, request=request)
        if not final.allowed:
            return deny(final.denial_code or "shared_sizing_denied")
        risk = final.risk + fee_bound
        reservation = final.notional + fee_bound
        if (
            risk > budget.planned_risk_budget
            or reservation > settled_cash
            or equity - reservation < budget.cash_floor
        ):
            return deny("final_capital_guard")
        return CapitalEntryDecision(
            True, quantity, final.notional, risk, reservation, None, loaded.config_hash
        )


@dataclass(frozen=True, slots=True)
class CapitalFeasibilityTier:
    budget: CapitalBudget
    compute_12_monthly_annual_equity_pct: Decimal


@dataclass(frozen=True, slots=True)
class CapitalFeasibilityReport:
    config_hash: ConfigHash
    tiers: tuple[CapitalFeasibilityTier, ...]
    schema: str = field(default="etf-capital-feasibility-v1", init=False)
    actual_recurring_data_cost: None = field(default=None, init=False)
    actual_customer_fee_cost: None = field(default=None, init=False)
    actual_tax_cost: None = field(default=None, init=False)
    broker_fractional_route_verified: bool = field(default=False, init=False)
    execution_enabled: bool = field(default=False, init=False)
    evidence_promotable: bool = field(default=False, init=False)
    operating_scenarios: tuple[str, ...] = field(
        default=("assumed_zero_data_and_compute", "assumed_zero_data_12_usd_monthly_compute"),
        init=False,
    )
    limitations: tuple[str, ...] = field(
        default=(
            "No price inputs or executable quantities are established by this report.",
            "Free historical SIP access and fresh consolidated quotes remain unverified.",
            "Actual subscription, infrastructure, customer fees and tax costs remain unknown.",
            "Instrument terms and stop execution require independent evidence.",
            "No economic result or production risk expansion is established.",
        ),
        init=False,
    )


def capital_feasibility(loaded: LoadedConfig) -> CapitalFeasibilityReport:
    config = _config(loaded)
    with localcontext(_CONTEXT):
        tiers = tuple(
            CapitalFeasibilityTier(
                capital_budgets(loaded, equity), Decimal("144") / equity * _HUNDRED
            )
            for equity in config.capital_research.capital_tiers
        )
    return CapitalFeasibilityReport(loaded.config_hash, tiers)
