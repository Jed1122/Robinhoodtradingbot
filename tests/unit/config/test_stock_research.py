import importlib
from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.config.loader import ConfigLoadError, restore_loaded_config
from trading_bot.hybrid.cli import configuration

ROOT = Path(__file__).resolve().parents[3]


def load(policy=None, **kwargs):
    return load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=policy or ROOT / "configs/hybrid/stock-research.yaml",
        **kwargs,
    )


def test_stock_extension_roundtrips_without_changing_existing_hybrid_identity():
    before = configuration(ROOT / "configs")
    loaded = load()
    module = importlib.import_module("trading_bot.config.stock_research")
    assert type(loaded.config) is module.StockResearchAppConfig
    assert loaded.config.stock_research.live_enabled is False
    assert loaded.config.hybrid == before.config.hybrid
    assert loaded.config_hash != before.config_hash
    assert restore_loaded_config(loaded.canonical_json, loaded.config_hash) == loaded
    assert configuration(ROOT / "configs") == before
    assert "stock_research" not in before.config.model_dump()


@pytest.mark.parametrize(
    "body",
    [
        "live_enabled: true\n",
        "minimum_price_usd: 0\n",
        "scan_minutes: 0\n",
        "max_calls_per_cycle: 33\n",
        "max_daily_calls: 99999\n",
        "llm_enabled: true\n",
        "quality_weight_pct: 100\n",
        "market_cap_boundaries_usd: [2000000000, 1000000000]\n",
        "market_cap_boundaries_usd: [3000000000, 5000000000]\n",
    ],
)
def test_invalid_stock_policy_fails_closed(tmp_path, body):
    policy = tmp_path / "policy.yaml"
    policy.write_text(body)
    with pytest.raises(ConfigLoadError):
        load(policy)


def test_stock_extension_requires_hybrid_and_rejects_environment_overrides():
    with pytest.raises(ConfigLoadError):
        load_config(
            ROOT / "configs/base.yaml",
            ROOT / "configs/paper.yaml",
            ROOT / "configs/safety-envelope.yaml",
            {},
            stock_research_policy_path=ROOT / "configs/hybrid/stock-research.yaml",
        )
    with pytest.raises(ConfigLoadError):
        load_config(
            ROOT / "configs/base.yaml",
            ROOT / "configs/hybrid/paper.yaml",
            ROOT / "configs/hybrid/safety-envelope.yaml",
            {"LIVE_TRADING_ENABLED": "false"},
            hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
            stock_research_policy_path=ROOT / "configs/hybrid/stock-research.yaml",
        )
