from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.runtime.paper_promotion_runtime import (
    PaperPromotionNotReady,
    run_paper_promotion_once,
)


def test_paper_runtime_reports_all_missing_trusted_composition_inputs(tmp_path: Path) -> None:
    root = Path(__file__).parents[3]
    loaded = load_config(
        root / "configs/base.yaml",
        root / "configs/paper.yaml",
        root / "configs/safety-envelope.yaml",
        {},
    )

    with pytest.raises(PaperPromotionNotReady) as raised:
        run_paper_promotion_once(
            loaded=loaded,
            repository_root=root,
            ledger=tmp_path / "evidence" / "ledger.db",
            lock_directory=tmp_path / "locks",
        )

    assert raised.value.blockers == (
        "accepted_research_evidence_unavailable",
        "account_identity_unavailable",
        "provider_evidence_unavailable",
        "strategy_cycle_composition_unavailable",
        "validated_market_data_unavailable",
        "clean_reconciliation_unavailable",
        "runtime_scope_attestation_unavailable",
    )
    assert not (tmp_path / "evidence").exists()
    assert not (tmp_path / "locks").exists()


def test_runtime_evaluates_and_persists_only_inside_owner_snapshot(tmp_path, monkeypatch) -> None:
    from contextlib import asynccontextmanager
    from dataclasses import replace
    from types import SimpleNamespace

    from tests.integration.runtime.test_paper import promotion_context
    from trading_bot.domain import PromotionAttestation
    from trading_bot.runtime import paper_promotion_runtime as runtime

    root = Path(__file__).parents[3]
    loaded = load_config(
        root / "configs/base.yaml",
        root / "configs/paper.yaml",
        root / "configs/safety-envelope.yaml",
        {},
    )
    context = promotion_context()
    context = replace(context, identity=replace(context.identity, config_hash=loaded.config_hash))
    active = False
    calls = []

    class Application:
        def __init__(self, **kwargs):
            pass

        async def run_cycle(self, request):
            calls.append("cycle")
            return SimpleNamespace(
                observation=SimpleNamespace(
                    evidence_hash="e" * 64, eligible=False, reason_codes=("fixture",)
                ),
                executed=False,
            )

        @asynccontextmanager
        async def promotion_observations(self):
            nonlocal active
            active = True
            calls.append("snapshot")
            try:
                yield ()
            finally:
                active = False

    original_evaluator = runtime.PromotionEvaluator

    class Evaluator:
        def __init__(self, settings):
            self.delegate = original_evaluator(settings)

        def evaluate(self, **kwargs):
            assert active
            calls.append("evaluate")
            return self.delegate.evaluate(**kwargs)

    class EvidenceStore:
        def __init__(self, factory):
            pass

        async def persist(self, decision, *, evaluated_at, expires_at):
            assert active and not decision.eligible
            calls.append("persist")
            return PromotionAttestation("paper", False, "f" * 64, evaluated_at, expires_at)

    class Engine:
        async def dispose(self):
            assert not active
            calls.append("dispose")

    monkeypatch.setattr(runtime, "migrate_sqlite_ledger", lambda *args, **kwargs: "fixture")
    monkeypatch.setattr(runtime, "create_engine", lambda *args: Engine())
    monkeypatch.setattr(runtime, "async_session_factory", lambda *args: None)
    monkeypatch.setattr(runtime, "SqlPromotionObservationStore", lambda *args: None)
    monkeypatch.setattr(runtime, "PaperCycleMutex", lambda *args: None)
    monkeypatch.setattr(runtime, "PaperPromotionApplication", Application)
    monkeypatch.setattr(runtime, "PromotionEvaluator", Evaluator)
    monkeypatch.setattr(runtime, "SqlPromotionEvidenceStore", EvidenceStore)
    report = run_paper_promotion_once(
        loaded=loaded,
        repository_root=root,
        ledger=tmp_path / "ledger.db",
        lock_directory=tmp_path / "locks",
        composition=SimpleNamespace(context=context, paper=None, request=None),
    )
    assert not report["live_enabled"] and not report["promotion_eligible"]
    assert calls == ["cycle", "snapshot", "evaluate", "persist", "dispose"]
