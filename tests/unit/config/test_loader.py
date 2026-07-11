"""Merge, environment, and canonical hash tests for configuration loading."""

from pathlib import Path

import pytest
import yaml

from trading_bot.config import ConfigLoadError, load_config

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


def test_lists_are_replaced_atomically_not_concatenated() -> None:
    loaded = load(
        environ={"TRADING_BOT__CRYPTO__INITIAL_SYMBOL_ALLOWLIST": '["BTC-USD"]'}
    )

    assert loaded.config.crypto.initial_symbol_allowlist == ("BTC-USD",)


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
