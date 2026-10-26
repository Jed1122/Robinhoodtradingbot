"""Conditional retrospective owner around the shared paused-account kernel.

No actual source loader or provider is called here. Complete retained originals
are freshly checked at owning boundaries; compiled contexts are never public
cache inputs. Independent cases share source views, never account cash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, cast

from trading_bot.research.hybrid_policies import (
    PolicyInput,
    SessionObservation,
    UniverseMembership,
    _compile_annual_policy_inventory,
    _CompiledAnnualPolicyInventory,
)
from trading_bot.research.hybrid_strategies import FAMILIES
from trading_bot.research.stock_economic_policies import _RetrospectivePolicyFrame
from trading_bot.research.stock_economic_replay import (
    StockEconomicReplayProtocol,
    StockEconomicReplayState,
    _advance_owned_economic_core,
    _begin_economic_core,
    _validate_cost_history,
)
from trading_bot.research.stock_monetary_admission import MonetaryCaseDependency
from trading_bot.research.stock_operating_costs import ModeledOperatingCostPlan
from trading_bot.research.stock_retrospective_replay_inputs import (
    PreparedRetrospectiveReplayInputs,
    _check,
    _check_native_calendar,
    _check_panel_metadata,
    _check_panel_window,
    _flags,
    _hash,
    _RetrospectivePanel,
    _same,
    _Unqualified,
    revalidate_retrospective_replay_inputs,
)


@dataclass(frozen=True, slots=True)
class RetrospectiveCaseSpec:
    family: str
    protocol: StockEconomicReplayProtocol
    operating_cost_plan: ModeledOperatingCostPlan
    long_term_profile: Literal["passive_75_SPY_baseline", "quality_stock_variant"] = (
        "passive_75_SPY_baseline"
    )

    def __post_init__(self) -> None:
        _check(
            self.family in FAMILIES and type(self.protocol) is StockEconomicReplayProtocol,
            "registered_retrospective_case_required",
        )
        self.protocol.__post_init__()
        _check(
            type(self.operating_cost_plan) is ModeledOperatingCostPlan,
            "explicit_operating_plan_required",
        )
        self.operating_cost_plan.__post_init__()
        _check(
            self.long_term_profile in ("passive_75_SPY_baseline", "quality_stock_variant"),
            "named_long_term_profile_required",
        )

    @property
    def evidence_hash(self) -> str:
        self.__post_init__()
        return _hash(
            (
                "retrospective-case-v1",
                self.family,
                self.protocol.evidence_hash,
                self.operating_cost_plan.evidence_hash,
                self.long_term_profile,
            )
        )


@dataclass(frozen=True, slots=True)
class _CaseRuntime:
    spec: RetrospectiveCaseSpec
    spec_hash: str
    core: StockEconomicReplayState | None
    unavailable_reasons: tuple[str, ...]
    seal: str


@dataclass(frozen=True, slots=True)
class RetrospectiveEconomicReplayState(_Unqualified):
    inputs: PreparedRetrospectiveReplayInputs
    panel: _RetrospectivePanel
    source_root: str
    annual: _CompiledAnnualPolicyInventory
    annual_root: str
    cases: tuple[_CaseRuntime, ...]
    next_session: int
    consumed_prefix: str
    full_constrained_cases: tuple[MonetaryCaseDependency, ...] = field(repr=False)
    long_term_quality_slots: tuple[tuple[str, str], ...]
    families: tuple[str, ...] = field(default=FAMILIES, init=False)

    @property
    def evidence_hash(self) -> str:
        _check_state(self)
        return _hash(
            (
                "retrospective-economic-state-v1",
                self.source_root,
                self.next_session,
                self.consumed_prefix,
                tuple((c.spec_hash, c.seal, c.unavailable_reasons) for c in self.cases),
                self.full_constrained_cases,
                self.long_term_quality_slots,
            )
        )


@dataclass(frozen=True, slots=True)
class RetrospectiveReplayCheckpoint(_Unqualified):
    source_root: str
    cases: tuple[RetrospectiveCaseSpec, ...]
    next_session: int
    state_hash: str
    active_state: Literal[False] = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class RetrospectiveEconomicReplayResult(_Unqualified):
    state: RetrospectiveEconomicReplayState
    source_root: str
    reused_late_window: Literal[True] = field(default=True, init=False)

    @property
    def evidence_hash(self) -> str:
        _flags(self)
        _check(
            self.state.next_session == 706 and self.source_root == self.state.source_root,
            "completed_retrospective_result_required",
        )
        return _hash(("conditional-retrospective-economic-result-v1", self.state.evidence_hash))


def _frame(
    panel: _RetrospectivePanel,
    spec: RetrospectiveCaseSpec,
    index: int,
    annual: _CompiledAnnualPolicyInventory,
) -> _RetrospectivePolicyFrame:
    _check_panel_metadata(panel)
    first = max(0, index - 252)
    _check_native_calendar(panel, first=first, last=min(index + 1, 705))
    at = panel.calendar[index].closes_at
    proxy = panel.convention.membership_available_at
    request = PolicyInput(
        panel.calendar[first : min(index + 2, 706)],
        tuple(
            SessionObservation(a.symbol, i, a.signal_bars[i], Decimal(a.native_volume[i]))
            for a in panel.assets[:8]
            for i in range(max(0, index - 252), index + 1)
        ),
        tuple(
            UniverseMembership(a.symbol, proxy, proxy, True, f"m:{a.symbol}:{panel.source_root}")
            for a in panel.assets[:8]
        ),
        at,
        True,
    )
    inventory = (
        annual
        if spec.family == "quality_momentum"
        else _CompiledAnnualPolicyInventory((), _hash(("owned-annual-policy-inventory-v1", ())))
    )
    return _RetrospectivePolicyFrame(spec.family, request, inventory, panel.source_root)


def _check_state(state: RetrospectiveEconomicReplayState, *, _owned_advance: bool = False) -> None:
    _check(type(state) is RetrospectiveEconomicReplayState, "active_retrospective_state_required")
    _flags(state)
    _check_panel_metadata(state.panel)
    _check(
        state.annual.root == state.annual_root == state.panel.annual_context_root,
        "owned_annual_inventory_changed",
    )
    _check(
        state.panel.source_root == state.source_root
        and type(state.next_session) is int
        and 200 <= state.next_session <= 706,
        "retrospective_state_source_or_clock_changed",
    )
    _check_panel_window(state.panel, first=state.next_session - 1, last=state.next_session - 1)
    _check_native_calendar(
        state.panel, first=max(0, state.next_session - 253), last=min(state.next_session, 705)
    )
    _check(
        state.consumed_prefix == state.panel.prefix_hashes[state.next_session],
        "retrospective_consumed_prefix_changed",
    )
    _check(
        type(state.cases) is tuple and 1 <= len(state.cases) <= 512,
        "bounded_registered_cases_required",
    )
    for case in state.cases:
        _check(case.spec.evidence_hash == case.spec_hash, "registered_case_changed")
        if case.core is not None:
            _check(
                case.core.protocol.evidence_hash == case.spec.protocol.evidence_hash
                and case.core.operating_cost_plan_hash
                == case.spec.operating_cost_plan.evidence_hash,
                "owned_case_protocol_changed",
            )
            _check(
                case.core.inputs is state.panel
                and case.core.next_session == state.next_session
                and (_owned_advance or case.core.evidence_hash == case.seal),
                "owned_retrospective_core_changed",
            )
        else:
            _check(
                bool(case.unavailable_reasons)
                and case.seal == _hash((case.spec_hash, case.unavailable_reasons)),
                "unavailable_case_changed",
            )
    _check(
        len(state.full_constrained_cases) == 56
        and all(
            c.evaluation_status == "unavailable"
            and c.qualified
            is c.source_qualified
            is c.strategy_qualified
            is c.investment_eligible
            is c.trading_enabled
            is c.live_authorized
            is False
            for c in state.full_constrained_cases
        )
        and tuple((c.symbol, c.family) for c in state.full_constrained_cases)
        == tuple(
            (symbol, family)
            for symbol in ("AXP", "AAPL", "BAC", "CVX", "KO", "KHC", "MCO", "OXY")
            for family in FAMILIES
        )
        and state.long_term_quality_slots
        == tuple(
            (symbol, "quality_stock_allocator_unavailable")
            for symbol in ("AXP", "AAPL", "BAC", "CVX", "KO", "KHC", "MCO", "OXY")
        )
        and state.families == FAMILIES,
        "complete_retrospective_missing_slots_required",
    )


def begin_retrospective_economic_replay(
    inputs: PreparedRetrospectiveReplayInputs, *, cases: tuple[RetrospectiveCaseSpec, ...]
) -> RetrospectiveEconomicReplayState:
    _check(
        type(inputs) is PreparedRetrospectiveReplayInputs, "prepared_retrospective_inputs_required"
    )
    fresh = revalidate_retrospective_replay_inputs(inputs)
    _check(
        type(fresh) is PreparedRetrospectiveReplayInputs, "available_retrospective_inputs_required"
    )
    _check(
        type(cases) is tuple
        and 1 <= len(cases) <= 512
        and all(type(c) is RetrospectiveCaseSpec for c in cases),
        "bounded_registered_cases_required",
    )
    hashes = tuple(c.evidence_hash for c in cases)
    _check(len(set(hashes)) == len(hashes), "duplicate_registered_case")
    fresh = cast(PreparedRetrospectiveReplayInputs, fresh)
    panel = fresh._panel
    _check_panel_window(panel, first=0, last=199)
    annual = _compile_annual_policy_inventory(panel.annual_quality)
    runtimes = []
    for spec, digest in zip(cases, hashes, strict=True):
        missing: tuple[str, ...] = ()
        if spec.long_term_profile == "quality_stock_variant":
            missing = ("quality_stock_allocator_unavailable",)
        elif spec.family in ("pead", "revision_momentum"):
            missing = ("historical_event_vintages_unavailable",)
        elif spec.family == "quality_momentum" and not annual.records:
            missing = ("annual_quality_inventory_unavailable",)
        if missing:
            runtimes.append(_CaseRuntime(spec, digest, None, missing, _hash((digest, missing))))
        else:
            core = _begin_economic_core(
                panel,
                spec.protocol,
                policy_frame=_frame(panel, spec, 199, annual),
                operating_cost_plan=spec.operating_cost_plan,
            )
            runtimes.append(_CaseRuntime(spec, digest, core, (), core.evidence_hash))
    return RetrospectiveEconomicReplayState(
        fresh,
        panel,
        panel.source_root,
        annual,
        annual.root,
        tuple(runtimes),
        200,
        panel.prefix_hashes[200],
        fresh.full_constrained_cases,
        fresh.long_term_quality_slots,
    )


def advance_retrospective_economic_session(
    state: RetrospectiveEconomicReplayState, *, session_index: int
) -> RetrospectiveEconomicReplayState:
    _check_state(state, _owned_advance=True)
    _check(
        type(session_index) is int and session_index == state.next_session and session_index < 706,
        "next_native_price_session_required",
    )
    _check_panel_window(state.panel, first=max(0, session_index - 252), last=session_index)
    runtimes = []
    for case in state.cases:
        if case.core is None:
            runtimes.append(case)
            continue
        core, seal = _advance_owned_economic_core(
            case.core,
            session_index=session_index,
            expected_seal=case.seal,
            policy_frame=_frame(state.panel, case.spec, session_index, state.annual),
        )
        runtimes.append(_CaseRuntime(case.spec, case.spec_hash, core, (), seal))
    return RetrospectiveEconomicReplayState(
        state.inputs,
        state.panel,
        state.source_root,
        state.annual,
        state.annual_root,
        tuple(runtimes),
        session_index + 1,
        state.panel.prefix_hashes[session_index + 1],
        state.full_constrained_cases,
        state.long_term_quality_slots,
    )


def checkpoint_retrospective_economic_replay(
    state: RetrospectiveEconomicReplayState,
) -> RetrospectiveReplayCheckpoint:
    return RetrospectiveReplayCheckpoint(
        state.source_root,
        tuple(c.spec for c in state.cases),
        state.next_session,
        state.evidence_hash,
    )


def resume_retrospective_economic_replay(
    checkpoint: RetrospectiveReplayCheckpoint, *, fresh_inputs: PreparedRetrospectiveReplayInputs
) -> RetrospectiveEconomicReplayState:
    _check(
        type(checkpoint) is RetrospectiveReplayCheckpoint and checkpoint.active_state is False,
        "inert_retrospective_checkpoint_required",
    )
    _flags(checkpoint)
    _check(
        type(checkpoint.next_session) is int and 200 <= checkpoint.next_session <= 706,
        "checkpoint_native_prefix_required",
    )
    state = begin_retrospective_economic_replay(fresh_inputs, cases=checkpoint.cases)
    _check(state.source_root == checkpoint.source_root, "checkpoint_source_identity_changed")
    while state.next_session < checkpoint.next_session:
        state = advance_retrospective_economic_session(state, session_index=state.next_session)
    _check(state.evidence_hash == checkpoint.state_hash, "checkpoint_owned_projection_changed")
    return state


def finish_retrospective_economic_replay(
    state: RetrospectiveEconomicReplayState, *, fresh_inputs: PreparedRetrospectiveReplayInputs
) -> RetrospectiveEconomicReplayResult:
    _check_state(state)
    _check(state.next_session == 706, "retrospective_study_not_finished")
    fresh = revalidate_retrospective_replay_inputs(fresh_inputs)
    _check(
        type(fresh) is PreparedRetrospectiveReplayInputs
        and fresh._panel.source_root == state.source_root
        and _same(fresh._panel, state.panel),
        "final_retrospective_sources_changed",
    )
    _check_panel_window(state.panel, first=0, last=705)
    for case in state.cases:
        if case.core is not None:
            _validate_cost_history(case.core)
    return RetrospectiveEconomicReplayResult(state, state.source_root)
