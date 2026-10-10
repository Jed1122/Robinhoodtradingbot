"""Owned raw SPY passive valuation in initial-share units, not order evidence."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, localcontext
from typing import cast

from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import Bar, ConfigHash, require_bounded_decimal
from trading_bot.market_data.etf_capital_actions import CapitalDistribution, CapitalSplit
from trading_bot.market_data.etf_capital_dataset import CapitalResearchDataset
from trading_bot.market_data.etf_capital_features import (
    _capital_feature_source,
    _capital_owned_raw_source,
)
from trading_bot.market_data.etf_capital_owned import _own_capital_source, _OwnedCapitalSource
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_benchmark import (
    EtfBenchmarkBar,
    EtfBenchmarkDistribution,
    EtfBenchmarkRequest,
    EtfBenchmarkResult,
    _money_context,
    run_etf_benchmark,
)
from trading_bot.research.etf_capital_feasibility import _CONTEXT, _config
from trading_bot.simulation.etf_capital_daily_entry import _Offline

_LIMITATIONS = (
    "full_mathematical_allocation_not_risk_admitted_or_executable",
    "kernel_shares_and_prices_are_initial_share_units_not_broker_terms",
    "raw_quantities_are_display_estimates_not_valuation_multipliers",
    "source_action_calendar_completeness_and_costs_unqualified",
    "liquidation_proxy_not_sale_settlement_or_finalized_profit",
    "operating_costs_and_taxes_reported_separately_not_cash_debits",
)


def _check(value: bool) -> None:
    if not value:
        raise ValueError("capital_passive_reference_invalid")


@dataclass(frozen=True, slots=True)
class CapitalPassiveRequest(_Offline):
    dataset: CapitalResearchDataset
    initial_cash: Decimal
    sessions: tuple[date, ...]
    roundtrip_friction_pct: Decimal
    entry_fee: Decimal
    estimated_exit_fee: Decimal


@dataclass(frozen=True, slots=True)
class CapitalPassiveReference(_Offline):
    input_hash: str
    source_hash: str
    config_hash: ConfigHash
    baseline_session: date
    session_dates: tuple[date, ...]
    raw_quantities: tuple[Decimal, ...]
    kernel_result: EtfBenchmarkResult
    reference_kind: str = field(default="full_mathematical_spy", init=False)
    realized_trading_pnl: None = field(default=None, init=False)
    limitations: tuple[str, ...] = field(default=_LIMITATIONS, init=False)


def run_capital_passive_reference(request: CapitalPassiveRequest) -> CapitalPassiveReference:
    """Own originals, then reuse the unchanged mathematical cash/value engine.

    Only effective splits AFTER the purchase alter its units. Normalized values
    use the entry's share unit, not a future terminal feature basis. No allocation
    policy, broker rounding, active risk admission or real fill is inferred.
    """
    try:
        _check(type(request) is CapitalPassiveRequest)
        _check(request.source_qualified is False and request.cost_qualified is False)
        _check(request.execution_enabled is False and request.economic_admitted is False)
        _check(request.evidence_promotable is False)
        owned = _own_capital_source(request.dataset)
        kernel, quantities, baseline = _capital_passive_values(owned, request)
        identity = content_hash(
            (
                "capital-passive-original-reference-v1",
                owned.source_hash,
                owned.dataset.config_hash,
                baseline,
                request.sessions,
                request.initial_cash,
                request.roundtrip_friction_pct,
                request.entry_fee,
                request.estimated_exit_fee,
                kernel.input_hash,
                _LIMITATIONS,
            )
        )
        return CapitalPassiveReference(
            identity,
            owned.source_hash,
            owned.dataset.config_hash,
            baseline,
            request.sessions,
            quantities,
            kernel,
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError, IndexError, KeyError):
        raise ValueError("capital_passive_reference_invalid") from None


def _capital_passive_values(
    owned: _OwnedCapitalSource,
    request: CapitalPassiveRequest,
    *,
    entry_notional: Decimal | None = None,
) -> tuple[EtfBenchmarkResult, tuple[Decimal, ...], date]:
    """Invocation-owned valuation seam; no public result or allocation authority."""
    try:
        with localcontext(_CONTEXT):
            loaded = restore_loaded_config(
                owned.dataset.canonical_config, owned.dataset.config_hash
            )
            policy = _config(loaded).capital_research
            require_bounded_decimal(request.initial_cash, "capital", positive=True)
            require_bounded_decimal(request.roundtrip_friction_pct, "friction", nonnegative=True)
            require_bounded_decimal(request.entry_fee, "entry fee", nonnegative=True)
            require_bounded_decimal(request.estimated_exit_fee, "exit fee", nonnegative=True)
            _check(request.initial_cash in policy.capital_tiers)
            _check(request.roundtrip_friction_pct in policy.round_trip_friction_pct)
            _check(request.entry_fee < request.initial_cash)
            _check(type(request.sessions) is tuple and 0 < len(request.sessions) <= 4000)
            _check(all(type(day) is date for day in request.sessions))
            dates = tuple(
                row.session_date
                for row in owned.dataset.calendar.sessions
                if owned.dataset.start <= row.session_date < owned.dataset.end
            )
            first_index = dates.index(request.sessions[0])
            _check(first_index > 0)
            _check(dates[first_index : first_index + len(request.sessions)] == request.sessions)
            archive = owned.dataset.archives[0]
            actions = owned.dataset.actions[0]
            _check(archive.request.symbol == actions.symbol == "SPY")
            # Ownership validated original and copied non-None action tuples.
            splits = cast(tuple[CapitalSplit, ...], actions.splits)
            declared_distributions = cast(tuple[CapitalDistribution, ...], actions.distributions)
            first, last = request.sessions[0], request.sessions[-1]
            split_dates = {
                row.effective_date for row in splits if first < row.effective_date <= last
            }
            _check(
                not any(
                    first < row.ex_date <= last and row.ex_date in split_dates
                    for row in declared_distributions
                )
            )
            source = _capital_owned_raw_source(
                _capital_feature_source(
                    archive, owned.dataset.calendar, actions, as_of_session=last
                )
            )
            raw = dict(cast(tuple[tuple[date, Bar], ...], source.raw_rows))
            # Same exact bounded financial context as the existing mathematical
            # kernel. Excess intermediate precision/size denies, never rounds.
            with localcontext(_money_context()):
                factors: dict[date, Decimal] = {}
                bars = []
                for day in request.sessions:
                    factor = Decimal(1)
                    for split in splits:
                        if first < split.effective_date <= day:
                            factor *= split.new_shares_per_old_share
                            require_bounded_decimal(factor, "split factor", positive=True)
                    factors[day] = factor
                    bar = raw[day]
                    bars.append(
                        EtfBenchmarkBar(
                            day, bar.open * factor, bar.close * factor, str(bar.data_hash)
                        )
                    )
                distributions = tuple(
                    EtfBenchmarkDistribution(
                        row.ex_date,
                        row.pay_date,
                        row.amount_per_share * factors[row.ex_date],
                        row.record_hash,
                    )
                    for row in declared_distributions
                    if first < row.ex_date <= last
                )
                kernel = run_etf_benchmark(
                    EtfBenchmarkRequest(
                        tuple(bars),
                        distributions,
                        request.initial_cash,
                        request.initial_cash - request.entry_fee
                        if entry_notional is None
                        else entry_notional,
                        request.roundtrip_friction_pct * Decimal(50),
                        request.entry_fee,
                        request.estimated_exit_fee,
                    )
                )
                quantities = tuple(kernel.shares * factors[day] for day in request.sessions)
                for quantity in quantities:
                    require_bounded_decimal(quantity, "raw quantity", nonnegative=True)
            return kernel, quantities, dates[first_index - 1]
    except (ValueError, TypeError, ArithmeticError, AttributeError, IndexError, KeyError):
        raise ValueError("capital_passive_reference_invalid") from None
