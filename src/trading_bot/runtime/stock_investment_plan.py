"""Current company research to auditable portfolio cash-ceiling proposals.

No transport, account lookup, order, reservation or execution attestation is
created here. A verified account context and issuer mapping must be supplied by
their owners. Missing account evidence leaves the research report useful while
preventing invented buying power. Risk authorization remains a separate step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.recording import content_hash
from trading_bot.portfolio.stock_allocation import (
    StockAllocationCandidate,
    StockAllocationContext,
    StockAllocationLimits,
    StockAllocationPlan,
    plan_stock_allocations,
)
from trading_bot.research.stock_investment_decisions import (
    CurrentInvestmentPolicy,
    CurrentStockRankings,
    rank_current_stocks,
)
from trading_bot.runtime.stock_investment_evidence import (
    PROFILE,
    CurrentStockEvidenceBatch,
    build_current_stock_evidence,
)
from trading_bot.runtime.stock_investment_inputs import CurrentStockResearchInputs

if TYPE_CHECKING:
    from trading_bot.runtime.stock_investment_holdings import StockOwnedHoldingContext
    from trading_bot.runtime.stock_portfolio_proposals import (
        StockPortfolioProposalSet,
        StockProfitProposalRequest,
    )

_SECTORS = {
    "Technology": "technology",
    "Healthcare": "healthcare",
    "Energy": "energy",
    "Industrials": "industrials",
    "Utilities": "utilities",
    "Real Estate": "real_estate",
    "Basic Materials": "basic_materials",
    "Consumer Cyclical": "consumer_cyclical",
    "Consumer Defensive": "consumer_defensive",
    "Communication Services": "communication_services",
    "Financial Services": "financial_services",
}
_EXECUTION_CHECKS = (
    "dedicated_agentic_account_and_live_authorization",
    "fresh_broker_quote_and_tradability",
    "known_eligible_market_session",
    "deterministic_risk_and_current_portfolio_reconciliation",
    "atomic_cash_reservation_and_duplicate_prevention",
    "official_order_review_and_broker_approval",
    "actual_fill_order_position_and_tax_lot_reconciliation",
)


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("current_stock_plan_invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class StockPlanningControls:
    research_enabled: bool
    kill_switch_active: bool
    tactical_entries_suspended: bool
    as_of: datetime
    expires_at: datetime
    source_hash: str

    def __post_init__(self) -> None:
        _check(
            all(
                type(x) is bool
                for x in (
                    self.research_enabled,
                    self.kill_switch_active,
                    self.tactical_entries_suspended,
                )
            )
        )
        require_utc(self.as_of)
        require_utc(self.expires_at)
        _check(self.as_of < self.expires_at)
        _require_sha256_hex(self.source_hash, "planning_controls_source")

    @property
    def evidence_hash(self) -> str:
        self.__post_init__()
        return str(content_hash(("current-stock-planning-controls-v1", self)))


@dataclass(frozen=True, slots=True, kw_only=True)
class StockIssuerIdentity:
    symbol: str
    instrument_id: str
    issuer_id: str
    as_of: datetime
    expires_at: datetime
    source_hash: str

    def __post_init__(self) -> None:
        _check(
            all(
                type(x) is str and 0 < len(x) <= 128 and x.isprintable()
                for x in (self.symbol, self.instrument_id, self.issuer_id)
            )
        )
        require_utc(self.as_of)
        require_utc(self.expires_at)
        _check(self.as_of < self.expires_at)
        _require_sha256_hex(self.source_hash, "issuer_identity_source")

    @property
    def evidence_hash(self) -> str:
        self.__post_init__()
        return str(content_hash(("stock-issuer-identity-v1", self)))


@dataclass(frozen=True, slots=True)
class CurrentStockPlan:
    as_of: datetime
    inputs_hash: str
    evidence_batch_hash: str
    policy_hash: str
    controls_hash: str | None
    issuer_hashes: tuple[str, ...]
    rankings: CurrentStockRankings | None
    allocation: StockAllocationPlan | None
    needs: tuple[str, ...]
    analysis_code_hash: str
    source_config_hash: str
    acquisition_code_hashes: tuple[str, ...]
    portfolio_proposals: StockPortfolioProposalSet | None
    performance_evidence: Literal["unproven_not_a_gate"] = field(
        default="unproven_not_a_gate", init=False
    )
    execution_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    orders_created: Literal[False] = field(default=False, init=False)
    reservations_created: Literal[False] = field(default=False, init=False)
    remaining_execution_checks: tuple[str, ...] = field(default=_EXECUTION_CHECKS, init=False)

    @property
    def evidence_hash(self) -> str:
        _check(
            self.execution_authorized
            is self.live_authorized
            is self.orders_created
            is self.reservations_created
            is False
        )
        _check(
            self.performance_evidence == "unproven_not_a_gate"
            and self.remaining_execution_checks == _EXECUTION_CHECKS
        )
        return str(
            content_hash(
                (
                    "current-stock-plan-v2",
                    self.as_of,
                    self.inputs_hash,
                    self.evidence_batch_hash,
                    self.policy_hash,
                    self.controls_hash,
                    self.issuer_hashes,
                    None if self.rankings is None else self.rankings.report_hash,
                    None if self.allocation is None else self.allocation.evidence_hash,
                    self.needs,
                    self.analysis_code_hash,
                    self.source_config_hash,
                    self.acquisition_code_hashes,
                    None
                    if self.portfolio_proposals is None
                    else self.portfolio_proposals.evidence_hash,
                )
            )
        )


def _candidates(
    batch: CurrentStockEvidenceBatch,
    rankings: CurrentStockRankings,
    issuers: dict[str, StockIssuerIdentity],
    controls: StockPlanningControls,
    reviewed_at: datetime,
) -> tuple[StockAllocationCandidate, ...]:
    evidence = {(x.symbol, x.horizon): x for x in batch.stocks}
    candidates = []
    for decision in (*rankings.long_term, *rankings.tactical):
        stock = evidence[decision.symbol, decision.horizon]
        if decision.action != "enter" or stock.held:
            continue
        identity = issuers.get(decision.symbol)
        if identity is not None and not (
            identity.instrument_id == decision.instrument_id
            and identity.as_of <= reviewed_at < identity.expires_at
        ):
            identity = None
        source_hash = str(
            content_hash(
                (
                    decision.evidence_hash,
                    None if identity is None else identity.evidence_hash,
                )
            )
        )
        _check(decision.instrument_id is not None and decision.ordinal_rank is not None)
        if decision.instrument_id is None or decision.ordinal_rank is None:
            raise ValueError("current_stock_plan_invalid")
        candidates.append(
            StockAllocationCandidate(
                instrument_id=decision.instrument_id,
                symbol=decision.symbol,
                issuer_id=None if identity is None else identity.issuer_id,
                sleeve=decision.horizon,
                sector=_SECTORS.get(stock.sector or ""),
                instrument_kind="stock",
                priority=decision.ordinal_rank,
                decision_status="ineligible"
                if decision.horizon == "tactical" and controls.tactical_entries_suspended
                else "eligible",
                decision_hash=decision.decision_hash,
                source_hash=source_hash,
                as_of=decision.as_of,
                expires_at=min(decision.expires_at, identity.expires_at)
                if decision.expires_at is not None and identity is not None
                else decision.expires_at,
            )
        )
    return tuple(candidates)


def compile_current_stock_plan(
    inputs: CurrentStockResearchInputs,
    *,
    worker_profile_id: str,
    policy: CurrentInvestmentPolicy,
    analysis_code_hash: str,
    controls: StockPlanningControls | None = None,
    allocation_context: StockAllocationContext | None = None,
    issuers: tuple[StockIssuerIdentity, ...] = (),
    held_sleeves: tuple[tuple[str, Literal["long_term", "tactical"]], ...] = (),
    limits: StockAllocationLimits | None = None,
    owned_holding_contexts: tuple[StockOwnedHoldingContext, ...] = (),
    profit_requests: tuple[StockProfitProposalRequest, ...] = (),
    reviewed_at: datetime | None = None,
) -> CurrentStockPlan:
    """Build present-use research and bounded proposals without execution authority."""
    try:
        from trading_bot.runtime.stock_portfolio_proposals import compile_stock_portfolio_proposals

        _check(worker_profile_id == PROFILE and type(policy) is CurrentInvestmentPolicy)
        _check(policy.financial_profile == "current_provider_v1")
        _require_sha256_hex(analysis_code_hash, "stock_analysis_code")
        policy_hash = policy.policy_hash
        batch = build_current_stock_evidence(
            inputs, worker_profile_id=worker_profile_id, held_sleeves=held_sleeves
        )
        reviewed = batch.as_of if reviewed_at is None else require_utc(reviewed_at)
        _check(batch.as_of <= reviewed)
        controls_hash = None
        if controls is not None:
            _check(type(controls) is StockPlanningControls)
            controls_hash = controls.evidence_hash
        _check(type(issuers) is tuple and len(issuers) <= 512)
        identities = {}
        for identity in issuers:
            _check(type(identity) is StockIssuerIdentity and identity.symbol not in identities)
            _ = identity.evidence_hash
            identities[identity.symbol] = identity
        issuer_hashes = tuple(sorted(x.evidence_hash for x in identities.values()))
        if controls is not None and not controls.research_enabled:
            return CurrentStockPlan(
                batch.as_of,
                inputs.evidence_hash,
                batch.evidence_hash,
                policy_hash,
                controls_hash,
                issuer_hashes,
                None,
                None,
                ("research_disabled",),
                analysis_code_hash,
                inputs.source_config_hash,
                inputs.acquisition_code_hashes,
                None,
            )
        rankings = rank_current_stocks(batch.stocks, policy=policy, as_of=batch.as_of)
        portfolio_proposals = compile_stock_portfolio_proposals(
            batch,
            rankings=rankings,
            allocation_context=allocation_context,
            owned=owned_holding_contexts,
            profit_requests=profit_requests,
            reviewed_at=reviewed,
        )
        needs = set(batch.needs)
        needs.update(portfolio_proposals.needs)
        needs.update(portfolio_proposals.entry_block_reasons)
        # Bounded discovery can intentionally outrun deeper company research.
        # Each unresearched new name stays REVIEW through its own assessment;
        # it must not deadlock other fully researched, exposure-safe candidates.
        # Missing held-company evidence and all source-wide failures still block.
        global_needs = tuple(
            reason
            for reason in inputs.needs
            if not (
                reason.startswith("discovery_dossier_missing:")
                and reason.partition(":")[2] not in inputs.held_symbols
            )
        )
        blocked = bool(global_needs) or any(x.startswith("held_") for x in batch.needs)
        blocked = blocked or bool(portfolio_proposals.entry_block_reasons)
        if controls is None:
            needs.add("planning_controls_missing")
            blocked = True
        elif not controls.as_of <= reviewed < controls.expires_at:
            needs.add("planning_controls_stale_or_future")
            blocked = True
        elif controls.kill_switch_active:
            needs.add("kill_switch_active")
            blocked = True
        if allocation_context is None:
            needs.add("account_context_missing")
            blocked = True
        else:
            if any(x.sector not in _SECTORS.values() for x in allocation_context.exposures):
                needs.add("portfolio_sector_namespace_unrecognized")
                blocked = True
            positions = {
                (x.symbol, x.instrument_id, x.sleeve)
                for x in allocation_context.exposures
                if x.origin == "position"
            }
            researched = {(x.symbol, x.instrument_id, x.horizon) for x in batch.stocks if x.held}
            if (
                positions != researched
                or {x[0] for x in positions} != set(inputs.held_symbols)
                or {(x[0], x[2]) for x in positions} != set(held_sleeves)
            ):
                needs.add("owned_research_inventory_mismatch")
                blocked = True
        allocation = None
        if not blocked and allocation_context is not None and controls is not None:
            allocation = plan_stock_allocations(
                allocation_context,
                candidates=_candidates(batch, rankings, identities, controls, reviewed),
                limits=limits,
                now=reviewed,
            )
        return CurrentStockPlan(
            batch.as_of,
            inputs.evidence_hash,
            batch.evidence_hash,
            policy_hash,
            controls_hash,
            issuer_hashes,
            rankings,
            allocation,
            tuple(sorted(needs)),
            analysis_code_hash,
            inputs.source_config_hash,
            inputs.acquisition_code_hashes,
            portfolio_proposals,
        )
    except Exception:
        raise ValueError("current_stock_plan_invalid") from None
