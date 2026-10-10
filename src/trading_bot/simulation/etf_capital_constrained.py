"""Source-owned policy-managed SPY comparison using the single execution owner."""

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, localcontext

from trading_bot.config.loader import restore_loaded_config
from trading_bot.domain import Instrument, require_bounded_decimal
from trading_bot.market_data.etf_capital_dataset import CapitalResearchDataset
from trading_bot.market_data.etf_capital_owned import _own_capital_source
from trading_bot.market_data.recording import content_hash
from trading_bot.research.etf_capital_constrained_policy import (
    _capital_constrained_policy,
    _CapitalConstrainedOpening,
    _CapitalConstrainedPolicy,
)
from trading_bot.research.etf_capital_feasibility import _config
from trading_bot.research.etf_capital_prepared import _prepare_owned_capital_days
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
        raise ValueError("capital_constrained_invalid")


@dataclass(frozen=True, slots=True)
class CapitalConstrainedDay:
    session: date
    entry_decision_allowed: bool = True
    entry_submission_allowed: bool = True
    weekly_review_assumed: bool = False

    def __post_init__(self) -> None:
        _check(type(self.session) is date)
        _check(type(self.entry_decision_allowed) is bool)
        _check(type(self.entry_submission_allowed) is bool)
        _check(type(self.weekly_review_assumed) is bool)


@dataclass(frozen=True, slots=True)
class CapitalConstrainedRequest(_Offline):
    dataset: CapitalResearchDataset
    initial_cash: Decimal
    days: tuple[CapitalConstrainedDay, ...]
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
class CapitalConstrainedPoint:
    at: datetime
    equity: Decimal
    account: CapitalActionAccountReplay
    policy: _CapitalConstrainedPolicy
    opening: _CapitalConstrainedOpening | None


@dataclass(frozen=True, slots=True)
class CapitalConstrainedResult(_Offline):
    events: tuple[_Event, ...]
    observations: tuple[CapitalRiskObservation, ...]
    points: tuple[CapitalConstrainedPoint, ...]
    account: CapitalActionAccountReplay
    risk: CapitalRiskReplay
    input_hash: str


def replay_capital_constrained(request: CapitalConstrainedRequest) -> CapitalConstrainedResult:
    """Never accept strategy scores, cached sources or saved account state."""
    try:
        with localcontext(_CONTEXT):
            _check(type(request) is CapitalConstrainedRequest)
            _check(request.source_qualified is False and request.cost_qualified is False)
            _check(request.execution_enabled is False and request.economic_admitted is False)
            _check(request.evidence_promotable is False)
            _check(type(request.days) is tuple and 0 < len(request.days) <= 2048)
            days = []
            for day in request.days:
                _check(type(day) is CapitalConstrainedDay)
                day.__post_init__()
                days.append(replace(day))
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
            sessions = tuple(d.session for d in schedule)
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

            def frame_at(
                index: int,
                events: tuple[_Event, ...],
                observations: tuple[CapitalRiskObservation, ...],
            ) -> _CapitalOwnerFrame:
                day, original = schedule[index], prepared.days[index]
                facts = _capital_due_facts(
                    initial_cash=terms.initial_cash,
                    events=events,
                    observations=observations,
                    calendar=source.calendar,
                    actions=source.actions,
                    session=day.session,
                    raw_bars=original.raw_bars,
                )
                overnight_split = any(
                    a.symbol == "SPY"
                    and any(s.effective_date == day.session for s in a.splits or ())
                    for a in source.actions
                )
                return _CapitalOwnerFrame(
                    original.raw_bars,
                    instruments,
                    tuple(
                        replace(
                            f,
                            daily_reset_reconciled=True,
                            weekly_reset_reviewed=day.weekly_review_assumed,
                        )
                        for f in facts
                    ),
                    True,
                    day.weekly_review_assumed,
                    day.entry_decision_allowed,
                    day.entry_submission_allowed and not overnight_split,
                )

            def policy_at(
                index: int, at: datetime, opening: _Opening | None
            ) -> _CapitalConstrainedPolicy:
                if opening is not None and type(opening) is not _CapitalConstrainedOpening:
                    raise ValueError("capital_constrained_invalid")
                return _capital_constrained_policy(
                    loaded=loaded, prepared=prepared, day_index=index, opening=opening
                )

            def identity() -> str:
                return content_hash(
                    (
                        "capital-constrained-spy-trajectory-v1",
                        owned.source_hash,
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
                        "20hold_no_regime_same_original_owner_daily-model-reset_declared-weekly_T+2",
                    )
                )

            result = _replay_capital_owner(
                terms,
                count=len(schedule),
                frame_at=frame_at,
                policy_at=policy_at,
                identity=identity,
            )
            points = []
            for point in result.points:
                if type(point.policy) is not _CapitalConstrainedPolicy or (
                    point.opening is not None
                    and type(point.opening) is not _CapitalConstrainedOpening
                ):
                    raise ValueError("capital_constrained_invalid")
                points.append(
                    CapitalConstrainedPoint(
                        point.at, point.equity, point.account, point.policy, point.opening
                    )
                )
            return CapitalConstrainedResult(
                result.events,
                result.observations,
                tuple(points),
                result.account,
                result.risk,
                result.input_hash,
            )
    except (ValueError, TypeError, AttributeError, ArithmeticError, StopIteration, IndexError):
        raise ValueError("capital_constrained_invalid") from None
