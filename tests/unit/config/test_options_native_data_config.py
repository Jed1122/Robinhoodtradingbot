"""Canonical native-data activation cannot authorize operating modes or larger bounds."""

from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.config.loader import enforce_safety_envelope
from trading_bot.config.models import AppConfig, SafetyEnvelope

ROOT = Path("configs")


def load(environ=None, *, profile="options/native-data/simulation.yaml"):
    return load_config(
        ROOT / "base.yaml", ROOT / profile, ROOT / "safety-envelope.yaml", environ or {}
    )


def ready():
    if not (ROOT / "options/native-data/simulation.yaml").exists():
        pytest.fail("canonical native research profile is not implemented")
    return load()


def test_native_profile_is_research_only():
    loaded = ready()
    assert loaded.config.options.native_data.max_records == 10_000_000
    assert loaded.config.options.native_data.enabled is True
    assert loaded.config.options.live_supported is False
    assert loaded.config.options.max_per_trade_loss_usd == 50
    assert loaded.config.options.cumulative_trial_loss_limit_usd == 50
    assert loaded.config.runtime.start_paused is True


@pytest.mark.parametrize("mode", ["paper", "shadow", "micro_live", "live"])
def test_native_profile_denied_in_operating_modes(mode):
    ready()
    with pytest.raises(ValueError):
        load({"TRADING_BOT__MODE": mode})


@pytest.mark.parametrize(
    "field,value",
    [
        ("MAX_RECORDS", "10000001"),
        ("MAX_COMPRESSED_BYTES", "536870913"),
        ("MAX_DECOMPRESSED_BYTES", "4294967297"),
        ("MAX_METADATA_BYTES", "268435457"),
        ("MAX_UNIQUE_SYMBOLS", "1000001"),
        ("MAX_PART_ROWS", "10001"),
        ("MAX_PART_BYTES", "16777217"),
        ("MAX_PARTS", "10001"),
        ("MAX_MANIFEST_BYTES", "16777217"),
        ("MAX_RECORDS", "true"),
        ("MAX_RECORDS", "1.0"),
        ("MAX_RECORDS", "0"),
    ],
)
def test_native_limits_cannot_exceed_release_bounds(field, value):
    ready()
    with pytest.raises(ValueError):
        load({f"TRADING_BOT__OPTIONS__NATIVE_DATA__{field}": value})


def test_native_intake_disabled_in_ordinary_profiles_and_without_options():
    ready()
    assert load(profile="options/simulation.yaml").config.options.native_data.enabled is False
    with pytest.raises(ValueError):
        load({"TRADING_BOT__OPTIONS__ENABLED": "false"})


def test_native_resource_tightening_changes_identity_and_scanner_limits():
    before = ready()
    from trading_bot.market_data.databento_bar_models import native_limits

    after = load({"TRADING_BOT__OPTIONS__NATIVE_DATA__MAX_RECORDS": "100"})
    assert after.config_hash != before.config_hash
    assert native_limits(after).max_records == 100
    with pytest.raises(ValueError):
        native_limits(load(profile="options/simulation.yaml"))


@pytest.mark.parametrize("model", [AppConfig, SafetyEnvelope])
def test_native_settings_have_no_implicit_defaults(model):
    loaded = ready()
    values = (loaded.config if model is AppConfig else loaded.safety_envelope).model_dump()
    del values["options"]["native_data"]
    with pytest.raises(ValueError):
        model.model_validate(values)


@pytest.mark.parametrize(
    "name",
    [
        "enabled",
        "max_compressed_bytes",
        "max_decompressed_bytes",
        "max_metadata_bytes",
        "max_records",
        "max_unique_symbols",
        "max_part_rows",
        "max_part_bytes",
        "max_parts",
        "max_manifest_bytes",
    ],
)
def test_reduced_release_envelope_is_enforced(name):
    loaded = ready()
    values = loaded.safety_envelope.model_dump()
    values["options"]["native_data"][name] = False if name == "enabled" else 1
    envelope = SafetyEnvelope.model_validate(values)
    with pytest.raises(ValueError):
        enforce_safety_envelope(loaded.config, envelope)
