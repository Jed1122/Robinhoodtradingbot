"""Merge, environment, and canonical hash tests for configuration loading."""

import traceback
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from trading_bot.config import ConfigLoadError, UnsafeConfiguration, load_config
from trading_bot.config.loader import (
    _environment_overlay,
    _load_yaml,
    _parse_environment_value,
)

ROOT = Path(__file__).parents[3]
CONFIGS = ROOT / "configs"


def load(mode: str = "backtest", environ: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    return load_config(
        base_path=CONFIGS / "base.yaml",
        mode_path=CONFIGS / f"{mode}.yaml",
        safety_path=CONFIGS / "safety-envelope.yaml",
        environ={} if environ is None else environ,
    )


@pytest.mark.parametrize(
    ("filename", "mode"),
    [
        ("backtest", "backtest"),
        ("simulation", "simulation"),
        ("paper", "paper"),
        ("shadow", "shadow"),
        ("micro_live", "micro_live"),
        ("normal_live", "normal_live"),
    ],
)
def test_every_mode_overlay_loads_the_mode_it_names(filename: str, mode: str) -> None:
    loaded = load(filename)

    assert loaded.config.mode.value == mode
    assert loaded.config.runtime.start_paused
    assert not loaded.config.live_trading_enabled
    assert loaded.config.portfolio.live_account_equity_ceiling_usd == Decimal("1000")


def test_environment_flag_is_only_one_live_gate_and_never_unpauses() -> None:
    loaded = load("normal_live", {"LIVE_TRADING_ENABLED": "true"})

    assert loaded.config.live_trading_enabled
    assert loaded.config.runtime.start_paused


def test_normal_and_micro_live_keep_distinct_approved_dollar_caps() -> None:
    normal = load("normal_live").config
    micro = load("micro_live").config

    assert normal.portfolio.max_gross_exposure_usd == 60
    assert normal.activity.max_order_notional_usd == 15
    assert normal.activity.max_new_orders_per_day == 3
    assert micro.portfolio.max_gross_exposure_usd == 20
    assert micro.activity.max_order_notional_usd == 5
    assert micro.activity.max_new_orders_per_day == 2


def test_release_envelope_keeps_exact_non_overridable_live_bounds() -> None:
    envelope = load().safety_envelope

    assert envelope.authorization.live_lease_lifetime_seconds == 86400
    assert envelope.micro_max_order_notional_usd == 5
    assert envelope.micro_max_gross_exposure_usd == 20
    assert envelope.micro_max_new_orders_per_day == 2
    assert not envelope.prediction_live_permitted


def test_nested_environment_values_are_applied() -> None:
    loaded = load(
        environ={
            "TRADING_BOT__PORTFOLIO__MAX_OPEN_POSITIONS": "4",
            "TRADING_BOT__FRESHNESS__MAX_EXECUTABLE_QUOTE_AGE_SECONDS": "4.5",
        }
    )

    assert loaded.config.portfolio.max_open_positions == 4
    assert str(loaded.config.freshness.max_executable_quote_age_seconds) == "4.5"


def test_logging_event_bound_environment_override_can_only_tighten() -> None:
    loaded = load(environ={"TRADING_BOT__LOGGING__MAX_EVENT_BYTES": "32768"})

    assert loaded.config.logging.max_event_bytes == 32768

    with pytest.raises(UnsafeConfiguration, match=r"logging\.max_event_bytes"):
        load(environ={"TRADING_BOT__LOGGING__MAX_EVENT_BYTES": "65537"})


@pytest.mark.parametrize("ceiling", ["150", "1000"])
def test_account_equity_ceiling_override_must_stay_within_release_bound(ceiling: str) -> None:
    loaded = load(environ={"TRADING_BOT__PORTFOLIO__LIVE_ACCOUNT_EQUITY_CEILING_USD": ceiling})

    assert loaded.config.portfolio.live_account_equity_ceiling_usd == Decimal(ceiling)
    assert not loaded.config.live_trading_enabled
    assert loaded.config.runtime.start_paused
    with pytest.raises(UnsafeConfiguration, match=r"portfolio\.live_account_equity_ceiling_usd"):
        load(environ={"TRADING_BOT__PORTFOLIO__LIVE_ACCOUNT_EQUITY_CEILING_USD": "1000.01"})


def test_account_ceiling_change_invalidates_previous_configuration_identity() -> None:
    current = load()
    previous_ceiling = load(
        environ={"TRADING_BOT__PORTFOLIO__LIVE_ACCOUNT_EQUITY_CEILING_USD": "150"}
    )

    assert current.config_hash != previous_ceiling.config_hash


def test_native_environment_integer_boolean_enum_and_list_values_remain_accepted() -> None:
    loaded = load(
        environ={
            "TRADING_BOT__MODE": "backtest",
            "TRADING_BOT__LIVE_TRADING_ENABLED": "false",
            "TRADING_BOT__PORTFOLIO__MAX_OPEN_POSITIONS": "4",
            "TRADING_BOT__CRYPTO__INITIAL_SYMBOL_ALLOWLIST": '["BTC-USD"]',
        }
    )

    assert loaded.config.mode.value == "backtest"
    assert loaded.config.live_trading_enabled is False
    assert loaded.config.portfolio.max_open_positions == 4
    assert loaded.config.crypto.initial_symbol_allowlist == ("BTC-USD",)


def test_lists_are_replaced_atomically_not_concatenated() -> None:
    loaded = load(environ={"TRADING_BOT__CRYPTO__INITIAL_SYMBOL_ALLOWLIST": '["BTC-USD"]'})

    assert loaded.config.crypto.initial_symbol_allowlist == ("BTC-USD",)


def test_research_scope_is_config_hash_bound_and_lists_replace_atomically() -> None:
    baseline = load()
    changed_universe = load(
        environ={
            "TRADING_BOT__EQUITY_STRATEGIES__RESEARCH_UNIVERSE_SYMBOLS": (
                '["SPY","QQQ","IWM"]'
            )
        }
    )
    changed_candidates = load(
        environ={
            "TRADING_BOT__EQUITY_STRATEGIES__RESEARCH_CANDIDATE_STRATEGY_IDS": (
                '["equity_momentum"]'
            )
        }
    )

    assert changed_universe.config.equity_strategies.research_universe_symbols == (
        "SPY",
        "QQQ",
        "IWM",
    )
    assert changed_universe.config_hash != baseline.config_hash
    assert changed_candidates.config_hash != baseline.config_hash


@pytest.mark.parametrize(
    "environ",
    [
        {
            "LIVE_TRADING_ENABLED": "true",
            "TRADING_BOT__LIVE_TRADING_ENABLED": "true",
        },
        {
            "PREDICTION_LIVE_ENABLED": "false",
            "TRADING_BOT__PREDICTION_MARKETS__LIVE_ENABLED": "false",
        },
        {
            "TRADING_BOT__PORTFOLIO__MAX_OPEN_POSITIONS": "4",
            "trading_bot__portfolio__max_open_positions": "4",
        },
    ],
)
def test_duplicate_environment_representations_are_rejected_even_when_equal(
    environ: dict[str, str],
) -> None:
    with pytest.raises(ConfigLoadError, match="duplicate"):
        load(environ=environ)


@pytest.mark.parametrize(
    "environ",
    [
        {"TRADING_BOT__PORTFOLIO__NOT_A_FIELD": "1"},
        {"TRADING_BOT__NOT_A_SECTION__VALUE": "1"},
        {"TRADING_BOT__PORTFOLIO____MAX_OPEN_POSITIONS": "4"},
        {"MAX_OPEN_POSITIONS": "4"},
        {"START_PAUSED": "false"},
    ],
)
def test_unknown_nested_paths_and_unapproved_leaf_aliases_are_rejected(
    environ: dict[str, str],
) -> None:
    with pytest.raises(ConfigLoadError):
        load(environ=environ)


def test_unrelated_os_and_secret_reference_variables_are_ignored() -> None:
    loaded = load(
        environ={
            "PATH": "/ordinary/bin",
            "HOME": "/ordinary/home",
            "ROBINHOOD_CRYPTO_API_KEY_FILE": "/restricted/reference",
            "TRADING_BOT_AUTH_VERIFY_KEY_FILE": "/restricted/reference",
        }
    )

    assert b"restricted" not in loaded.canonical_json
    assert b"ROBINHOOD" not in loaded.canonical_json


@pytest.mark.parametrize(
    "environ",
    [
        {"PREDICTION_LIVE_ENABLED": "true"},
        {"TRADING_BOT__PREDICTION_MARKETS__LIVE_ENABLED": "true"},
    ],
)
def test_prediction_live_true_is_rejected_through_every_environment_form(
    environ: dict[str, str],
) -> None:
    with pytest.raises(ConfigLoadError):
        load(environ=environ)


def test_environment_cannot_select_a_different_mode() -> None:
    with pytest.raises(ConfigLoadError, match="mode"):
        load("backtest", {"TRADING_BOT__MODE": "paper"})


def test_mode_filename_and_declared_mode_must_match(tmp_path: Path) -> None:
    path = tmp_path / "paper.yaml"
    path.write_text("mode: shadow\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="mode"):
        load_config(
            base_path=CONFIGS / "base.yaml",
            mode_path=path,
            safety_path=CONFIGS / "safety-envelope.yaml",
            environ={},
        )


def test_mapping_scalar_conflicts_fail_instead_of_replacing_types(tmp_path: Path) -> None:
    path = tmp_path / "paper.yaml"
    path.write_text("mode: paper\nportfolio: 10\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="type"):
        load_config(
            base_path=CONFIGS / "base.yaml",
            mode_path=path,
            safety_path=CONFIGS / "safety-envelope.yaml",
            environ={},
        )


def test_unknown_yaml_key_fails(tmp_path: Path) -> None:
    path = tmp_path / "paper.yaml"
    path.write_text("mode: paper\nmystery: true\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError):
        load_config(
            base_path=CONFIGS / "base.yaml",
            mode_path=path,
            safety_path=CONFIGS / "safety-envelope.yaml",
            environ={},
        )


@pytest.mark.parametrize(
    "source",
    (
        "value: 1\nvalue: 2\n",
        "outer:\n  value: 1\n  value: 2\n",
    ),
)
def test_file_yaml_rejects_duplicate_keys_at_every_depth(tmp_path: Path, source: str) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text(source, encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="duplicate"):
        _load_yaml(path)


def test_environment_yaml_rejects_duplicate_mapping_keys() -> None:
    with pytest.raises(ConfigLoadError, match="duplicate"):
        _parse_environment_value("{value: 1, value: 2}")


def test_file_yaml_rejects_python_object_construction_tags(tmp_path: Path) -> None:
    path = tmp_path / "unsafe-tag.yaml"
    path.write_text(
        "value: !!python/object/new:builtins.str [ordinary]\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match="malformed"):
        _load_yaml(path)


def test_environment_yaml_rejects_python_object_construction_tags() -> None:
    with pytest.raises(ConfigLoadError, match="malformed"):
        _parse_environment_value("!!python/object/new:builtins.str [ordinary]")


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, Mapping):
        return any(_contains_float(key) or _contains_float(item) for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_float(item) for item in value)
    return False


def test_file_decimal_scalars_are_constructed_directly_as_decimal() -> None:
    raw = _load_yaml(CONFIGS / "base.yaml")

    assert raw["position_risk"]["max_risk_per_trade_pct"] == Decimal("0.50")
    assert type(raw["position_risk"]["max_risk_per_trade_pct"]) is Decimal
    assert not _contains_float(raw)


def test_environment_decimal_scalars_are_constructed_directly_as_decimal() -> None:
    raw = _load_yaml(CONFIGS / "base.yaml")
    overlay = _environment_overlay(
        {"TRADING_BOT__FRESHNESS__MAX_EXECUTABLE_QUOTE_AGE_SECONDS": "4.5"},
        raw,
    )

    value = overlay["freshness"]["max_executable_quote_age_seconds"]
    assert value == Decimal("4.5")
    assert type(value) is Decimal
    assert not _contains_float(overlay)


@pytest.mark.parametrize("scalar", [".nan", ".inf", "-.inf"])
def test_nonfinite_yaml_decimal_scalars_fail_during_construction(
    tmp_path: Path, scalar: str
) -> None:
    path = tmp_path / "value.yaml"
    path.write_text(f"value: {scalar}\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="decimal"):
        _load_yaml(path)


def _assert_secret_absent(exc: BaseException) -> None:
    sentinel = "actual-secret-value"
    rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    assert sentinel not in str(exc)
    assert sentinel not in repr(exc)
    assert sentinel not in rendered


def test_pydantic_validation_failure_never_echoes_invalid_value(tmp_path: Path) -> None:
    path = tmp_path / "paper.yaml"
    path.write_text("mode: paper\nmystery: actual-secret-value\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as captured:
        load_config(
            base_path=CONFIGS / "base.yaml",
            mode_path=path,
            safety_path=CONFIGS / "safety-envelope.yaml",
            environ={},
        )

    _assert_secret_absent(captured.value)


def test_malformed_yaml_never_echoes_source_value_in_exception_chain(tmp_path: Path) -> None:
    path = tmp_path / "paper.yaml"
    path.write_text("mode: paper\nmystery: [actual-secret-value\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as captured:
        load_config(
            base_path=CONFIGS / "base.yaml",
            mode_path=path,
            safety_path=CONFIGS / "safety-envelope.yaml",
            environ={},
        )

    _assert_secret_absent(captured.value)


def test_malformed_environment_yaml_never_echoes_source_value() -> None:
    environ = {"TRADING_BOT__CRYPTO__INITIAL_SYMBOL_ALLOWLIST": "[actual-secret-value"}
    with pytest.raises(ConfigLoadError) as captured:
        load(environ=environ)

    _assert_secret_absent(captured.value)


@pytest.mark.parametrize(
    "tagged_value",
    ["!!int actual-secret-value", "!!timestamp actual-secret-value"],
)
def test_explicit_yaml_constructor_failure_never_echoes_source_value(
    tmp_path: Path, tagged_value: str
) -> None:
    path = tmp_path / "tagged.yaml"
    path.write_text(f"value: {tagged_value}\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as captured:
        _load_yaml(path)

    _assert_secret_absent(captured.value)


@pytest.mark.parametrize(
    "tagged_value",
    ["!!int actual-secret-value", "!!timestamp actual-secret-value"],
)
def test_explicit_environment_constructor_failure_never_echoes_source_value(
    tagged_value: str,
) -> None:
    with pytest.raises(ConfigLoadError) as captured:
        load(
            environ={
                "TRADING_BOT__PORTFOLIO__MAX_OPEN_POSITIONS": tagged_value,
            }
        )

    _assert_secret_absent(captured.value)


def test_environment_binary_values_cannot_coerce_enum_tuple_members() -> None:
    with pytest.raises(ConfigLoadError):
        load(
            environ={
                "TRADING_BOT__MARKET_DATA__CANONICAL_BAR_INTERVALS": ("[!!binary b25lX21pbnV0ZQ==]")
            }
        )


def test_unknown_environment_path_never_echoes_supplied_path_value() -> None:
    with pytest.raises(ConfigLoadError) as captured:
        load(environ={"TRADING_BOT__ACTUAL-SECRET-VALUE__FIELD": "1"})

    _assert_secret_absent(captured.value)


def test_nested_non_string_yaml_key_fails_as_config_error(tmp_path: Path) -> None:
    path = tmp_path / "paper.yaml"
    path.write_text("mode: paper\nportfolio:\n  1: 2\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="key"):
        load_config(
            base_path=CONFIGS / "base.yaml",
            mode_path=path,
            safety_path=CONFIGS / "safety-envelope.yaml",
            environ={},
        )


def test_hash_is_deterministic_across_environment_iteration_order() -> None:
    first = load(
        environ={
            "TRADING_BOT__PORTFOLIO__MAX_OPEN_POSITIONS": "4",
            "TRADING_BOT__FRESHNESS__MAX_EXECUTABLE_QUOTE_AGE_SECONDS": "4",
        }
    )
    second = load(
        environ={
            "TRADING_BOT__FRESHNESS__MAX_EXECUTABLE_QUOTE_AGE_SECONDS": "4",
            "TRADING_BOT__PORTFOLIO__MAX_OPEN_POSITIONS": "4",
        }
    )

    assert first.canonical_json == second.canonical_json
    assert first.config_hash == second.config_hash


def test_envelope_only_change_invalidates_loaded_hash(tmp_path: Path) -> None:
    first = load()
    raw = yaml.safe_load((CONFIGS / "safety-envelope.yaml").read_text(encoding="utf-8"))
    raw["authorization"]["live_lease_lifetime_seconds"] = 80000
    changed = tmp_path / "safety-envelope.yaml"
    changed.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    second = load_config(
        base_path=CONFIGS / "base.yaml",
        mode_path=CONFIGS / "backtest.yaml",
        safety_path=changed,
        environ={},
    )

    assert first.config == second.config
    assert first.canonical_json != second.canonical_json
    assert first.config_hash != second.config_hash
