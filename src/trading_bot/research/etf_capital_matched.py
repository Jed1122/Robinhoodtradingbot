"""Retrospective mean-exposure SPY comparison, never causal policy authority."""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, localcontext

from trading_bot.domain import ConfigHash, require_bounded_decimal
from trading_bot.market_data.etf_capital_owned import _own_capital_source, _OwnedCapitalSource
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import EtfBenchmarkResult, _money_context
from trading_bot.research.etf_capital_passive import CapitalPassiveRequest, _capital_passive_values
from trading_bot.research.etf_capital_path_economics import _capital_close_exposures, _ratio
from trading_bot.simulation.etf_capital_account import replay_capital_action_account_prefixes
from trading_bot.simulation.etf_capital_daily_entry import _CONTEXT, _Offline
from trading_bot.simulation.etf_capital_trajectory import (
    CapitalTrajectoryRequest,
    CapitalTrajectoryResult,
    replay_capital_trajectory,
)

_LIMITATIONS = (
    "future_conditioned_mean_not_causal_or_attainable_policy",
    "net_fee_fundable_initial_allocation_not_daily_exposure_replication",
    "cash_zero_yield_lower_bound_not_observed_customer_interest",
    "daily_marked_nav_not_executable_liquidation_or_settlement",
    "source_actions_costs_fractional_terms_and_independent_support_unqualified",
    "no_operating_cost_or_tax_cash_debits",
)


def _check(value: bool) -> None:
    if not value:
        raise ValueError("capital_matched_reference_invalid")


@dataclass(frozen=True, slots=True)
class CapitalMatchedRequest(_Offline):
    trajectory: CapitalTrajectoryRequest
    test_sessions: tuple[date, ...]


@dataclass(frozen=True, slots=True)
class CapitalMatchedReference(_Offline):
    input_hash: str
    source_hash: str
    config_hash: ConfigHash
    trajectory_hash: str
    baseline_session: date
    session_dates: tuple[date, ...]
    close_exposures: tuple[Decimal, ...]
    mean_exposure: Decimal
    raw_quantities: tuple[Decimal, ...]
    kernel_result: EtfBenchmarkResult
    cash_nav: tuple[Decimal, ...]
    reference_kind: str = field(default="retrospective_mean_exposure_scaled_spy", init=False)
    realized_trading_pnl: None = field(default=None, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)


def run_capital_matched_reference(request: CapitalMatchedRequest) -> CapitalMatchedReference:
    """Never accept supplied exposures, account balances or precomputed results."""
    try:
        _check(type(request) is CapitalMatchedRequest)
        _check(request.source_qualified is False and request.cost_qualified is False)
        _check(request.execution_enabled is False and request.economic_admitted is False)
        _check(request.evidence_promotable is False)
        _check(type(request.trajectory) is CapitalTrajectoryRequest)
        _check(
            request.trajectory.source_qualified is False
            and request.trajectory.cost_qualified is False
        )
        _check(
            request.trajectory.execution_enabled is False
            and request.trajectory.economic_admitted is False
        )
        _check(request.trajectory.evidence_promotable is False)
        owned = _own_capital_source(request.trajectory.dataset)
        original = replace(request.trajectory, dataset=owned.dataset)
        result = replay_capital_trajectory(original)
        return _capital_matched_reference(owned, original, result, request.test_sessions)
    except (ValueError, TypeError, ArithmeticError, AttributeError, IndexError, KeyError):
        raise ValueError("capital_matched_reference_invalid") from None


def _capital_matched_reference(
    owned: _OwnedCapitalSource,
    original: CapitalTrajectoryRequest,
    trajectory: CapitalTrajectoryResult,
    test_sessions: tuple[date, ...],
) -> CapitalMatchedReference:
    """Private invocation-owned path seam for later source-owned panel composition."""
    with localcontext(_CONTEXT):
        _check(type(test_sessions) is tuple and 0 < len(test_sessions) <= 2047)
        _check(all(type(day) is date for day in test_sessions))
        dates = tuple(point.at.date() for point in trajectory.points)
        _check(dates[1 : 1 + len(test_sessions)] == test_sessions)
        prefixes = replay_capital_action_account_prefixes(
            initial_cash=original.initial_cash, events=trajectory.events
        )
        _check(prefixes[-1] == trajectory.account)
        all_exposures = _capital_close_exposures(trajectory, prefixes)
        exposures = all_exposures[1 : 1 + len(test_sessions)]
        with localcontext(_CONTEXT) as ratio_context:
            ratio_context.prec = 64
            mean = _ratio(sum(exposures, Decimal(0)), Decimal(len(exposures)))
        for exposure in (*exposures, mean):
            require_bounded_decimal(exposure, "exposure", nonnegative=True)
            _check(exposure <= 1)
        with localcontext(_money_context()):
            notional = (
                Decimal(0) if mean == 0 else (original.initial_cash - original.entry_fee) * mean
            )
        kernel, quantities, baseline = _capital_passive_values(
            owned,
            CapitalPassiveRequest(
                owned.dataset,
                original.initial_cash,
                test_sessions,
                original.roundtrip_friction_pct,
                original.entry_fee,
                original.exit_fee,
            ),
            entry_notional=notional,
        )
        _check(baseline == dates[0])
        cash = tuple(point.cash_reference_nav for point in kernel.points)
        identity = content_hash(
            (
                "capital-retrospective-matched-spy-v1",
                owned.source_hash,
                owned.dataset.config_hash,
                trajectory.input_hash,
                dates[0],
                test_sessions,
                original.initial_cash,
                exposures,
                mean,
                notional,
                original.roundtrip_friction_pct,
                original.entry_fee,
                original.exit_fee,
                "gross_close_ratio64_mean64_net_fee_fundable_exact_notional_no_DRIP",
                kernel.input_hash,
                cash,
                _LIMITATIONS,
            )
        )
        return CapitalMatchedReference(
            identity,
            owned.source_hash,
            owned.dataset.config_hash,
            trajectory.input_hash,
            baseline,
            test_sessions,
            exposures,
            mean,
            quantities,
            kernel,
            cash,
        )
