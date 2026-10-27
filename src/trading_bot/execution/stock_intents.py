"""Pure, explicit SIMULATION-only drafts from current stock investment policy.

No transport, credential, account discovery, reservation or fill occurs here.
The journal owner passes its exact base Account inside the atomic transition.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timedelta
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)
from fractions import Fraction
from math import lcm
from typing import Any, Literal, cast
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel

from trading_bot.brokers.robinhood_stock_payloads import (
    PreparedStockOrderPayloads,
    StockOrderTerms,
    prepare_stock_order_payloads,
)
from trading_bot.clock import require_utc
from trading_bot.config.hybrid import HybridSettings
from trading_bot.domain import (
    AssetClass,
    ExecutionMode,
    Instrument,
    MarketClock,
    OrderIntent,
    OrderPurpose,
    OrderType,
    Side,
    TimeInForce,
    quantize_down,
)
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.domain.identifiers import AccountId, ConfigHash, DataHash, OrderIntentId
from trading_bot.hybrid.execution import mark_equity, reserve_order
from trading_bot.hybrid.models import Account, PaperOrder, Quote
from trading_bot.market_data.recording import content_hash
from trading_bot.portfolio.stock_allocation import (
    StockAllocationContext,
    StockAllocationLimits,
    StockAllocationPlan,
    StockAllocationProposal,
)
from trading_bot.portfolio.stock_profit_taking import (
    ProfitMethod,
    StockProfitExitState,
    StockProfitOrigin,
)
from trading_bot.research.stock_investment_decisions import (
    CurrentInvestmentPolicy,
    CurrentStockRankings,
)
from trading_bot.runtime.stock_investment_holdings import StockOwnedHoldingContext
from trading_bot.runtime.stock_investment_inputs import CurrentStockResearchInputs
from trading_bot.runtime.stock_investment_plan import (
    CurrentStockPlan,
    StockIssuerIdentity,
    StockPlanningControls,
    compile_current_stock_plan,
)
from trading_bot.runtime.stock_investment_reports import current_stock_plan_document
from trading_bot.runtime.stock_portfolio_proposals import (
    StockPortfolioProposalSet,
    StockProfitProposalRequest,
)

_VERSION = "current-stock-simulation-intents-v1"
_CONTEXT = Context(
    prec=50,
    rounding=ROUND_HALF_EVEN,
    Emin=-999999,
    Emax=999999,
    capitals=1,
    clamp=0,
    flags=[],
    traps=[InvalidOperation, DivisionByZero, Overflow, Underflow],
)
Sleeve = Literal["long_term", "tactical"]


def _check(valid: bool) -> None:
    if not valid:
        raise ValueError("stock_simulation_intent_unavailable")


def _text(value: str) -> None:
    _check(type(value) is str and 0 < len(value) <= 128 and value.isascii() and value.isprintable())


def _number(value: Decimal, *, positive: bool = False) -> None:
    require_bounded_decimal(
        value, "stock_simulation_value", positive=positive, nonnegative=not positive
    )


def _wire(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _wire(value.model_dump())
    if is_dataclass(value) and not isinstance(value, type):
        return _wire(asdict(value))
    if isinstance(value, dict):
        return {key: _wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_wire(item) for item in value)
    return value


def _hash(value: object) -> str:
    with localcontext(_CONTEXT):
        return str(content_hash(_wire(value)))


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class StockExecutionMarketEvidence:
    instrument: Instrument
    quote: Quote
    market_clock: MarketClock
    currency: Literal["USD"]
    received_at: datetime
    expires_at: datetime
    source_hash: str
    sector_source_hash: str | None
    earnings_source_hash: str | None
    liquidity_source_hash: str | None

    @property
    def evidence_hash(self) -> str:
        _check(type(self.instrument) is Instrument and type(self.quote) is Quote)
        self.instrument.__post_init__()
        Quote.model_validate(self.quote.model_dump())
        _check(type(self.market_clock) is MarketClock)
        self.market_clock.__post_init__()
        _check(self.currency == "USD")
        require_utc(self.received_at)
        require_utc(self.expires_at)
        _check(
            self.instrument.asset_class is self.market_clock.asset_class is AssetClass.EQUITY
            and self.instrument.symbol == self.quote.symbol
            and self.quote.as_of <= self.received_at < self.expires_at
            and self.instrument.observed_at <= self.received_at
            and self.market_clock.observed_at <= self.received_at
        )
        for digest in (
            self.source_hash,
            self.sector_source_hash,
            self.earnings_source_hash,
            self.liquidity_source_hash,
        ):
            if digest is not None:
                _require_sha256_hex(digest, "stock_execution_market")
        return _hash((_VERSION, "market", self))


@dataclass(frozen=True, slots=True, kw_only=True)
class StockExecutionRiskStop:
    instrument_id: str
    symbol: str
    price: Decimal
    as_of: datetime
    expires_at: datetime
    source_hash: str

    @property
    def evidence_hash(self) -> str:
        _text(self.instrument_id)
        _text(self.symbol)
        _number(self.price, positive=True)
        require_utc(self.as_of)
        require_utc(self.expires_at)
        _check(self.as_of < self.expires_at)
        _require_sha256_hex(self.source_hash, "stock_risk_stop")
        return _hash((_VERSION, "risk-stop", self))


@dataclass(frozen=True, slots=True, kw_only=True)
class StockExecutionSelection:
    kind: Literal["entry", "holding_exit", "profit_reduction"]
    symbol: str
    sleeve: Sleeve
    source_evidence_hash: str
    episode_id: str | None
    method: ProfitMethod | None
    order_type: Literal["market", "limit"]
    limit_price: Decimal | None
    risk_stop: StockExecutionRiskStop | None

    @property
    def evidence_hash(self) -> str:
        _check(self.kind in ("entry", "holding_exit", "profit_reduction"))
        _text(self.symbol)
        _check(self.sleeve in ("long_term", "tactical"))
        _require_sha256_hex(self.source_evidence_hash, "stock_selection")
        _check(self.order_type in ("market", "limit"))
        _check((self.limit_price is None) == (self.order_type == "market"))
        if self.limit_price is not None:
            _number(self.limit_price, positive=True)
        if self.episode_id is not None:
            _text(self.episode_id)
        _check((self.episode_id is None) == (self.kind == "entry"))
        _check((self.method is None) == (self.kind != "profit_reduction"))
        _check(
            self.method is None
            or self.method in ("principal", "partial_first", "partial_second", "trend")
        )
        if self.risk_stop is not None:
            _check(type(self.risk_stop) is StockExecutionRiskStop)
            _ = self.risk_stop.evidence_hash
        _check(self.risk_stop is None or (self.kind == "entry" and self.sleeve == "tactical"))
        return _hash((_VERSION, "selection", self))


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class StockExecutionContext:
    plan: CurrentStockPlan
    inputs: CurrentStockResearchInputs
    policy: CurrentInvestmentPolicy
    controls: StockPlanningControls
    allocation_context: StockAllocationContext
    issuers: tuple[StockIssuerIdentity, ...]
    held_sleeves: tuple[tuple[str, Sleeve], ...]
    owned_holding_contexts: tuple[StockOwnedHoldingContext, ...]
    profit_requests: tuple[StockProfitProposalRequest, ...]
    limits: StockAllocationLimits | None
    execution_policy: HybridSettings
    execution_config_hash: str
    source_report_body_sha256: str
    market: tuple[StockExecutionMarketEvidence, ...]

    @property
    def evidence_hash(self) -> str:
        _validate_context(self)
        return _hash((_VERSION, "context", self))


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class StockSimulationGrant:
    approval_id: str
    mode: ExecutionMode
    simulation_account_id: str
    sleeve: Sleeve
    approved_at: datetime
    expires_at: datetime
    plan_hash: str
    policy_hash: str
    source_config_hash: str
    analysis_code_hash: str
    execution_config_hash: str
    source_report_body_sha256: str
    context_hash: str
    selection_hash: str
    before_account_hash: str

    @property
    def evidence_hash(self) -> str:
        _text(self.approval_id)
        _text(self.simulation_account_id)
        _check(self.mode is ExecutionMode.SIMULATION)
        _check(
            self.simulation_account_id.startswith("sim-") and len(self.simulation_account_id) > 4
        )
        _check(self.sleeve in ("long_term", "tactical"))
        require_utc(self.approved_at)
        require_utc(self.expires_at)
        _check(self.approved_at < self.expires_at)
        for digest in (
            self.plan_hash,
            self.policy_hash,
            self.source_config_hash,
            self.analysis_code_hash,
            self.execution_config_hash,
            self.source_report_body_sha256,
            self.context_hash,
            self.selection_hash,
            self.before_account_hash,
        ):
            _require_sha256_hex(digest, "stock_simulation_binding")
        return _hash((_VERSION, "manual-simulation-grant", self))


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class PreparedStockExecution:
    intent: OrderIntent
    paper_order: PaperOrder
    payloads: PreparedStockOrderPayloads
    quote: Quote
    exposure_quotes: tuple[Quote, ...]
    approval_hash: str
    selection_hash: str
    context_hash: str
    plan_hash: str
    policy_hash: str
    source_config_hash: str
    analysis_code_hash: str
    execution_config_hash: str
    source_report_body_sha256: str
    before_account_hash: str
    request_hash: str
    created_at: datetime
    expires_at: datetime
    mode: ExecutionMode = field(default=ExecutionMode.SIMULATION, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    broker_transport_allowed: Literal[False] = field(default=False, init=False)
    reservations_created: Literal[False] = field(default=False, init=False)

    @property
    def evidence_hash(self) -> str:
        try:
            _check(self.mode is ExecutionMode.SIMULATION)
            _check(
                self.live_authorized
                is self.broker_transport_allowed
                is self.reservations_created
                is False
            )
            _check(type(self.intent) is OrderIntent and type(self.paper_order) is PaperOrder)
            self.intent.__post_init__()
            PaperOrder.model_validate(self.paper_order.model_dump())
            _check(type(self.payloads) is PreparedStockOrderPayloads and type(self.quote) is Quote)
            arguments = self.payloads.review_arguments
            _ = self.payloads.place_arguments
            for digest in (
                self.approval_hash,
                self.selection_hash,
                self.context_hash,
                self.plan_hash,
                self.policy_hash,
                self.source_config_hash,
                self.analysis_code_hash,
                self.execution_config_hash,
                self.source_report_body_sha256,
                self.before_account_hash,
                self.request_hash,
            ):
                _require_sha256_hex(digest, "prepared_stock_binding")
            request = _hash(
                (
                    _VERSION,
                    "request",
                    self.approval_hash,
                    self.selection_hash,
                    self.context_hash,
                    self.before_account_hash,
                )
            )
            _check(request == self.request_hash)
            _check(
                self.intent.id
                == self.paper_order.id
                == self.payloads.ref_id
                == str(uuid5(NAMESPACE_URL, _VERSION + ":" + request))
            )
            _check(
                self.intent.account_id.startswith("sim-")
                and self.intent.account_id == arguments["account_number"]
            )
            _check(
                self.intent.data_hash == self.request_hash
                and self.intent.config_hash == self.execution_config_hash
            )
            require_utc(self.created_at)
            require_utc(self.expires_at)
            _check(
                self.created_at == self.intent.created_at
                and self.expires_at == self.intent.expires_at
            )
            _check(self.created_at < self.expires_at)
            paper = self.paper_order
            _check(paper.symbol == self.quote.symbol == arguments["symbol"])
            _check(self.intent.quantity == paper.quantity == self.payloads.terms.quantity)
            _check(self.intent.side.value == paper.side == arguments["side"])
            _check(
                self.intent.order_type.value == arguments["type"]
                and self.intent.limit_price == paper.limit_price == self.payloads.terms.limit_price
            )
            _check(
                self.intent.time_in_force is TimeInForce.GOOD_FOR_DAY
                and self.intent.stop_price is None
            )
            _check(paper.status == "open" and paper.filled == paper.reserved_cash == 0)
            _check(type(self.exposure_quotes) is tuple and 0 < len(self.exposure_quotes) <= 512)
            _check(
                len({quote.symbol for quote in self.exposure_quotes}) == len(self.exposure_quotes)
            )
            _check(any(quote == self.quote for quote in self.exposure_quotes))
            for quote in self.exposure_quotes:
                _check(type(quote) is Quote)
                Quote.model_validate(quote.model_dump())
                _check(
                    quote.as_of
                    <= self.created_at
                    < self.expires_at
                    <= quote.as_of + timedelta(seconds=5)
                )
            return _hash((_VERSION, "prepared", self))
        except (ValueError, TypeError, ArithmeticError, AttributeError, KeyError):
            raise ValueError("stock_simulation_intent_unavailable") from None

    def to_record(self) -> dict[str, Any]:
        _ = self.evidence_hash
        body = _wire(self)
        _check(type(body) is dict)
        return dict(body)


def stock_simulation_account_hash(account: Account) -> str:
    _check(type(account) is Account)
    checked = Account.model_validate(account.model_dump())
    return _hash((_VERSION, "base-account", checked))


def _validate_context(context: StockExecutionContext) -> None:
    _check(
        type(context.plan) is CurrentStockPlan
        and type(context.inputs) is CurrentStockResearchInputs
    )
    _check(
        type(context.policy) is CurrentInvestmentPolicy
        and type(context.controls) is StockPlanningControls
    )
    _check(type(context.allocation_context) is StockAllocationContext)
    _check(type(context.execution_policy) is HybridSettings)
    HybridSettings.model_validate(context.execution_policy.model_dump())
    _require_sha256_hex(context.execution_config_hash, "stock_execution_config")
    _require_sha256_hex(context.source_report_body_sha256, "stock_report")
    proposals = context.plan.portfolio_proposals
    if proposals is None:
        raise ValueError("stock_simulation_intent_unavailable")
    rebuilt = compile_current_stock_plan(
        context.inputs,
        worker_profile_id="stock-worker-current-provider-v1",
        policy=context.policy,
        analysis_code_hash=context.plan.analysis_code_hash,
        controls=context.controls,
        allocation_context=context.allocation_context,
        issuers=context.issuers,
        held_sleeves=context.held_sleeves,
        owned_holding_contexts=context.owned_holding_contexts,
        profit_requests=context.profit_requests,
        limits=context.limits,
        reviewed_at=proposals.reviewed_at,
    )
    _check(rebuilt.evidence_hash == context.plan.evidence_hash)
    _check(
        str(content_hash(current_stock_plan_document(context.plan)))
        == context.source_report_body_sha256
    )
    _check(type(context.market) is tuple and 0 < len(context.market) <= 512)
    symbols = set()
    instruments = set()
    for market in context.market:
        _check(type(market) is StockExecutionMarketEvidence)
        _ = market.evidence_hash
        _check(market.quote.symbol not in symbols and market.instrument.id not in instruments)
        symbols.add(market.quote.symbol)
        instruments.add(market.instrument.id)


def _active(account: Account) -> tuple[PaperOrder, ...]:
    return tuple(order for order in account.orders if order.status in ("open", "partial"))


def _markets(
    context: StockExecutionContext, at: datetime
) -> dict[str, StockExecutionMarketEvidence]:
    output = {}
    for evidence in context.market:
        quote = evidence.quote
        clock = evidence.market_clock
        _check(
            evidence.received_at <= at < evidence.expires_at
            and 0 <= (at - quote.as_of).total_seconds() < 5
            and 0 <= (at - clock.observed_at).total_seconds() < 5
            and evidence.instrument.provider_status == "active"
            and evidence.instrument.tradable
            and quote.tradable
            and quote.regular_session
            and not quote.halted
            and not quote.diversified_etf
            and clock.is_open
            and not (clock.halted or clock.trading_disabled or clock.cancel_only)
            and (clock.next_close_at is None or at < clock.next_close_at)
            and quote.bid <= quote.ask
            and (quote.ask - quote.bid) / quote.ask <= Decimal(".0035")
        )
        output[quote.symbol] = evidence
    return output


def _bind_account(
    context: StockExecutionContext,
    account: Account,
    account_id: str,
    markets: dict[str, StockExecutionMarketEvidence],
    now: datetime,
) -> None:
    source = context.allocation_context
    before = stock_simulation_account_hash(account)
    _check(source.reconciliation_hash == before)
    _check(source.account.account_id == source.portfolio.account_id == account_id)
    _check(source.account_type == "cash" and source.currency == "USD")
    _check(source.as_of <= now < source.expires_at and source.tax_reserve == account.tax_reserve)
    _check(source.account.cash == source.portfolio.cash == account.cash)
    powers = tuple(
        power for power in source.account.buying_power if power.asset_class is AssetClass.EQUITY
    )
    _check(
        len(powers) == 1
        and powers[0].amount
        == source.unleveraged_buying_power
        == account.cash - account.reserved_cash
    )
    positions = {str(position.instrument_id): position for position in source.portfolio.positions}
    held = tuple(row for row in source.exposures if row.origin == "position")
    actual = {(lot.symbol, lot.sleeve) for lot in account.lots}
    orders = {order.id: order for order in account.orders}
    _check(all(fill.order_id in orders for fill in account.fills))
    for order in account.orders:
        _check(
            sum(
                (Fraction(fill.quantity) for fill in account.fills if fill.order_id == order.id),
                Fraction(),
            )
            == Fraction(order.filled)
        )
    _check({(row.symbol, row.sleeve) for row in held} == actual)
    _check(len({lot.symbol for lot in account.lots}) == len(actual))
    _check(len(positions) == len(held) == len(actual))
    for row in held:
        _check(row.symbol in markets and row.instrument_id in positions)
        market = markets[row.symbol]
        position = positions[row.instrument_id]
        lots = tuple(
            lot for lot in account.lots if (lot.symbol, lot.sleeve) == (row.symbol, row.sleeve)
        )
        _check(market.instrument.id == row.instrument_id and market.quote.sector == row.sector)
        _check(
            sum((Fraction(lot.quantity) for lot in lots), Fraction()) == Fraction(position.quantity)
        )
        value = sum(
            (Fraction(lot.quantity) * Fraction(market.quote.bid) for lot in lots), Fraction()
        )
        _check(
            Fraction(position.market_value) == value
            and row.remaining_notional == position.market_value
        )
    position_value = sum((Fraction(p.market_value) for p in positions.values()), Fraction())
    _check(Fraction(source.portfolio.equity) == Fraction(account.cash) + position_value)
    pending = {order.id: order for order in _active(account) if order.side == "buy"}
    exposures = tuple(row for row in source.exposures if row.origin != "position")
    _check(
        len(exposures) == len(pending) and {row.reference_id for row in exposures} == set(pending)
    )
    for row in exposures:
        order = pending[row.reference_id]
        _check(row.origin == "broker_pending" and row.local_cash_reservation == 0)
        _check((row.symbol, row.sleeve) == (order.symbol, order.sleeve))
        _check(row.remaining_notional == order.reserved_cash and row.symbol in markets)
        _check(
            row.instrument_id == markets[row.symbol].instrument.id
            and row.sector == markets[row.symbol].quote.sector
        )
    for owner in context.owned_holding_contexts:
        _check(owner.reconciliation_hash == before and owner.as_of <= now < owner.expires_at)
        mandate = owner.mandate
        expected = tuple(
            lot
            for lot in account.lots
            if (lot.symbol, lot.sleeve) == (mandate.symbol, mandate.sleeve)
        )
        if owner.remaining_lots is None:
            raise ValueError("stock_simulation_intent_unavailable")
        _check(
            {(lot.id, lot.quantity, lot.basis, lot.acquired_at, lot.episode_id) for lot in expected}
            == {
                (lot.lot_id, lot.quantity, lot.basis, lot.acquired_at, lot.episode_id)
                for lot in owner.remaining_lots
            }
        )
        _check(all(lot.episode_id == mandate.episode_id for lot in expected))
        episodes = tuple(
            episode for episode in account.episodes if episode.id == mandate.episode_id
        )
        _check(
            len(episodes) == 1
            and (episodes[0].symbol, episodes[0].sleeve) == (mandate.symbol, mandate.sleeve)
        )
        buys = tuple(
            fill
            for fill in account.fills
            if orders[fill.order_id].side == "buy"
            and (orders[fill.order_id].episode_id or orders[fill.order_id].id) == mandate.episode_id
        )
        sells = tuple(
            fill
            for fill in account.fills
            if orders[fill.order_id].side == "sell"
            and orders[fill.order_id].episode_id == mandate.episode_id
        )
        _check(bool(buys) and min(fill.at for fill in buys) == mandate.first_fill_at)
        cost = sum(
            (Fraction(fill.quantity) * Fraction(fill.price) + Fraction(fill.fee) for fill in buys),
            Fraction(),
        )
        _check(cost == Fraction(episodes[0].original_cash))
        _check(
            sum((Fraction(fill.quantity) for fill in buys), Fraction())
            == Fraction(episodes[0].original_quantity)
        )
        if owner.realized_gains is not None:
            _check({gain.fill_id for gain in owner.realized_gains} == {fill.id for fill in sells})
            times = {fill.id: fill.at for fill in sells}
            _check(all(gain.at == times[gain.fill_id] for gain in owner.realized_gains))
            proceeds = sum(
                (
                    Fraction(fill.quantity) * Fraction(fill.price) - Fraction(fill.fee)
                    for fill in sells
                ),
                Fraction(),
            )
            remaining = sum((Fraction(lot.basis) for lot in expected), Fraction())
            _check(
                sum((Fraction(gain.net_gain) for gain in owner.realized_gains), Fraction())
                == proceeds - (cost - remaining)
            )
    _check(not (account.paused or account.kill_switch))


def _quantity_step(instrument: Instrument, fractional: bool) -> Decimal:
    left = Fraction(instrument.quantity_increment)
    right = Fraction(Decimal(".000001") if fractional else Decimal(1))
    denominator = lcm(left.denominator, right.denominator)
    numerator = lcm(
        left.numerator * (denominator // left.denominator),
        right.numerator * (denominator // right.denominator),
    )
    return Decimal(numerator) / Decimal(denominator)


def _floor_quantity(value: Fraction, step: Decimal) -> Decimal:
    quantity = Decimal(value // Fraction(step)) * step
    return quantize_down(quantity, step)


def _threshold(episode_id: str, method: str) -> str:
    return _hash((_VERSION, "profit-threshold", episode_id, method))


def _source_order(
    context: StockExecutionContext,
    selection: StockExecutionSelection,
    account: Account,
    market: StockExecutionMarketEvidence,
    at: datetime,
) -> tuple[Fraction, str | None, OrderPurpose, str | None]:
    plan = context.plan
    proposals = plan.portfolio_proposals
    _check(proposals is not None)
    proposals = cast(StockPortfolioProposalSet, proposals)
    if selection.kind == "entry":
        _check(
            not proposals.entry_block_reasons
            and plan.allocation is not None
            and not account.settlements
        )
        _check(not any(lot.symbol == selection.symbol for lot in account.lots))
        _check(
            not (context.controls.tactical_entries_suspended or account.tactical_suspended)
            or selection.sleeve != "tactical"
        )
        allocation = cast(StockAllocationPlan, plan.allocation)
        matched = tuple(
            row
            for row in allocation.proposals
            if (row.symbol, row.sleeve, row.decision_hash)
            == (selection.symbol, selection.sleeve, selection.source_evidence_hash)
        )
        _check(len(matched) == 1)
        row = matched[0]
        _check(row.instrument_id == market.instrument.id and row.sector == market.quote.sector)
        identities = tuple(x for x in context.issuers if x.symbol == row.symbol)
        _check(len(identities) == 1)
        identity = identities[0]
        _check(
            identity.instrument_id == row.instrument_id
            and identity.issuer_id == row.issuer_id
            and identity.as_of <= at < identity.expires_at
        )
        decision = (
            tuple(
                x
                for x in plan.rankings.assessments
                if (x.symbol, x.horizon, x.decision_hash)
                == (row.symbol, row.sleeve, row.decision_hash)
            )
            if plan.rankings is not None
            else ()
        )
        _check(
            len(decision) == 1
            and decision[0].analytically_eligible
            and decision[0].expires_at is not None
            and at < decision[0].expires_at
        )
        _check(
            market.sector_source_hash is not None
            and market.earnings_source_hash is not None
            and market.liquidity_source_hash is not None
        )
        _check(
            market.quote.average_dollar_volume is not None
            and market.quote.average_dollar_volume >= 20000000
            and market.quote.ask >= 10
            and market.quote.earnings_clear
        )
        policy = context.execution_policy
        unit = max(
            Fraction(market.quote.ask) * (1 + Fraction(policy.simulation_slippage_bps) / 10000),
            Fraction(selection.limit_price or 0),
        )
        allowance = Fraction(row.cash_ceiling) - Fraction(policy.simulation_fee_usd)
        _check(allowance > 0)
        maximum = allowance / unit
        if selection.sleeve == "tactical":
            stop = selection.risk_stop
            if stop is None:
                raise ValueError("stock_simulation_intent_unavailable")
            _check(
                stop.instrument_id == market.instrument.id
                and stop.symbol == selection.symbol
                and stop.as_of <= at < stop.expires_at
                and 0 < stop.price < market.quote.bid
            )
            equity = Fraction(
                mark_equity(account, {key.quote.symbol: key.quote for key in context.market})
            )
            risk = equity / 200 - 2 * Fraction(policy.simulation_fee_usd)
            loss = unit - Fraction(stop.price) * (
                1 - Fraction(policy.simulation_slippage_bps) / 10000
            )
            _check(risk > 0 and loss > 0)
            maximum = min(maximum, risk / loss)
        return maximum, None, OrderPurpose.ENTRY, None
    owner = tuple(
        x
        for x in context.owned_holding_contexts
        if (x.mandate.episode_id, x.mandate.symbol, x.mandate.sleeve)
        == (selection.episode_id, selection.symbol, selection.sleeve)
    )
    _check(len(owner) == 1)
    quantity = sum(
        (
            lot.quantity
            for lot in account.lots
            if lot.episode_id == selection.episode_id
            and lot.symbol == selection.symbol
            and lot.sleeve == selection.sleeve
        ),
        Decimal(0),
    )
    if selection.kind == "holding_exit":
        reviews = (
            ()
            if proposals.holding_reviews is None
            else tuple(
                x
                for x in proposals.holding_reviews.reviews
                if x.mandate.episode_id == selection.episode_id
                and x.evidence_hash == selection.source_evidence_hash
            )
        )
        _check(len(reviews) == 1 and reviews[0].action == "EXIT")
        return (
            Fraction(quantity),
            selection.episode_id,
            OrderPurpose.PROTECTIVE_EXIT
            if reviews[0].review_state == "protective"
            else OrderPurpose.STRATEGY_EXIT,
            None,
        )
    reductions = tuple(
        x
        for x in proposals.profit_reductions
        if x.mandate.episode_id == selection.episode_id
        and x.method == selection.method
        and x.evidence_hash == selection.source_evidence_hash
    )
    _check(
        len(reductions) == 1
        and reductions[0].status == "proposed"
        and reductions[0].quantity is not None
    )
    target = cast(Decimal, reductions[0].quantity)
    requests = tuple(
        request
        for request in context.profit_requests
        if request.episode_id == selection.episode_id and request.method == selection.method
    )
    _check(len(requests) == 1 and requests[0].origin is not None and requests[0].state is not None)
    request = requests[0]
    origin = cast(StockProfitOrigin, request.origin)
    state = cast(StockProfitExitState, request.state)
    episode = next(item for item in account.episodes if item.id == selection.episode_id)
    _check(
        origin.original_quantity == episode.original_quantity
        and origin.designated_cash == episode.original_cash
    )
    _check(state.source_hash == stock_simulation_account_hash(account))
    pending = sum(
        (
            order.quantity - order.filled
            for order in _active(account)
            if order.side == "sell" and order.episode_id == selection.episode_id
        ),
        Decimal(0),
    )
    _check(state.pending_exit_quantity == pending)
    _profit_progress(account, selection, state.progress, state.information_at)
    maximum = min(Fraction(quantity), Fraction(target))
    if selection.method == "principal":
        maximum = min(
            maximum,
            max(
                Fraction(),
                Fraction(quantity) - Fraction(origin.designated_cash) / Fraction(market.quote.bid),
            ),
        )
    return (
        maximum,
        selection.episode_id,
        OrderPurpose.STRATEGY_EXIT,
        _threshold(str(selection.episode_id), str(selection.method)),
    )


def _profit_progress(
    account: Account, selection: StockExecutionSelection, progress: Any, information_at: datetime
) -> None:
    methods = ("principal", "partial_first", "partial_second", "trend")
    keys = {_threshold(str(selection.episode_id), method): method for method in methods}
    actual = {keys[row.threshold]: row for row in account.exit_progress if row.threshold in keys}
    source = {row.method: row for row in progress}
    _check(actual.keys() == source.keys())
    for method, row in source.items():
        owned = actual[method]
        _check(
            (owned.symbol, owned.sleeve, owned.target, owned.filled)
            == (selection.symbol, selection.sleeve, row.target_quantity, row.filled_quantity)
        )
        orders = {
            order.id
            for order in account.orders
            if order.threshold == _threshold(str(selection.episode_id), method)
            and order.episode_id == selection.episode_id
        }
        fills = tuple(fill for fill in account.fills if fill.order_id in orders)
        _check(all(fill.at <= information_at for fill in fills))
        _check(set(row.fill_ids) == {fill.id for fill in fills})
        _check(
            Fraction(row.filled_quantity)
            == sum((Fraction(fill.quantity) for fill in fills), Fraction())
        )


def _entry_caps(
    context: StockExecutionContext,
    account: Account,
    market: StockExecutionMarketEvidence,
    selection: StockExecutionSelection,
    quantity: Decimal,
) -> None:
    policy = context.execution_policy
    limits = context.limits or StockAllocationLimits()
    proposal = (
        next(
            row
            for row in context.plan.allocation.proposals
            if (row.symbol, row.sleeve, row.decision_hash)
            == (selection.symbol, selection.sleeve, selection.source_evidence_hash)
        )
        if context.plan.allocation is not None
        else None
    )
    _check(proposal is not None)
    proposal = cast(StockAllocationProposal, proposal)
    unit = max(
        Fraction(market.quote.ask) * (1 + Fraction(policy.simulation_slippage_bps) / 10000),
        Fraction(selection.limit_price or 0),
    )
    cost = Fraction(quantity) * unit + Fraction(policy.simulation_fee_usd)
    _check(cost <= Fraction(proposal.cash_ceiling))
    marks = {item.quote.symbol: item.quote for item in context.market}
    equity = Fraction(mark_equity(account, marks))
    exposures = context.allocation_context.exposures
    values = {}
    for row in exposures:
        values[row.reference_id] = (
            sum(
                (
                    Fraction(lot.quantity) * Fraction(marks[lot.symbol].ask)
                    for lot in account.lots
                    if (lot.symbol, lot.sleeve) == (row.symbol, row.sleeve)
                ),
                Fraction(),
            )
            if row.origin == "position"
            else Fraction(row.remaining_notional or 0)
        )
    issuer = sum(
        (values[row.reference_id] for row in exposures if row.issuer_id == proposal.issuer_id),
        Fraction(),
    )
    sector = sum(
        (values[row.reference_id] for row in exposures if row.sector == proposal.sector), Fraction()
    )
    sleeve = sum(
        (values[row.reference_id] for row in exposures if row.sleeve == selection.sleeve),
        Fraction(),
    )
    cap = min(Fraction(limits.company_cap), Fraction(policy.company_pct) / 100)
    if selection.sleeve == "tactical":
        cap = min(
            cap,
            Fraction(limits.tactical_position_cap),
            Fraction(policy.tactical_position_pct) / 100,
        )
    _check(issuer + cost <= equity * cap)
    _check(
        sector + cost
        <= equity * min(Fraction(limits.sector_cap), Fraction(policy.sector_pct) / 100)
    )
    target = min(
        Fraction(
            limits.long_term_target if selection.sleeve == "long_term" else limits.tactical_target
        ),
        Fraction(policy.long_term_pct if selection.sleeve == "long_term" else policy.tactical_pct)
        / 100,
    )
    _check(sleeve + cost <= equity * target)


def _entry_issuers(
    context: StockExecutionContext,
    selection: StockExecutionSelection,
    instrument_id: str,
    approved_at: datetime,
    now: datetime,
) -> tuple[StockIssuerIdentity, ...]:
    allocation = context.plan.allocation
    _check(allocation is not None)
    allocation = cast(StockAllocationPlan, allocation)
    proposal = next(
        row
        for row in allocation.proposals
        if (row.symbol, row.sleeve, row.decision_hash)
        == (selection.symbol, selection.sleeve, selection.source_evidence_hash)
    )
    expected: dict[str, tuple[str, str | None]] = {
        selection.symbol: (instrument_id, proposal.issuer_id)
    }
    for row in context.allocation_context.exposures:
        value = (row.instrument_id, row.issuer_id)
        _check(row.symbol not in expected or expected[row.symbol] == value)
        expected[row.symbol] = value
    supplied = {identity.symbol: identity for identity in context.issuers}
    accepted = []
    for symbol, (instrument, issuer) in sorted(expected.items()):
        identity = supplied.get(symbol)
        _check(identity is not None and issuer is not None)
        identity = cast(StockIssuerIdentity, identity)
        _check(
            identity.instrument_id == instrument
            and identity.issuer_id == issuer
            and identity.as_of <= approved_at <= now < identity.expires_at
        )
        accepted.append(identity)
    return tuple(accepted)


def prepare_stock_execution(
    context: StockExecutionContext,
    *,
    account: Account,
    simulation_account_id: str,
    grant: StockSimulationGrant,
    selection: StockExecutionSelection,
    now: datetime,
) -> PreparedStockExecution:
    """Prepare draft facts only; journal owner separately calls reserve_order."""
    try:
        with localcontext(_CONTEXT):
            _check(
                type(context) is StockExecutionContext
                and type(grant) is StockSimulationGrant
                and type(selection) is StockExecutionSelection
            )
            now = require_utc(now)
            context_hash = context.evidence_hash
            approval_hash = grant.evidence_hash
            selection_hash = selection.evidence_hash
            before = stock_simulation_account_hash(account)
            _check(
                simulation_account_id == grant.simulation_account_id
                and grant.sleeve == selection.sleeve
            )
            _check(grant.approved_at <= now < grant.expires_at)
            _check(
                (grant.context_hash, grant.selection_hash, grant.before_account_hash)
                == (context_hash, selection_hash, before)
            )
            _check(
                (
                    grant.plan_hash,
                    grant.policy_hash,
                    grant.source_config_hash,
                    grant.analysis_code_hash,
                    grant.execution_config_hash,
                    grant.source_report_body_sha256,
                )
                == (
                    context.plan.evidence_hash,
                    context.plan.policy_hash,
                    context.plan.source_config_hash,
                    context.plan.analysis_code_hash,
                    context.execution_config_hash,
                    context.source_report_body_sha256,
                )
            )
            _check(
                context.controls.research_enabled
                and not context.controls.kill_switch_active
                and context.controls.as_of <= now < context.controls.expires_at
            )
            markets = _markets(context, now)
            _check(all(market.received_at <= grant.approved_at for market in context.market))
            _check(
                context.controls.as_of <= grant.approved_at
                and context.allocation_context.as_of <= grant.approved_at
            )
            _check(
                context.plan.portfolio_proposals is not None
                and context.plan.portfolio_proposals.reviewed_at <= grant.approved_at
            )
            _check(selection.symbol in markets)
            market = markets[selection.symbol]
            _bind_account(context, account, simulation_account_id, markets, now)
            _check(not any(order.symbol == selection.symbol for order in _active(account)))
            maximum, episode, purpose, threshold = _source_order(
                context, selection, account, market, now
            )
            fractional = (
                selection.order_type == "market"
                and market.instrument.fractional_eligible
                and market.quote.fractional
            )
            step = _quantity_step(market.instrument, fractional)
            if market.instrument.maximum_quantity is not None:
                maximum = min(maximum, Fraction(market.instrument.maximum_quantity))
            quantity = _floor_quantity(maximum, step)
            _check(quantity > 0 and quantity >= market.instrument.minimum_quantity)
            _check(
                quantity * (market.quote.ask if purpose is OrderPurpose.ENTRY else market.quote.bid)
                >= market.instrument.minimum_notional
            )
            if selection.limit_price is not None:
                _check(selection.limit_price % market.instrument.price_increment == 0)
            used_issuers: tuple[StockIssuerIdentity, ...] = ()
            if purpose is OrderPurpose.ENTRY:
                used_issuers = _entry_issuers(
                    context, selection, market.instrument.id, grant.approved_at, now
                )
                _entry_caps(context, account, market, selection, quantity)
            deadlines = [
                grant.expires_at,
                context.controls.expires_at,
                context.allocation_context.expires_at,
            ]
            for evidence in context.market:
                deadlines.extend(
                    (
                        evidence.expires_at,
                        evidence.quote.as_of + timedelta(seconds=5),
                        evidence.market_clock.observed_at + timedelta(seconds=5),
                    )
                )
                if evidence.market_clock.next_close_at is not None:
                    deadlines.append(evidence.market_clock.next_close_at)
            for identity in used_issuers:
                deadlines.append(identity.expires_at)
            # A freshly recompiled plan with a selected active entry/EXIT/proposed
            # reduction has both rankings and active proposal validity. All other
            # states already failed their retained runtime selection checks.
            proposals = cast(StockPortfolioProposalSet, context.plan.portfolio_proposals)
            deadlines.append(cast(datetime, proposals.expires_at))
            rankings = cast(CurrentStockRankings, context.plan.rankings)
            deadlines.extend(
                x.expires_at
                for x in rankings.assessments
                if x.analytically_eligible and x.expires_at is not None
            )
            if selection.risk_stop is not None:
                _check(selection.risk_stop.as_of <= grant.approved_at)
                deadlines.append(selection.risk_stop.expires_at)
            expiry = min(deadlines)
            _check(context.plan.as_of <= grant.approved_at <= now < expiry)
            request_hash = _hash(
                (_VERSION, "request", approval_hash, selection_hash, context_hash, before)
            )
            order_id = str(uuid5(NAMESPACE_URL, _VERSION + ":" + request_hash))
            paper = PaperOrder(
                id=order_id,
                symbol=selection.symbol,
                side="buy" if purpose is OrderPurpose.ENTRY else "sell",
                sleeve=selection.sleeve,
                quantity=quantity,
                limit_price=selection.limit_price,
                risk_stop=None if selection.risk_stop is None else selection.risk_stop.price,
                threshold=threshold,
                reason=_VERSION,
                episode_id=order_id if episode is None else episode,
            )
            # The pure legacy helper exercises unchanged risk math; this detached
            # return is discarded. Only the journal owner may commit a reservation.
            quotes = tuple(
                value.quote for value in sorted(markets.values(), key=lambda x: x.quote.symbol)
            )
            reserve_order(
                account,
                paper,
                market.quote,
                now,
                context.execution_policy,
                exposure_quotes={q.symbol: q for q in quotes},
            )
            intent = OrderIntent(
                OrderIntentId(order_id),
                AccountId(simulation_account_id),
                market.instrument.id,
                AssetClass.EQUITY,
                Side.BUY if purpose is OrderPurpose.ENTRY else Side.SELL,
                purpose,
                OrderType.MARKET if selection.order_type == "market" else OrderType.LIMIT,
                TimeInForce.GOOD_FOR_DAY,
                quantity,
                selection.limit_price,
                None,
                grant.approved_at,
                expiry,
                context.policy.policy_id,
                ConfigHash(context.execution_config_hash),
                DataHash(request_hash),
                "current-stock-calendar-month-holding-v1"
                if purpose is OrderPurpose.ENTRY
                else None,
            )
            payloads = prepare_stock_order_payloads(
                StockOrderTerms(
                    account_number=simulation_account_id,
                    symbol=selection.symbol,
                    side=paper.side,
                    order_type=selection.order_type,
                    quantity=quantity,
                    limit_price=selection.limit_price,
                ),
                ref_id=order_id,
            )
            prepared = PreparedStockExecution(
                intent=intent,
                paper_order=paper,
                payloads=payloads,
                quote=market.quote,
                exposure_quotes=quotes,
                approval_hash=approval_hash,
                selection_hash=selection_hash,
                context_hash=context_hash,
                plan_hash=grant.plan_hash,
                policy_hash=grant.policy_hash,
                source_config_hash=grant.source_config_hash,
                analysis_code_hash=grant.analysis_code_hash,
                execution_config_hash=grant.execution_config_hash,
                source_report_body_sha256=grant.source_report_body_sha256,
                before_account_hash=before,
                request_hash=request_hash,
                created_at=grant.approved_at,
                expires_at=expiry,
            )
            _ = prepared.evidence_hash
            return prepared
    except (ValueError, TypeError, ArithmeticError, AttributeError, KeyError, StopIteration):
        raise ValueError("stock_simulation_intent_unavailable") from None
