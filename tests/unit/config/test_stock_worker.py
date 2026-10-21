import importlib
from dataclasses import replace
from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.config.loader import (
    ConfigLoadError,
    enforce_safety_envelope,
    restore_loaded_config,
)

ROOT = Path(__file__).resolve().parents[3]


def load(worker=None):
    return load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=ROOT / "configs/hybrid/stock-research.yaml",
        **({"stock_worker_policy_path": worker} if worker else {}),
    )


def test_worker_extension_preserves_previous_stock_canonical_identity(tmp_path):
    before = load()
    policy = tmp_path / "worker.yaml"
    policy.write_text("policy_id: stock-worker-v1\n")
    loaded = load(policy)
    module = importlib.import_module("trading_bot.config.stock_research")
    assert type(loaded.config) is module.StockWorkerAppConfig
    assert loaded.config.stock_worker.max_run_seconds == 450
    assert loaded.config.stock_worker.live_enabled is False
    assert loaded.config.stock_research == before.config.stock_research
    assert restore_loaded_config(loaded.canonical_json, loaded.config_hash) == loaded
    assert restore_loaded_config(before.canonical_json, before.config_hash) == before
    assert load() == before
    assert "stock_worker" not in before.config.model_dump()


@pytest.mark.parametrize(
    "body",
    [
        "live_enabled: true\n",
        "enrichment_refresh_minutes: 0\n",
        "max_run_seconds: 451\n",
        "max_archive_bytes: 1\n",
        "max_archive_files: 0\n",
        "max_archive_files: true\n",
        "auth_store: /tmp/credential\n",
    ],
)
def test_worker_policy_rejects_unsafe_or_unknown_values(tmp_path, body):
    policy = tmp_path / "worker.yaml"
    policy.write_text(body)
    with pytest.raises(ConfigLoadError):
        load(policy)


def test_worker_requires_stock_extension(tmp_path):
    policy = tmp_path / "worker.yaml"
    policy.write_text("policy_id: stock-worker-v1\n")
    with pytest.raises(ConfigLoadError):
        load_config(
            ROOT / "configs/base.yaml",
            ROOT / "configs/hybrid/paper.yaml",
            ROOT / "configs/hybrid/safety-envelope.yaml",
            {},
            hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
            stock_worker_policy_path=policy,
        )


def test_worker_envelope_mismatch_and_unpaired_canonical_graph_fail(tmp_path):
    policy = tmp_path / "worker.yaml"
    policy.write_text("policy_id: stock-worker-v1\n")
    loaded = load(policy)
    changed = loaded.config.model_copy(
        update={
            "stock_worker": loaded.config.stock_worker.model_copy(
                update={"max_archive_files": 1000}
            )
        }
    )
    with pytest.raises(ConfigLoadError):
        enforce_safety_envelope(changed, loaded.safety_envelope)
    corrupted = replace(
        loaded,
        canonical_json=loaded.canonical_json.replace(b'"stock_worker":', b'"unpaired_worker":', 1),
    )
    with pytest.raises(ConfigLoadError):
        restore_loaded_config(corrupted.canonical_json, corrupted.config_hash)
