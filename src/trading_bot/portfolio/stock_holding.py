"""Pure owned-stock holding observations and calendar-month review recommendations.

Input hashes bind caller-supplied facts; they do not authenticate sources. This
module creates no order, account update, execution authority or return forecast.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
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
from typing import Literal
from zoneinfo import ZoneInfo

from trading_bot.clock import require_utc
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.recording import content_hash

_NY = ZoneInfo("America/New_York")
_ZERO = Decimal(0)
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
_POLICY = "current-stock-calendar-month-holding-v1"
_RECEIPT_POLICY = "current-stock-calendar-month-holding-receipt-snapshot-v1"
_RECEIPT_DISCLOSURES = (
    "indicative_provider_receipt_snapshot",
    "not_completed_close_or_trade_timestamp",
    "not_executable_quote",
    "no_price_or_execution_guarantee",
)
type HoldingReviewBasis = Literal["completed_close_v1", "receipt_snapshot_v1"]


def _check(value: bool, reason: str) -> None:
    if not value:
        raise ValueError(reason)


def _review_basis_parameters(basis: HoldingReviewBasis, maximum_age: int | None) -> None:
    _check(
        type(basis) is str and basis in ("completed_close_v1", "receipt_snapshot_v1"),
        "stock_holding_review_basis_invalid",
    )
    _check(
        maximum_age is None
        if basis == "completed_close_v1"
        else type(maximum_age) is int and 1 <= maximum_age <= 120,
        "stock_holding_snapshot_age_policy_invalid",
    )


def _text(value: str) -> None:
    _check(
        type(value) is str and 0 < len(value) <= 128 and value.isprintable(),
        "bounded_stock_holding_identifier_required",
    )


def _symbol(value: str) -> None:
    _text(value)
    _check(
        value[0].isalpha()
        and value == value.upper()
        and all(c.isascii() and (c.isalnum() or c in ".-/") for c in value),
        "stock_holding_symbol_invalid",
    )


def _hash(value: object) -> str:
    with localcontext(_CONTEXT):
        return str(content_hash(value))


@dataclass(frozen=True, slots=True)
class StockHoldingMandate:
    episode_id: str
    instrument_id: str
    symbol: str
    sleeve: Literal["long_term", "tactical"]
    first_fill_at: datetime
    first_fill_hash: str

    def __post_init__(self) -> None:
        _text(self.episode_id)
        _text(self.instrument_id)
        _symbol(self.symbol)
        _check(self.sleeve in ("long_term", "tactical"), "stock_holding_sleeve_invalid")
        require_utc(self.first_fill_at)
        _require_sha256_hex(self.first_fill_hash, "first_fill")

    @property
    def evidence_hash(self) -> str:
        self.__post_init__()
        return _hash(("stock-holding-mandate-v1", self))


@dataclass(frozen=True, slots=True)
class StockHoldingLot:
    lot_id: str
    episode_id: str
    instrument_id: str
    symbol: str
    quantity: Decimal
    basis: Decimal
    acquired_at: datetime
    source_hash: str

    def __post_init__(self) -> None:
        for value in (self.lot_id, self.episode_id, self.instrument_id):
            _text(value)
        _symbol(self.symbol)
        require_bounded_decimal(self.quantity, "holding_quantity", positive=True)
        require_bounded_decimal(self.basis, "holding_basis", nonnegative=True)
        require_utc(self.acquired_at)
        _require_sha256_hex(self.source_hash, "holding_lot")


@dataclass(frozen=True, slots=True)
class StockRealizedPriceGain:
    fill_id: str
    episode_id: str
    instrument_id: str
    symbol: str
    net_gain: Decimal
    at: datetime
    source_hash: str

    def __post_init__(self) -> None:
        for value in (self.fill_id, self.episode_id, self.instrument_id):
            _text(value)
        _symbol(self.symbol)
        require_bounded_decimal(self.net_gain, "net_realized_price_gain")
        require_utc(self.at)
        _require_sha256_hex(self.source_hash, "realized_price_gain")


@dataclass(frozen=True, slots=True)
class StockHoldingPrice:
    instrument_id: str
    symbol: str
    value: Decimal
    at: datetime
    received_at: datetime
    source_hash: str

    def __post_init__(self) -> None:
        _text(self.instrument_id)
        _symbol(self.symbol)
        require_bounded_decimal(self.value, "holding_price", positive=True)
        require_utc(self.at)
        require_utc(self.received_at)
        _check(self.at <= self.received_at, "holding_price_receipt_precedes_information")
        _require_sha256_hex(self.source_hash, "holding_price")


@dataclass(frozen=True, slots=True)
class StockSaleCostAssumptions:
    adverse_slippage_bps: Decimal
    fee: Decimal
    policy_hash: str

    def __post_init__(self) -> None:
        require_bounded_decimal(self.adverse_slippage_bps, "holding_sale_bps", nonnegative=True)
        require_bounded_decimal(self.fee, "holding_sale_fee", nonnegative=True)
        _check(self.adverse_slippage_bps < 10000, "holding_sale_bps_out_of_range")
        _require_sha256_hex(self.policy_hash, "holding_sale_cost_policy")


@dataclass(frozen=True, slots=True)
class OwnedStockPricePnl:
    status: Literal["known", "unavailable"]
    remaining_quantity: Decimal | None
    remaining_basis: Decimal | None
    prior_net_realized_gain: Decimal | None
    remaining_sale_proceeds: Decimal | None
    price_pnl: Decimal | None
    reason: str | None
    input_evidence_hash: str
    excludes_dividends_taxes_and_operating_costs: Literal[True] = field(default=True, init=False)

    @property
    def evidence_hash(self) -> str:
        _check(self.excludes_dividends_taxes_and_operating_costs is True, "price_pnl_scope_changed")
        return _hash(("owned-stock-price-pnl-v1", self))


def _month(day: date, months: int) -> date:
    offset = day.year * 12 + day.month - 1 + months
    year, month0 = divmod(offset, 12)
    return date(year, month0 + 1, min(day.day, monthrange(year, month0 + 1)[1]))


def holding_anniversaries(
    mandate: StockHoldingMandate,
) -> tuple[date | None, date | None]:
    _check(type(mandate) is StockHoldingMandate, "typed_holding_mandate_required")
    mandate.__post_init__()
    if mandate.sleeve == "long_term":
        return None, None
    day = mandate.first_fill_at.astimezone(_NY).date()
    try:
        return _month(day, 1), _month(day, 2)
    except (OverflowError, ValueError):
        raise ValueError("stock_holding_anniversary_out_of_range") from None


def _owned(
    mandate: StockHoldingMandate,
    remaining_lots: tuple[StockHoldingLot, ...] | None,
    realized_gains: tuple[StockRealizedPriceGain, ...] | None,
    cutoff: datetime,
) -> None:
    for rows, kind in ((remaining_lots, StockHoldingLot), (realized_gains, StockRealizedPriceGain)):
        if rows is None:
            continue
        _check(type(rows) is tuple and len(rows) <= 10000, "immutable_owned_holding_facts_required")
        identities = set()
        for row in rows:
            _check(type(row) is kind, "typed_owned_holding_fact_required")
            row.__post_init__()
            _check(
                (row.episode_id, row.instrument_id, row.symbol)
                == (mandate.episode_id, mandate.instrument_id, mandate.symbol),
                "stock_holding_ownership_mismatch",
            )
            if isinstance(row, StockHoldingLot):
                identity, stamp = row.lot_id, row.acquired_at
            else:
                identity, stamp = row.fill_id, row.at
            _check(
                identity not in identities and mandate.first_fill_at <= stamp <= cutoff,
                "duplicate_or_noncausal_holding_fact",
            )
            identities.add(identity)


def owned_price_pnl(
    mandate: StockHoldingMandate,
    *,
    remaining_lots: tuple[StockHoldingLot, ...] | None,
    realized_gains: tuple[StockRealizedPriceGain, ...] | None,
    price: StockHoldingPrice | None,
    costs: StockSaleCostAssumptions | None,
    cutoff: datetime,
) -> OwnedStockPricePnl:
    """Prior net disposal gain plus one remaining-sale estimate, never gross profit."""
    with localcontext(_CONTEXT):
        _check(type(mandate) is StockHoldingMandate, "typed_holding_mandate_required")
        mandate.__post_init__()
        require_utc(cutoff)
        _check(mandate.first_fill_at <= cutoff, "holding_review_precedes_first_fill")
        _owned(mandate, remaining_lots, realized_gains, cutoff)
        if price is not None:
            _check(type(price) is StockHoldingPrice, "typed_stock_holding_price_required")
            price.__post_init__()
            _check(
                (price.instrument_id, price.symbol) == (mandate.instrument_id, mandate.symbol)
                and mandate.first_fill_at <= price.at <= price.received_at <= cutoff,
                "holding_price_ownership_or_clock_mismatch",
            )
        if costs is not None:
            _check(type(costs) is StockSaleCostAssumptions, "typed_sale_cost_assumptions_required")
            costs.__post_init__()
        if remaining_lots and price is not None:
            _check(
                all(row.acquired_at <= price.at for row in remaining_lots)
                and (realized_gains is None or all(row.at <= price.at for row in realized_gains)),
                "owned_activity_after_price_mark",
            )
        identity = _hash((_POLICY, mandate, remaining_lots, realized_gains, price, costs, cutoff))
        quantity = (
            None if remaining_lots is None else sum((x.quantity for x in remaining_lots), _ZERO)
        )
        basis = None if remaining_lots is None else sum((x.basis for x in remaining_lots), _ZERO)
        gains = None if realized_gains is None else sum((x.net_gain for x in realized_gains), _ZERO)
        missing = []
        if quantity is None:
            missing.append("remaining_lots_unknown")
        if gains is None:
            missing.append("prior_net_realized_gains_unknown")
        if quantity is not None and quantity > 0:
            if price is None:
                missing.append("current_price_unknown")
            if costs is None:
                missing.append("remaining_sale_costs_unknown")
        if missing:
            return OwnedStockPricePnl(
                "unavailable", quantity, basis, gains, None, None, ";".join(missing), identity
            )
        proceeds = _ZERO
        if quantity and price is not None and costs is not None:
            proceeds = quantity * price.value * (1 - costs.adverse_slippage_bps / 10000) - costs.fee
        if gains is None or basis is None:
            raise ValueError("owned_price_pnl_inputs_inconsistent")
        return OwnedStockPricePnl(
            "known", quantity, basis, gains, proceeds, gains + proceeds - basis, None, identity
        )


@dataclass(frozen=True, slots=True)
class StockRegularSession:
    """Source-bound calendar assertion, not authentication or a future schedule."""

    status: Literal["known_regular", "unknown", "conflicting"]
    opens_at: datetime | None
    closes_at: datetime | None
    observed_at: datetime
    source_hash: str | None

    def __post_init__(self) -> None:
        _check(
            self.status in ("known_regular", "unknown", "conflicting"),
            "stock_regular_session_status_invalid",
        )
        require_utc(self.observed_at)
        if self.source_hash is not None:
            _require_sha256_hex(self.source_hash, "regular_session")
        for stamp in (self.opens_at, self.closes_at):
            if stamp is not None:
                require_utc(stamp)
        if self.status == "known_regular":
            _check(
                self.opens_at is not None
                and self.closes_at is not None
                and self.source_hash is not None,
                "regular_session_evidence_missing",
            )
            if self.opens_at is None or self.closes_at is None:
                raise ValueError("regular_session_evidence_missing")
            _check(
                self.opens_at < self.closes_at <= self.observed_at, "regular_session_not_completed"
            )
            _check(
                self.opens_at.astimezone(_NY).date() == self.closes_at.astimezone(_NY).date(),
                "regular_session_date_mismatch",
            )


@dataclass(frozen=True, slots=True)
class StockProtectiveEvidence:
    episode_id: str
    instrument_id: str
    symbol: str
    observed_at: datetime
    reason: Literal["protective_stop", "thesis_invalidated", "concentration_reduction"]
    source_hash: str

    def __post_init__(self) -> None:
        _text(self.episode_id)
        _text(self.instrument_id)
        _symbol(self.symbol)
        require_utc(self.observed_at)
        _check(
            self.reason in ("protective_stop", "thesis_invalidated", "concentration_reduction"),
            "independent_stock_protective_reason_required",
        )
        _require_sha256_hex(self.source_hash, "stock_protective_evidence")


@dataclass(frozen=True, slots=True)
class StockContinuationEvidence:
    """A declared current decision source, not independently authenticated here."""

    episode_id: str
    instrument_id: str
    symbol: str
    status: Literal["active", "inactive"]
    information_at: datetime
    received_at: datetime
    expires_at: datetime
    source_hash: str

    def __post_init__(self) -> None:
        _text(self.episode_id)
        _text(self.instrument_id)
        _symbol(self.symbol)
        _check(self.status in ("active", "inactive"), "known_continuation_status_required")
        for stamp in (self.information_at, self.received_at, self.expires_at):
            require_utc(stamp)
        _check(
            self.information_at <= self.received_at < self.expires_at,
            "continuation_clock_or_expiry_invalid",
        )
        _require_sha256_hex(self.source_hash, "stock_continuation")

    @property
    def evidence_hash(self) -> str:
        self.__post_init__()
        return _hash(("stock-holding-continuation-v1", self))


@dataclass(frozen=True, slots=True)
class StockHoldingReview:
    mandate: StockHoldingMandate
    action: Literal["HOLD", "REVIEW", "EXIT"]
    reason: str
    phase: Literal["before_month_one", "month_one", "month_two", "long_term"]
    review_state: Literal[
        "not_due",
        "due",
        "awaiting_completed_close",
        "unknown_session",
        "not_applicable",
        "flat",
        "protective",
    ]
    reviewed_at: datetime
    review_session_at: datetime | None
    information_cutoff: datetime | None
    first_anniversary: date | None
    terminal_anniversary: date | None
    review_delayed: bool | None
    continuation: Literal["active", "inactive", "unknown"]
    extension_approved: bool
    partial_profit_reductions_allowed: bool
    price_pnl: OwnedStockPricePnl
    input_evidence_hash: str
    continuation_evidence_hash: str | None
    execution_timing: Literal["next_eligible_market_opportunity"] | None
    review_basis: HoldingReviewBasis = "completed_close_v1"
    maximum_snapshot_age_minutes: int | None = None
    valuation_disclosures: tuple[str, ...] = field(default=(), init=False)
    execute_not_before: None = field(default=None, init=False)
    first_eligible_session_verified: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)
    order_created: Literal[False] = field(default=False, init=False)
    performance_proven: Literal[False] = field(default=False, init=False)
    policy_version: str = field(default=_POLICY, init=False)

    def __post_init__(self) -> None:
        _review_basis_parameters(self.review_basis, self.maximum_snapshot_age_minutes)
        if self.review_basis == "receipt_snapshot_v1":
            object.__setattr__(self, "policy_version", _RECEIPT_POLICY)
            object.__setattr__(self, "valuation_disclosures", _RECEIPT_DISCLOSURES)

    @property
    def evidence_hash(self) -> str:
        _review_basis_parameters(self.review_basis, self.maximum_snapshot_age_minutes)
        receipt = self.review_basis == "receipt_snapshot_v1"
        _check(
            self.execute_not_before is None
            and self.first_eligible_session_verified
            is self.execution_authorized
            is self.live_authorized
            is self.order_created
            is self.performance_proven
            is False
            and self.policy_version == (_RECEIPT_POLICY if receipt else _POLICY)
            and type(self.valuation_disclosures) is tuple
            and self.valuation_disclosures == (_RECEIPT_DISCLOSURES if receipt else ()),
            "stock_holding_review_scope_changed",
        )
        if receipt:
            return _hash(("stock-holding-review-receipt-snapshot-v1", self))
        # Preserve the original completed-close wire preimage, excluding only
        # the three newly declared opt-in fields (whose legacy values are fixed).
        original = asdict(self)
        original.pop("review_basis")
        original.pop("maximum_snapshot_age_minutes")
        original.pop("valuation_disclosures")
        return _hash(("stock-holding-review-v1", original))


def evaluate_stock_holding(
    mandate: StockHoldingMandate,
    *,
    reviewed_at: datetime,
    session: StockRegularSession,
    remaining_lots: tuple[StockHoldingLot, ...] | None,
    realized_gains: tuple[StockRealizedPriceGain, ...] | None,
    price: StockHoldingPrice | None,
    costs: StockSaleCostAssumptions | None,
    continuation: StockContinuationEvidence | None,
    protective_evidence: StockProtectiveEvidence | None = None,
    review_basis: HoldingReviewBasis = "completed_close_v1",
    maximum_snapshot_age_minutes: int | None = None,
) -> StockHoldingReview:
    """Recommend only; a separate owner determines executable market opportunity.

    receipt_snapshot_v1 uses original provider observation/receipt clocks for an
    indicative valuation. They are neither a completed close nor a venue trade
    timestamp/executable quote. Actual analytical time is never backdated.
    """
    with localcontext(_CONTEXT):
        _review_basis_parameters(review_basis, maximum_snapshot_age_minutes)
        receipt = review_basis == "receipt_snapshot_v1"
        _check(type(mandate) is StockHoldingMandate, "typed_holding_mandate_required")
        mandate.__post_init__()
        require_utc(reviewed_at)
        _check(mandate.first_fill_at <= reviewed_at, "holding_review_precedes_first_fill")
        _check(type(session) is StockRegularSession, "typed_regular_session_required")
        session.__post_init__()
        _check(session.observed_at <= reviewed_at, "future_session_observation")
        close = session.closes_at if session.status == "known_regular" else None
        continuation_status: Literal["active", "inactive", "unknown"] = "unknown"
        continuation_hash = None
        if continuation is not None:
            _check(
                type(continuation) is StockContinuationEvidence,
                "typed_stock_continuation_evidence_required",
            )
            continuation.__post_init__()
            _check(
                (continuation.episode_id, continuation.instrument_id, continuation.symbol)
                == (mandate.episode_id, mandate.instrument_id, mandate.symbol),
                "stock_continuation_ownership_mismatch",
            )
            if receipt:
                _check(
                    continuation.received_at <= reviewed_at,
                    "stock_continuation_cutoff_or_freshness_mismatch",
                )
                if (
                    close is not None
                    and close <= continuation.information_at
                    and reviewed_at < continuation.expires_at
                ):
                    continuation_status = continuation.status
            else:
                _check(
                    close is not None
                    and continuation.information_at == close
                    and continuation.received_at <= reviewed_at < continuation.expires_at,
                    "stock_continuation_cutoff_or_freshness_mismatch",
                )
                continuation_status = continuation.status
            continuation_hash = continuation.evidence_hash
        if price is not None and close is not None and not receipt:
            _check(price.at == close, "holding_price_must_match_completed_session")
        if protective_evidence is not None:
            _check(
                type(protective_evidence) is StockProtectiveEvidence,
                "typed_stock_protective_evidence_required",
            )
            protective_evidence.__post_init__()
            _check(
                (
                    protective_evidence.episode_id,
                    protective_evidence.instrument_id,
                    protective_evidence.symbol,
                )
                == (mandate.episode_id, mandate.instrument_id, mandate.symbol)
                and mandate.first_fill_at <= protective_evidence.observed_at <= reviewed_at,
                "protective_evidence_ownership_or_clock_mismatch",
            )
        pnl = owned_price_pnl(
            mandate,
            remaining_lots=remaining_lots,
            realized_gains=realized_gains,
            price=price,
            costs=costs,
            cutoff=reviewed_at,
        )
        if (
            receipt
            and price is not None
            and pnl.remaining_quantity is not None
            and pnl.remaining_quantity > 0
        ):
            if maximum_snapshot_age_minutes is None:
                raise ValueError("stock_holding_snapshot_age_policy_invalid")
            unavailable = (
                "receipt_snapshot_precedes_session"
                if close is not None and price.at < close
                else "receipt_snapshot_stale"
                if reviewed_at - price.at >= timedelta(minutes=maximum_snapshot_age_minutes)
                else None
            )
            if unavailable is not None:
                pnl = replace(
                    pnl,
                    status="unavailable",
                    remaining_sale_proceeds=None,
                    price_pnl=None,
                    reason=unavailable,
                )
        first, terminal = holding_anniversaries(mandate)
        day = reviewed_at.astimezone(_NY).date()
        phase: Literal["before_month_one", "month_one", "month_two", "long_term"]
        phase = (
            "long_term"
            if first is None
            else "month_two"
            if terminal is not None and day >= terminal
            else "month_one"
            if day >= first
            else "before_month_one"
        )
        due = terminal if phase == "month_two" else first
        delay = None if close is None or due is None else close.astimezone(_NY).date() > due
        inputs = (
            _POLICY,
            mandate,
            reviewed_at,
            session,
            remaining_lots,
            realized_gains,
            price,
            costs,
            continuation,
            protective_evidence,
        )
        identity = _hash(
            (_RECEIPT_POLICY, review_basis, maximum_snapshot_age_minutes, *inputs[1:])
            if receipt
            else inputs
        )

        def result(
            action: Literal["HOLD", "REVIEW", "EXIT"],
            reason: str,
            state: Literal[
                "not_due",
                "due",
                "awaiting_completed_close",
                "unknown_session",
                "not_applicable",
                "flat",
                "protective",
            ],
            extension: bool = False,
        ) -> StockHoldingReview:
            return StockHoldingReview(
                mandate,
                action,
                reason,
                phase,
                state,
                reviewed_at,
                close,
                reviewed_at,
                first,
                terminal,
                delay,
                continuation_status,
                extension,
                mandate.sleeve == "tactical",
                pnl,
                identity,
                continuation_hash,
                "next_eligible_market_opportunity" if action == "EXIT" else None,
                review_basis=review_basis,
                maximum_snapshot_age_minutes=maximum_snapshot_age_minutes,
            )

        if remaining_lots == ():
            return result("HOLD", "no_remaining_owned_shares", "flat")
        if remaining_lots is None:
            return result("REVIEW", "remaining_owned_position_unknown", "not_applicable")
        if protective_evidence is not None:
            if protective_evidence.reason == "concentration_reduction":
                return result("REVIEW", "portfolio_reduction_plan_required", "protective")
            return result("EXIT", protective_evidence.reason, "protective")
        if mandate.sleeve == "long_term":
            return result("HOLD", "long_term_has_no_monthly_profit_deadline", "not_applicable")
        if close is None:
            return result("REVIEW", "completed_regular_session_unknown", "unknown_session")
        if phase == "before_month_one":
            return result("HOLD", "before_month_one", "not_due")
        if due is None or close.astimezone(_NY).date() < due:
            return result(
                "REVIEW",
                "anniversary_awaiting_supported_completed_close",
                "awaiting_completed_close",
            )
        if phase == "month_two":
            return result("EXIT", "two_calendar_month_terminal_review", "due")
        if continuation_status == "inactive":
            return result("EXIT", "continuation_inactive", "due")
        if pnl.status == "known" and pnl.price_pnl is not None and pnl.price_pnl <= 0:
            return result("EXIT", "nonpositive_owned_price_pnl", "due")
        if continuation_status == "unknown":
            return result("REVIEW", "continuation_unknown", "due")
        if pnl.status != "known" or pnl.price_pnl is None:
            return result("REVIEW", "owned_price_pnl_unavailable", "due")
        return result("HOLD", "positive_price_pnl_and_active_continuation", "due", True)
