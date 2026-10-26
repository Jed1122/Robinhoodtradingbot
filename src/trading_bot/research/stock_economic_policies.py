"""Pure fictional policy/session orchestration; no data admission or live authority."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.recording import content_hash
from trading_bot.research.hybrid_policies import (
    BOUNDS,
    PolicyInput,
    StrategyProposal,
    UnavailablePolicy,
    evaluate_policies,
)
from trading_bot.research.hybrid_strategies import FAMILIES

if TYPE_CHECKING:
    from trading_bot.research.stock_economic_replay import (
        StockEconomicReplayInputs,
        StockEconomicReplayProtocol,
        StockEconomicReplayResult,
    )
    from trading_bot.research.stock_operating_costs import ModeledOperatingCostPlan

STOCK_POLICY_SYMBOLS = ("AXP", "AAPL", "BAC", "CVX", "KO", "KHC", "MCO", "OXY")
ECONOMIC_POLICY_SYMBOLS = (*STOCK_POLICY_SYMBOLS, "SPY")


def _check(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def family_holding_limit(family: str) -> int:
    _check(family in FAMILIES, "unknown_policy_family")
    return min(40, BOUNDS[family][1])


@dataclass(frozen=True, slots=True)
class _Unqualified:
    qualified: Literal[False] = field(default=False, init=False)
    source_qualified: Literal[False] = field(default=False, init=False)
    strategy_qualified: Literal[False] = field(default=False, init=False)
    investment_eligible: Literal[False] = field(default=False, init=False)
    trading_enabled: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    full_task5_complete: Literal[False] = field(default=False, init=False)


def _flags(value: _Unqualified) -> None:
    _check(
        value.qualified
        is value.source_qualified
        is value.strategy_qualified
        is value.investment_eligible
        is value.trading_enabled
        is value.live_authorized
        is value.full_task5_complete
        is False,
        "unqualified_policy_scope_required",
    )


@dataclass(frozen=True, slots=True)
class EconomicPolicyFrame(_Unqualified):
    family: str
    request: PolicyInput

    def __post_init__(self) -> None:
        _flags(self)
        _check(type(self.family) is str and self.family in FAMILIES, "unknown_policy_family")
        _check(type(self.request) is PolicyInput, "typed_policy_observations_required")
        self.request.__post_init__()
        _check(not self.request.held_positions, "held_state_is_kernel_owned")
        _check(
            1 <= len(self.request.sessions) <= 10000
            and len(self.request.observations) <= 8 * 253
            and len(self.request.universe) <= 1024
            and len(self.request.facts) <= 4096
            and len(self.request.events) <= 4096
            and len(self.request.annual_quality) <= 64,
            "bounded_policy_observations_required",
        )
        _check(
            {row.symbol for row in self.request.universe} == set(STOCK_POLICY_SYMBOLS)
            and all(row.symbol in STOCK_POLICY_SYMBOLS for row in self.request.observations),
            "full_eight_stock_policy_frame_required",
        )


@dataclass(frozen=True, slots=True)
class KnownPolicyCondition:
    symbol: str
    family: str
    active: bool
    proposal: StrategyProposal

    def __post_init__(self) -> None:
        _check(
            type(self.proposal) is StrategyProposal and type(self.active) is bool,
            "typed_known_policy_condition_required",
        )
        self.proposal.__post_init__()
        _check(
            self.proposal.qualified is False
            and self.symbol == self.proposal.symbol
            and self.family == self.proposal.family,
            "matching_unqualified_condition_required",
        )


@dataclass(frozen=True, slots=True)
class UnavailablePolicyCondition:
    symbol: str
    family: str
    outcome: UnavailablePolicy

    def __post_init__(self) -> None:
        _check(
            type(self.outcome) is UnavailablePolicy
            and self.outcome.qualified is False
            and self.symbol == self.outcome.symbol
            and self.family == self.outcome.family,
            "matching_unavailable_condition_required",
        )


PolicyCondition = KnownPolicyCondition | UnavailablePolicyCondition


@dataclass(frozen=True, slots=True)
class EconomicPolicyClose(_Unqualified):
    session_index: int
    information_at: datetime
    family: str
    held_positions: tuple[tuple[str, str], ...]
    conditions: tuple[PolicyCondition, ...]
    input_evidence_hash: str

    def __post_init__(self) -> None:
        _flags(self)
        require_utc(self.information_at)
        _require_sha256_hex(self.input_evidence_hash, "policy_input_evidence_hash")
        _check(
            type(self.session_index) is int
            and self.session_index >= 199
            and self.family in FAMILIES
            and type(self.conditions) is tuple
            and tuple(row.symbol for row in self.conditions) == STOCK_POLICY_SYMBOLS,
            "complete_typed_policy_close_required",
        )
        _check(
            type(self.held_positions) is tuple
            and self.held_positions == tuple(sorted(set(self.held_positions)))
            and all(
                symbol in STOCK_POLICY_SYMBOLS and family == self.family
                for symbol, family in self.held_positions
            ),
            "owned_policy_close_holdings_required",
        )
        for row in self.conditions:
            _check(
                type(row) in (KnownPolicyCondition, UnavailablePolicyCondition),
                "typed_policy_condition_required",
            )
            row.__post_init__()
            outcome = row.proposal if isinstance(row, KnownPolicyCondition) else row.outcome
            _check(
                row.family == self.family and outcome.information_at == self.information_at,
                "policy_condition_clock_or_family_mismatch",
            )
            if isinstance(row, KnownPolicyCondition):
                active = row.proposal.decision == "enter" or (
                    row.proposal.decision == "hold"
                    and (row.symbol, self.family) in self.held_positions
                )
                _check(row.active is active, "condition_must_match_owned_proposal")

    @property
    def evidence_hash(self) -> str:
        self.__post_init__()
        return str(content_hash(("fictional-economic-policy-close-v1", self)))


@dataclass(frozen=True, slots=True)
class OwnedPolicyEpisode:
    episode_id: str
    family: str
    maximum_holding_sessions: int

    def __post_init__(self) -> None:
        _check(
            type(self.episode_id) is str
            and bool(self.episode_id)
            and type(self.maximum_holding_sessions) is int
            and self.maximum_holding_sessions == family_holding_limit(self.family),
            "entry_owned_policy_holding_limit_required",
        )


@dataclass(frozen=True, slots=True)
class UnavailableLongTermQuality(_Unqualified):
    status: Literal["unavailable"] = field(default="unavailable", init=False)
    slots: tuple[tuple[str, str], ...] = field(
        default=tuple(
            (symbol, "quality_stock_allocator_and_complete_source_profile_unavailable")
            for symbol in STOCK_POLICY_SYMBOLS
        ),
        init=False,
    )

    def __post_init__(self) -> None:
        _flags(self)
        _check(
            self.status == "unavailable"
            and self.slots
            == tuple(
                (symbol, "quality_stock_allocator_and_complete_source_profile_unavailable")
                for symbol in STOCK_POLICY_SYMBOLS
            ),
            "complete_unavailable_quality_slots_required",
        )


@dataclass(frozen=True, slots=True)
class StockEconomicFamilyCase(_Unqualified):
    family: str
    replay: StockEconomicReplayResult
    policy_closes: tuple[EconomicPolicyClose, ...]
    long_term_quality: UnavailableLongTermQuality = field(
        default_factory=UnavailableLongTermQuality, init=False
    )
    long_term_profile: Literal["passive_75_SPY_baseline"] = field(
        default="passive_75_SPY_baseline", init=False
    )

    def __post_init__(self) -> None:
        _flags(self)
        self.long_term_quality.__post_init__()
        _check(
            self.replay.qualified
            is self.replay.source_qualified
            is self.replay.investment_eligible
            is self.replay.trading_enabled
            is self.replay.live_authorized
            is self.replay.full_task5_complete
            is False,
            "unqualified_replay_result_required",
        )
        _check(
            self.family in FAMILIES
            and type(self.policy_closes) is tuple
            and bool(self.policy_closes)
            and self.long_term_profile == "passive_75_SPY_baseline",
            "fixed_family_passive_case_required",
        )
        for close in self.policy_closes:
            close.__post_init__()
            _check(close.family == self.family, "case_family_close_mismatch")


@dataclass(frozen=True, slots=True)
class SevenFamilyEconomicReplay(_Unqualified):
    cases: tuple[StockEconomicFamilyCase, ...]

    def __post_init__(self) -> None:
        _flags(self)
        _check(
            type(self.cases) is tuple and tuple(case.family for case in self.cases) == FAMILIES,
            "all_seven_independent_family_cases_required",
        )
        for case in self.cases:
            case.__post_init__()

    @property
    def evidence_hash(self) -> str:
        self.__post_init__()
        return str(
            content_hash(
                (
                    "fictional-seven-family-economic-replay-v1",
                    tuple(
                        (
                            case.family,
                            case.replay.evidence_hash,
                            tuple(close.evidence_hash for close in case.policy_closes),
                            case.long_term_profile,
                            case.long_term_quality,
                        )
                        for case in self.cases
                    ),
                )
            )
        )


def validate_policy_assets(inputs: StockEconomicReplayInputs) -> None:
    """The optional seam has a complete fixed cohort and an explicit passive baseline."""
    _check(
        tuple(asset.symbol for asset in inputs.assets) == ECONOMIC_POLICY_SYMBOLS,
        "full_eight_stock_and_SPY_slots_required",
    )
    _check(
        all(asset.role == "stock_candidate" for asset in inputs.assets[:8])
        and inputs.assets[-1].role == "passive_comparison",
        "SPY_is_passive_only",
    )
    _check(
        inputs.long_term_allocations == (("SPY", Decimal(".75")),),
        "explicit_passive_75_SPY_baseline_required",
    )


def evaluate_economic_policy_close(
    frame: EconomicPolicyFrame,
    *,
    session_index: int,
    information_at: datetime,
    next_open: datetime | None,
    held_positions: tuple[tuple[str, str], ...],
) -> EconomicPolicyClose:
    """Project actual policy proposals using current filled holdings, never intended fills."""
    _check(type(frame) is EconomicPolicyFrame, "typed_policy_frame_required")
    frame.__post_init__()
    request = frame.request
    _check(request.information_at == information_at, "policy_close_clock_mismatch")
    sessions = {row.index: row for row in request.sessions}
    _check(
        session_index in sessions and sessions[session_index].closes_at == information_at,
        "policy_session_clock_mismatch",
    )
    if next_open is None:
        _check(
            not any(index > session_index for index in sessions),
            "no_fabricated_final_policy_execution_row",
        )
    else:
        following = sessions.get(session_index + 1)
        _check(
            following is not None
            and following.opens_at == next_open
            and not any(index > session_index + 1 for index in sessions),
            "policy_next_open_mismatch",
        )
    held = tuple(sorted(held_positions))
    _check(
        all(symbol in STOCK_POLICY_SYMBOLS and family == frame.family for symbol, family in held),
        "owned_family_held_state_required",
    )
    supplied = replace(request, held_positions=held)
    outcomes = tuple(row for row in evaluate_policies(supplied) if row.family == frame.family)
    _check(
        len(outcomes) == 8 and {row.symbol for row in outcomes} == set(STOCK_POLICY_SYMBOLS),
        "all_eight_actual_policy_outcomes_required",
    )
    by_symbol = {row.symbol: row for row in outcomes}
    conditions: list[PolicyCondition] = []
    for symbol in STOCK_POLICY_SYMBOLS:
        outcome = by_symbol[symbol]
        if isinstance(outcome, UnavailablePolicy):
            conditions.append(UnavailablePolicyCondition(symbol, frame.family, outcome))
        else:
            _check(
                outcome.qualified is False
                and outcome.information_at == information_at
                and outcome.execute_not_before == next_open,
                "causal_unqualified_proposal_required",
            )
            active = outcome.decision == "enter" or (
                outcome.decision == "hold" and (symbol, frame.family) in held
            )
            conditions.append(KnownPolicyCondition(symbol, frame.family, active, outcome))
    return EconomicPolicyClose(
        session_index,
        information_at,
        frame.family,
        held,
        tuple(conditions),
        str(
            content_hash(
                (
                    "fictional-economic-policy-input-v1",
                    replace(supplied, annual_quality=()),
                    # Annual evidence already binds every native lexical value and
                    # complete batch. Re-encoding its derived unused Decimal fields
                    # would incorrectly narrow the normalized native exponent range.
                    tuple(sorted({bundle.evidence_hash for bundle in supplied.annual_quality})),
                )
            )
        ),
    )


def run_seven_family_fictional_replay(
    inputs: StockEconomicReplayInputs,
    policy_inputs: tuple[PolicyInput, ...],
    protocol: StockEconomicReplayProtocol,
    *,
    operating_cost_plan: ModeledOperatingCostPlan | None = None,
) -> SevenFamilyEconomicReplay:
    """Seven independent hypothetical accounts, with no selection or financial claim."""
    from trading_bot.research.stock_economic_replay import (
        advance_stock_economic_session,
        begin_stock_economic_replay,
        finish_stock_economic_replay,
    )

    validate_policy_assets(inputs)
    count = len(inputs.assets[0].bars)
    _check(
        type(policy_inputs) is tuple and len(policy_inputs) == count - 199,
        "every_activated_policy_close_required",
    )
    cases = []
    for family in FAMILIES:
        state = begin_stock_economic_replay(
            inputs,
            protocol,
            policy_frame=EconomicPolicyFrame(family, policy_inputs[0]),
            operating_cost_plan=operating_cost_plan,
        )
        for offset, request in enumerate(policy_inputs[1:], start=200):
            state = advance_stock_economic_session(
                state, session_index=offset, policy_frame=EconomicPolicyFrame(family, request)
            )
        cases.append(
            StockEconomicFamilyCase(
                family, finish_stock_economic_replay(state), state.policy_closes
            )
        )
    return SevenFamilyEconomicReplay(tuple(cases))
