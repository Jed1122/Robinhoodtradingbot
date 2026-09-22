from datetime import UTC, datetime

from trading_bot.runtime.shadow import ShadowCycleEvidence


def test_shadow_evidence_fields_bind_replay_identity() -> None:
    fields = set(ShadowCycleEvidence.__dataclass_fields__)
    assert {"cycle_id", "config_hash", "data_hash", "code_hash", "result"} <= fields
    assert datetime(2026, 7, 17, tzinfo=UTC).tzinfo is UTC
