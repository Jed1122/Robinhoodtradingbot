from decimal import Decimal
from pathlib import Path

import pytest

from trading_bot.config import ConfigLoadError, load_config
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.config.loader import restore_loaded_config

ROOT = Path(__file__).resolve().parents[3]


def test_hybrid_is_canonical_and_never_live():
    loaded = load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
    )
    assert loaded.config.hybrid.starting_capital_usd == 1000
    assert loaded.config.hybrid.paper_period_required is False
    assert loaded.config.live_trading_enabled is False
    assert restore_loaded_config(loaded.canonical_json, loaded.config_hash) == loaded


def test_environment_cannot_turn_hybrid_live():
    with pytest.raises(ConfigLoadError):
        load_config(
            ROOT / "configs/base.yaml",
            ROOT / "configs/hybrid/paper.yaml",
            ROOT / "configs/hybrid/safety-envelope.yaml",
            {"LIVE_TRADING_ENABLED": "true"},
            hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        )


def test_nonnull_tax_assumption_restores_canonical_identity():
    loaded = load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
    )
    policy = loaded.config.hybrid.model_copy(update={"tax_rate": Decimal(".25")})
    config = loaded.config.model_copy(update={"hybrid": policy})
    envelope = loaded.safety_envelope.model_copy(update={"hybrid": policy})
    canonical, digest = hash_loaded_config(config, envelope)
    assert restore_loaded_config(canonical, digest).config.hybrid.tax_rate == Decimal(".25")
