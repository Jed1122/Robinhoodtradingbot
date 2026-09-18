"""Config-bound synthetic exit triggers, never fills, cancellation or order authority."""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from trading_bot.domain import Bar, ConfigHash, DataHash, InstrumentId, Quote, Side, TimestampSource
from trading_bot.domain.decimal_utils import _require_sha256_hex, require_bounded_decimal
from trading_bot.market_data.recording import content_hash
from trading_bot.portfolio.targets import ExitPolicy
from trading_bot.simulation.equity_replay_models import (
    EquityStrategyReplayRequest,
    checked,
    deny,
    label,
    utc,
)
from trading_bot.simulation.equity_replay_portfolio import ReplayOrderRecord
from trading_bot.simulation.lifecycle import replay_order_lifecycle
from trading_bot.simulation.lifecycle_models import LifecycleFillEvent
from trading_bot.strategies.momentum import MomentumStrategy
from trading_bot.strategies.protocol import FeatureVector, StrategyAction, StrategyContext
from trading_bot.strategies.relative_strength import RelativeStrengthStrategy


@dataclass(frozen=True, slots=True)
class ReplayEntryPolicy:
    instrument_id: InstrumentId
    config_hash: ConfigHash
    feature_hash: DataHash
    observed_at: datetime
    entry_limit: Decimal
    stop_distance: Decimal
    target_price: Decimal
    stop_price: Decimal
    first_fill_at: datetime | None = None
    holding_bars: int = 0

    def __post_init__(self) -> None:
        with checked():
            label(self.instrument_id)
            _require_sha256_hex(self.config_hash, "config")
            _require_sha256_hex(self.feature_hash, "features")
            utc(self.observed_at)
            for value in (self.entry_limit, self.stop_distance, self.target_price, self.stop_price):
                require_bounded_decimal(value, "policy_value", positive=True)
            if (
                self.stop_price != self.entry_limit - self.stop_distance
                or self.target_price <= self.entry_limit
            ):
                deny("replay_policy_invalid")
            if type(self.holding_bars) is not int or self.holding_bars < 0:
                deny("replay_policy_invalid")
            if self.first_fill_at is None:
                if self.holding_bars:
                    deny("replay_policy_invalid")
            else:
                utc(self.first_fill_at)
                if self.first_fill_at < self.observed_at:
                    deny("replay_policy_invalid")

    @property
    def version(self) -> str:
        with checked():
            return "replay-exit:" + content_hash(
                (
                    "synthetic-equity-exit-v1",
                    self.instrument_id,
                    self.config_hash,
                    self.feature_hash,
                    self.observed_at,
                    self.entry_limit,
                    self.stop_distance,
                    self.stop_price,
                    self.target_price,
                )
            )


def _feature(vector: FeatureVector, required: tuple[str, ...], at: datetime) -> dict[str, Decimal]:
    if type(vector) is not FeatureVector or type(vector.values) is not tuple:
        deny("replay_features_invalid")
    label(vector.instrument_id)
    utc(vector.observed_at)
    _require_sha256_hex(vector.data_hash, "features")
    if vector.observed_at != at:
        deny("replay_features_invalid")
    values: dict[str, object] = {}
    for row in vector.values:
        if type(row) is not tuple or len(row) != 2:
            deny("replay_features_invalid")
        key, value = row
        label(key)
        if key in values or type(value) not in (Decimal, int, bool, str, type(None)):
            deny("replay_features_invalid")
        if type(value) is Decimal:
            require_bounded_decimal(value, "feature")
        values[key] = value
    result: dict[str, Decimal] = {}
    for key in required:
        required_value = values.get(key)
        if type(required_value) is not Decimal:
            deny("replay_features_unavailable")
        result[key] = required_value
    return result


def validate_policy(policy: ReplayEntryPolicy, request: EquityStrategyReplayRequest) -> None:
    if type(policy) is not ReplayEntryPolicy:
        deny("replay_policy_invalid")
    policy.__post_init__()
    if (
        policy.config_hash != request.loaded.config_hash
        or policy.instrument_id not in {i.id for i in request.instruments}
        or policy.target_price
        != policy.entry_limit
        + policy.stop_distance * request.loaded.config.equity_strategies.exit_reward_to_initial_risk
    ):
        deny("replay_policy_identity_invalid")


def derive_entry_policy(
    request: EquityStrategyReplayRequest, features: FeatureVector, entry_limit: Decimal
) -> ReplayEntryPolicy:
    with checked():
        if type(request) is not EquityStrategyReplayRequest or type(features) is not FeatureVector:
            deny()
        request = replace(request)
        utc(features.observed_at)
        if not request.starts_at <= features.observed_at <= request.end_at:
            deny("replay_features_invalid")
        values = _feature(features, ("average_true_range",), features.observed_at)
        atr = require_bounded_decimal(values["average_true_range"], "atr", positive=True)
        require_bounded_decimal(entry_limit, "entry", positive=True)
        settings = request.loaded.config.equity_strategies
        distance = atr * settings.stop_loss_atr_multiplier
        policy = ReplayEntryPolicy(
            features.instrument_id,
            ConfigHash(request.loaded.config_hash),
            features.data_hash,
            features.observed_at,
            entry_limit,
            distance,
            entry_limit + distance * settings.exit_reward_to_initial_risk,
            entry_limit - distance,
        )
        validate_policy(policy, request)
        return policy


def planning_policy(policy: ReplayEntryPolicy, request: EquityStrategyReplayRequest) -> ExitPolicy:
    with checked():
        validate_policy(policy, request)
        settings = request.loaded.config.equity_strategies
        return ExitPolicy(
            policy.version,
            "atr",
            policy.stop_distance,
            settings.exit_reward_to_initial_risk,
            settings.maximum_holding_bars,
        )


def observe_entry(
    policy: ReplayEntryPolicy,
    entry: ReplayOrderRecord,
    bars: tuple[Bar, ...],
    as_of: datetime,
    request: EquityStrategyReplayRequest,
) -> ReplayEntryPolicy:
    with checked():
        validate_policy(policy, request)
        utc(as_of)
        if type(entry) is not ReplayOrderRecord or type(bars) is not tuple:
            deny()
        if (
            entry.intent.side is not Side.BUY
            or entry.intent.account_id != request.account_id
            or entry.initial.order.account_id != request.account_id
            or entry.initial.order.intent_id != entry.intent.id
            or entry.initial.order.instrument_id != entry.intent.instrument_id
            or entry.initial.order.side != entry.intent.side
            or entry.initial.order.purpose != entry.intent.purpose
            or entry.initial.order.requested_quantity != entry.intent.quantity
            or entry.initial.order.limit_price != entry.intent.limit_price
            or entry.initial.order.created_at != entry.intent.created_at
            or entry.intent.instrument_id != policy.instrument_id
            or entry.intent.config_hash != policy.config_hash
            or entry.intent.exit_policy_version != policy.version
            or entry.intent.limit_price != policy.entry_limit
            or entry.result is None
            or not policy.observed_at <= as_of <= request.end_at
            or entry.lifecycle
            != replay_order_lifecycle(replace(entry.initial, events=entry.result.events))
        ):
            deny("replay_policy_identity_invalid")
        fills = tuple(e for e in entry.result.events if type(e) is LifecycleFillEvent)
        if any(e.cursor.occurred_at > as_of for e in entry.result.events):
            deny("replay_ordering_invalid")
        first = fills[0].cursor.occurred_at if fills else None
        if policy.first_fill_at is not None and policy.first_fill_at != first:
            deny("replay_policy_identity_invalid")
        previous_end: datetime | None = None
        count = 0
        for bar in bars:
            if type(bar) is not Bar:
                deny()
            bar.__post_init__()
            if (
                bar.instrument_id != policy.instrument_id
                or bar.interval is not request.snapshot_settings.interval
                or bar.ends_at > as_of
                or bar.interpolated
                or (previous_end is not None and bar.starts_at < previous_end)
            ):
                deny("replay_holding_history_invalid")
            previous_end = bar.ends_at
            if first is not None and bar.ends_at > first:
                count += 1
        if count < policy.holding_bars:
            deny("replay_holding_history_invalid")
        return replace(policy, first_fill_at=first, holding_bars=count)


def exit_reason(
    policy: ReplayEntryPolicy,
    quote: Quote,
    selected: bool | None,
    as_of: datetime,
    request: EquityStrategyReplayRequest,
) -> str | None:
    with checked():
        validate_policy(policy, request)
        utc(as_of)
        if type(quote) is not Quote or (selected is not None and type(selected) is not bool):
            deny("replay_exit_quote_invalid")
        quote.__post_init__()
        utc(quote.observed_at)
        age = as_of - quote.observed_at
        seconds = Decimal(age.days * 86400 + age.seconds) + Decimal(age.microseconds) / 1000000
        if (
            quote.instrument_id != policy.instrument_id
            or not quote.freshness_verified
            or quote.timestamp_source is not TimestampSource.SIMULATED
            or quote.source != "synthetic-configured-order-v1"
            or seconds < 0
            or seconds > request.loaded.config.freshness.max_executable_quote_age_seconds
            or not policy.observed_at <= as_of <= request.end_at
        ):
            deny("replay_exit_quote_invalid")
        require_bounded_decimal(quote.bid, "bid", positive=True)
        if policy.first_fill_at is None:
            return None
        if policy.first_fill_at > as_of:
            deny("replay_ordering_invalid")
        settings = request.loaded.config.equity_strategies
        if quote.bid <= policy.stop_price:
            return "replay_stop_triggered"
        if quote.bid >= policy.target_price:
            return "replay_target_triggered"
        if policy.holding_bars >= settings.maximum_holding_bars:
            return "replay_maximum_holding"
        if selected is False:
            if request.candidate.strategy_id == "equity_relative_strength":
                if settings.research_unselected_symbols_exit_to_cash:
                    return "replay_deselected"
            elif settings.exit_on_regime_change:
                return "replay_regime_exit"
        return None


def selected_instruments(
    request: EquityStrategyReplayRequest, context: StrategyContext, *, completed_bars: int
) -> tuple[InstrumentId, ...] | None:
    with checked():
        if (
            type(context) is not StrategyContext
            or type(completed_bars) is not int
            or completed_bars < 0
        ):
            deny()
        utc(context.as_of)
        if (
            context.config_hash != request.loaded.config_hash
            or context.features.observed_at != context.as_of
            or type(context.features.vectors) is not tuple
            or type(context.eligible_instruments) is not tuple
            or not request.starts_at <= context.as_of <= request.end_at
        ):
            deny("replay_features_invalid")
        known = {i.id for i in request.instruments}
        if not set(context.eligible_instruments) <= known or len(
            set(context.eligible_instruments)
        ) != len(context.eligible_instruments):
            deny("replay_features_invalid")
        candidate = request.candidate
        required = (
            ("total_return_pct", "moving_average_short", "moving_average_long", "latest_close")
            if candidate.strategy_id == "equity_momentum"
            else ("total_return_pct",)
        )
        seen: set[InstrumentId] = set()
        for vector in context.features.vectors:
            _feature(vector, required, context.as_of)
            if vector.instrument_id in seen or vector.instrument_id not in known:
                deny("replay_features_invalid")
            seen.add(vector.instrument_id)
        if not set(context.eligible_instruments) <= seen:
            deny("replay_features_unavailable")
        if candidate.strategy_id == "equity_momentum":
            decisions = MomentumStrategy(
                short_window=candidate.short_window, long_window=candidate.long_window
            ).decide(context)
        else:
            if completed_bars % request.loaded.config.equity_strategies.research_rebalance_bars:
                return None
            if candidate.top_n is None:
                deny()
            decisions = RelativeStrengthStrategy(
                lookback_window=candidate.long_window, top_n=candidate.top_n
            ).decide(context)
        return tuple(
            sorted(d.instrument_id for d in decisions if d.action is StrategyAction.ENTER_LONG)
        )
