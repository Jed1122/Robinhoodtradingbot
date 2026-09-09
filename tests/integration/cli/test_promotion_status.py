from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from trading_bot.cli.main import app
from trading_bot.monitoring.promotion import (
    PromotionIdentity,
    PromotionObservation,
    PromotionStage,
)
from trading_bot.persistence.migrations import migrate_sqlite_ledger

ROOT = Path(__file__).parents[3]
NOW = datetime(2025, 1, 10, 12, tzinfo=UTC)


def _identity(seed: str, strategy_version: str) -> PromotionIdentity:
    return PromotionIdentity(
        account_fingerprint=seed * 64,
        provider_evidence_hash=chr(ord(seed) + 1) * 64,
        strategy_version=strategy_version,
        strategy_eligibility_hash=chr(ord(seed) + 2) * 64,
        config_hash=chr(ord(seed) + 3) * 64,
        code_hash=chr(ord(seed) + 4) * 64,
    )


def _observation(
    *,
    identity: PromotionIdentity,
    stage: PromotionStage,
    cycle_seed: str,
    completed_at: datetime,
    eligible: bool,
) -> PromotionObservation:
    return PromotionObservation.create(
        stage=stage,
        cycle_id=cycle_seed * 64,
        identity=identity,
        started_at=completed_at - timedelta(seconds=1),
        completed_at=completed_at,
        data_hash="f" * 64,
        identity_verified=True,
        provider_evidence_verified=True,
        strategy_eligible=eligible,
        authenticated_reads=True,
        data_validated=True,
        outcomes_complete=True,
        reconciliation_clean=True,
        fixture_data=False,
        runtime_scope_valid=True,
        order_state_known=True,
    )


def _timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _insert_observation(connection: sqlite3.Connection, value: PromotionObservation) -> None:
    connection.execute(
        """
        INSERT INTO promotion_observations (
            id, stage, cycle_id, account_fingerprint, provider_evidence_hash,
            strategy_version, strategy_eligibility_hash, config_hash, code_hash,
            data_hash, started_at, completed_at, identity_verified,
            provider_evidence_verified, strategy_eligible, authenticated_reads,
            data_validated, outcomes_complete, reconciliation_clean, fixture_data,
            runtime_scope_valid, order_state_known, eligible, reason_codes_json,
            evidence_hash
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            value.evidence_hash[:32],
            value.stage.value,
            value.cycle_id,
            value.identity.account_fingerprint,
            value.identity.provider_evidence_hash,
            value.identity.strategy_version,
            value.identity.strategy_eligibility_hash,
            value.identity.config_hash,
            value.identity.code_hash,
            value.data_hash,
            _timestamp(value.started_at),
            _timestamp(value.completed_at),
            int(value.identity_verified),
            int(value.provider_evidence_verified),
            int(value.strategy_eligible),
            int(value.authenticated_reads),
            int(value.data_validated),
            int(value.outcomes_complete),
            int(value.reconciliation_clean),
            int(value.fixture_data),
            int(value.runtime_scope_valid),
            int(value.order_state_known),
            int(value.eligible),
            json.dumps(value.reason_codes, separators=(",", ":")),
            value.evidence_hash,
        ),
    )


def _seed_ledger(tmp_path: Path) -> tuple[Path, PromotionIdentity, PromotionIdentity]:
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    ledger = evidence / "ledger.db"
    migrate_sqlite_ledger(
        ledger,
        alembic_ini=ROOT / "alembic.ini",
        migrations_dir=ROOT / "migrations",
    )
    first = _identity("1", "private-strategy-a")
    second = _identity("5", "private-strategy-b")
    with closing(sqlite3.connect(ledger)) as connection:
        _insert_observation(
            connection,
            _observation(
                identity=first,
                stage=PromotionStage.PAPER,
                cycle_seed="a",
                completed_at=NOW - timedelta(days=2),
                eligible=True,
            ),
        )
        _insert_observation(
            connection,
            _observation(
                identity=first,
                stage=PromotionStage.SHADOW,
                cycle_seed="b",
                completed_at=NOW - timedelta(days=1),
                eligible=False,
            ),
        )
        _insert_observation(
            connection,
            _observation(
                identity=second,
                stage=PromotionStage.PAPER,
                cycle_seed="c",
                completed_at=NOW - timedelta(days=1),
                eligible=True,
            ),
        )
        connection.execute(
            """
            INSERT INTO research_acceptance_evidence (
                id, strategy_version, eligible, config_hash, code_hash,
                research_manifest_hash, report_hash, evidence_hash,
                reason_codes_json, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "research-rejected",
                "private-strategy-a",
                0,
                "1" * 64,
                "2" * 64,
                "3" * 64,
                "4" * 64,
                "5" * 64,
                '["assumptions_unvalidated"]',
                _timestamp(NOW - timedelta(days=1)),
            ),
        )
        connection.execute(
            """
            INSERT INTO promotion_evidence (
                id, stage, eligible, evidence_hash, reason_codes_json,
                evaluated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "promotion-rejected",
                "shadow",
                0,
                "9" * 64,
                '["insufficient_shadow_calendar_days"]',
                _timestamp(NOW - timedelta(hours=1)),
                _timestamp(NOW + timedelta(hours=1)),
            ),
        )
        connection.commit()
    ledger.chmod(0o600)
    return ledger, first, second


def test_promotion_status_groups_progress_by_identity_without_mutating_ledger(
    tmp_path: Path,
) -> None:
    ledger, first, second = _seed_ledger(tmp_path)
    digest_before = hashlib.sha256(ledger.read_bytes()).hexdigest()

    result = CliRunner().invoke(
        app,
        [
            "promotion-status",
            "--config",
            "configs/micro_live.yaml",
            "--ledger",
            str(ledger),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "promotion_preview_only"
    assert payload["live_activation_permitted"] is False
    assert payload["ledger_integrity"] == "ok"
    assert payload["inventory"] == {
        "execution_leases": 0,
        "live_authorizations": 0,
        "live_leases": 0,
        "promotion_evidence": {"eligible": 0, "ineligible": 1, "total": 1},
        "research_acceptance_evidence": {"eligible": 0, "ineligible": 1, "total": 1},
        "submission_attempts": 0,
    }
    assert len(payload["identity_series"]) == 2
    series_with_rejected_shadow = next(
        series
        for series in payload["identity_series"]
        if series["observations"]["shadow"]["total"] == 1
    )
    assert series_with_rejected_shadow["observations"]["paper"] == {
        "eligible": 1,
        "ineligible": 0,
        "total": 1,
    }
    assert series_with_rejected_shadow["observations"]["shadow"] == {
        "eligible": 0,
        "ineligible": 1,
        "total": 1,
    }
    assert series_with_rejected_shadow["promotion_previews"]["micro_live"]["eligible"] is False
    assert (
        "insufficient_paper_cycles"
        in series_with_rejected_shadow["promotion_previews"]["micro_live"]["reasons"]
    )
    assert (
        "latest_observation_ineligible"
        in series_with_rejected_shadow["promotion_previews"]["micro_live"]["reasons"]
    )
    assert first.account_fingerprint not in result.stdout
    assert second.account_fingerprint not in result.stdout
    assert first.strategy_version not in result.stdout
    assert second.strategy_version not in result.stdout
    assert hashlib.sha256(ledger.read_bytes()).hexdigest() == digest_before
    assert not Path(f"{ledger}-wal").exists()
    assert not Path(f"{ledger}-shm").exists()


def test_promotion_status_missing_ledger_fails_with_stable_nonsecret_output(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "secret-ledger-name.db"

    result = CliRunner().invoke(
        app,
        ["promotion-status", "--ledger", str(missing)],
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr == "promotion_status_unavailable\n"
    assert str(missing) not in result.output


def test_promotion_status_rejects_an_uncheckpointed_wal_snapshot(tmp_path: Path) -> None:
    ledger, _, _ = _seed_ledger(tmp_path)
    writer = sqlite3.connect(ledger)
    try:
        writer.execute(
            """
            INSERT INTO promotion_evidence (
                id, stage, eligible, evidence_hash, reason_codes_json,
                evaluated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "uncheckpointed-promotion",
                "shadow",
                0,
                "8" * 64,
                '["insufficient_shadow_calendar_days"]',
                _timestamp(NOW - timedelta(minutes=1)),
                _timestamp(NOW + timedelta(minutes=1)),
            ),
        )
        writer.commit()
        assert Path(f"{ledger}-wal").is_file()

        result = CliRunner().invoke(
            app,
            ["promotion-status", "--ledger", str(ledger)],
        )

        assert result.exit_code == 2
        assert result.stderr == "promotion_status_unavailable\n"
    finally:
        writer.close()
