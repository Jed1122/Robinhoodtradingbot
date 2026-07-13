"""Fail-closed YAML/environment loading and release-envelope enforcement."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from trading_bot.config.hashing import hash_loaded_config
from trading_bot.config.models import AppConfig, SafetyEnvelope
from trading_bot.domain import ConfigHash, ExecutionMode

ENV_PREFIX = "TRADING_BOT__"
ENV_ALIASES: dict[str, tuple[str, ...]] = {
    "LIVE_TRADING_ENABLED": ("live_trading_enabled",),
    "PREDICTION_LIVE_ENABLED": ("prediction_markets", "live_enabled"),
}


class ConfigLoadError(ValueError):
    """Configuration input is malformed, ambiguous, or invalid."""


class UnsafeConfiguration(ConfigLoadError):
    """Resolved values exceed the non-overridable release safety envelope."""


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    config: AppConfig
    safety_envelope: SafetyEnvelope
    canonical_json: bytes
    config_hash: ConfigHash


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ConfigLoadError("configuration mapping key must be a string")
        if key in result:
            raise ConfigLoadError("duplicate YAML mapping key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


def _construct_decimal(loader: _UniqueKeyLoader, node: yaml.ScalarNode) -> Decimal:
    scalar = loader.construct_scalar(node)
    try:
        value = Decimal(scalar.replace("_", ""))
    except InvalidOperation:
        raise ConfigLoadError("invalid decimal scalar") from None
    if not value.is_finite():
        raise ConfigLoadError("nonfinite decimal scalar is not allowed")
    return value


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)
_UniqueKeyLoader.add_constructor("tag:yaml.org,2002:float", _construct_decimal)


def _load_yaml_document(source: str) -> Any:
    loader = _UniqueKeyLoader(source)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()  # type: ignore[no-untyped-call]  # PyYAML has no typed stub.


def _validate_mapping_keys(value: Any, depth: int = 0) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ConfigLoadError(
                    f"configuration mapping key must be a string at depth {depth}"
                )
            _validate_mapping_keys(nested, depth + 1)
    elif isinstance(value, list):
        for nested in value:
            _validate_mapping_keys(nested, depth + 1)


def _reject_nulls(value: Any, path: tuple[str, ...] = ()) -> None:
    if value is None:
        raise ConfigLoadError(f"null configuration value at depth {len(path)}")
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_nulls(nested, (*path, str(key)))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_nulls(nested, (*path, str(index)))


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        raise ConfigLoadError("cannot read YAML configuration") from None
    try:
        loaded = _load_yaml_document(source)
    except ConfigLoadError:
        raise
    except MemoryError:
        raise
    except Exception:
        raise ConfigLoadError("malformed YAML configuration") from None
    if not isinstance(loaded, dict):
        raise ConfigLoadError("configuration root must be a mapping")
    _validate_mapping_keys(loaded)
    _reject_nulls(loaded)
    return loaded


def _parse_environment_value(raw_value: str) -> Any:
    try:
        parsed = _load_yaml_document(raw_value)
    except ConfigLoadError:
        raise
    except MemoryError:
        raise
    except Exception:
        raise ConfigLoadError("malformed environment YAML value") from None
    _validate_mapping_keys(parsed)
    _reject_nulls(parsed)
    return parsed


def _value_kind(value: Any) -> str:
    if isinstance(value, Mapping):
        return "mapping"
    if isinstance(value, list):
        return "list"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float, Decimal)):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def _merge_mappings(
    lower: Mapping[str, Any],
    higher: Mapping[str, Any],
    path: tuple[str, ...] = (),
) -> dict[str, Any]:
    merged = deepcopy(dict(lower))
    for key, incoming in higher.items():
        location = (*path, key)
        if key not in merged:
            merged[key] = deepcopy(incoming)
            continue
        current = merged[key]
        current_kind = _value_kind(current)
        incoming_kind = _value_kind(incoming)
        if current_kind == "mapping" and incoming_kind == "mapping":
            merged[key] = _merge_mappings(current, incoming, location)
            continue
        if current_kind != incoming_kind:
            raise ConfigLoadError("conflicting configuration value types")
        # Lists are replaced atomically; scalars follow normal precedence.
        merged[key] = deepcopy(incoming)
    return merged


def _leaf_names(value: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for key, nested in value.items():
        if isinstance(nested, Mapping):
            names.update(_leaf_names(nested))
        else:
            names.add(key.upper())
    return names


def _validate_environment_path(config: Mapping[str, Any], path: tuple[str, ...]) -> None:
    if not path:
        raise ConfigLoadError("empty nested environment path")
    current: Any = config
    for index, segment in enumerate(path):
        if not isinstance(current, Mapping) or segment not in current:
            raise ConfigLoadError("unknown nested environment path")
        current = current[segment]
        if index < len(path) - 1 and not isinstance(current, Mapping):
            raise ConfigLoadError("unknown nested environment path")
    if isinstance(current, Mapping):
        raise ConfigLoadError("nested environment path must identify one leaf")


def _assign_nested(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = target
    for segment in path[:-1]:
        nested = current.setdefault(segment, {})
        if not isinstance(nested, dict):
            raise ConfigLoadError("duplicate environment representation")
        current = nested
    current[path[-1]] = value


def _environment_overlay(
    environ: Mapping[str, str], resolved_yaml: Mapping[str, Any]
) -> dict[str, Any]:
    overlay: dict[str, Any] = {}
    represented: dict[tuple[str, ...], str] = {}
    known_unprefixed_leaves = _leaf_names(resolved_yaml)

    for supplied_name, raw_value in environ.items():
        upper_name = supplied_name.upper()
        if upper_name.startswith(ENV_PREFIX):
            suffix = supplied_name[len(ENV_PREFIX) :]
            segments = suffix.split("__")
            if any(not segment for segment in segments):
                raise ConfigLoadError("malformed nested environment path")
            path = tuple(segment.lower() for segment in segments)
            _validate_environment_path(resolved_yaml, path)
        elif upper_name in ENV_ALIASES:
            path = ENV_ALIASES[upper_name]
        elif upper_name in known_unprefixed_leaves:
            raise ConfigLoadError("unapproved unprefixed configuration alias")
        else:
            continue

        if path in represented:
            raise ConfigLoadError("duplicate environment representation")
        represented[path] = supplied_name
        parsed = _parse_environment_value(raw_value)
        _assign_nested(overlay, path, parsed)

    return overlay


def _require_at_most(name: str, actual: Decimal | int, maximum: Decimal | int) -> None:
    if actual > maximum:
        raise UnsafeConfiguration(f"{name} exceeds release maximum")


def _require_at_least(name: str, actual: Decimal | int, minimum: Decimal | int) -> None:
    if actual < minimum:
        raise UnsafeConfiguration(f"{name} is below release minimum")


def _require_not_enabled(name: str, actual: bool, permitted: bool) -> None:
    if actual and not permitted:
        raise UnsafeConfiguration(f"{name} is prohibited by the release envelope")


def enforce_safety_envelope(config: AppConfig, envelope: SafetyEnvelope) -> None:
    """Reject every resolved value that weakens release-level safety."""

    if config.mode not in envelope.allowed_modes:
        raise UnsafeConfiguration(f"mode {config.mode.value} is not release-allowed")
    _require_not_enabled(
        "live_trading_enabled", config.live_trading_enabled, envelope.live_trading_permitted
    )
    if config.prediction_markets.live_enabled or envelope.prediction_live_permitted:
        raise UnsafeConfiguration("prediction live execution is always prohibited")

    max_pairs = (
        (
            "portfolio.expected_starting_equity_usd",
            config.portfolio.expected_starting_equity_usd,
            envelope.portfolio.expected_starting_equity_usd,
        ),
        (
            "portfolio.live_account_equity_ceiling_usd",
            config.portfolio.live_account_equity_ceiling_usd,
            envelope.portfolio.live_account_equity_ceiling_usd,
        ),
        (
            "portfolio.max_total_gross_exposure_pct",
            config.portfolio.max_total_gross_exposure_pct,
            envelope.portfolio.max_total_gross_exposure_pct,
        ),
        (
            "portfolio.max_open_positions",
            config.portfolio.max_open_positions,
            envelope.portfolio.max_open_positions,
        ),
        (
            "portfolio.max_gross_exposure_usd",
            config.portfolio.max_gross_exposure_usd,
            envelope.portfolio.max_gross_exposure_usd,
        ),
        (
            "position_risk.max_risk_per_trade_pct",
            config.position_risk.max_risk_per_trade_pct,
            envelope.position_risk.max_risk_per_trade_pct,
        ),
        (
            "position_risk.max_position_notional_pct",
            config.position_risk.max_position_notional_pct,
            envelope.position_risk.max_position_notional_pct,
        ),
        (
            "position_risk.max_correlated_group_exposure_pct",
            config.position_risk.max_correlated_group_exposure_pct,
            envelope.position_risk.max_correlated_group_exposure_pct,
        ),
        (
            "loss_limits.max_daily_loss_pct",
            config.loss_limits.max_daily_loss_pct,
            envelope.loss_limits.max_daily_loss_pct,
        ),
        (
            "loss_limits.max_weekly_loss_pct",
            config.loss_limits.max_weekly_loss_pct,
            envelope.loss_limits.max_weekly_loss_pct,
        ),
        (
            "loss_limits.max_peak_to_trough_drawdown_pct",
            config.loss_limits.max_peak_to_trough_drawdown_pct,
            envelope.loss_limits.max_peak_to_trough_drawdown_pct,
        ),
        (
            "loss_limits.consecutive_loss_pause_count",
            config.loss_limits.consecutive_loss_pause_count,
            envelope.loss_limits.consecutive_loss_pause_count,
        ),
        (
            "activity.max_new_orders_per_day",
            config.activity.max_new_orders_per_day,
            envelope.activity.max_new_orders_per_day,
        ),
        (
            "activity.max_orders_per_symbol_per_day",
            config.activity.max_orders_per_symbol_per_day,
            envelope.activity.max_orders_per_symbol_per_day,
        ),
        (
            "activity.max_order_notional_usd",
            config.activity.max_order_notional_usd,
            envelope.activity.max_order_notional_usd,
        ),
        (
            "equities.max_spread_pct",
            config.equities.max_spread_pct,
            envelope.equities.max_spread_pct,
        ),
        (
            "equities.reconciliation_quantity_tolerance",
            config.equities.reconciliation_quantity_tolerance,
            envelope.equities.reconciliation_quantity_tolerance,
        ),
        (
            "crypto.max_total_crypto_exposure_pct",
            config.crypto.max_total_crypto_exposure_pct,
            envelope.crypto.max_total_crypto_exposure_pct,
        ),
        (
            "crypto.max_single_crypto_exposure_pct",
            config.crypto.max_single_crypto_exposure_pct,
            envelope.crypto.max_single_crypto_exposure_pct,
        ),
        (
            "crypto.max_spread_pct",
            config.crypto.max_spread_pct,
            envelope.crypto.max_spread_pct,
        ),
        (
            "crypto.reconciliation_quantity_tolerance",
            config.crypto.reconciliation_quantity_tolerance,
            envelope.crypto.reconciliation_quantity_tolerance,
        ),
        (
            "prediction.future_max_single_contract_risk_pct",
            config.prediction_markets.future_max_single_contract_risk_pct,
            envelope.prediction_markets.future_max_single_contract_risk_pct,
        ),
        (
            "prediction.future_max_total_exposure_pct",
            config.prediction_markets.future_max_total_exposure_pct,
            envelope.prediction_markets.future_max_total_exposure_pct,
        ),
        (
            "costs.max_slippage_pct",
            config.costs.max_slippage_pct,
            envelope.costs.max_slippage_pct,
        ),
        (
            "promotion.micro_order_review_interval",
            config.promotion.micro_order_review_interval,
            envelope.promotion.micro_order_review_interval,
        ),
        (
            "logging.max_event_bytes",
            config.logging.max_event_bytes,
            envelope.logging.max_event_bytes,
        ),
    )
    for name, actual, maximum in max_pairs:
        _require_at_most(name, actual, maximum)

    min_pairs = (
        (
            "portfolio.min_cash_reserve_pct",
            config.portfolio.min_cash_reserve_pct,
            envelope.portfolio.min_cash_reserve_pct,
        ),
        (
            "position_risk.minimum_reward_to_initial_risk",
            config.position_risk.minimum_reward_to_initial_risk,
            envelope.position_risk.minimum_reward_to_initial_risk,
        ),
        (
            "loss_limits.consecutive_loss_pause_minutes",
            config.loss_limits.consecutive_loss_pause_minutes,
            envelope.loss_limits.consecutive_loss_pause_minutes,
        ),
        (
            "activity.minimum_minutes_between_new_orders",
            config.activity.minimum_minutes_between_new_orders,
            envelope.activity.minimum_minutes_between_new_orders,
        ),
        (
            "equities.minimum_price_usd",
            config.equities.minimum_price_usd,
            envelope.equities.minimum_price_usd,
        ),
        (
            "equities.minimum_average_daily_dollar_volume_usd",
            config.equities.minimum_average_daily_dollar_volume_usd,
            envelope.equities.minimum_average_daily_dollar_volume_usd,
        ),
        (
            "equities.avoid_new_entry_before_earnings_trading_days",
            config.equities.avoid_new_entry_before_earnings_trading_days,
            envelope.equities.avoid_new_entry_before_earnings_trading_days,
        ),
        (
            "equities.avoid_new_entry_after_earnings_trading_days",
            config.equities.avoid_new_entry_after_earnings_trading_days,
            envelope.equities.avoid_new_entry_after_earnings_trading_days,
        ),
        (
            "promotion.paper_min_eligible_unique_cycles",
            config.promotion.paper_min_eligible_unique_cycles,
            envelope.promotion.paper_min_eligible_unique_cycles,
        ),
        (
            "promotion.shadow_min_calendar_days",
            config.promotion.shadow_min_calendar_days,
            envelope.promotion.shadow_min_calendar_days,
        ),
        (
            "promotion.normal_min_combined_calendar_days",
            config.promotion.normal_min_combined_calendar_days,
            envelope.promotion.normal_min_combined_calendar_days,
        ),
        (
            "promotion.normal_min_valid_observations",
            config.promotion.normal_min_valid_observations,
            envelope.promotion.normal_min_valid_observations,
        ),
        (
            "costs.stressed_cost_multiplier",
            config.costs.stressed_cost_multiplier,
            envelope.costs.stressed_cost_multiplier,
        ),
    )
    for name, actual, minimum in min_pairs:
        _require_at_least(name, actual, minimum)

    freshness_fields = (
        "max_executable_quote_age_seconds",
        "max_account_snapshot_age_seconds",
        "max_broker_health_age_seconds",
        "max_broker_review_age_seconds",
        "max_preflight_age_seconds",
        "max_clock_drift_seconds",
    )
    for field in freshness_fields:
        _require_at_most(
            f"freshness.{field}",
            getattr(config.freshness, field),
            getattr(envelope.freshness, field),
        )
    for field in ("activation_lifetime_seconds", "live_lease_lifetime_seconds"):
        _require_at_most(
            f"authorization.{field}",
            getattr(config.authorization, field),
            getattr(envelope.authorization, field),
        )
    for field in (
        "broker_timeout_seconds",
        "shutdown_deadline_seconds",
        "remainder_order_max_age_seconds",
    ):
        _require_at_most(
            f"runtime.{field}", getattr(config.runtime, field), getattr(envelope.runtime, field)
        )
    for field in (
        "max_data_age_bars",
        "max_anomaly_change_pct",
        "max_cross_response_timestamp_skew_seconds",
    ):
        _require_at_most(
            f"market_data.{field}",
            getattr(config.market_data, field),
            getattr(envelope.market_data, field),
        )

    prohibited = (
        (
            "position_risk.averaging_down_allowed",
            config.position_risk.averaging_down_allowed,
            envelope.position_risk.averaging_down_allowed,
        ),
        (
            "position_risk.pyramiding_allowed",
            config.position_risk.pyramiding_allowed,
            envelope.position_risk.pyramiding_allowed,
        ),
        (
            "equities.margin_allowed",
            config.equities.margin_allowed,
            envelope.equities.margin_allowed,
        ),
        (
            "equities.short_sales_allowed",
            config.equities.short_sales_allowed,
            envelope.equities.short_sales_allowed,
        ),
        (
            "equities.options_allowed",
            config.equities.options_allowed,
            envelope.equities.options_allowed,
        ),
        (
            "equities.leveraged_etfs_allowed",
            config.equities.leveraged_etfs_allowed,
            envelope.equities.leveraged_etfs_allowed,
        ),
        (
            "equities.inverse_etfs_allowed",
            config.equities.inverse_etfs_allowed,
            envelope.equities.inverse_etfs_allowed,
        ),
        ("equities.otc_allowed", config.equities.otc_allowed, envelope.equities.otc_allowed),
        (
            "equities.microcaps_allowed",
            config.equities.microcaps_allowed,
            envelope.equities.microcaps_allowed,
        ),
        (
            "crypto.leverage_allowed",
            config.crypto.leverage_allowed,
            envelope.crypto.leverage_allowed,
        ),
        (
            "runtime.automatic_live_activation_enabled",
            config.runtime.automatic_live_activation_enabled,
            envelope.runtime.automatic_live_activation_enabled,
        ),
        (
            "runtime.automatic_liquidation_enabled",
            config.runtime.automatic_liquidation_enabled,
            envelope.runtime.automatic_liquidation_enabled,
        ),
        (
            "runtime.normal_entry_market_orders_allowed",
            config.runtime.normal_entry_market_orders_allowed,
            envelope.runtime.normal_entry_market_orders_allowed,
        ),
        (
            "runtime.emergency_market_orders_allowed",
            config.runtime.emergency_market_orders_allowed,
            envelope.runtime.emergency_market_orders_allowed,
        ),
        (
            "market_data.interpolated_bars_allowed",
            config.market_data.interpolated_bars_allowed,
            envelope.market_data.interpolated_bars_allowed,
        ),
        (
            "research.assumptions_validated",
            config.research.assumptions_validated,
            envelope.research.assumptions_validated,
        ),
        (
            "research.evidence_promotable",
            config.research.evidence_promotable,
            envelope.research.evidence_promotable,
        ),
        (
            "simulation.assumptions_validated",
            config.simulation.assumptions_validated,
            envelope.simulation.assumptions_validated,
        ),
        (
            "simulation.evidence_promotable",
            config.simulation.evidence_promotable,
            envelope.simulation.evidence_promotable,
        ),
        ("llm_reporting.enabled", config.llm_reporting.enabled, envelope.llm_reporting.enabled),
    )
    for name, actual, permitted in prohibited:
        _require_not_enabled(name, actual, permitted)

    if not set(config.crypto.initial_symbol_allowlist).issubset(
        envelope.crypto.initial_symbol_allowlist
    ):
        raise UnsafeConfiguration("crypto initial symbol allowlist exceeds release allowlist")
    if not set(config.market_data.canonical_bar_intervals).issubset(
        envelope.market_data.canonical_bar_intervals
    ):
        raise UnsafeConfiguration("market data bar intervals exceed release allowlist")
    if envelope.runtime.start_paused and not config.runtime.start_paused:
        raise UnsafeConfiguration("mode/environment cannot unpause release startup")
    if config.retry.read_attempts < 1:
        raise UnsafeConfiguration("retry.read_attempts must remain at least one")
    if config.retry.write_attempts != 1:
        raise UnsafeConfiguration("retry.write_attempts must remain exactly one")
    if config.mode is ExecutionMode.MICRO_LIVE:
        _require_at_most(
            "micro max order notional",
            config.activity.max_order_notional_usd,
            envelope.micro_max_order_notional_usd,
        )
        _require_at_most(
            "micro max gross exposure",
            config.portfolio.max_gross_exposure_usd,
            envelope.micro_max_gross_exposure_usd,
        )
        _require_at_most(
            "micro max new orders per day",
            config.activity.max_new_orders_per_day,
            envelope.micro_max_new_orders_per_day,
        )


def load_config(
    base_path: Path,
    mode_path: Path,
    safety_path: Path,
    environ: Mapping[str, str],
) -> LoadedConfig:
    """Load base, one named mode, environment, and immutable safety envelope."""

    base = _load_yaml(base_path)
    mode = _load_yaml(mode_path)
    selected_mode = mode_path.stem.replace("-", "_")
    declared_mode = mode.get("mode")
    if declared_mode != selected_mode:
        raise ConfigLoadError("mode overlay declares a mode inconsistent with its filename")
    merged = _merge_mappings(base, mode)
    environment = _environment_overlay(environ, merged)
    merged = _merge_mappings(merged, environment)
    if merged.get("mode") != selected_mode:
        raise ConfigLoadError("environment cannot select a mode different from the overlay")

    try:
        config = AppConfig.model_validate(merged)
        envelope = SafetyEnvelope.model_validate(_load_yaml(safety_path))
    except ValidationError as exc:
        error_types = sorted(
            {
                str(error["type"])
                for error in exc.errors(
                    include_context=False,
                    include_input=False,
                    include_url=False,
                )
            }
        )
        reason = ", ".join(error_types) or "invalid value"
        raise ConfigLoadError(f"configuration validation failed: {reason}") from None
    enforce_safety_envelope(config, envelope)
    canonical, config_hash = hash_loaded_config(config, envelope)
    return LoadedConfig(
        config=config,
        safety_envelope=envelope,
        canonical_json=canonical,
        config_hash=config_hash,
    )
