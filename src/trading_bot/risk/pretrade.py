"""Pure, ordered, broker-neutral pretrade risk evaluation."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, Decimal, DecimalException, localcontext
from enum import StrEnum
from typing import Final, Self

from pydantic import ValidationError

from trading_bot.clock import Clock, require_utc
from trading_bot.config import AppConfig
from trading_bot.domain import (
    AccountId,
    AccountSnapshot,
    AlertAttestation,
    AssetClass,
    BrokerHealth,
    BrokerOrder,
    BrokerOrderReview,
    CheckResult,
    ClientOrderId,
    CodeHash,
    ConfigHash,
    DataHash,
    DomainValidationError,
    ExecutionMode,
    Instrument,
    InstrumentId,
    LiveLeaseAttestation,
    MarketClock,
    OrderIntent,
    OrderIntentId,
    OrderPurpose,
    OrderState,
    OrderType,
    PortfolioSnapshot,
    Position,
    Quote,
    ReconciliationAttestation,
    RiskEvaluation,
    RuntimeState,
    Side,
    StrategyEligibilityAttestation,
    canonical_decimal_text,
    canonical_order_intent_payload,
    require_bounded_decimal,
)
from trading_bot.domain.decimal_utils import (
    MAX_CANONICAL_DECIMAL_TEXT_LENGTH,
    _require_exact_bool,
    _require_exact_enum,
    _require_nonempty,
    _require_sha256_hex,
    _require_tuple,
)
from trading_bot.risk.limits import evaluate_exposure_limits
from trading_bot.risk.losses import (
    ActivitySnapshot,
    LossSnapshot,
    evaluate_activity_limits,
    evaluate_loss_limits,
)
from trading_bot.risk.models import ExposureProjection

_PERCENT_DENOMINATOR: Final = Decimal("100")
_MAX_SLIPPAGE_PCT: Final = Decimal("100")
_MAX_SPREAD_PCT: Final = Decimal("200")
_MICROSECONDS_PER_SECOND: Final = Decimal("1000000")
_ARITHMETIC_PRECISION: Final = MAX_CANONICAL_DECIMAL_TEXT_LENGTH * 4
_EVIDENCE_PRECISION: Final = MAX_CANONICAL_DECIMAL_TEXT_LENGTH // 2
_ACTIVE_PROVIDER_STATE: Final = "active"
_LIVE_MODES: Final = frozenset(
    {
        ExecutionMode.MICRO_LIVE,
        ExecutionMode.NORMAL_LIVE,
    }
)
_LIVE_EXIT_STATES: Final = frozenset(
    {
        RuntimeState.RUNNING_LIVE,
        RuntimeState.ENTRY_BLOCKED,
    }
)
_ACTIVE_ORDER_STATES: Final = frozenset(
    {
        OrderState.SUBMISSION_PENDING,
        OrderState.SUBMITTED,
        OrderState.PARTIALLY_FILLED,
        OrderState.CANCEL_PENDING,
        OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    }
)


class PretradeCheckCode(StrEnum):
    """Stable checklist codes in the approved evaluation order."""

    LIVE_AUTHORIZATION = "live_authorization"
    KILL_SWITCH = "kill_switch"
    ACCOUNT_ALLOWLIST = "account_allowlist"
    BROKER_HEALTH = "broker_health"
    MARKET_DATA_FRESHNESS = "market_data_freshness"
    SYMBOL_TRADABILITY = "symbol_tradability"
    FRACTIONAL_ELIGIBILITY = "fractional_eligibility"
    MARKET_SESSION = "market_session"
    MARKET_HALT = "market_halt"
    BUYING_POWER = "buying_power"
    CASH_RESERVE = "cash_reserve"
    POSITION_CAP = "position_cap"
    CORRELATION_CAP = "correlation_cap"
    CRYPTO_CAP = "crypto_cap"
    LOSS_LIMITS = "loss_limits"
    ACTIVITY_LIMITS = "activity_limits"
    SPREAD = "spread"
    SLIPPAGE = "slippage"
    AFTER_COST_EDGE = "after_cost_edge"
    DUPLICATE_ORDER = "duplicate_order"
    EXIT_POLICY = "exit_policy"
    REVIEW_MATCH = "review_match"
    BROKER_MINIMUMS = "broker_minimums"
    RECONCILIATION = "reconciliation"


@dataclass(frozen=True, slots=True)
class InstrumentEligibility:
    """Current, externally derived instrument-policy evidence."""

    instrument_id: InstrumentId
    symbol_allowlisted: bool
    asset_policy_eligible: bool
    provider_restriction_clear: bool
    fractional_eligibility_verified: bool
    earnings_restriction_clear: bool
    session_order_type_eligible: bool
    exit_policy_monitorable: bool
    average_daily_dollar_volume_usd: Decimal | None
    observed_at: datetime
    evidence_hash: str

    def __post_init__(self) -> None:
        _require_nonempty(self.instrument_id, "instrument_id")
        for field_name, value in (
            ("symbol_allowlisted", self.symbol_allowlisted),
            ("asset_policy_eligible", self.asset_policy_eligible),
            ("provider_restriction_clear", self.provider_restriction_clear),
            ("fractional_eligibility_verified", self.fractional_eligibility_verified),
            ("earnings_restriction_clear", self.earnings_restriction_clear),
            ("session_order_type_eligible", self.session_order_type_eligible),
            ("exit_policy_monitorable", self.exit_policy_monitorable),
        ):
            _require_exact_bool(value, field_name)
        if self.average_daily_dollar_volume_usd is not None:
            require_bounded_decimal(
                self.average_daily_dollar_volume_usd,
                "average_daily_dollar_volume_usd",
                nonnegative=True,
            )
        require_utc(self.observed_at)
        _require_sha256_hex(self.evidence_hash, "evidence_hash")


@dataclass(frozen=True, slots=True, init=False)
class ExecutionCostEstimate:
    """Intent- and quote-bound execution cost evidence before thresholds."""

    intent_id: OrderIntentId
    instrument_id: InstrumentId
    quote_data_hash: DataHash
    quantity: Decimal
    executable_price: Decimal
    spread_pct: Decimal
    slippage_pct: Decimal
    fees_usd: Decimal
    commission_usd: Decimal
    expected_gross_edge_usd: Decimal
    expected_reward_usd: Decimal
    initial_risk_usd: Decimal
    verified: bool
    observed_at: datetime
    data_hash: DataHash

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ExecutionCostEstimate must be constructed by from_quote")

    @classmethod
    def from_quote(
        cls,
        *,
        intent: OrderIntent,
        quote: Quote,
        slippage_pct: Decimal,
        fees_usd: Decimal,
        commission_usd: Decimal,
        expected_gross_edge_usd: Decimal,
        expected_reward_usd: Decimal,
        initial_risk_usd: Decimal,
        verified: bool,
        observed_at: datetime,
        data_hash: DataHash,
    ) -> Self:
        if type(intent) is not OrderIntent:
            raise DomainValidationError("intent must be an OrderIntent")
        if type(quote) is not Quote:
            raise DomainValidationError("quote must be a Quote")
        require_bounded_decimal(intent.quantity, "intent.quantity", positive=True)
        require_bounded_decimal(quote.bid, "quote.bid", positive=True)
        require_bounded_decimal(quote.ask, "quote.ask", positive=True)
        if intent.limit_price is not None:
            require_bounded_decimal(intent.limit_price, "intent.limit_price", positive=True)
        if intent.stop_price is not None:
            require_bounded_decimal(intent.stop_price, "intent.stop_price", positive=True)
        require_utc(observed_at)
        if observed_at < quote.observed_at:
            raise DomainValidationError("cost evidence cannot predate its quote")
        executable_price = quote.ask if intent.side is Side.BUY else quote.bid
        instance = object.__new__(cls)
        for field_name, value in (
            ("intent_id", intent.id),
            ("instrument_id", quote.instrument_id),
            ("quote_data_hash", quote.data_hash),
            ("quantity", intent.quantity),
            ("executable_price", executable_price),
            ("spread_pct", _quote_spread_pct(quote)),
            ("slippage_pct", slippage_pct),
            ("fees_usd", fees_usd),
            ("commission_usd", commission_usd),
            ("expected_gross_edge_usd", expected_gross_edge_usd),
            ("expected_reward_usd", expected_reward_usd),
            ("initial_risk_usd", initial_risk_usd),
            ("verified", verified),
            ("observed_at", observed_at),
            ("data_hash", data_hash),
        ):
            object.__setattr__(instance, field_name, value)
        instance.__post_init__()
        return instance

    def __post_init__(self) -> None:
        _require_nonempty(self.intent_id, "intent_id")
        _require_nonempty(self.instrument_id, "instrument_id")
        _require_sha256_hex(self.quote_data_hash, "quote_data_hash")
        require_bounded_decimal(self.quantity, "quantity", positive=True)
        require_bounded_decimal(self.executable_price, "executable_price", positive=True)
        for field_name, value, maximum in (
            ("spread_pct", self.spread_pct, _MAX_SPREAD_PCT),
            ("slippage_pct", self.slippage_pct, _MAX_SLIPPAGE_PCT),
        ):
            require_bounded_decimal(value, field_name, nonnegative=True)
            if value > maximum:
                raise DomainValidationError(f"{field_name} exceeds its physical bound")
        require_bounded_decimal(self.fees_usd, "fees_usd", nonnegative=True)
        require_bounded_decimal(self.commission_usd, "commission_usd", nonnegative=True)
        require_bounded_decimal(self.expected_gross_edge_usd, "expected_gross_edge_usd")
        require_bounded_decimal(
            self.expected_reward_usd,
            "expected_reward_usd",
            nonnegative=True,
        )
        require_bounded_decimal(self.initial_risk_usd, "initial_risk_usd", nonnegative=True)
        _require_exact_bool(self.verified, "verified")
        require_utc(self.observed_at)
        _require_sha256_hex(self.data_hash, "data_hash")


@dataclass(frozen=True, slots=True)
class InitialRiskContext:
    """Immutable evidence snapshot for the preliminary 23-check pass."""

    intent: OrderIntent
    account: AccountSnapshot
    portfolio: PortfolioSnapshot
    instrument: Instrument
    eligibility: InstrumentEligibility
    quote: Quote
    market_clock: MarketClock
    broker_health: BrokerHealth
    open_orders: tuple[BrokerOrder, ...]
    local_pending_intents: tuple[OrderIntent, ...]
    reconciliation: ReconciliationAttestation
    live_lease: LiveLeaseAttestation | None
    alerts: AlertAttestation
    strategy_eligibility: StrategyEligibilityAttestation
    runtime_state: RuntimeState
    kill_switch_active: bool
    losses: LossSnapshot
    activity: ActivitySnapshot
    projection: ExposureProjection
    costs: ExecutionCostEstimate
    observed_at: datetime

    def __post_init__(self) -> None:
        for field_name, value, expected_type in (
            ("intent", self.intent, OrderIntent),
            ("account", self.account, AccountSnapshot),
            ("portfolio", self.portfolio, PortfolioSnapshot),
            ("instrument", self.instrument, Instrument),
            ("eligibility", self.eligibility, InstrumentEligibility),
            ("quote", self.quote, Quote),
            ("market_clock", self.market_clock, MarketClock),
            ("broker_health", self.broker_health, BrokerHealth),
            ("reconciliation", self.reconciliation, ReconciliationAttestation),
            ("alerts", self.alerts, AlertAttestation),
            (
                "strategy_eligibility",
                self.strategy_eligibility,
                StrategyEligibilityAttestation,
            ),
            ("losses", self.losses, LossSnapshot),
            ("activity", self.activity, ActivitySnapshot),
            ("projection", self.projection, ExposureProjection),
            ("costs", self.costs, ExecutionCostEstimate),
        ):
            if type(value) is not expected_type:
                raise DomainValidationError(f"{field_name} must be a {expected_type.__name__}")
        _require_tuple(self.open_orders, "open_orders")
        if any(type(order) is not BrokerOrder for order in self.open_orders):
            raise DomainValidationError("open_orders must contain BrokerOrder records")
        _require_tuple(self.local_pending_intents, "local_pending_intents")
        if any(type(intent) is not OrderIntent for intent in self.local_pending_intents):
            raise DomainValidationError("local_pending_intents must contain OrderIntent records")
        if self.live_lease is not None and type(self.live_lease) is not LiveLeaseAttestation:
            raise DomainValidationError("live_lease must be a LiveLeaseAttestation or None")
        _require_exact_enum(self.runtime_state, RuntimeState, "runtime_state")
        _require_exact_bool(self.kill_switch_active, "kill_switch_active")
        require_utc(self.observed_at)


@dataclass(frozen=True, slots=True)
class FinalPretradeContext:
    """Fresh preliminary evidence plus one broker-reviewed order."""

    initial: InitialRiskContext
    reviewed_order: BrokerOrderReview

    def __post_init__(self) -> None:
        if type(self.initial) is not InitialRiskContext:
            raise DomainValidationError("initial must be an InitialRiskContext")
        if type(self.reviewed_order) is not BrokerOrderReview:
            raise DomainValidationError("reviewed_order must be a BrokerOrderReview")


def _evidence_decimal_text(value: Decimal) -> str:
    try:
        return canonical_decimal_text(value)
    except DomainValidationError:
        return "outside_safe_decimal_bounds"


def canonical_review_payload_sha256(
    intent: OrderIntent,
    *,
    client_order_id: ClientOrderId | None,
) -> str:
    """Hash every normalized outbound field used by the broker-neutral review."""

    if type(intent) is not OrderIntent:
        raise DomainValidationError("intent must be an OrderIntent")
    if client_order_id is not None:
        _require_nonempty(client_order_id, "client_order_id")
    payload = canonical_order_intent_payload(intent)
    payload["client_order_id"] = None if client_order_id is None else str(client_order_id)
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _elapsed_seconds(started_at: datetime, ended_at: datetime) -> Decimal:
    elapsed = ended_at - started_at
    microseconds = (elapsed.days * 86400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds
    return Decimal(microseconds) / _MICROSECONDS_PER_SECOND


def _is_current(observed_at: datetime, current_at: datetime, maximum_age: Decimal) -> bool:
    age = _elapsed_seconds(observed_at, current_at)
    return Decimal("0") <= age <= maximum_age


def _quote_spread_pct(quote: Quote) -> Decimal:
    with localcontext() as arithmetic:
        arithmetic.prec = max(arithmetic.prec, _ARITHMETIC_PRECISION)
        numerator = (quote.ask - quote.bid) * (_PERCENT_DENOMINATOR * Decimal("2"))
        denominator = quote.ask + quote.bid
    with localcontext() as context:
        context.prec = _EVIDENCE_PRECISION
        context.rounding = ROUND_CEILING
        return numerator / denominator


def _result(
    *,
    code: PretradeCheckCode,
    allowed: bool,
    observed: str,
    configured_limit: str,
    reason: str,
    observed_at: datetime,
) -> CheckResult:
    return CheckResult(
        code=code.value,
        allowed=allowed,
        observed=observed,
        configured_limit=configured_limit,
        reason=reason,
        observed_at=observed_at,
    )


def _status_result(
    *,
    code: PretradeCheckCode,
    allowed: bool,
    reason: str,
    observed_at: datetime,
    configured_limit: str = "required",
) -> CheckResult:
    return _result(
        code=code,
        allowed=allowed,
        observed="satisfied" if allowed else "denied",
        configured_limit=configured_limit,
        reason=reason,
        observed_at=observed_at,
    )


def _reference_price(context: InitialRiskContext) -> Decimal:
    intent = context.intent
    if intent.limit_price is not None:
        return intent.limit_price
    if intent.stop_price is not None:
        return intent.stop_price
    return context.quote.ask if intent.side is Side.BUY else context.quote.bid


def _notional(quantity: Decimal, price: Decimal) -> Decimal:
    with localcontext() as arithmetic:
        arithmetic.prec = max(arithmetic.prec, _ARITHMETIC_PRECISION)
        return quantity * price


def _is_exact_multiple(value: Decimal, increment: Decimal) -> bool:
    try:
        with localcontext() as context:
            context.prec = max(context.prec, _ARITHMETIC_PRECISION)
            return value % increment == 0
    except DecimalException:
        return False


def _validate_pretrade_config(config: AppConfig) -> None:
    for field_name, value in (
        (
            "portfolio.live_account_equity_ceiling_usd",
            config.portfolio.live_account_equity_ceiling_usd,
        ),
        ("activity.max_order_notional_usd", config.activity.max_order_notional_usd),
        ("equities.max_spread_pct", config.equities.max_spread_pct),
        ("equities.minimum_price_usd", config.equities.minimum_price_usd),
        (
            "equities.minimum_average_daily_dollar_volume_usd",
            config.equities.minimum_average_daily_dollar_volume_usd,
        ),
        ("crypto.max_spread_pct", config.crypto.max_spread_pct),
        (
            "costs.assumed_prediction_spread_pct",
            config.costs.assumed_prediction_spread_pct,
        ),
        ("costs.max_slippage_pct", config.costs.max_slippage_pct),
        (
            "position_risk.minimum_reward_to_initial_risk",
            config.position_risk.minimum_reward_to_initial_risk,
        ),
        (
            "freshness.max_executable_quote_age_seconds",
            config.freshness.max_executable_quote_age_seconds,
        ),
        (
            "freshness.max_account_snapshot_age_seconds",
            config.freshness.max_account_snapshot_age_seconds,
        ),
        (
            "freshness.max_broker_health_age_seconds",
            config.freshness.max_broker_health_age_seconds,
        ),
        (
            "freshness.max_broker_review_age_seconds",
            config.freshness.max_broker_review_age_seconds,
        ),
        (
            "freshness.max_preflight_age_seconds",
            config.freshness.max_preflight_age_seconds,
        ),
    ):
        require_bounded_decimal(value, field_name, nonnegative=True)


class PretradeEngine:
    """Evaluate all pretrade checks against one immutable context snapshot."""

    __slots__ = (
        "_account_allowlist",
        "_active_code_hash",
        "_checks",
        "_clock",
        "_config",
        "_config_hash",
        "_initial_checks",
    )

    def __init__(
        self,
        config: AppConfig,
        *,
        config_hash: ConfigHash,
        account_allowlist: tuple[AccountId, ...],
        active_code_hash: CodeHash,
        clock: Clock,
    ) -> None:
        if type(config) is not AppConfig:
            raise DomainValidationError("config must be an AppConfig")
        try:
            validated_config = AppConfig.model_validate(
                config.model_dump(mode="python", round_trip=True, warnings=False)
            )
        except ValidationError:
            raise DomainValidationError("config failed canonical revalidation") from None
        _validate_pretrade_config(validated_config)
        _require_sha256_hex(config_hash, "config_hash")
        _require_sha256_hex(active_code_hash, "active_code_hash")
        if not isinstance(clock, Clock):
            raise DomainValidationError("clock must implement Clock")
        _require_tuple(account_allowlist, "account_allowlist")
        for account_id in account_allowlist:
            _require_nonempty(account_id, "account_allowlist item")
        if len(set(account_allowlist)) != len(account_allowlist):
            raise DomainValidationError("account_allowlist cannot contain duplicates")
        self._config = validated_config
        self._config_hash = config_hash
        self._account_allowlist = frozenset(account_allowlist)
        self._active_code_hash = active_code_hash
        self._clock = clock
        self._checks: tuple[
            Callable[
                [InitialRiskContext, BrokerOrderReview | None, datetime],
                CheckResult,
            ],
            ...,
        ] = (
            self._check_live_authorization,
            self._check_kill_switch,
            self._check_account_allowlist,
            self._check_broker_health,
            self._check_market_data_freshness,
            self._check_symbol_tradability,
            self._check_fractional_eligibility,
            self._check_market_session,
            self._check_market_halt,
            self._check_buying_power,
            self._check_cash_reserve,
            self._check_position_cap,
            self._check_correlation_cap,
            self._check_crypto_cap,
            self._check_loss_limits,
            self._check_activity_limits,
            self._check_spread,
            self._check_slippage,
            self._check_after_cost_edge,
            self._check_duplicate_order,
            self._check_exit_policy,
            self._check_review_match,
            self._check_broker_minimums,
            self._check_reconciliation,
        )
        self._initial_checks = tuple(
            check for check in self._checks if check != self._check_review_match
        )

    def evaluate_initial(self, context: InitialRiskContext) -> RiskEvaluation:
        if type(context) is not InitialRiskContext:
            raise DomainValidationError("context must be an InitialRiskContext")
        evaluated_at = require_utc(self._clock.now())
        checks = tuple(check(context, None, evaluated_at) for check in self._initial_checks)
        return self._evaluation(context, checks, evaluated_at)

    def evaluate_final(self, context: FinalPretradeContext) -> RiskEvaluation:
        if type(context) is not FinalPretradeContext:
            raise DomainValidationError("context must be a FinalPretradeContext")
        evaluated_at = require_utc(self._clock.now())
        checks = tuple(
            check(context.initial, context.reviewed_order, evaluated_at) for check in self._checks
        )
        return self._evaluation(context.initial, checks, evaluated_at)

    @staticmethod
    def _evaluation(
        context: InitialRiskContext,
        checks: tuple[CheckResult, ...],
        evaluated_at: datetime,
    ) -> RiskEvaluation:
        return RiskEvaluation(
            intent_id=context.intent.id,
            allowed=all(check.allowed for check in checks),
            checks=checks,
            evaluated_at=evaluated_at,
            config_hash=context.intent.config_hash,
        )

    def _costs_bound(
        self,
        context: InitialRiskContext,
        evaluated_at: datetime,
    ) -> bool:
        costs = context.costs
        return (
            costs.intent_id == context.intent.id
            and costs.instrument_id == context.intent.instrument_id
            and costs.instrument_id == context.quote.instrument_id
            and costs.quote_data_hash == context.quote.data_hash
            and costs.quantity == context.intent.quantity
            and costs.executable_price
            == (context.quote.ask if context.intent.side is Side.BUY else context.quote.bid)
            and costs.spread_pct == _quote_spread_pct(context.quote)
            and costs.verified
            and _is_current(
                costs.observed_at,
                evaluated_at,
                self._config.freshness.max_executable_quote_age_seconds,
            )
        )

    def _projection_bound(self, context: InitialRiskContext) -> bool:
        return (
            context.projection.account_id == context.intent.account_id
            and context.projection.intent_id == context.intent.id
            and context.projection.instrument_id == context.intent.instrument_id
            and context.projection.asset_class is context.intent.asset_class
            and context.projection.correlation_group == context.instrument.correlation_group
            and context.projection.equity == context.account.equity
            and context.projection.observed_at == context.observed_at
        )

    def _check_live_authorization(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        strategy = context.strategy_eligibility
        base_allowed = (
            context.intent.config_hash == self._config_hash
            and _is_current(
                context.observed_at,
                evaluated_at,
                self._config.freshness.max_preflight_age_seconds,
            )
            and context.intent.created_at <= evaluated_at
            and evaluated_at < context.intent.expires_at
            and strategy.eligible
            and strategy.strategy_version == context.intent.strategy_version
            and strategy.config_hash == self._config_hash
            and strategy.code_hash == self._active_code_hash
            and context.alerts.critical_count == 0
            and _is_current(
                strategy.observed_at,
                evaluated_at,
                self._config.freshness.max_preflight_age_seconds,
            )
            and _is_current(
                context.alerts.observed_at,
                evaluated_at,
                self._config.freshness.max_preflight_age_seconds,
            )
        )
        if self._config.mode not in _LIVE_MODES:
            allowed = base_allowed and not self._config.live_trading_enabled
            return _status_result(
                code=PretradeCheckCode.LIVE_AUTHORIZATION,
                allowed=allowed,
                reason=(
                    "not_applicable_non_live_mode"
                    if allowed
                    else "non_live_identity_or_research_denied"
                ),
                observed_at=evaluated_at,
                configured_limit="non_live_mode_with_bound_research_evidence",
            )

        lease = context.live_lease
        runtime_allowed = (
            context.runtime_state is RuntimeState.RUNNING_LIVE
            if context.intent.purpose is OrderPurpose.ENTRY
            else context.runtime_state in _LIVE_EXIT_STATES
        )
        allowed = (
            base_allowed
            and self._config.live_trading_enabled
            and self._config.research.assumptions_validated
            and self._config.research.evidence_promotable
            and lease is not None
            and lease.valid
            and lease.account_id == context.intent.account_id
            and lease.config_hash == self._config_hash
            and lease.mode is self._config.mode
            and lease.expires_at > evaluated_at
            and runtime_allowed
        )
        return _status_result(
            code=PretradeCheckCode.LIVE_AUTHORIZATION,
            allowed=allowed,
            reason="authorized" if allowed else "live_authorization_denied",
            observed_at=evaluated_at,
            configured_limit="current_stage_bound_live_lease",
        )

    def _check_kill_switch(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        allowed = (
            not context.kill_switch_active
            and context.runtime_state is not RuntimeState.KILL_SWITCH_ACTIVE
        )
        return _status_result(
            code=PretradeCheckCode.KILL_SWITCH,
            allowed=allowed,
            reason="inactive" if allowed else "kill_switch_active",
            observed_at=evaluated_at,
            configured_limit="all_switch_sources_inactive",
        )

    def _check_account_allowlist(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        account = context.account
        portfolio = context.portfolio
        maximum_age = self._config.freshness.max_account_snapshot_age_seconds
        identities_match = (
            account.account_id == context.intent.account_id
            and portfolio.account_id == context.intent.account_id
            and context.losses.account_id == context.intent.account_id
            and context.activity.account_id == context.intent.account_id
            and context.projection.account_id == context.intent.account_id
            and context.reconciliation.account_id == context.intent.account_id
        )
        allowed = (
            identities_match
            and account.account_id in self._account_allowlist
            and account.provider_state == _ACTIVE_PROVIDER_STATE
            and not account.restricted
            and account.equity <= self._config.portfolio.live_account_equity_ceiling_usd
            and account.cash <= account.equity
            and portfolio.cash <= portfolio.equity
            and account.equity == portfolio.equity
            and account.cash == portfolio.cash
            and _is_current(account.observed_at, evaluated_at, maximum_age)
            and _is_current(portfolio.observed_at, evaluated_at, maximum_age)
        )
        return _result(
            code=PretradeCheckCode.ACCOUNT_ALLOWLIST,
            allowed=allowed,
            observed=_evidence_decimal_text(account.equity),
            configured_limit=_evidence_decimal_text(
                self._config.portfolio.live_account_equity_ceiling_usd
            ),
            reason="allowlisted_active_account" if allowed else "account_policy_denied",
            observed_at=evaluated_at,
        )

    def _check_broker_health(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        health = context.broker_health
        allowed = health.healthy and _is_current(
            health.observed_at,
            evaluated_at,
            self._config.freshness.max_broker_health_age_seconds,
        )
        return _result(
            code=PretradeCheckCode.BROKER_HEALTH,
            allowed=allowed,
            observed="healthy" if health.healthy else "unhealthy",
            configured_limit=_evidence_decimal_text(
                self._config.freshness.max_broker_health_age_seconds
            ),
            reason="healthy_and_current" if allowed else "broker_health_denied",
            observed_at=evaluated_at,
        )

    def _check_market_data_freshness(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        quote = context.quote
        allowed = (
            quote.instrument_id == context.intent.instrument_id
            and quote.instrument_id == context.instrument.id
            and quote.freshness_verified
            and _is_current(
                quote.observed_at,
                evaluated_at,
                self._config.freshness.max_executable_quote_age_seconds,
            )
            and context.costs.quote_data_hash == quote.data_hash
        )
        return _result(
            code=PretradeCheckCode.MARKET_DATA_FRESHNESS,
            allowed=allowed,
            observed="verified_current_quote" if allowed else "invalid_or_stale_quote",
            configured_limit=_evidence_decimal_text(
                self._config.freshness.max_executable_quote_age_seconds
            ),
            reason="freshness_verified" if allowed else "market_data_denied",
            observed_at=evaluated_at,
        )

    def _check_symbol_tradability(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        instrument = context.instrument
        eligibility = context.eligibility
        current = _is_current(
            instrument.observed_at,
            evaluated_at,
            self._config.freshness.max_account_snapshot_age_seconds,
        ) and _is_current(
            eligibility.observed_at,
            evaluated_at,
            self._config.freshness.max_account_snapshot_age_seconds,
        )
        base_allowed = (
            instrument.id == context.intent.instrument_id
            and eligibility.instrument_id == context.intent.instrument_id
            and instrument.asset_class is context.intent.asset_class
            and instrument.tradable
            and instrument.provider_status == _ACTIVE_PROVIDER_STATE
            and eligibility.provider_restriction_clear
            and current
        )
        if context.intent.purpose is not OrderPurpose.ENTRY:
            asset_allowed = instrument.asset_class is not AssetClass.PREDICTION or (
                self._config.prediction_markets.simulation_enabled
                and not self._config.prediction_markets.live_enabled
                and self._config.mode not in _LIVE_MODES
            )
        elif instrument.asset_class is AssetClass.EQUITY:
            volume = eligibility.average_daily_dollar_volume_usd
            asset_allowed = (
                self._config.equities.enabled
                and eligibility.symbol_allowlisted
                and eligibility.asset_policy_eligible
                and context.quote.ask >= self._config.equities.minimum_price_usd
                and volume is not None
                and volume >= self._config.equities.minimum_average_daily_dollar_volume_usd
                and eligibility.earnings_restriction_clear
            )
        elif instrument.asset_class is AssetClass.CRYPTO:
            asset_allowed = (
                self._config.crypto.enabled
                and eligibility.symbol_allowlisted
                and eligibility.asset_policy_eligible
                and instrument.symbol in self._config.crypto.initial_symbol_allowlist
                and not self._config.crypto.leverage_allowed
            )
        else:
            asset_allowed = (
                self._config.prediction_markets.simulation_enabled
                and not self._config.prediction_markets.live_enabled
                and self._config.mode not in _LIVE_MODES
                and eligibility.symbol_allowlisted
                and eligibility.asset_policy_eligible
            )
        allowed = base_allowed and asset_allowed
        return _status_result(
            code=PretradeCheckCode.SYMBOL_TRADABILITY,
            allowed=allowed,
            reason="symbol_tradable" if allowed else "symbol_policy_denied",
            observed_at=evaluated_at,
            configured_limit="allowlist_provider_and_asset_policy",
        )

    def _check_fractional_eligibility(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        quantity_is_integer = context.intent.quantity == context.intent.quantity.to_integral_value()
        allowed = (
            context.instrument.id == context.intent.instrument_id
            and context.eligibility.instrument_id == context.intent.instrument_id
            and (
                quantity_is_integer
                or (
                    context.instrument.fractional_eligible
                    and context.eligibility.fractional_eligibility_verified
                )
            )
        )
        return _status_result(
            code=PretradeCheckCode.FRACTIONAL_ELIGIBILITY,
            allowed=allowed,
            reason="integer_or_fractional_verified" if allowed else "fractional_denied",
            observed_at=evaluated_at,
            configured_limit="verified_when_fractional",
        )

    def _check_market_session(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        clock = context.market_clock
        market_order_allowed = True
        if context.intent.order_type is OrderType.MARKET:
            market_order_allowed = (
                self._config.runtime.normal_entry_market_orders_allowed
                if context.intent.purpose is OrderPurpose.ENTRY
                else self._config.runtime.emergency_market_orders_allowed
            )
        allowed = (
            clock.asset_class is context.intent.asset_class
            and clock.is_open
            and context.eligibility.session_order_type_eligible
            and market_order_allowed
            and _is_current(
                clock.observed_at,
                evaluated_at,
                self._config.freshness.max_executable_quote_age_seconds,
            )
        )
        return _status_result(
            code=PretradeCheckCode.MARKET_SESSION,
            allowed=allowed,
            reason="session_accepts_order" if allowed else "market_session_denied",
            observed_at=evaluated_at,
            configured_limit="current_permitted_session_and_order_type",
        )

    def _check_market_halt(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        clock = context.market_clock
        allowed = (
            clock.asset_class is context.intent.asset_class
            and not clock.halted
            and not clock.trading_disabled
            and not clock.cancel_only
            and context.instrument.tradable
            and context.instrument.provider_status == _ACTIVE_PROVIDER_STATE
            and context.eligibility.provider_restriction_clear
        )
        return _status_result(
            code=PretradeCheckCode.MARKET_HALT,
            allowed=allowed,
            reason="no_halt_or_restriction" if allowed else "market_halt_denied",
            observed_at=evaluated_at,
            configured_limit="no_halt_cancel_only_or_trading_disablement",
        )

    def _cost_amounts(
        self,
        context: InitialRiskContext,
    ) -> tuple[Decimal, Decimal, Decimal]:
        costs = context.costs
        with localcontext() as arithmetic:
            arithmetic.prec = max(arithmetic.prec, _ARITHMETIC_PRECISION)
            notional = costs.quantity * costs.executable_price
            spread_cost = notional * costs.spread_pct / _PERCENT_DENOMINATOR
            slippage_cost = notional * costs.slippage_pct / _PERCENT_DENOMINATOR
        return notional, spread_cost, slippage_cost

    def _check_buying_power(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        if context.intent.purpose is not OrderPurpose.ENTRY:
            return _status_result(
                code=PretradeCheckCode.BUYING_POWER,
                allowed=True,
                reason="not_applicable_reduce_only_exit",
                observed_at=evaluated_at,
                configured_limit="no_new_debit",
            )
        if not self._costs_bound(context, evaluated_at):
            return _status_result(
                code=PretradeCheckCode.BUYING_POWER,
                allowed=False,
                reason="cost_evidence_unbound",
                observed_at=evaluated_at,
            )
        try:
            available = context.account.buying_power_for(context.intent.asset_class)
        except DomainValidationError:
            return _status_result(
                code=PretradeCheckCode.BUYING_POWER,
                allowed=False,
                reason="authoritative_buying_power_unavailable",
                observed_at=evaluated_at,
            )
        notional, spread_cost, slippage_cost = self._cost_amounts(context)
        with localcontext() as arithmetic:
            arithmetic.prec = max(arithmetic.prec, _ARITHMETIC_PRECISION)
            required = (
                notional
                + spread_cost
                + slippage_cost
                + context.costs.fees_usd
                + context.costs.commission_usd
            )
        unleveraged = (
            not self._config.equities.margin_allowed
            if context.intent.asset_class is AssetClass.EQUITY
            else (
                not self._config.crypto.leverage_allowed
                if context.intent.asset_class is AssetClass.CRYPTO
                else True
            )
        )
        allowed = available >= required and unleveraged
        return _result(
            code=PretradeCheckCode.BUYING_POWER,
            allowed=allowed,
            observed=_evidence_decimal_text(available),
            configured_limit=_evidence_decimal_text(required),
            reason="buying_power_sufficient" if allowed else "buying_power_denied",
            observed_at=evaluated_at,
        )

    def _exposure_results(self, context: InitialRiskContext) -> dict[str, CheckResult] | None:
        if not self._projection_bound(context):
            return None
        return {
            result.code: result
            for result in evaluate_exposure_limits(
                context.projection,
                portfolio=self._config.portfolio,
                position_risk=self._config.position_risk,
                crypto=self._config.crypto,
            )
        }

    def _check_cash_reserve(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        results = self._exposure_results(context)
        if results is None:
            return _status_result(
                code=PretradeCheckCode.CASH_RESERVE,
                allowed=False,
                reason="projection_unbound",
                observed_at=evaluated_at,
            )
        source = results["cash_reserve"]
        return _result(
            code=PretradeCheckCode.CASH_RESERVE,
            allowed=source.allowed,
            observed=source.observed or "missing",
            configured_limit=source.configured_limit or "missing",
            reason=source.reason,
            observed_at=evaluated_at,
        )

    def _check_position_cap(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        results = self._exposure_results(context)
        if results is None or not self._costs_bound(context, evaluated_at):
            return _status_result(
                code=PretradeCheckCode.POSITION_CAP,
                allowed=False,
                reason="projection_or_cost_evidence_unbound",
                observed_at=evaluated_at,
            )
        relevant = tuple(
            results[code]
            for code in (
                "total_gross_exposure",
                "open_position_count",
                "position_notional",
            )
        )
        order_notional = _notional(
            context.costs.quantity,
            context.costs.executable_price,
        )
        absolute_order_allowed = (
            context.intent.purpose is not OrderPurpose.ENTRY
            or order_notional <= self._config.activity.max_order_notional_usd
        )
        projection_contains_order = (
            context.intent.purpose is not OrderPurpose.ENTRY
            or context.projection.position_notional >= order_notional
        )
        allowed = (
            all(result.allowed for result in relevant)
            and absolute_order_allowed
            and projection_contains_order
        )
        return _result(
            code=PretradeCheckCode.POSITION_CAP,
            allowed=allowed,
            observed=_evidence_decimal_text(context.projection.position_notional),
            configured_limit=_evidence_decimal_text(self._config.activity.max_order_notional_usd),
            reason="within_position_caps" if allowed else "position_cap_denied",
            observed_at=evaluated_at,
        )

    def _check_correlation_cap(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        results = self._exposure_results(context)
        if results is None:
            return _status_result(
                code=PretradeCheckCode.CORRELATION_CAP,
                allowed=False,
                reason="projection_unbound",
                observed_at=evaluated_at,
            )
        source = results["correlated_group_exposure"]
        return _result(
            code=PretradeCheckCode.CORRELATION_CAP,
            allowed=source.allowed,
            observed=source.observed or "missing",
            configured_limit=source.configured_limit or "missing",
            reason=source.reason,
            observed_at=evaluated_at,
        )

    def _check_crypto_cap(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        results = self._exposure_results(context)
        if results is None:
            return _status_result(
                code=PretradeCheckCode.CRYPTO_CAP,
                allowed=False,
                reason="projection_unbound",
                observed_at=evaluated_at,
            )
        total = results["total_crypto_exposure"]
        single = results["single_crypto_exposure"]
        allowed = total.allowed and single.allowed
        return _result(
            code=PretradeCheckCode.CRYPTO_CAP,
            allowed=allowed,
            observed=total.observed or "missing",
            configured_limit=total.configured_limit or "missing",
            reason="within_crypto_caps" if allowed else "crypto_cap_denied",
            observed_at=evaluated_at,
        )

    def _check_loss_limits(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        if (
            context.losses.account_id != context.intent.account_id
            or context.losses.observed_at != context.observed_at
        ):
            return _status_result(
                code=PretradeCheckCode.LOSS_LIMITS,
                allowed=False,
                reason="loss_evidence_unbound",
                observed_at=evaluated_at,
            )
        decision = evaluate_loss_limits(
            snapshot=context.losses,
            settings=self._config.loss_limits,
            purpose=context.intent.purpose,
        )
        return _status_result(
            code=PretradeCheckCode.LOSS_LIMITS,
            allowed=decision.allowed,
            reason=decision.reason_code,
            observed_at=evaluated_at,
            configured_limit="canonical_loss_settings",
        )

    def _check_activity_limits(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        if context.intent.purpose is not OrderPurpose.ENTRY:
            return _status_result(
                code=PretradeCheckCode.ACTIVITY_LIMITS,
                allowed=True,
                reason="not_applicable_reduce_only_exit",
                observed_at=evaluated_at,
                configured_limit="entry_intents_only",
            )
        if (
            context.activity.account_id != context.intent.account_id
            or context.activity.instrument_id != context.intent.instrument_id
            or context.activity.observed_at != context.observed_at
        ):
            return _status_result(
                code=PretradeCheckCode.ACTIVITY_LIMITS,
                allowed=False,
                reason="activity_evidence_unbound",
                observed_at=evaluated_at,
            )
        decision = evaluate_activity_limits(
            context.activity,
            settings=self._config.activity,
        )
        return _result(
            code=PretradeCheckCode.ACTIVITY_LIMITS,
            allowed=decision.allowed,
            observed=decision.observed or "missing",
            configured_limit=decision.configured_limit or "missing",
            reason=decision.code,
            observed_at=evaluated_at,
        )

    def _maximum_spread_pct(self, asset_class: AssetClass) -> Decimal:
        if asset_class is AssetClass.EQUITY:
            return self._config.equities.max_spread_pct
        if asset_class is AssetClass.CRYPTO:
            return self._config.crypto.max_spread_pct
        return self._config.costs.assumed_prediction_spread_pct

    def _check_spread(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        maximum = self._maximum_spread_pct(context.intent.asset_class)
        allowed = self._costs_bound(context, evaluated_at) and context.costs.spread_pct <= maximum
        return _result(
            code=PretradeCheckCode.SPREAD,
            allowed=allowed,
            observed=_evidence_decimal_text(context.costs.spread_pct),
            configured_limit=_evidence_decimal_text(maximum),
            reason="within_spread_limit" if allowed else "spread_denied",
            observed_at=evaluated_at,
        )

    def _check_slippage(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        maximum = self._config.costs.max_slippage_pct
        allowed = self._costs_bound(context, evaluated_at) and context.costs.slippage_pct <= maximum
        return _result(
            code=PretradeCheckCode.SLIPPAGE,
            allowed=allowed,
            observed=_evidence_decimal_text(context.costs.slippage_pct),
            configured_limit=_evidence_decimal_text(maximum),
            reason="within_slippage_limit" if allowed else "slippage_denied",
            observed_at=evaluated_at,
        )

    def _check_after_cost_edge(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        if context.intent.purpose is not OrderPurpose.ENTRY:
            return _status_result(
                code=PretradeCheckCode.AFTER_COST_EDGE,
                allowed=True,
                reason="not_applicable_reduce_only_exit",
                observed_at=evaluated_at,
                configured_limit="entry_intents_only",
            )
        if not self._costs_bound(context, evaluated_at) or context.costs.initial_risk_usd <= 0:
            return _status_result(
                code=PretradeCheckCode.AFTER_COST_EDGE,
                allowed=False,
                reason="edge_evidence_unbound_or_zero_risk",
                observed_at=evaluated_at,
            )
        _, spread_cost, slippage_cost = self._cost_amounts(context)
        with localcontext() as arithmetic:
            arithmetic.prec = max(arithmetic.prec, _ARITHMETIC_PRECISION)
            after_cost_edge = (
                context.costs.expected_gross_edge_usd
                - spread_cost
                - slippage_cost
                - context.costs.fees_usd
                - context.costs.commission_usd
            )
            required_reward = (
                context.costs.initial_risk_usd
                * self._config.position_risk.minimum_reward_to_initial_risk
            )
        allowed = after_cost_edge > 0 and context.costs.expected_reward_usd >= required_reward
        return _result(
            code=PretradeCheckCode.AFTER_COST_EDGE,
            allowed=allowed,
            observed=_evidence_decimal_text(after_cost_edge),
            configured_limit=_evidence_decimal_text(
                self._config.position_risk.minimum_reward_to_initial_risk
            ),
            reason="positive_edge_and_reward_risk" if allowed else "after_cost_edge_denied",
            observed_at=evaluated_at,
        )

    def _check_duplicate_order(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        broker_evidence_scoped = all(
            order.account_id == context.intent.account_id for order in context.open_orders
        )
        local_evidence_scoped = all(
            intent.account_id == context.intent.account_id
            for intent in context.local_pending_intents
        )
        unresolved = any(
            order.state is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
            for order in context.open_orders
        )
        broker_conflict = any(
            order.instrument_id == context.intent.instrument_id
            and order.purpose is context.intent.purpose
            and order.state in _ACTIVE_ORDER_STATES
            for order in context.open_orders
        )
        local_conflict = any(
            intent.id != context.intent.id
            and intent.instrument_id == context.intent.instrument_id
            and intent.purpose is context.intent.purpose
            for intent in context.local_pending_intents
        )
        allowed = (
            broker_evidence_scoped
            and local_evidence_scoped
            and not unresolved
            and not broker_conflict
            and not local_conflict
        )
        return _status_result(
            code=PretradeCheckCode.DUPLICATE_ORDER,
            allowed=allowed,
            reason="no_conflict" if allowed else "duplicate_or_unresolved_order",
            observed_at=evaluated_at,
            configured_limit="no_same_purpose_conflict_or_unknown_submission",
        )

    def _matching_position(self, context: InitialRiskContext) -> Position | None:
        positions = tuple(
            position
            for position in context.portfolio.positions
            if position.instrument_id == context.intent.instrument_id
        )
        return positions[0] if len(positions) == 1 else None

    def _check_exit_policy(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        matching_position = self._matching_position(context)
        if context.intent.purpose is OrderPurpose.ENTRY:
            allowed = (
                context.intent.exit_policy_version is not None
                and context.eligibility.exit_policy_monitorable
                and matching_position is None
                and not self._config.position_risk.averaging_down_allowed
                and not self._config.position_risk.pyramiding_allowed
            )
            reason = "versioned_monitorable_exit_policy" if allowed else "entry_exit_policy_denied"
        else:
            allowed = (
                matching_position is not None
                and matching_position.account_id == context.intent.account_id
                and matching_position.quantity >= context.intent.quantity
                and self._projection_bound(context)
                and context.projection.gross_exposure <= context.portfolio.gross_exposure
                and context.projection.position_notional <= matching_position.market_value
            )
            reason = "reduce_only_exit" if allowed else "exit_could_increase_exposure"
        return _status_result(
            code=PretradeCheckCode.EXIT_POLICY,
            allowed=allowed,
            reason=reason,
            observed_at=evaluated_at,
            configured_limit="versioned_entry_policy_or_nonincreasing_exit",
        )

    def _check_review_match(
        self,
        context: InitialRiskContext,
        review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        if review is None:
            return _status_result(
                code=PretradeCheckCode.REVIEW_MATCH,
                allowed=False,
                reason="review_missing",
                observed_at=evaluated_at,
            )
        expected_client_id = (
            ClientOrderId(str(context.intent.id))
            if context.intent.asset_class is AssetClass.CRYPTO
            else review.client_order_id
        )
        expected_hash = canonical_review_payload_sha256(
            context.intent,
            client_order_id=expected_client_id,
        )
        expected_notional = _notional(
            context.intent.quantity,
            _reference_price(context),
        )
        with localcontext() as arithmetic:
            arithmetic.prec = max(arithmetic.prec, _ARITHMETIC_PRECISION)
            expected_fees = context.costs.fees_usd + context.costs.commission_usd
        allowed = (
            review.normalized_order == context.intent
            and review.client_order_id == expected_client_id
            and review.outbound_payload_sha256 == expected_hash
            and review.estimated_notional == expected_notional
            and review.estimated_fees == expected_fees
            and review.expires_at > evaluated_at
            and _is_current(
                review.reviewed_at,
                evaluated_at,
                self._config.freshness.max_broker_review_age_seconds,
            )
        )
        return _status_result(
            code=PretradeCheckCode.REVIEW_MATCH,
            allowed=allowed,
            reason="exact_fresh_review_match" if allowed else "review_mismatch_or_stale",
            observed_at=evaluated_at,
            configured_limit="exact_normalized_fields_and_payload_hash",
        )

    def _check_broker_minimums(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        instrument = context.instrument
        intent = context.intent
        quantity_allowed = (
            instrument.id == intent.instrument_id
            and _is_exact_multiple(intent.quantity, instrument.quantity_increment)
            and intent.quantity >= instrument.minimum_quantity
            and (
                instrument.maximum_quantity is None
                or intent.quantity <= instrument.maximum_quantity
            )
        )
        prices = tuple(
            price for price in (intent.limit_price, intent.stop_price) if price is not None
        )
        prices_allowed = all(
            _is_exact_multiple(price, instrument.price_increment) for price in prices
        )
        notional = _notional(intent.quantity, _reference_price(context))
        allowed = quantity_allowed and prices_allowed and notional >= instrument.minimum_notional
        return _result(
            code=PretradeCheckCode.BROKER_MINIMUMS,
            allowed=allowed,
            observed=_evidence_decimal_text(notional),
            configured_limit=_evidence_decimal_text(instrument.minimum_notional),
            reason="broker_bounds_satisfied" if allowed else "broker_minimums_denied",
            observed_at=evaluated_at,
        )

    def _check_reconciliation(
        self,
        context: InitialRiskContext,
        _review: BrokerOrderReview | None,
        evaluated_at: datetime,
    ) -> CheckResult:
        cadence = (
            self._config.scheduler.crypto_reconciliation_cadence_seconds
            if context.intent.asset_class is AssetClass.CRYPTO
            else self._config.scheduler.equity_reconciliation_cadence_seconds
        )
        evidence_scoped = (
            context.reconciliation.account_id == context.intent.account_id
            and all(
                position.account_id == context.intent.account_id
                for position in context.portfolio.positions
            )
            and all(order.account_id == context.intent.account_id for order in context.open_orders)
        )
        no_unknown_orders = all(
            order.state is not OrderState.UNKNOWN_REQUIRES_RECONCILIATION
            for order in context.open_orders
        )
        allowed = (
            context.reconciliation.clean
            and evidence_scoped
            and no_unknown_orders
            and _is_current(
                context.reconciliation.observed_at,
                evaluated_at,
                Decimal(cadence),
            )
        )
        return _result(
            code=PretradeCheckCode.RECONCILIATION,
            allowed=allowed,
            observed="clean_current" if allowed else "dirty_stale_or_unscoped",
            configured_limit=str(cadence),
            reason="reconciliation_clean" if allowed else "reconciliation_denied",
            observed_at=evaluated_at,
        )


__all__ = [
    "ExecutionCostEstimate",
    "FinalPretradeContext",
    "InitialRiskContext",
    "InstrumentEligibility",
    "PretradeCheckCode",
    "PretradeEngine",
    "canonical_review_payload_sha256",
]
