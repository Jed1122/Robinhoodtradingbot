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
