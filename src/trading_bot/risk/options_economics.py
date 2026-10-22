"""Necessary offline economic checks, never a substitute for final pretrade admission."""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal

from trading_bot.config import LoadedConfig, enforce_safety_envelope
from trading_bot.domain.decimal_utils import (
    DomainValidationError,
    _require_nonnegative_int,
    require_bounded_decimal,
)
from trading_bot.risk.trial_losses import TrialEpisode as TrialEpisode
from trading_bot.risk.trial_losses import TrialLossState as TrialLossState


@dataclass(frozen=True, slots=True)
class OptionsCapitalState:
    """Hypothetical/reconciled input amounts; pending exposure must already be included."""

    equity: Decimal
    cash: Decimal
    buying_power: Decimal
    portfolio_risk: Decimal
    group_risk: Decimal
    open_positions: int
    new_positions_this_session: int

    def __post_init__(self) -> None:
        require_bounded_decimal(self.equity, "equity", positive=True)
        for value, name in (
            (self.cash, "cash"),
            (self.buying_power, "buying_power"),
            (self.portfolio_risk, "portfolio_risk"),
            (self.group_risk, "group_risk"),
        ):
            require_bounded_decimal(value, name, nonnegative=True)
        _require_nonnegative_int(self.open_positions, "open_positions")
        _require_nonnegative_int(self.new_positions_this_session, "new_positions_this_session")
        if self.group_risk > self.portfolio_risk:
            raise DomainValidationError("group risk cannot exceed portfolio risk")


@dataclass(frozen=True, slots=True)
class OptionsFeasibility:
    admissible_units: int
    per_trade_budget: Decimal
    unit_payoff_risk: Decimal
    cash_after_reserve: Decimal
    reason_codes: tuple[str, ...]

    @property
    def production_eligible(self) -> Literal[False]:
        return False


def long_option_feasibility(
    loaded: LoadedConfig,
    capital: OptionsCapitalState,
    *,
    premium: Decimal,
    multiplier: Decimal,
    fee_reserve_per_unit: Decimal,
    trial: TrialLossState,
) -> OptionsFeasibility:
    """Bound one complete long-option unit using full premium plus both-side fee reserve.

    This is a necessary capital filter only: no Greeks, market admission, account evidence,
    loss-window evidence, or live authority is inferred. A higher research equity is
    explicitly hypothetical and never changes the canonical authorized equity ceiling.
    """
    if (
        type(loaded) is not LoadedConfig
        or type(capital) is not OptionsCapitalState
        or (type(trial) is not TrialLossState)
    ):
        raise DomainValidationError("validated configuration, capital and trial state required")
    enforce_safety_envelope(loaded.config, loaded.safety_envelope)
    c = loaded.config
    if not c.options.enabled or c.live_trading_enabled:
        raise DomainValidationError("offline options profile required")
    require_bounded_decimal(premium, "premium", positive=True)
    require_bounded_decimal(multiplier, "multiplier", positive=True)
    require_bounded_decimal(fee_reserve_per_unit, "fee reserve", nonnegative=True)
    with localcontext() as ctx:
        ctx.prec = 2048
        premium_cash = premium * multiplier
        unit_risk = premium_cash + fee_reserve_per_unit
        trade_budget = min(
            capital.equity * c.position_risk.max_risk_per_trade_pct / 100,
            c.options.max_per_trade_loss_usd,
        )
        cash_floor = (
            capital.equity
            * max(c.options.min_unencumbered_cash_pct, c.portfolio.min_cash_reserve_pct)
            / 100
        )
        budgets = (
            ("per_trade_risk", trade_budget, unit_risk),
            ("trial_budget", trial.remaining(c.options.cumulative_trial_loss_limit_usd), unit_risk),
            (
                "portfolio_payoff_risk",
                capital.equity * c.options.max_total_payoff_risk_pct / 100 - capital.portfolio_risk,
                unit_risk,
            ),
            (
                "underlying_group_risk",
                capital.equity * c.options.max_underlying_group_payoff_risk_pct / 100
                - capital.group_risk,
                unit_risk,
            ),
            ("cash_reserve", capital.cash - cash_floor, unit_risk),
            ("buying_power", capital.buying_power, unit_risk),
            ("legacy_order_notional", c.activity.max_order_notional_usd, premium_cash),
            (
                "legacy_position_notional",
                capital.equity * c.position_risk.max_position_notional_pct / 100,
                premium_cash,
            ),
            (
                "legacy_gross_exposure",
                min(
                    c.portfolio.max_gross_exposure_usd,
                    capital.equity * c.portfolio.max_total_gross_exposure_pct / 100,
                )
                - capital.portfolio_risk,
                unit_risk,
            ),
        )
        reasons = [name for name, remaining, required in budgets if remaining < required]
        if capital.open_positions >= c.options.max_open_strategy_positions:
            reasons.append("position_count")
        if capital.new_positions_this_session >= c.options.max_new_positions_per_session:
            reasons.append("session_activity")
        if any(not item.complete for item in trial.episodes):
            reasons.append("trial_slot_reserved")
        if c.options.max_structure_units_per_entry == 0:
            reasons.append("structure_unit_limit")
        # The release envelope permits at most one unit. Do not linearize an unknown
        # multi-unit fee schedule, and never round a sub-unit risk allowance upward.
        units = 0 if reasons else 1
        return OptionsFeasibility(
            units, trade_budget, unit_risk, capital.cash - units * unit_risk, tuple(reasons)
        )
