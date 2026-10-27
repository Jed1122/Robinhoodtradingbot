"""Compose source-bound current decisions with owned monthly stock reviews.

The portfolio owner supplies actual fill/lot/session evidence. This module never
discovers an account, invents a mandate, changes a lot or credits sale proceeds.
Its provider receipt mark is indicative and is not a completed-close trade or an
executable quote. Every result remains an unexecuted proposal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.recording import content_hash
from trading_bot.portfolio.stock_holding import (
    StockContinuationEvidence,
    StockHoldingLot,
    StockHoldingMandate,
    StockHoldingPrice,
    StockHoldingReview,
    StockProtectiveEvidence,
    StockRealizedPriceGain,
    StockRegularSession,
    StockSaleCostAssumptions,
    evaluate_stock_holding,
)
from trading_bot.research.stock_investment_decisions import (
    CurrentStockEvidence,
    CurrentStockRankings,
)
from trading_bot.runtime.stock_investment_evidence import CurrentStockEvidenceBatch


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("current_stock_holdings_invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class StockOwnedHoldingContext:
    mandate: StockHoldingMandate
    remaining_lots: tuple[StockHoldingLot, ...] | None
    realized_gains: tuple[StockRealizedPriceGain, ...] | None
    session: StockRegularSession
    costs: StockSaleCostAssumptions | None
    as_of: datetime
    expires_at: datetime
    source_hash: str
    reconciliation_hash: str
    currency: Literal["USD"] | None
    protective_evidence: StockProtectiveEvidence | None = None

    def __post_init__(self) -> None:
        _check(type(self.mandate) is StockHoldingMandate)
        self.mandate.__post_init__()
        require_utc(self.as_of)
        require_utc(self.expires_at)
        _check(self.mandate.first_fill_at <= self.as_of < self.expires_at)
        _require_sha256_hex(self.source_hash, "owned_holding_source")
        _require_sha256_hex(self.reconciliation_hash, "owned_holding_reconciliation")
        _check(self.currency in ("USD", None))
        _check(type(self.session) is StockRegularSession)
        self.session.__post_init__()
        _check(self.session.observed_at <= self.as_of)
        if self.costs is not None:
            _check(type(self.costs) is StockSaleCostAssumptions)
            self.costs.__post_init__()
        identity = (self.mandate.episode_id, self.mandate.instrument_id, self.mandate.symbol)
        seen_lots, seen_fills = set(), set()
        for rows, kind in ((self.remaining_lots, "lots"), (self.realized_gains, "gains")):
            _check(rows is None or (type(rows) is tuple and len(rows) <= 10000))
            for row in rows or ():
                _check(type(row) is (StockHoldingLot if kind == "lots" else StockRealizedPriceGain))
                row.__post_init__()
                _check((row.episode_id, row.instrument_id, row.symbol) == identity)
                if type(row) is StockHoldingLot:
                    _check(row.lot_id not in seen_lots and row.acquired_at <= self.as_of)
                    seen_lots.add(row.lot_id)
                elif type(row) is StockRealizedPriceGain:
                    _check(row.fill_id not in seen_fills and row.at <= self.as_of)
                    seen_fills.add(row.fill_id)
                else:
                    raise ValueError("current_stock_holdings_invalid")
        if self.protective_evidence is not None:
            self.protective_evidence.__post_init__()
            _check(
                (
                    self.protective_evidence.episode_id,
                    self.protective_evidence.instrument_id,
                    self.protective_evidence.symbol,
                )
                == identity
                and self.protective_evidence.observed_at <= self.as_of
            )

    @property
    def evidence_hash(self) -> str:
        self.__post_init__()
        return str(content_hash(("owned-current-stock-holding-context-v1", self)))


@dataclass(frozen=True, slots=True)
class CurrentStockHoldingReviews:
    reviews: tuple[StockHoldingReview, ...]
    needs: tuple[str, ...]
    reviewed_at: datetime
    input_evidence_hash: str
    execution_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    @property
    def evidence_hash(self) -> str:
        _check(self.execution_authorized is self.live_authorized is False)
        return str(
            content_hash(
                (
                    "current-stock-holding-reviews-v1",
                    tuple(x.evidence_hash for x in self.reviews),
                    self.needs,
                    self.reviewed_at,
                    self.input_evidence_hash,
                )
            )
        )


def current_stock_snapshot_price(
    stock: CurrentStockEvidence,
    *,
    batch_evidence_hash: str,
    currency: Literal["USD"] | None,
    reviewed_at: datetime,
) -> StockHoldingPrice | None:
    """Validate an owned, same-unit raw mark independently of entry eligibility.

    An unsuitable entry signal or missing company financial fact does not erase
    a valid price. A foreign/expired/wrong-purpose price must never be relabelled
    with an owned instrument's identity or combined with an unknown money unit.
    """
    try:
        _require_sha256_hex(batch_evidence_hash, "current_holding_batch")
        now = require_utc(reviewed_at)
        _check(currency == "USD" and stock.instrument_type == "stock")
        _check(stock.instrument_id is not None)
        metrics = tuple(x for x in stock.metrics if x.name == "scanner_price")
        _check(len(metrics) == 1)
        metric = metrics[0]
        _check(metric.value is not None and metric.value > 0)
        _check(metric.unit == "price_per_share" and metric.period_basis == "provider_current")
        _check(metric.currency == currency and len(metric.refs) == 1)
        ref = metric.refs[0]
        _check(stock.identity_refs == (ref,) and ref.tool == "preview_scan")
        _check(ref.symbol == stock.symbol and ref.instrument_id == stock.instrument_id)
        _require_sha256_hex(ref.observation_sha256, "current_holding_price_source")
        if ref.normalized_sha256 is not None:
            _require_sha256_hex(ref.normalized_sha256, "current_holding_price_normalization")
        received, expires = require_utc(ref.received_at), require_utc(ref.expires_at)
        _check(received <= now < min(expires, received + timedelta(minutes=120)))
        _check(ref.effective_date is None or ref.effective_date <= now.date())
        _check(metric.period_start is None and metric.period_end is None)
        if stock.instrument_id is None or metric.value is None:
            return None
        return StockHoldingPrice(
            stock.instrument_id,
            stock.symbol,
            metric.value,
            received,
            received,
            str(
                content_hash(
                    (
                        batch_evidence_hash,
                        ref.observation_sha256,
                        ref.record_ref,
                        str(metric.value),
                        currency,
                    )
                )
            ),
        )
    except Exception:
        return None


def review_current_stock_holdings(
    batch: CurrentStockEvidenceBatch,
    *,
    rankings: CurrentStockRankings,
    owned: tuple[StockOwnedHoldingContext, ...],
    reviewed_at: datetime,
) -> CurrentStockHoldingReviews:
    """Review existing owned episodes only, at the actual analytical/composition time."""
    try:
        _check(type(batch) is CurrentStockEvidenceBatch and type(rankings) is CurrentStockRankings)
        require_utc(reviewed_at)
        _check(batch.as_of == rankings.as_of <= reviewed_at)
        _check(type(owned) is tuple and len(owned) <= 256)
        by_symbol = {}
        for owned_context in owned:
            _check(type(owned_context) is StockOwnedHoldingContext)
            owned_context.__post_init__()
            _check(owned_context.mandate.symbol not in by_symbol)
            by_symbol[owned_context.mandate.symbol] = owned_context
        stocks = {x.symbol: x for x in batch.stocks if x.held}
        _check(len(stocks) == sum(x.held for x in batch.stocks))
        _check(set(by_symbol) <= set(stocks))
        decisions = {(x.symbol, x.horizon): x for x in rankings.assessments}
        needs, reviews = [], []
        for symbol, stock in sorted(stocks.items()):
            context = by_symbol.get(symbol)
            if context is None:
                needs.append("owned_holding_context_missing:" + symbol)
                continue
            mandate = context.mandate
            _check((stock.instrument_id, stock.horizon) == (mandate.instrument_id, mandate.sleeve))
            if not context.as_of <= reviewed_at < context.expires_at:
                needs.append("owned_holding_context_stale_or_future:" + symbol)
                continue
            price = current_stock_snapshot_price(
                stock,
                batch_evidence_hash=batch.evidence_hash,
                currency=context.currency,
                reviewed_at=reviewed_at,
            )
            if price is None:
                needs.append("owned_price_evidence_unusable:" + symbol)
            continuation = None
            decision = decisions.get((symbol, mandate.sleeve))
            protective = context.protective_evidence
            if decision is not None:
                _check(
                    decision.evidence_hash == stock.evidence_hash
                    and decision.instrument_id == mandate.instrument_id
                )
                if (
                    decision.continuation_status in ("active", "inactive")
                    and decision.expires_at is not None
                    and reviewed_at < decision.expires_at
                ):
                    continuation = StockContinuationEvidence(
                        mandate.episode_id,
                        mandate.instrument_id,
                        symbol,
                        decision.continuation_status,
                        decision.as_of,
                        reviewed_at,
                        decision.expires_at,
                        decision.decision_hash,
                    )
                if decision.action == "reduce" and protective is None:
                    protective = StockProtectiveEvidence(
                        mandate.episode_id,
                        mandate.instrument_id,
                        symbol,
                        decision.as_of,
                        "thesis_invalidated",
                        decision.decision_hash,
                    )
                if decision.action == "review":
                    needs.append("owned_thesis_review_required:" + symbol)
            else:
                needs.append("owned_current_decision_missing:" + symbol)
            reviews.append(
                evaluate_stock_holding(
                    mandate,
                    reviewed_at=reviewed_at,
                    session=context.session,
                    remaining_lots=context.remaining_lots,
                    realized_gains=context.realized_gains,
                    price=price,
                    costs=context.costs,
                    continuation=continuation,
                    protective_evidence=protective,
                    review_basis="receipt_snapshot_v1",
                    maximum_snapshot_age_minutes=120,
                )
            )
        identity = str(
            content_hash(
                (
                    batch.evidence_hash,
                    rankings.report_hash,
                    tuple(x.evidence_hash for x in owned),
                    reviewed_at,
                )
            )
        )
        return CurrentStockHoldingReviews(tuple(reviews), tuple(needs), reviewed_at, identity)
    except Exception:
        raise ValueError("current_stock_holdings_invalid") from None
