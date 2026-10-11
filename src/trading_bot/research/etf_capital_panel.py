"""Original-source DEVELOPMENT panel; never qualification or promotion authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from itertools import pairwise
from typing import TYPE_CHECKING, Literal, cast

from trading_bot.config import LoadedConfig
from trading_bot.config.capital_research import CapitalResearchAppConfig
from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import Instrument, require_bounded_decimal
from trading_bot.market_data.etf_capital_dataset import CapitalResearchDataset
from trading_bot.market_data.etf_capital_owned import _OwnedCapitalSource
from trading_bot.research.etf_capital_feasibility import _config
from trading_bot.research.etf_capital_panel_models import (
    _FLAGS,
    _ROLES,
    _TAGS,
    CapitalPanelFamily,
    CapitalPanelFinal,
    CapitalPanelLabel,
    _check,
    _panel_hash,
    _PanelRecord,
    _typed,
)
from trading_bot.research.etf_capital_path_economics import _ratio
from trading_bot.research.etf_resampling import dependent_capital_simultaneous_mean_intervals
from trading_bot.simulation.etf_capital_constrained import CapitalConstrainedResult
from trading_bot.simulation.etf_capital_daily_entry import _CONTEXT, _Offline
from trading_bot.simulation.etf_capital_daily_owner import _Outcome
from trading_bot.simulation.etf_capital_trajectory import CapitalTrajectoryResult

if TYPE_CHECKING:
    from trading_bot.simulation.etf_capital_walk_forward import CapitalWalkForwardRequest


def _record[T: _PanelRecord](cls: type[T], *values: object) -> T:
    return cast(Callable[..., T], cls)(*values, _panel_hash(_TAGS[cls], *values))


@dataclass(frozen=True, slots=True)
class CapitalEconomicPanelRequest(_Offline):
    dataset: CapitalResearchDataset
    instruments: tuple[Instrument, ...]
    episode_fee_bound: Decimal | None
    entry_fee: Decimal
    exit_fee: Decimal
    recurring_usd_per_day: Decimal | None
    sunk_research_usd: Decimal | None
    weekly_review_sessions: tuple[date, ...] = ()
    entry_outcome: _Outcome = "filled"
    entry_fill_fraction: Decimal = Decimal(1)
    exit_outcome: _Outcome = "filled"
    exit_fill_fraction: Decimal = Decimal(1)


def _panel_inputs(
    request: CapitalEconomicPanelRequest, owned: _OwnedCapitalSource
) -> tuple[CapitalResearchAppConfig, LoadedConfig, CapitalWalkForwardRequest]:
    from trading_bot.simulation.etf_capital_walk_forward import (
        CapitalWalkForwardRequest,
        _walk_forward_inputs,
    )

    try:
        _check(type(request) is CapitalEconomicPanelRequest)
        _check(all(getattr(request, flag) is False for flag in _FLAGS))
        loaded = restore_loaded_config(owned.dataset.canonical_config, owned.dataset.config_hash)
        cfg = _config(loaded)
        for amount in (request.entry_fee, request.exit_fee):
            require_bounded_decimal(amount, "declared fee", nonnegative=True)
        _check(request.entry_fee < min(cfg.capital_research.capital_tiers))
        for expense in (request.recurring_usd_per_day, request.sunk_research_usd):
            if expense is not None:
                require_bounded_decimal(expense, "declared expense", nonnegative=True)
        walk = CapitalWalkForwardRequest(
            request.dataset,
            cfg.capital_research.capital_tiers[0],
            request.instruments,
            request.episode_fee_bound,
            request.entry_fee,
            request.exit_fee,
            cfg.capital_research.round_trip_friction_pct[0],
            request.weekly_review_sessions,
            request.entry_outcome,
            request.entry_fill_fraction,
            request.exit_outcome,
            request.exit_fill_fraction,
        )
        _walk_forward_inputs(walk, owned)
        return cfg, loaded, walk
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        raise ValueError("capital_economic_panel_invalid") from None


def _paired_column(
    candidate: tuple[Decimal, ...], reference: tuple[Decimal, ...], capital: Decimal
) -> tuple[Decimal, ...]:
    try:
        with localcontext(_CONTEXT):
            _check(type(candidate) is tuple and type(reference) is tuple)
            _check(len(candidate) == len(reference) == 631)
            require_bounded_decimal(capital, "paired capital", positive=True)
            for value in (*candidate, *reference):
                require_bounded_decimal(value, "paired NAV")
            return tuple(
                _ratio((b - a) - (d - c), capital)
                for (a, b), (c, d) in zip(pairwise(candidate), pairwise(reference), strict=True)
            )
    except (ValueError, TypeError, ArithmeticError):
        raise ValueError("capital_economic_panel_invalid") from None


def _build_family(
    kind: Literal["trading", "operating"],
    dates: tuple[date, ...],
    labels: tuple[CapitalPanelLabel, ...],
    columns: tuple[tuple[Decimal, ...], ...],
    *,
    capitals: tuple[Decimal, ...],
    frictions: tuple[Decimal, ...],
    seed: int,
    draws: int,
) -> CapitalPanelFamily:
    try:
        _check(type(kind) is str and kind in ("trading", "operating"))
        _check(type(dates) is tuple and len(dates) == 630)
        _check(all(type(day) is date for day in dates) and all(a < b for a, b in pairwise(dates)))
        _check(type(labels) is tuple and type(columns) is tuple)
        _check(len(capitals) == 6 and len(frictions) == 4)
        _check(len(labels) == len(columns) == 2784)
        expected = tuple(
            CapitalPanelLabel(
                capital,
                cost,
                path,
                cast(Literal["full_spy", "managed_spy", "matched_spy", "cash"], role),
            )
            for capital in capitals
            for cost in frictions
            for path in range(29)
            for role in _ROLES
        )
        for label, want, column in zip(labels, expected, columns, strict=True):
            _typed(label, CapitalPanelLabel)
            _check(label == want)
            _check(type(column) is tuple and len(column) == 630)
            for value in column:
                require_bounded_decimal(value, "paired increment")
        hashes = tuple(
            _panel_hash("column", kind, label, dates, column)
            for label, column in zip(labels, columns, strict=True)
        )
        bands = dependent_capital_simultaneous_mean_intervals(
            columns, seed=seed, block_lengths=(20, 100), draws=draws
        )
        return _record(CapitalPanelFamily, kind, dates, labels, columns, hashes, bands)
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        raise ValueError("capital_economic_panel_invalid") from None


def _retain_final(
    trajectory: CapitalTrajectoryResult | CapitalConstrainedResult,
    *,
    initial_cash: Decimal,
    test_count: int,
) -> CapitalPanelFinal:
    with localcontext(_CONTEXT):
        _check(type(trajectory) in (CapitalTrajectoryResult, CapitalConstrainedResult))
        _check(all(getattr(trajectory, flag) is False for flag in _FLAGS))
        _check(type(test_count) is int and 0 < test_count < len(trajectory.points))
        require_bounded_decimal(initial_cash, "capital", positive=True)
        account, cutoff = trajectory.account, trajectory.points[test_count].account
        complete = account.complete and account.quantity == 0
        _check(type(account.marked_equity) is Decimal)
        return _record(
            CapitalPanelFinal,
            trajectory.input_hash,
            account.economic_hash,
            trajectory.risk.result_hash,
            account.complete,
            account.cash,
            account.available_cash,
            account.quantity,
            account.unsettled_proceeds,
            account.distribution_receivable,
            account.fees,
            account.marked_equity,
            account.cash - initial_cash if complete else None,
            account.cash - cutoff.cash,
            account.fees - cutoff.fees,
            (
                "final_original_tail_state_not_test_finality",
                "marked_equity_not_realized_cash",
                *(() if complete else ("final_outcome_incomplete",)),
            ),
        )
