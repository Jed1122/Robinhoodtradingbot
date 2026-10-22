import importlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.config.loader import (
    ConfigLoadError,
    enforce_safety_envelope,
    restore_loaded_config,
)

ROOT = Path(__file__).resolve().parents[3]


def load(worker=None, research=None):
    return load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=research or ROOT / "configs/hybrid/stock-research.yaml",
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


@pytest.mark.parametrize(
    "body",
    [
        *(f"shortlist_count: {count}\n" for count in range(13, 21)),
        "shortlist_count: 10\nmax_calls_per_cycle: 24\n",
        "maximum_source_age_minutes: 59\n",
        "maximum_source_age_minutes: 60\n",
    ],
)
def test_worker_rejects_infeasible_enrichment_without_restricting_scanner(tmp_path, body):
    worker = tmp_path / "worker.yaml"
    worker.write_text("policy_id: stock-worker-v1\n")
    research = tmp_path / "research.yaml"
    research.write_text(body)
    scanner = load(research=research)
    assert "stock_worker" not in scanner.config.model_dump()
    with pytest.raises(ConfigLoadError):
        load(worker, research)


@pytest.mark.parametrize("count", range(1, 21))
def test_worker_capacity_matches_actual_complete_enrichment_planner(tmp_path, count):
    from trading_bot.research.stock_requests import enrichment_requests

    worker = tmp_path / "worker.yaml"
    worker.write_text("policy_id: stock-worker-v1\n")
    research = tmp_path / "research.yaml"
    research.write_text(
        f"shortlist_count: {count}\nmarket_cap_boundaries_usd: [2000000000]\n"
    )
    scanner = load(research=research)
    symbols = tuple(f"ALFA{index}" for index in range(count))
    try:
        requests = enrichment_requests(
            symbols=symbols,
            as_of=datetime(2026, 10, 22, tzinfo=UTC),
            policy=scanner.config.stock_research,
        )
    except ValueError:
        with pytest.raises(ConfigLoadError):
            load(worker, research)
    else:
        research.write_text(research.read_text() + f"max_calls_per_cycle: {len(requests)}\n")
        accepted = load(worker, research)
        assert accepted.config.stock_research.max_calls_per_cycle == len(requests)
        assert restore_loaded_config(accepted.canonical_json, accepted.config_hash) == accepted
        research.write_text(
            research.read_text().replace(
                f"max_calls_per_cycle: {len(requests)}", f"max_calls_per_cycle: {len(requests) - 1}"
            )
        )
        with pytest.raises(ConfigLoadError):
            load(worker, research)


def test_worker_source_age_leaves_time_after_next_admission(tmp_path):
    worker = tmp_path / "worker.yaml"
    worker.write_text("policy_id: stock-worker-v1\n")
    research = tmp_path / "research.yaml"
    research.write_text("scan_minutes: 60\nmaximum_source_age_minutes: 61\n")
    accepted = load(worker, research)
    assert accepted.config.stock_research.maximum_source_age_minutes == 61


@pytest.mark.parametrize(
    "field,value", [("max_calls_per_cycle", 24), ("maximum_source_age_minutes", 60)]
)
@pytest.mark.parametrize("side", ["config", "safety_envelope"])
def test_both_worker_graph_sides_require_constructible_enrichment(tmp_path, field, value, side):
    from pydantic import ValidationError

    worker = tmp_path / "worker.yaml"
    worker.write_text("policy_id: stock-worker-v1\n")
    original = getattr(load(worker), side)
    invalid = original.model_dump()
    invalid["stock_research"][field] = value
    with pytest.raises(ValidationError, match="stock worker"):
        type(original).model_validate(invalid)
