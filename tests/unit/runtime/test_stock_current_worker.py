"""Short source-bound profile/selection tests, without SDK/provider/account calls."""

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.research.test_stock_current_screen import PROFILE, current_sample
from tests.unit.research.test_stock_screen import NOW
from trading_bot.config import load_config
from trading_bot.config.loader import restore_loaded_config
from trading_bot.runtime import stock_research_worker as worker

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def current_config(tmp_path):
    path = tmp_path / "current.yaml"
    path.write_text(f"policy_id: {PROFILE}\n")
    loaded = load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=ROOT / "configs/hybrid/stock-research.yaml",
        stock_worker_policy_path=path,
    )
    assert restore_loaded_config(loaded.canonical_json, loaded.config_hash) == loaded
    return loaded


def test_worker_identity_selects_new_plan_and_config_hash(current_config):
    policy = current_config.config
    requests = worker._requests("discovery", policy, NOW, ())
    assert len(requests) == 17
    assert requests[1].arguments["columns"][-1]["display_name"] == "Quotation currency"
    assert (
        len(worker._requests("enrichment", policy, NOW, tuple(f"NAME{i}" for i in range(10)))) == 27
    )
    assert policy.stock_research.max_calls_per_cycle == 32
    assert policy.stock_research.max_daily_calls == 512


def test_screen_and_restart_recompute_same_profile(current_config, monkeypatch):
    policy = current_config.config.model_copy(update={"stock_research": current_sample()[0]})
    _, observations = current_sample()
    claim = SimpleNamespace(
        claim_id="a" * 64,
        config_hash="b" * 64,
        code_hash="c" * 64,
        plan_sha256="d" * 64,
        claimed_at=NOW,
    )
    manifest_sha = "e" * 64
    report = worker._screen_body(
        claim=claim,
        observations=tuple(observations),
        manifest_sha256=manifest_sha,
        policy=policy,
        at=NOW,
    )
    assert report["worker_profile_id"] == report["screen"]["worker_profile_id"] == PROFILE
    head = SimpleNamespace(
        claim_id=claim.claim_id,
        phase="discovery",
        manifest_sha256=manifest_sha,
        report_sha256="f" * 64,
        recorded_at=NOW,
    )
    state = SimpleNamespace(discovery_head=head, enrichment_head=None, claims=(claim,))
    monkeypatch.setattr(worker, "_read", lambda *a: deepcopy(report))
    seen = []

    def verified(**kwargs):
        seen.append(kwargs["plan"])
        return {"status": "complete", "completed_at": NOW.isoformat()}, tuple(observations)

    monkeypatch.setattr(worker, "_verified_capture", verified)
    restored, enrichment = worker._cached(
        state=state,
        archive=SimpleNamespace(directory_fd=-1),
        root=Path("/unused-fictional"),
        policy=policy,
        now=NOW,
    )
    assert restored == report and enrichment is None
    assert seen == [worker._requests("discovery", policy, NOW, ())]
    report["worker_profile_id"] = "stock-worker-v1"
    with pytest.raises(worker.StockWorkerError):
        worker._cached(
            state=state,
            archive=SimpleNamespace(directory_fd=-1),
            root=Path("/unused-fictional"),
            policy=policy,
            now=NOW,
        )


def selection_state():
    old = NOW - timedelta(hours=1)
    claim = SimpleNamespace(
        claim_id="a", claimed_at=old, phase="discovery", config_hash="config", code_hash="code"
    )
    head = SimpleNamespace(claim_id="a", record_sha256="c" * 64)
    return SimpleNamespace(discovery_head=head, claims=(claim,), results=(), enrichment_head=None)


def watch(**changes):
    values = dict(
        held_symbols=("HELD",),
        watch_symbols=("WATCH",),
        as_of=NOW,
        expires_at=NOW + timedelta(hours=1),
        source_sha256="d" * 64,
    )
    return worker.StockResearchWatch(**(values | changes))


def test_held_watch_names_precede_new_ranked_names_even_outside_universe(current_config):
    discovery = {"screen": {"opportunities": [{"symbol": "NEW"}, {"symbol": "HELD"}]}}
    phase, symbols, source = worker._select(
        state=selection_state(),
        discovery=discovery,
        enrichment=None,
        policy=current_config.config,
        now=NOW,
        watch=watch(),
    )
    assert phase == "enrichment" and symbols == ("HELD", "WATCH", "NEW")
    assert source == "c" * 64


def test_watch_capacity_cannot_silently_drop_owned_names(current_config):
    manifest = watch(held_symbols=tuple(f"HELD{i}" for i in range(11)), watch_symbols=())
    with pytest.raises(worker.StockWorkerError, match="watch_coverage_capacity_exceeded"):
        worker._select(
            state=selection_state(),
            discovery={"screen": {"opportunities": []}},
            enrichment=None,
            policy=current_config.config,
            now=NOW,
            watch=manifest,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"held_symbols": ["HELD"]},
        {"held_symbols": ("HELD", "HELD")},
        {"held_symbols": ("bad",)},
        {"as_of": NOW.replace(tzinfo=None)},
        {"source_sha256": "bad"},
        {"expires_at": NOW},
    ],
)
def test_watch_manifest_rejects_malformed_mutable_or_unbound_inputs(changes):
    with pytest.raises(ValueError):
        watch(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"as_of": NOW + timedelta(minutes=1)},
        {"expires_at": NOW - timedelta(minutes=1), "as_of": NOW - timedelta(hours=1)},
        {"as_of": NOW - timedelta(hours=3)},
    ],
)
def test_future_stale_expired_watch_blocks_before_selection(current_config, changes):
    with pytest.raises(worker.StockWorkerError, match="watch_unavailable"):
        worker._select(
            state=selection_state(),
            discovery=None,
            enrichment=None,
            policy=current_config.config,
            now=NOW,
            watch=watch(**changes),
        )


def test_bypassed_watch_mutation_is_revalidated(current_config):
    manifest = watch()
    object.__setattr__(manifest, "source_sha256", "wrong")
    with pytest.raises(ValueError):
        worker._select(
            state=selection_state(),
            discovery=None,
            enrichment=None,
            policy=current_config.config,
            now=NOW,
            watch=manifest,
        )


def test_watch_selection_still_requires_fresh_discovery_head(current_config):
    state = selection_state()
    state.claims[0].claimed_at = NOW - timedelta(hours=3)
    assert worker._select(
        state=state,
        discovery={"screen": {"opportunities": []}},
        enrichment=None,
        policy=current_config.config,
        now=NOW,
        watch=watch(),
    ) == ("discovery", (), None)


def test_current_config_has_new_only_whole_cycle_capacity_guard(current_config):
    from pydantic import ValidationError

    from trading_bot.config.stock_research import StockWorkerAppConfig

    body = current_config.config.model_dump()
    body["stock_research"]["shortlist_count"] = 12
    with pytest.raises(ValidationError, match="enrichment call budget"):
        StockWorkerAppConfig.model_validate(body)
    body["stock_worker"]["policy_id"] = "stock-worker-v1"
    assert StockWorkerAppConfig.model_validate(body).stock_research.shortlist_count == 12


def test_watch_does_not_override_legacy_or_accept_naive_selection_clock(current_config):
    from trading_bot.config.stock_research import StockWorkerAppConfig

    body = current_config.config.model_dump()
    body["stock_worker"]["policy_id"] = "stock-worker-v1"
    legacy = StockWorkerAppConfig.model_validate(body)
    with pytest.raises(worker.StockWorkerError, match="watch_profile_required"):
        worker._select(
            state=selection_state(),
            discovery=None,
            enrichment=None,
            policy=legacy,
            now=NOW,
            watch=watch(),
        )
    with pytest.raises(ValueError):
        worker._select(
            state=selection_state(),
            discovery=None,
            enrichment=None,
            policy=current_config.config,
            now=NOW.replace(tzinfo=None),
            watch=watch(),
        )


def test_paired_examples_preserve_universe_and_fit_existing_daily_quota():
    loaded = load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=ROOT
        / "configs/hybrid/stock-research-current-provider.example.yaml",
        stock_worker_policy_path=ROOT / "configs/hybrid/stock-worker-current-provider.example.yaml",
    )
    assert restore_loaded_config(loaded.canonical_json, loaded.config_hash) == loaded
    policy = loaded.config
    assert policy.stock_worker.policy_id == PROFILE
    assert policy.stock_worker.enrichment_refresh_minutes == 60
    assert policy.stock_research.shortlist_count == 9
    assert len(policy.stock_research.market_cap_boundaries_usd) == 16
    discovery = worker._requests("discovery", policy, NOW, ())
    enrichment = worker._requests("enrichment", policy, NOW, tuple(f"NAME{i}" for i in range(9)))
    assert len(discovery) == 17 and len(enrichment) == 25
    assert (
        (len(discovery) + len(enrichment)) * 12
        == 504
        <= policy.stock_research.max_daily_calls
        == 512
    )
    assert policy.stock_research.live_enabled is policy.stock_worker.live_enabled is False


def rotation_state(history):
    """Minimal verified-state shape; the selector does not authenticate ledger history."""
    state = selection_state()
    claims, results = [], []
    for index, (phase, status, config, code) in enumerate(history):
        claim_id = f"history-{index}"
        claims.append(
            SimpleNamespace(claim_id=claim_id, phase=phase, config_hash=config, code_hash=code)
        )
        results.append(SimpleNamespace(claim_id=claim_id, status=status))
    state.claims = (*claims, *state.claims)
    state.results = tuple(results)
    return state


def rotation_selection(current_config, history, *, held=8, candidates=("A", "B", "C")):
    policy = current_config.config.model_copy(
        update={
            "stock_research": current_config.config.stock_research.model_copy(
                update={"shortlist_count": 9}
            )
        }
    )
    return worker._select(
        state=rotation_state(history),
        discovery={"screen": {"opportunities": [{"symbol": name} for name in candidates]}},
        enrichment=None,
        policy=policy,
        now=NOW,
        watch=watch(held_symbols=tuple(f"HELD{i}" for i in range(held)), watch_symbols=()),
    )


@pytest.mark.parametrize("completed,want", [(0, "A"), (1, "B"), (2, "C"), (3, "A")])
def test_current_held_priority_leaves_fair_round_robin_research_slot(
    current_config, completed, want
):
    history = [("enrichment", "succeeded", "config", "code")] * completed
    phase, symbols, source = rotation_selection(current_config, history)
    assert phase == "enrichment" and source == "c" * 64
    assert symbols == (*tuple(f"HELD{i}" for i in range(8)), want)


@pytest.mark.parametrize("status", ["failed", "blocked", "cancelled"])
def test_unsuccessful_enrichment_does_not_advance_research_rotation(current_config, status):
    history = [
        ("enrichment", "succeeded", "config", "code"),
        ("enrichment", status, "config", "code"),
    ]
    assert rotation_selection(current_config, history)[1][-1] == "B"


def test_rotation_joins_claim_phase_and_excludes_other_config_code_history(current_config):
    history = [
        ("discovery", "succeeded", "config", "code"),
        ("enrichment", "succeeded", "older-config", "code"),
        ("enrichment", "succeeded", "config", "older-code"),
        ("enrichment", "succeeded", "config", "code"),
    ]
    assert rotation_selection(current_config, history)[1][-1] == "B"


@pytest.mark.parametrize("held,want", [(6, ("A", "B", "C")), (9, ())])
def test_rotation_keeps_full_and_zero_capacity_cohorts_in_original_order(
    current_config, held, want
):
    phase, symbols, _ = rotation_selection(
        current_config, [("enrichment", "succeeded", "config", "code")], held=held
    )
    assert phase == "enrichment"
    assert symbols == (*tuple(f"HELD{i}" for i in range(held)), *want)


def test_rotating_new_names_preserves_watch_priority_and_removes_priority_duplicates(
    current_config,
):
    policy = current_config.config.model_copy(
        update={
            "stock_research": current_config.config.stock_research.model_copy(
                update={"shortlist_count": 3}
            )
        }
    )
    _, symbols, _ = worker._select(
        state=rotation_state([("enrichment", "succeeded", "config", "code")]),
        discovery={"screen": {"opportunities": [{"symbol": s} for s in ("HELD", "A", "B", "C")]}},
        enrichment=None,
        policy=policy,
        now=NOW,
        watch=watch(),
    )
    assert symbols == ("HELD", "WATCH", "B")


def test_legacy_selector_order_is_unchanged_by_completed_enrichment(current_config):
    from trading_bot.config.stock_research import StockWorkerAppConfig

    body = current_config.config.model_dump()
    body["stock_worker"]["policy_id"] = "stock-worker-v1"
    body["stock_research"]["shortlist_count"] = 1
    policy = StockWorkerAppConfig.model_validate(body)
    _, symbols, _ = worker._select(
        state=rotation_state([("enrichment", "succeeded", "config", "code")]),
        discovery={"screen": {"opportunities": [{"symbol": s} for s in ("A", "B", "C")]}},
        enrichment=None,
        policy=policy,
        now=NOW,
    )
    assert symbols == ("A", "B", "C")
