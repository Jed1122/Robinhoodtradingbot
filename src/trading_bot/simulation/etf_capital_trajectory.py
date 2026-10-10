"""Owned original-dataset daily research; never authenticated economic evidence."""

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, localcontext

from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import Instrument, require_bounded_decimal
from trading_bot.market_data.etf_capital_dataset import CapitalResearchDataset
from trading_bot.market_data.etf_capital_owned import _own_capital_source
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_daily_policy import CapitalDailyPolicy, CapitalOpeningPolicy
from trading_bot.research.etf_capital_feasibility import _config
from trading_bot.research.etf_capital_prepared import (
    _prepare_owned_capital_days,
    _PreparedCapitalInput,
)
from trading_bot.research.etf_capital_prepared_policy import _capital_prepared_policy
from trading_bot.research.etf_capital_signals import CapitalCandidate
from trading_bot.simulation.etf_capital_account import CapitalActionAccountReplay
from trading_bot.simulation.etf_capital_daily_entry import _CONTEXT, _Offline
from trading_bot.simulation.etf_capital_daily_owner import (
    _CapitalOwnerFrame,
    _CapitalOwnerTerms,
    _Event,
    _Opening,
    _Outcome,
    _replay_capital_owner,
    _validate_owner_terms,
)
from trading_bot.simulation.etf_capital_due_facts import _capital_due_facts
from trading_bot.simulation.etf_capital_risk import CapitalRiskObservation, CapitalRiskReplay


def _check(value: bool) -> None:
    if not value:
        raise ValueError("capital_trajectory_invalid")


@dataclass(frozen=True, slots=True)
class CapitalTrajectoryDay:
    session: date
    candidate: CapitalCandidate | None
    entry_decision_allowed: bool = True
    entry_submission_allowed: bool = True
    weekly_review_assumed: bool = False

    def __post_init__(self) -> None:
        _check(type(self.session) is date)
        _check(type(self.entry_decision_allowed) is bool)
        _check(type(self.entry_submission_allowed) is bool)
        _check(type(self.weekly_review_assumed) is bool)
        if self.candidate is not None:
            _check(type(self.candidate) is CapitalCandidate)
            self.candidate.__post_init__()


@dataclass(frozen=True, slots=True)
class CapitalTrajectoryRequest(_Offline):
    dataset: CapitalResearchDataset
    initial_cash: Decimal
    days: tuple[CapitalTrajectoryDay, ...]
    instruments: tuple[Instrument, ...]
    episode_fee_bound: Decimal | None
    entry_fee: Decimal
    exit_fee: Decimal
    roundtrip_friction_pct: Decimal
    entry_outcome: _Outcome = "filled"
    entry_fill_fraction: Decimal = Decimal(1)
    exit_outcome: _Outcome = "filled"
    exit_fill_fraction: Decimal = Decimal(1)


@dataclass(frozen=True, slots=True)
class CapitalTrajectoryPoint:
    at: datetime
    equity: Decimal
    account: CapitalActionAccountReplay
    policy: CapitalDailyPolicy | None
    opening: CapitalOpeningPolicy | None


@dataclass(frozen=True, slots=True)
class CapitalTrajectoryResult(_Offline):
    events: tuple[_Event, ...]
    observations: tuple[CapitalRiskObservation, ...]
    points: tuple[CapitalTrajectoryPoint, ...]
    account: CapitalActionAccountReplay
    risk: CapitalRiskReplay
    input_hash: str


def replay_capital_trajectory(request: CapitalTrajectoryRequest) -> CapitalTrajectoryResult:
    """Own complete source/schedule; reuse the one original-event execution loop.

    Daily model reconciliation, declared weekly-review assumptions, T+2,
    fractional terms, fees and synthetic clocks are research assumptions.
    No cached/prepared/account state is a
    public input and no qualification or live capability is constructed.
    """
    try:
        with localcontext(_CONTEXT):
            _check(type(request) is CapitalTrajectoryRequest)
            _check(request.source_qualified is False and request.cost_qualified is False)
            _check(request.execution_enabled is False and request.economic_admitted is False)
            _check(request.evidence_promotable is False)
            _check(type(request.days) is tuple and 0 < len(request.days) <= 2048)
            days = []
            for day in request.days:
                _check(type(day) is CapitalTrajectoryDay)
                day.__post_init__()
                days.append(
                    replace(day, candidate=replace(day.candidate) if day.candidate else None)
                )
            schedule = tuple(days)
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
            start = dates.index(schedule[0].session)
            sessions = tuple(day.session for day in schedule)
            _check(sessions == dates[start : start + len(schedule)])
            _check(type(request.instruments) is tuple and len(request.instruments) == 5)
            for item in request.instruments:
                _check(type(item) is Instrument)
                item.__post_init__()
                _check(item.observed_at.tzinfo is source.calendar.sessions[0].opens_at.tzinfo)
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
            prepared = _prepare_owned_capital_days(owned, sessions=sessions)
            _check(prepared.source_hash == owned.source_hash)

            return _replay_prepared_capital_trajectory(
                source=source,
                source_hash=owned.source_hash,
                prepared=prepared,
                terms=terms,
                instruments=instruments,
                schedule=schedule,
            )
    except (ValueError, TypeError, AttributeError, ArithmeticError, StopIteration):
        raise ValueError("capital_trajectory_invalid") from None


def _replay_prepared_capital_trajectory(
    *,
    source: CapitalResearchDataset,
    source_hash: str,
    prepared: _PreparedCapitalInput,
    terms: _CapitalOwnerTerms,
    instruments: tuple[Instrument, ...],
    schedule: tuple[CapitalTrajectoryDay, ...],
    opening_candidates: tuple[CapitalCandidate | None, ...] | None = None,
) -> CapitalTrajectoryResult:
    """Invocation-local owned inputs only; never a public preparation factory.

    The walk-forward frontend distinguishes a prior instruction's opening
    winner from the new close winner. Public trajectory-v1 remains unchanged.
    """
    _check(prepared.source_hash == source_hash and prepared.config_hash == source.config_hash)
    if opening_candidates is not None:
        _check(len(opening_candidates) == len(schedule))
    indices = {day.session: index for index, day in enumerate(prepared.days)}

    def frame_at(
        index: int,
        events: tuple[_Event, ...],
        observations: tuple[CapitalRiskObservation, ...],
    ) -> _CapitalOwnerFrame:
        day = schedule[index]
        original = prepared.days[indices[day.session]]
        facts = _capital_due_facts(
            initial_cash=terms.initial_cash,
            events=events,
            observations=observations,
            calendar=source.calendar,
            actions=source.actions,
            session=day.session,
            raw_bars=original.raw_bars,
        )
        opening_candidate = (
            day.candidate if opening_candidates is None else opening_candidates[index]
        )
        allowed = day.entry_submission_allowed and opening_candidate is not None
        if index:
            previous = schedule[index - 1]
            allowed = allowed and previous.candidate == opening_candidate
            if previous.candidate is not None:
                signal = next(
                    s
                    for s in prepared.days[indices[previous.session]].signals
                    if s.candidate == previous.candidate
                )
                for archive in source.actions:
                    if archive.symbol == signal.entry_symbol and any(
                        s.effective_date == day.session for s in archive.splits or ()
                    ):
                        allowed = False
        return _CapitalOwnerFrame(
            original.raw_bars,
            instruments,
            tuple(
                replace(
                    fact,
                    daily_reset_reconciled=True,
                    weekly_reset_reviewed=day.weekly_review_assumed,
                )
                for fact in facts
            ),
            True,
            day.weekly_review_assumed,
            day.entry_decision_allowed and day.candidate is not None,
            allowed,
        )

    def policy_at(index: int, at: datetime, opening: _Opening | None) -> CapitalDailyPolicy | None:
        if opening is not None and type(opening) is not CapitalOpeningPolicy:
            raise ValueError("capital_trajectory_invalid")
        candidate = opening.candidate if opening else schedule[index].candidate
        if candidate is None:
            return None
        return _capital_prepared_policy(
            loaded=terms.loaded,
            prepared=prepared,
            day_index=indices[schedule[index].session],
            candidate=candidate,
            opening=opening,
        )

    def identity() -> str:
        preimage = (
            "capital-dataset-trajectory-v1",
            source_hash,
            prepared.input_hash,
            schedule,
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
            "close-signal-close-plus3-observation_daily-model-reset_declared-weekly-assumption_T+2",
        )
        if opening_candidates is not None:
            return content_hash(
                ("capital-trajectory-opening-selection-v1", preimage, opening_candidates)
            )
        return content_hash(preimage)

    result = _replay_capital_owner(
        terms,
        count=len(schedule),
        frame_at=frame_at,
        policy_at=policy_at,
        identity=identity,
    )
    points = []
    for point in result.points:
        if (point.policy is not None and type(point.policy) is not CapitalDailyPolicy) or (
            point.opening is not None and type(point.opening) is not CapitalOpeningPolicy
        ):
            raise ValueError("capital_trajectory_invalid")
        points.append(
            CapitalTrajectoryPoint(
                point.at, point.equity, point.account, point.policy, point.opening
            )
        )
    return CapitalTrajectoryResult(
        result.events,
        result.observations,
        tuple(points),
        result.account,
        result.risk,
        result.input_hash,
    )
