"""Shared-feature and canonical-budget composition for offline options research.

Only the source-bound runner supplies reconstructed state and verified inputs.
These pure helpers confer no broker, promotion, calibration or source capability.
"""

from datetime import datetime
from decimal import Decimal, localcontext

from trading_bot.config import LoadedConfig
from trading_bot.domain import InstrumentId
from trading_bot.domain.options import (
    OptionContract,
    OptionKind,
    OptionQuote,
    OptionSession,
    executable_quote_reasons,
)
from trading_bot.lifecycle.options_expiry import OptionExpiryCalendar, assess_option_expiry
from trading_bot.market_data.options_source_models import check
from trading_bot.research.options_study_models import StudyScenario
from trading_bot.research.options_study_registration import study_settings
from trading_bot.risk.options_economics import OptionsCapitalState, long_option_feasibility
from trading_bot.simulation.options_historical_models import OptionsAccountPathState
from trading_bot.strategies.features import FeaturePipeline
from trading_bot.strategies.options.momentum import OptionsMomentumStrategy
from trading_bot.strategies.protocol import (
    FeatureSnapshot,
    HistoricalSlice,
    StrategyContext,
    StrategyDecision,
)


def historical_signal(
    history: HistoricalSlice, *, at: datetime, loaded: LoadedConfig
) -> tuple[tuple[OptionKind, StrategyDecision], ...]:
    study_settings(loaded)
    check(type(history) is HistoricalSlice)
    check(len(history.bars) >= loaded.config.research.minimum_history_bars)
    check(history.instrument_id == "SPY" and all(b.ends_at <= at for b in history.bars))
    # The preregistered hypothesis is fixed; configuration may not substitute a grid.
    short, long = 20, 100
    with localcontext() as context:
        context.prec = 64
        features = FeaturePipeline(short_window=short, long_window=long).compute(history, as_of=at)
        decision_context = StrategyContext(
            at,
            FeatureSnapshot(at, (features,), features.data_hash),
            loaded.config_hash,
            (InstrumentId("SPY"),),
        )
        return tuple(
            (
                kind,
                OptionsMomentumStrategy(kind=kind, short_window=short, long_window=long).decide(
                    decision_context
                )[0],
            )
            for kind in (OptionKind.CALL, OptionKind.PUT)
        )


def evaluate_historical_entry(
    *,
    state: OptionsAccountPathState,
    contract: OptionContract,
    quote: OptionQuote,
    calendar: OptionExpiryCalendar,
    session: OptionSession,
    at: datetime,
    scenario: StudyScenario,
    loaded: LoadedConfig,
    loss_reasons: tuple[str, ...],
) -> tuple[str, ...]:
    study_settings(loaded)
    check(state.config_hash == loaded.config_hash and state.scenario_hash == scenario.scenario_hash)
    reasons = set((*state.incidents, *state.latched_halts, *loss_reasons))
    c = loaded.config
    reasons.update(
        executable_quote_reasons(
            contract,
            quote,
            as_of=at,
            max_age_seconds=c.freshness.max_executable_quote_age_seconds,
            max_underlying_skew_seconds=c.market_data.max_cross_response_timestamp_skew_seconds,
            allow_locked=c.options.allow_locked_quotes,
        )
    )
    reasons.update(
        assess_option_expiry(
            contract=contract,
            calendar=calendar,
            as_of=at,
            has_exposure=True,
        ).reasons
    )
    if session not in contract.eligible_sessions or not session.opens_at <= at < session.closes_at:
        reasons.add("outside_session")
    if state.risk_capital <= 0 or state.available_cash < 0:
        reasons.add("capital_unavailable")
        return tuple(sorted(reasons))
    reserved = state.trial.reserved_risk
    feasible = long_option_feasibility(
        loaded,
        OptionsCapitalState(
            state.risk_capital,
            state.available_cash,
            state.available_cash,
            reserved,
            reserved,
            sum(not e.finalized for e in state.episodes),
            dict(state.session_entry_counts).get(session.session_id, 0),
        ),
        premium=quote.ask,
        multiplier=contract.premium_multiplier,
        fee_reserve_per_unit=scenario.fee_bound_per_unit,
        trial=state.trial,
    )
    reasons.update(feasible.reason_codes)
    with localcontext() as context:
        context.prec = 2048
        if quote.ask % contract.tick_size or quote.bid % contract.tick_size:
            reasons.add("invalid_option_tick")
    if quote.bid <= Decimal(0):
        reasons.add("zero_bid")
    return tuple(sorted(reasons))
