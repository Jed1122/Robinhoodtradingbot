from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from trading_bot.config.models import PromotionSettings
from trading_bot.monitoring.promotion import (
    PromotionEvaluator,
    PromotionIdentity,
    PromotionObservation,
    PromotionStage,
)
from trading_bot.persistence import async_session_factory
from trading_bot.persistence.base import PersistenceDataError
from trading_bot.persistence.promotion import (
    PromotionObservationConflict,
    SqlPromotionEvidenceStore,
    SqlPromotionObservationStore,
)

NOW = datetime(2026, 7, 21, 12, tzinfo=UTC)


def identity() -> PromotionIdentity:
    return PromotionIdentity(
        "a" * 64,
        "b" * 64,
        "strategy-v1",
        "c" * 64,
        "d" * 64,
        "e" * 64,
    )


def observation(seed: str = "1") -> PromotionObservation:
    return PromotionObservation.create(
        stage=PromotionStage.SHADOW,
        cycle_id=seed * 64,
        identity=identity(),
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        data_hash="f" * 64,
        identity_verified=True,
        provider_evidence_verified=True,
        strategy_eligible=True,
        authenticated_reads=True,
        data_validated=True,
        outcomes_complete=True,
        reconciliation_clean=True,
        fixture_data=False,
        runtime_scope_valid=True,
        order_state_known=True,
    )


def promotion_settings(*, shadow_days: int = 1) -> PromotionSettings:
    return PromotionSettings(
        paper_min_eligible_unique_cycles=1,
        shadow_min_calendar_days=shadow_days,
        micro_order_review_interval=10,
        normal_min_combined_calendar_days=30,
        normal_min_valid_observations=100,
        clean_reconciliation_required=True,
        no_critical_security_findings_required=True,
        current_manual_acknowledgement_required=True,
        pause_on_unknown_order_state=True,
    )


@pytest.fixture
def migrated(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")


@pytest.mark.asyncio
async def test_store_is_restart_safe_and_idempotent(sqlite_engine, migrated: None) -> None:
    first_store = SqlPromotionObservationStore(async_session_factory(sqlite_engine))
    value = observation()

    assert await first_store.append(value)
    assert not await first_store.append(value)

    restarted = SqlPromotionObservationStore(async_session_factory(sqlite_engine))
    assert await restarted.list_for_identity(identity()) == (value,)


@pytest.mark.asyncio
async def test_evaluator_decision_is_durable_and_cannot_renew_without_new_evidence(
    sqlite_engine,
    migrated: None,
) -> None:
    factory = async_session_factory(sqlite_engine)
    store = SqlPromotionEvidenceStore(factory)
    decision = PromotionEvaluator(promotion_settings()).evaluate(
        stage=PromotionStage.SHADOW,
        identity=identity(),
        observations=(observation(),),
        now=NOW + timedelta(minutes=1),
    )
    first = await store.persist(
        decision,
        evaluated_at=NOW + timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=6),
    )
    repeated = await store.persist(
        decision,
        evaluated_at=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1, minutes=5),
    )

    assert first.eligible
    assert repeated == first
    assert await SqlPromotionEvidenceStore(factory).get(decision.evidence_hash) == first


@pytest.mark.asyncio
async def test_ineligible_promotion_decision_is_also_retained(
    sqlite_engine,
    migrated: None,
) -> None:
    store = SqlPromotionEvidenceStore(async_session_factory(sqlite_engine))
    decision = PromotionEvaluator(promotion_settings(shadow_days=2)).evaluate(
        stage=PromotionStage.SHADOW,
        identity=identity(),
        observations=(observation(),),
        now=NOW + timedelta(minutes=1),
    )

    attestation = await store.persist(
        decision,
        evaluated_at=NOW + timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=6),
    )

    assert not attestation.eligible
    assert attestation.evidence_hash == decision.evidence_hash


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    (
        "UPDATE promotion_evidence SET eligible = 0 WHERE evidence_hash = :evidence_hash",
        "DELETE FROM promotion_evidence WHERE evidence_hash = :evidence_hash",
        "INSERT OR REPLACE INTO promotion_evidence "
        "SELECT * FROM promotion_evidence WHERE evidence_hash = :evidence_hash",
    ),
)
async def test_database_rejects_mutating_durable_promotion_decision(
    sqlite_engine,
    migrated: None,
    statement: str,
) -> None:
    factory = async_session_factory(sqlite_engine)
    store = SqlPromotionEvidenceStore(factory)
    decision = PromotionEvaluator(promotion_settings()).evaluate(
        stage=PromotionStage.SHADOW,
        identity=identity(),
        observations=(observation(),),
        now=NOW + timedelta(minutes=1),
    )
    await store.persist(
        decision,
        evaluated_at=NOW + timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=6),
    )

    async with factory.begin() as session:
        with pytest.raises(IntegrityError, match="append-only"):
            await session.execute(
                text(statement),
                {"evidence_hash": decision.evidence_hash},
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed_identity",
    [
        replace(identity(), account_fingerprint="0" * 64),
        replace(identity(), provider_evidence_hash="1" * 64),
        replace(identity(), strategy_version="strategy-v2"),
        replace(identity(), strategy_eligibility_hash="2" * 64),
        replace(identity(), config_hash="3" * 64),
        replace(identity(), code_hash="4" * 64),
    ],
)
async def test_store_never_blends_observations_across_identity_drift(
    sqlite_engine,
    migrated: None,
    changed_identity: PromotionIdentity,
) -> None:
    store = SqlPromotionObservationStore(async_session_factory(sqlite_engine))
    await store.append(observation())

    assert await store.list_for_identity(changed_identity) == ()


@pytest.mark.asyncio
async def test_same_cycle_cannot_be_rewritten(sqlite_engine, migrated: None) -> None:
    store = SqlPromotionObservationStore(async_session_factory(sqlite_engine))
    value = observation()
    await store.append(value)
    conflicting = PromotionObservation.create(
        stage=value.stage,
        cycle_id=value.cycle_id,
        identity=value.identity,
        started_at=value.started_at,
        completed_at=value.completed_at,
        data_hash="0" * 64,
        identity_verified=value.identity_verified,
        provider_evidence_verified=value.provider_evidence_verified,
        strategy_eligible=value.strategy_eligible,
        authenticated_reads=value.authenticated_reads,
        data_validated=value.data_validated,
        outcomes_complete=value.outcomes_complete,
        reconciliation_clean=value.reconciliation_clean,
        fixture_data=value.fixture_data,
        runtime_scope_valid=value.runtime_scope_valid,
        order_state_known=value.order_state_known,
    )

    with pytest.raises(PromotionObservationConflict):
        await store.append(conflicting)


@pytest.mark.asyncio
async def test_database_rejects_eligibility_tampering(sqlite_engine, migrated: None) -> None:
    store = SqlPromotionObservationStore(async_session_factory(sqlite_engine))
    value = observation()
    await store.append(value)

    async with async_session_factory(sqlite_engine).begin() as session:
        with pytest.raises(IntegrityError, match="append-only"):
            await session.execute(
                text(
                    "UPDATE promotion_observations SET eligible = 0 "
                    "WHERE evidence_hash = :evidence_hash"
                ),
                {"evidence_hash": value.evidence_hash},
            )


@pytest.mark.asyncio
async def test_database_rejects_deleting_durable_observation(
    sqlite_engine,
    migrated: None,
) -> None:
    store = SqlPromotionObservationStore(async_session_factory(sqlite_engine))
    value = observation()
    await store.append(value)

    async with async_session_factory(sqlite_engine).begin() as session:
        with pytest.raises(IntegrityError, match="append-only"):
            await session.execute(
                text("DELETE FROM promotion_observations WHERE evidence_hash = :evidence_hash"),
                {"evidence_hash": value.evidence_hash},
            )


@pytest.mark.asyncio
async def test_database_rejects_insert_or_replace_of_durable_observation(
    sqlite_engine,
    migrated: None,
) -> None:
    store = SqlPromotionObservationStore(async_session_factory(sqlite_engine))
    value = observation()
    await store.append(value)

    async with async_session_factory(sqlite_engine).begin() as session:
        with pytest.raises(IntegrityError, match="append-only"):
            await session.execute(
                text(
                    "INSERT OR REPLACE INTO promotion_observations "
                    "SELECT * FROM promotion_observations "
                    "WHERE evidence_hash = :evidence_hash"
                ),
                {"evidence_hash": value.evidence_hash},
            )


@pytest.mark.asyncio
async def test_store_fails_closed_on_inserted_hash_inconsistent_row(
    sqlite_engine,
    migrated: None,
) -> None:
    async with async_session_factory(sqlite_engine).begin() as session:
        await session.execute(
            text(
                """
                INSERT INTO promotion_observations (
                    id, stage, cycle_id, account_fingerprint,
                    provider_evidence_hash, strategy_version,
                    strategy_eligibility_hash, config_hash, code_hash, data_hash,
                    started_at, completed_at, identity_verified,
                    provider_evidence_verified, strategy_eligible,
                    authenticated_reads, data_validated, outcomes_complete,
                    reconciliation_clean, fixture_data, runtime_scope_valid,
                    order_state_known, eligible, reason_codes_json, evidence_hash
                ) VALUES (
                    'externally-inserted', 'shadow', :cycle_id, :account_fingerprint,
                    :provider_evidence_hash, 'strategy-v1',
                    :strategy_eligibility_hash, :config_hash, :code_hash, :data_hash,
                    '2026-07-21T12:00:00.000000Z',
                    '2026-07-21T12:00:01.000000Z',
                    1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, '[]', :evidence_hash
                )
                """
            ),
            {
                "cycle_id": "9" * 64,
                "account_fingerprint": identity().account_fingerprint,
                "provider_evidence_hash": identity().provider_evidence_hash,
                "strategy_eligibility_hash": identity().strategy_eligibility_hash,
                "config_hash": identity().config_hash,
                "code_hash": identity().code_hash,
                "data_hash": "f" * 64,
                "evidence_hash": "0" * 64,
            },
        )

    store = SqlPromotionObservationStore(async_session_factory(sqlite_engine))
    with pytest.raises(PersistenceDataError, match="stored promotion observation"):
        await store.list_for_identity(identity())


def test_domain_rejects_hash_tampering() -> None:
    with pytest.raises(ValueError, match="hash"):
        replace(observation(), evidence_hash="0" * 64)
