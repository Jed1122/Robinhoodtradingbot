"""Owned original-input walk-forward development, never economic admission."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING, cast, overload

from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import Instrument, require_bounded_decimal
from trading_bot.market_data.etf_capital_dataset import CapitalResearchDataset
from trading_bot.market_data.etf_capital_observed import CapitalObservedDataset
from trading_bot.market_data.etf_capital_owned import (
    _own_capital_observed_source,
    _own_capital_source,
    _owned_capital_source_kind_valid,
    _OwnedCapitalObservedSource,
    _OwnedCapitalSource,
)
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_feasibility import _config
from trading_bot.research.etf_capital_prepared import (
    _prepare_owned_capital_days,
    _PreparedCapitalInput,
    _validate_owned_capital_days,
)
from trading_bot.research.etf_capital_protocol import CapitalStudyProtocol
from trading_bot.research.etf_capital_selection import (
    CapitalTrainingOutcome,
    CapitalTrainingSelection,
    select_capital_training,
)
from trading_bot.research.etf_capital_signals import (
    CapitalCandidate,
    CapitalWalkForwardFold,
    capital_candidates,
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

if TYPE_CHECKING:
    from trading_bot.research.etf_capital_panel import (
        _CapitalCompactWalkForward,
        _CapitalPanelRetention,
    )
    from trading_bot.research.etf_capital_panel_models import (
        CapitalObservedPanelFold,
        CapitalObservedPanelPath,
        CapitalObservedPanelTraining,
        CapitalPanelFold,
        CapitalPanelPath,
        CapitalPanelTraining,
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
class CapitalObservedWalkForwardRequest(_Offline):
    dataset: CapitalObservedDataset
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


type _WalkRequest = CapitalWalkForwardRequest | CapitalObservedWalkForwardRequest
type _OwnedSource = _OwnedCapitalSource | _OwnedCapitalObservedSource


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


@dataclass(frozen=True, slots=True)
class CapitalObservedWalkForwardResult(_Offline):
    folds: tuple[CapitalWalkForwardAttempt, ...]
    selected: CapitalTrajectoryResult
    fixed: tuple[CapitalFixedTrajectory, ...]
    used_sessions: tuple[date, ...]
    unused_sessions: tuple[date, ...]
    input_hash: str


def _walk_forward_protocol(request: _WalkRequest, owned: _OwnedSource) -> CapitalStudyProtocol:
    _check(_owned_capital_source_kind_valid(owned))
    if type(owned) is _OwnedCapitalObservedSource:
        _check(type(request) is CapitalObservedWalkForwardRequest)
        _check(type(request.dataset) is CapitalObservedDataset)
        return CapitalStudyProtocol("observed-252x84-v2")
    _check(type(request) is CapitalWalkForwardRequest)
    _check(type(request.dataset) is CapitalResearchDataset)
    return CapitalStudyProtocol("legacy-750x126-v1")


def _walk_forward_inputs(
    request: _WalkRequest, owned: _OwnedSource
) -> tuple[
    _CapitalOwnerTerms,
    tuple[Instrument, ...],
    tuple[date, ...],
    tuple[CapitalWalkForwardFold, ...],
    tuple[date, ...],
]:
    protocol = _walk_forward_protocol(request, owned)
    _check(request.source_qualified is False and request.cost_qualified is False)
    _check(request.execution_enabled is False and request.economic_admitted is False)
    _check(request.evidence_promotable is False)
    _check(request.dataset == owned.dataset)
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
    folds = protocol.folds(dates)
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
    return terms, instruments, dates, folds, reviews


def replay_capital_walk_forward(request: CapitalWalkForwardRequest) -> CapitalWalkForwardResult:
    """Freshly own original public inputs, never accept prepared state."""
    _check(type(request) is CapitalWalkForwardRequest)
    return cast(CapitalWalkForwardResult, _replay_public_capital_walk_forward(request))


def replay_capital_observed_walk_forward(
    request: CapitalObservedWalkForwardRequest,
) -> CapitalObservedWalkForwardResult:
    """Explicit shorter conditional-development study, never legacy admission."""
    _check(type(request) is CapitalObservedWalkForwardRequest)
    return cast(CapitalObservedWalkForwardResult, _replay_public_capital_walk_forward(request))


def _replay_public_capital_walk_forward(
    request: _WalkRequest,
) -> CapitalWalkForwardResult | CapitalObservedWalkForwardResult:
    try:
        with localcontext(_CONTEXT):
            _check(type(request) in (CapitalWalkForwardRequest, CapitalObservedWalkForwardRequest))
            _check(request.source_qualified is False and request.cost_qualified is False)
            _check(request.execution_enabled is False and request.economic_admitted is False)
            _check(request.evidence_promotable is False)
            owned: _OwnedSource
            if type(request) is CapitalObservedWalkForwardRequest:
                owned = _own_capital_observed_source(request.dataset)
            else:
                owned = _own_capital_source(cast(CapitalWalkForwardRequest, request).dataset)
            protocol = _walk_forward_protocol(request, owned)
            _, _, dates, _, _ = _walk_forward_inputs(request, owned)
            prepared = _prepare_owned_capital_days(owned, sessions=dates[: protocol.used_count])
            return _replay_owned_capital_walk_forward(request, owned=owned, prepared=prepared)
    except (ValueError, TypeError, AttributeError, ArithmeticError, StopIteration, KeyError):
        raise ValueError("capital_walk_forward_invalid") from None


@overload
def _replay_owned_capital_walk_forward(
    request: _WalkRequest,
    *,
    owned: _OwnedSource,
    prepared: _PreparedCapitalInput,
    retention: None = None,
) -> CapitalWalkForwardResult | CapitalObservedWalkForwardResult: ...


@overload
def _replay_owned_capital_walk_forward(
    request: _WalkRequest,
    *,
    owned: _OwnedSource,
    prepared: _PreparedCapitalInput,
    retention: _CapitalPanelRetention,
) -> _CapitalCompactWalkForward: ...


def _replay_owned_capital_walk_forward(
    request: _WalkRequest,
    *,
    owned: _OwnedSource,
    prepared: _PreparedCapitalInput,
    retention: _CapitalPanelRetention | None = None,
) -> CapitalWalkForwardResult | CapitalObservedWalkForwardResult | _CapitalCompactWalkForward:
    """Derive all training scores internally, then carry complete test accounts.

    Later rolling training may use already elapsed earlier-fold dates. Current
    and future fold test outcomes never enter that fold's selector. Full source
    digests are integrity bindings, not proof of publication chronology.
    """
    try:
        with localcontext(_CONTEXT):
            from trading_bot.research.etf_capital_matched import _CapitalMatchedTerms
            from trading_bot.research.etf_capital_panel import (
                _CapitalCompactWalkForward,
                _CapitalPanelRetention,
            )

            _check(retention is None or type(retention) is _CapitalPanelRetention)
            protocol = _walk_forward_protocol(request, owned)
            terms, instruments, dates, folds, reviews = _walk_forward_inputs(request, owned)
            source = owned.dataset
            used = dates[: protocol.used_count]
            sessions_by_date = {s.session_date: s for s in source.calendar.sessions}
            _validate_owned_capital_days(owned, prepared, required_sessions=used, exact=True)
            if retention is not None:
                _check(retention.owned is owned and retention.prepared is prepared)
                _check(
                    type(retention.protocol) is CapitalStudyProtocol
                    and retention.protocol == protocol
                )
                _check(
                    retention.terms
                    == _CapitalMatchedTerms(
                        terms.initial_cash,
                        terms.roundtrip_friction_pct,
                        terms.entry_fee,
                        terms.exit_fee,
                    )
                )
                _check(retention.test_sessions == dates[protocol.test_start : protocol.test_end])

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

            attempts: list[CapitalWalkForwardAttempt] = []
            compact_folds: list[CapitalPanelFold | CapitalObservedPanelFold] = []
            selections: list[CapitalTrainingSelection] = []
            fold_identities = []
            for fold in folds:
                cutoff = sessions_by_date[fold.train_sessions[-1]].closes_at + timedelta(seconds=3)
                selection_date = dates[dates.index(fold.test_sessions[0]) - 1]
                selection_at = sessions_by_date[selection_date].closes_at
                training_attempts: list[CapitalTrainingAttempt] = []
                retained: list[CapitalPanelTraining | CapitalObservedPanelTraining] = []
                outcomes_list: list[CapitalTrainingOutcome] = []
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
                    outcomes_list.append(outcome)
                    if retention is None:
                        training_attempts.append(CapitalTrainingAttempt(candidate, result, outcome))
                    else:
                        retained.append(retention.training(result, candidate, outcome))
                        del result
                outcomes = tuple(outcomes_list)
                selection = select_capital_training(
                    outcomes,
                    loaded=terms.loaded,
                    capital=terms.initial_cash,
                    training_cutoff=cutoff,
                    selection_at=selection_at,
                )
                selections.append(selection)
                fold_identities.append((fold, cutoff, selection_at, selection.panel_hash))
                if retention is None:
                    attempts.append(
                        CapitalWalkForwardAttempt(
                            fold, cutoff, selection_at, tuple(training_attempts), selection
                        )
                    )
                else:
                    compact_folds.append(
                        retention.fold(fold, cutoff, selection_at, tuple(retained), selection)
                    )
            recorded = tuple(attempts)
            # A boundary open belongs to the old fold; its close prepares the
            # new one. Selection knowledge at close must not reach backward.
            starts = tuple(
                protocol.baseline_index + protocol.test_count_per_fold * index
                for index in range(protocol.fold_count)
            )

            def close_candidate(index: int) -> CapitalCandidate | None:
                return selections[
                    max(i for i, start in enumerate(starts) if start <= index)
                ].selected

            schedule = tuple(
                CapitalTrajectoryDay(
                    day,
                    close_candidate(index),
                    index < protocol.test_end - 1,
                    index < protocol.test_end,
                    day in reviews,
                )
                for index, day in enumerate(
                    dates[protocol.baseline_index : protocol.used_count],
                    start=protocol.baseline_index,
                )
            )
            opening_candidates = tuple(
                close_candidate(index - 1) if index > protocol.baseline_index else None
                for index in range(protocol.baseline_index, protocol.used_count)
            )
            selected = trajectory(schedule, opening_candidates=opening_candidates)
            selected_hash = selected.input_hash
            compact_paths: list[CapitalPanelPath | CapitalObservedPanelPath] = []
            if retention is not None:
                compact_paths.append(retention.path(selected, 0, None))
                del selected
            fixed_results: list[CapitalFixedTrajectory] = []
            fixed_identities = []
            for index, candidate in enumerate(capital_candidates(), start=1):
                result = trajectory(tuple(replace(day, candidate=candidate) for day in schedule))
                fixed_identities.append((candidate, result.input_hash))
                if retention is None:
                    fixed_results.append(CapitalFixedTrajectory(candidate, result))
                else:
                    compact_paths.append(retention.path(result, index, candidate))
                    del result
            fixed = tuple(fixed_results)
            identity = content_hash(
                (
                    "capital-owned-walk-forward-v1"
                    if type(owned) is _OwnedCapitalSource
                    else ("capital-observed-owned-walk-forward-v1", protocol.protocol_hash),
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
                    dates[protocol.used_count :],
                    tuple(fold_identities),
                    selected_hash,
                    tuple(fixed_identities),
                    "positive-complete-USDPNL-at-.40_grid-order-cash-zero_continuous-account_final23-exit-only",
                )
            )
            if retention is not None:
                return _CapitalCompactWalkForward(
                    tuple(compact_folds), tuple(compact_paths), identity
                )
            result_type = (
                CapitalObservedWalkForwardResult
                if type(owned) is _OwnedCapitalObservedSource
                else CapitalWalkForwardResult
            )
            return result_type(
                recorded, selected, fixed, used, dates[protocol.used_count :], identity
            )
    except (ValueError, TypeError, AttributeError, ArithmeticError, StopIteration, KeyError):
        raise ValueError("capital_walk_forward_invalid") from None
