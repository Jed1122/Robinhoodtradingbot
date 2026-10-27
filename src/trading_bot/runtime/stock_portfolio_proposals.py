"""Compose source-bound owned stock proposals without cash or execution authority.

Callers supply actual portfolio, lot, fill, policy and reconciliation evidence.
This module performs no account lookup, invents no ledger facts, and never feeds
projected sale proceeds or estimated gains into the separate cash allocator.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import require_bounded_decimal
from trading_bot.domain.enums import AssetClass
from trading_bot.market_data.recording import content_hash
from trading_bot.portfolio.stock_allocation import (
    StockAllocationContext,
    plan_stock_allocations,
)
from trading_bot.portfolio.stock_holding import StockHoldingPrice
from trading_bot.portfolio.stock_profit_taking import (
    ProfitMethod,
    StockProfitExitState,
    StockProfitOrigin,
    StockProfitPolicy,
    StockProfitReduction,
    propose_stock_profit_reduction,
)
from trading_bot.research.stock_investment_decisions import CurrentStockRankings
from trading_bot.runtime.stock_investment_evidence import CurrentStockEvidenceBatch
from trading_bot.runtime.stock_investment_holdings import (
    CurrentStockHoldingReviews,
    StockOwnedHoldingContext,
    current_stock_snapshot_price,
    review_current_stock_holdings,
)

_VERSION = "current-stock-portfolio-proposals-v1"


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("stock_portfolio_proposals_invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class StockProfitProposalRequest:
    episode_id: str
    method: ProfitMethod
    origin: StockProfitOrigin | None
    state: StockProfitExitState | None
    fractional_eligible: bool | None
    peak_price: StockHoldingPrice | None
    tax_rate: Decimal | None
    disposal_method: Literal["unknown", "fifo_estimate"]
    policy: StockProfitPolicy

    def __post_init__(self) -> None:
        _check(
            type(self.episode_id) is str
            and 0 < len(self.episode_id) <= 128
            and self.episode_id.isprintable()
        )
        _check(self.method in ("principal", "partial_first", "partial_second", "trend"))
        _check(self.origin is None or type(self.origin) is StockProfitOrigin)
        _check(self.state is None or type(self.state) is StockProfitExitState)
        _check(self.fractional_eligible is None or type(self.fractional_eligible) is bool)
        _check(self.peak_price is None or type(self.peak_price) is StockHoldingPrice)
        if self.tax_rate is not None:
            require_bounded_decimal(self.tax_rate, "profit_tax_rate", nonnegative=True)
            _check(self.tax_rate <= 1)
        _check(self.disposal_method in ("unknown", "fifo_estimate"))
        _check(type(self.policy) is StockProfitPolicy)
        _ = self.policy.evidence_hash

    @property
    def evidence_hash(self) -> str:
        self.__post_init__()
        return str(content_hash((_VERSION, "profit-request", self)))


@dataclass(frozen=True, slots=True)
class StockPortfolioProposalSet:
    holding_reviews: CurrentStockHoldingReviews | None
    profit_reductions: tuple[StockProfitReduction, ...]
    entry_block_reasons: tuple[str, ...]
    needs: tuple[str, ...]
    reviewed_at: datetime
    expires_at: datetime | None
    input_evidence_hash: str
    execution_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    orders_created: Literal[False] = field(default=False, init=False)
    reservations_created: Literal[False] = field(default=False, init=False)
    cash_credited: Literal[False] = field(default=False, init=False)
    global_concurrency_authority: Literal[False] = field(default=False, init=False)

    @property
    def evidence_hash(self) -> str:
        require_utc(self.reviewed_at)
        if self.expires_at is not None:
            require_utc(self.expires_at)
            _check(self.reviewed_at < self.expires_at)
        _check(
            self.execution_authorized
            is self.live_authorized
            is self.orders_created
            is self.reservations_created
            is self.cash_credited
            is self.global_concurrency_authority
            is False
        )
        return str(
            content_hash(
                (
                    _VERSION,
                    None if self.holding_reviews is None else self.holding_reviews.evidence_hash,
                    tuple(x.evidence_hash for x in self.profit_reductions),
                    self.entry_block_reasons,
                    self.needs,
                    self.reviewed_at,
                    self.expires_at,
                    self.input_evidence_hash,
                )
            )
        )


def _context(
    context: StockAllocationContext | None, now: datetime, blockers: set[str]
) -> StockAllocationContext | None:
    if context is None:
        blockers.add("portfolio_context_missing")
        return None
    try:
        _check(type(context) is StockAllocationContext)
        # Reuse every public source, nested-position, exposure and cash check.
        # Zero candidates cannot allocate, reserve or credit anything.
        validation = plan_stock_allocations(context, (), now=now)
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        blockers.add("portfolio_context_invalid")
        return None
    blockers.update("portfolio_" + x for x in validation.reason_codes)
    if (
        not context.as_of <= now < context.expires_at
        or context.currency != "USD"
        or context.source_hash is None
        or context.reconciliation_hash is None
    ):
        return None
    return context


def _bound_owners(
    batch: CurrentStockEvidenceBatch,
    context: StockAllocationContext,
    owners: dict[str, StockOwnedHoldingContext],
    blockers: set[str],
    now: datetime,
) -> tuple[StockOwnedHoldingContext, ...]:
    positions = {str(x.instrument_id): x for x in context.portfolio.positions}
    exposures = {x.symbol: x for x in context.exposures if x.origin == "position"}
    held = {x.symbol: x for x in batch.stocks if x.held}
    _check(len(held) == sum(x.held for x in batch.stocks))
    if len(exposures) != len(positions) or {
        (x.symbol, x.instrument_id, x.sleeve) for x in exposures.values()
    } != {(x.symbol, x.instrument_id, x.horizon) for x in held.values()}:
        blockers.add("portfolio_research_inventory_mismatch")
    accepted = []
    for symbol, stock in sorted(held.items()):
        row = exposures.get(symbol)
        owner = owners.get(symbol)
        if owner is None:
            blockers.add("owned_holding_context_missing:" + symbol)
            continue
        mandate = owner.mandate
        if (
            row is None
            or row.instrument_id not in positions
            or row.instrument_kind != "stock"
            or (row.instrument_id, row.sleeve) != (stock.instrument_id, stock.horizon)
            or (mandate.instrument_id, mandate.sleeve) != (row.instrument_id, row.sleeve)
        ):
            blockers.add("owned_position_identity_mismatch:" + symbol)
            continue
        if (
            owner.currency != "USD"
            or owner.reconciliation_hash != context.reconciliation_hash
            or not owner.as_of <= context.as_of <= now < owner.expires_at
        ):
            blockers.add("owned_source_or_clock_mismatch:" + symbol)
            continue
        position = positions[row.instrument_id]
        if position.asset_class is not AssetClass.EQUITY or position.quantity <= 0:
            blockers.add("owned_position_unsupported:" + symbol)
            continue
        if owner.remaining_lots is None:
            blockers.add("owned_lots_unknown:" + symbol)
        elif sum((Fraction(x.quantity) for x in owner.remaining_lots), Fraction(0)) != Fraction(
            position.quantity
        ):
            blockers.add("owned_quantity_mismatch:" + symbol)
            continue
        accepted.append(owner)
    for symbol in owners.keys() - held.keys():
        blockers.add("owned_research_context_missing:" + symbol)
    return tuple(accepted)


def compile_stock_portfolio_proposals(
    batch: CurrentStockEvidenceBatch,
    *,
    rankings: CurrentStockRankings,
    allocation_context: StockAllocationContext | None,
    owned: tuple[StockOwnedHoldingContext, ...] = (),
    profit_requests: tuple[StockProfitProposalRequest, ...] = (),
    reviewed_at: datetime,
) -> StockPortfolioProposalSet:
    """Join actual supplied ownership before any unexecuted holding/profit proposal."""
    try:
        _check(type(batch) is CurrentStockEvidenceBatch and type(rankings) is CurrentStockRankings)
        require_utc(reviewed_at)
        _check(batch.as_of == rankings.as_of <= reviewed_at)
        inventory = {(x.symbol, x.horizon): x for x in batch.stocks}
        assessments = {(x.symbol, x.horizon): x for x in rankings.assessments}
        _check(
            len(inventory) == len(batch.stocks)
            and len(assessments) == len(rankings.assessments)
            and inventory.keys() == assessments.keys()
        )
        for key, stock in inventory.items():
            decision = assessments[key]
            _check(
                decision.evidence_hash == stock.evidence_hash
                and decision.instrument_id == stock.instrument_id
                and decision.as_of == batch.as_of
            )
        for sleeve, rows in (("long_term", rankings.long_term), ("tactical", rankings.tactical)):
            for decision in rows:
                _check(
                    decision.horizon == sleeve
                    and (decision.symbol, decision.horizon) in assessments
                    and decision.decision_hash
                    == assessments[decision.symbol, decision.horizon].decision_hash
                )
        _check(type(owned) is tuple and len(owned) <= 256)
        _check(type(profit_requests) is tuple and len(profit_requests) <= 256)
        blockers: set[str] = set()
        needs: set[str] = set()
        owners: dict[str, StockOwnedHoldingContext] = {}
        episodes: set[str] = set()
        for owner in owned:
            _check(type(owner) is StockOwnedHoldingContext)
            _check(owner.mandate.symbol not in owners and owner.mandate.episode_id not in episodes)
            episodes.add(owner.mandate.episode_id)
            try:
                owner.__post_init__()
            except (ValueError, TypeError, ArithmeticError, AttributeError):
                blockers.add("owned_holding_context_invalid:" + owner.mandate.symbol)
                continue
            owners[owner.mandate.symbol] = owner
        requested: set[str] = set()
        for request in profit_requests:
            _check(type(request) is StockProfitProposalRequest)
            request.__post_init__()
            _check(request.episode_id not in requested)
            requested.add(request.episode_id)
        identity = str(
            content_hash(
                (
                    _VERSION,
                    batch.evidence_hash,
                    rankings.report_hash,
                    allocation_context,
                    owned,
                    tuple(x.evidence_hash for x in profit_requests),
                    reviewed_at,
                )
            )
        )
        context = _context(allocation_context, reviewed_at, blockers)
        holding = None
        reductions = []
        expires_at = None
        if context is not None:
            bound = _bound_owners(batch, context, owners, blockers, reviewed_at)
            # The holding adapter owns source/decision/indicative-price validation.
            holding = review_current_stock_holdings(
                batch, rankings=rankings, owned=bound, reviewed_at=reviewed_at
            )
            by_episode = {x.mandate.episode_id: x for x in bound}
            unknown_quantity = {x.mandate.episode_id for x in bound if x.remaining_lots is None}
            reviews = []
            for review in holding.reviews:
                if review.mandate.episode_id in unknown_quantity and review.action == "EXIT":
                    needs.add("owned_exit_quantity_unverified:" + review.mandate.symbol)
                else:
                    reviews.append(review)
            holding = replace(holding, reviews=tuple(reviews))
            needs.update(holding.needs)
            exits = {x.mandate.episode_id for x in holding.reviews if x.action == "EXIT"}
            stocks = {x.symbol: x for x in batch.stocks if x.held}
            expiries = [context.expires_at]
            prices = {}
            for owner in bound:
                symbol = owner.mandate.symbol
                expiries.append(owner.expires_at)
                price = current_stock_snapshot_price(
                    stocks[symbol],
                    batch_evidence_hash=batch.evidence_hash,
                    currency=owner.currency,
                    reviewed_at=reviewed_at,
                )
                prices[symbol] = price
                if price is not None:
                    metric = next(x for x in stocks[symbol].metrics if x.name == "scanner_price")
                    expiries.extend(
                        (metric.refs[0].expires_at, price.received_at + timedelta(minutes=120))
                    )
                for decision in rankings.assessments:
                    if (
                        (decision.symbol, decision.horizon) == (symbol, owner.mandate.sleeve)
                        and decision.continuation_status in ("active", "inactive")
                        and decision.expires_at is not None
                        and reviewed_at < decision.expires_at
                    ):
                        expiries.append(decision.expires_at)
            for request in profit_requests:
                request_owner = by_episode.get(request.episode_id)
                if request_owner is None:
                    blockers.add("profit_request_owner_missing:" + request.episode_id)
                    continue
                mandate = request_owner.mandate
                if mandate.episode_id in exits:
                    needs.add("profit_trim_suppressed_by_full_exit:" + mandate.symbol)
                    continue
                price = prices[mandate.symbol]
                reductions.append(
                    propose_stock_profit_reduction(
                        mandate,
                        method=request.method,
                        remaining_lots=request_owner.remaining_lots,
                        origin=request.origin,
                        state=request.state,
                        price=price,
                        costs=request_owner.costs,
                        fractional_eligible=request.fractional_eligible,
                        reviewed_at=reviewed_at,
                        tax_rate=request.tax_rate,
                        disposal_method=request.disposal_method,
                        peak_price=request.peak_price,
                        policy=request.policy,
                    )
                )
                if request.state is not None:
                    expiries.extend(
                        (
                            request.state.expires_at,
                            request.state.information_at
                            + timedelta(minutes=request.policy.state_max_age_minutes),
                        )
                    )
                if price is not None:
                    expiries.append(
                        price.at + timedelta(minutes=request.policy.price_max_age_minutes)
                    )
            active = (
                not blockers
                or any(
                    x.action != "REVIEW" or x.price_pnl.status == "known" for x in holding.reviews
                )
                or any(x.status != "unavailable" for x in reductions)
            )
            if active:
                expires_at = min(expiries)
                _check(reviewed_at < expires_at)
        return StockPortfolioProposalSet(
            holding,
            tuple(reductions),
            tuple(sorted(blockers)),
            tuple(sorted(needs)),
            reviewed_at,
            expires_at,
            identity,
        )
    except (ValueError, TypeError, ArithmeticError, AttributeError):
        raise ValueError("stock_portfolio_proposals_invalid") from None
