"""Owned original-input walk-forward development, never economic admission."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext

from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import Instrument, require_bounded_decimal
from trading_bot.market_data.etf_capital_dataset import CapitalResearchDataset
from trading_bot.market_data.etf_capital_owned import _own_capital_source
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_feasibility import _config
from trading_bot.research.etf_capital_prepared import _prepare_owned_capital_days
from trading_bot.research.etf_capital_selection import (
    CapitalTrainingOutcome,
    CapitalTrainingSelection,
    select_capital_training,
)
from trading_bot.research.etf_capital_signals import (
    CapitalCandidate,
    CapitalWalkForwardFold,
    capital_candidates,
    capital_walk_forward_folds,
)
from trading_bot.simulation.etf_capital_daily_entry import _CONTEXT, _Offline
from trading_bot.simulation.etf_capital_daily_owner import (
    _CapitalOwnerTerms,
    _Outcome,
    _validate_owner_terms,
)
from trading_bot.simulation.etf_capital_trajectory import (
    CapitalTrajectoryDay,
    CapitalTrajectoryResult,
    _replay_prepared_capital_trajectory,
)


def _check(value: bool) -> None:
    if not value:
        raise ValueError("capital_walk_forward_invalid")


@dataclass(frozen=True, slots=True)
class CapitalWalkForwardRequest(_Offline):
    dataset: CapitalResearchDataset
    initial_cash: Decimal
    instruments: tuple[Instrument, ...]
    episode_fee_bound: Decimal | None
    entry_fee: Decimal
    exit_fee: Decimal
    roundtrip_friction_pct: Decimal
    weekly_review_sessions: tuple[date, ...] = ()
    entry_outcome: _Outcome = "filled"
    entry_fill_fraction: Decimal = Decimal(1)
    exit_outcome: _Outcome = "filled"
    exit_fill_fraction: Decimal = Decimal(1)


@dataclass(frozen=True, slots=True)
class CapitalTrainingAttempt:
    candidate: CapitalCandidate
    trajectory: CapitalTrajectoryResult
    outcome: CapitalTrainingOutcome


@dataclass(frozen=True, slots=True)
class CapitalWalkForwardAttempt:
    fold: CapitalWalkForwardFold
    training_cutoff: datetime
    selection_at: datetime
    training: tuple[CapitalTrainingAttempt, ...]
    selection: CapitalTrainingSelection


@dataclass(frozen=True, slots=True)
class CapitalFixedTrajectory:
    candidate: CapitalCandidate
    trajectory: CapitalTrajectoryResult


@dataclass(frozen=True, slots=True)
class CapitalWalkForwardResult(_Offline):
    folds: tuple[CapitalWalkForwardAttempt, ...]
    selected: CapitalTrajectoryResult
    fixed: tuple[CapitalFixedTrajectory, ...]
    used_sessions: tuple[date, ...]
    unused_sessions: tuple[date, ...]
    input_hash: str


def replay_capital_walk_forward(request: CapitalWalkForwardRequest) -> CapitalWalkForwardResult:
    """Derive all training scores internally, then carry complete test accounts.

    Later rolling training may use already elapsed earlier-fold dates. Current
    and future fold test outcomes never enter that fold's selector. Full source
    digests are integrity bindings, not proof of publication chronology.
    """
    try:
        with localcontext(_CONTEXT):
            _check(type(request) is CapitalWalkForwardRequest)
            _check(request.source_qualified is False and request.cost_qualified is False)
            _check(request.execution_enabled is False and request.economic_admitted is False)
            _check(request.evidence_promotable is False)
            owned = _own_capital_source(request.dataset)
            source = owned.dataset
            loaded = restore_loaded_config(source.canonical_config, source.config_hash)
            cfg = _config(loaded)
            require_bounded_decimal(request.initial_cash, "research capital", positive=True)
            _check(request.initial_cash in cfg.capital_research.capital_tiers)
            dates = tuple(
                s.session_date
                for s in source.calendar.sessions
                if source.start <= s.session_date < source.end
            )
            folds = capital_walk_forward_folds(dates)
            _check(type(request.weekly_review_sessions) is tuple)
            reviews = request.weekly_review_sessions
            _check(all(type(day) is date for day in reviews))
            _check(reviews == tuple(sorted(set(reviews))) and set(reviews) <= set(dates))
            _check(type(request.instruments) is tuple and len(request.instruments) == 5)
            for item in request.instruments:
                _check(type(item) is Instrument)
                item.__post_init__()
                _check(item.observed_at.tzinfo is UTC)
                _check(item.observed_at <= source.calendar.sessions[0].opens_at)
            instruments = tuple(replace(item) for item in request.instruments)
            _check(tuple(i.symbol for i in instruments) == cfg.capital_research.universe)
            terms = _CapitalOwnerTerms(
                loaded,
                request.initial_cash,
                request.episode_fee_bound,
                request.entry_fee,
                request.exit_fee,
                request.roundtrip_friction_pct,
                source.calendar,
                request.entry_outcome,
                request.entry_fill_fraction,
                request.exit_outcome,
                request.exit_fill_fraction,
            )
            _validate_owner_terms(terms)
            used = dates[:1423]
            prepared = _prepare_owned_capital_days(owned, sessions=used)
            _check(prepared.source_hash == owned.source_hash)
            sessions_by_date = {s.session_date: s for s in source.calendar.sessions}

            def trajectory(
                schedule: tuple[CapitalTrajectoryDay, ...],
                *,
                training: bool = False,
                opening_candidates: tuple[CapitalCandidate | None, ...] | None = None,
            ) -> CapitalTrajectoryResult:
                return _replay_prepared_capital_trajectory(
                    source=source,
                    source_hash=owned.source_hash,
                    prepared=prepared,
                    terms=replace(terms, roundtrip_friction_pct=Decimal(".40"))
                    if training
                    else terms,
                    instruments=instruments,
                    schedule=schedule,
                    opening_candidates=opening_candidates,
                )

            attempts = []
            for fold in folds:
                cutoff = sessions_by_date[fold.train_sessions[-1]].closes_at + timedelta(seconds=3)
                selection_date = dates[dates.index(fold.test_sessions[0]) - 1]
                selection_at = sessions_by_date[selection_date].closes_at
                training_attempts = []
                for candidate in capital_candidates():
                    schedule = tuple(
                        CapitalTrajectoryDay(
                            day,
                            candidate,
                            day in fold.selection_sessions,
                            True,
                            day in reviews,
                        )
                        for day in fold.train_sessions
                    )
                    result = trajectory(schedule, training=True)
                    complete = result.account.complete and result.account.quantity == 0
                    outcome = CapitalTrainingOutcome(
                        candidate,
                        result.account.cash - terms.initial_cash if complete else None,
                        complete,
                        result.points[-1].at,
                        result.input_hash,
                    )
                    training_attempts.append(CapitalTrainingAttempt(candidate, result, outcome))
                outcomes = tuple(a.outcome for a in training_attempts)
                selection = select_capital_training(
                    outcomes,
                    loaded=loaded,
                    capital=terms.initial_cash,
                    training_cutoff=cutoff,
                    selection_at=selection_at,
                )
                attempts.append(
                    CapitalWalkForwardAttempt(
                        fold, cutoff, selection_at, tuple(training_attempts), selection
                    )
                )
            recorded = tuple(attempts)
            # At session895, the open belongs to fold0 and the close prepares
            # fold1. Selection knowledge at close must not reach backward.
            starts = tuple(769 + 126 * index for index in range(5))

            def close_candidate(index: int) -> CapitalCandidate | None:
                return recorded[
                    max(i for i, start in enumerate(starts) if start <= index)
                ].selection.selected

            schedule = tuple(
                CapitalTrajectoryDay(
                    day, close_candidate(index), index < 1399, index < 1400, day in reviews
                )
                for index, day in enumerate(dates[769:1423], start=769)
            )
            opening_candidates = tuple(
                close_candidate(index - 1) if index > 769 else None for index in range(769, 1423)
            )
            selected = trajectory(schedule, opening_candidates=opening_candidates)
            fixed = tuple(
                CapitalFixedTrajectory(
                    candidate,
                    trajectory(tuple(replace(day, candidate=candidate) for day in schedule)),
                )
                for candidate in capital_candidates()
            )
            identity = content_hash(
                (
                    "capital-owned-walk-forward-v1",
                    owned.source_hash,
                    prepared.input_hash,
                    source.config_hash,
                    instruments,
                    terms.initial_cash,
                    terms.episode_fee_bound,
                    terms.entry_fee,
                    terms.exit_fee,
                    terms.roundtrip_friction_pct,
                    terms.entry_outcome,
                    terms.entry_fill_fraction,
                    terms.exit_outcome,
                    terms.exit_fill_fraction,
                    reviews,
                    used,
                    dates[1423:],
                    tuple(
                        (a.fold, a.training_cutoff, a.selection_at, a.selection.panel_hash)
                        for a in recorded
                    ),
                    selected.input_hash,
                    tuple((a.candidate, a.trajectory.input_hash) for a in fixed),
                    "positive-complete-USDPNL-at-.40_grid-order-cash-zero_continuous-account_final23-exit-only",
                )
            )
            return CapitalWalkForwardResult(recorded, selected, fixed, used, dates[1423:], identity)
    except (ValueError, TypeError, AttributeError, ArithmeticError, StopIteration, KeyError):
        raise ValueError("capital_walk_forward_invalid") from None
