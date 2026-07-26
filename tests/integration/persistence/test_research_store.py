import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from trading_bot.domain import CodeHash, ConfigHash, StrategyEligibilityAttestation
from trading_bot.market_data import content_hash
from trading_bot.persistence import async_session_factory
from trading_bot.persistence.base import PersistenceDataError
from trading_bot.persistence.models import ResearchAcceptanceEvidenceRow
from trading_bot.persistence.research import SqlResearchEvidenceStore
from trading_bot.research.validation import ResearchAssessment

NOW = datetime(2026, 7, 26, 12, tzinfo=UTC)


@pytest.fixture
def migrated(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")


def attestation(*, eligible: bool, strategy_version: str) -> StrategyEligibilityAttestation:
    return StrategyEligibilityAttestation(
        eligible=eligible,
        strategy_version=strategy_version,
        config_hash=ConfigHash("a" * 64),
        code_hash=CodeHash("b" * 64),
        research_manifest_hash="c" * 64,
        report_hash="d" * 64,
        observed_at=NOW,
    )


@pytest.mark.asyncio
async def test_eligible_evidence_round_trips_by_pinned_hash(
    sqlite_engine,
    migrated: None,
) -> None:
    store = SqlResearchEvidenceStore(async_session_factory(sqlite_engine))
    accepted = attestation(eligible=True, strategy_version="accepted-v1")
    assessment = ResearchAssessment(True, True, ())
    evidence_hash = content_hash({"assessment": assessment, "attestation": accepted})

    await store.append(accepted, assessment)

    persisted = await store.get_eligible(
        evidence_hash,
        strategy_version="accepted-v1",
        config_hash=ConfigHash("a" * 64),
        code_hash=CodeHash("b" * 64),
        as_of=NOW,
    )
    assert persisted is not None
    assert persisted.attestation == accepted
    assert persisted.evidence_hash == evidence_hash


@pytest.mark.asyncio
async def test_missing_or_rejected_evidence_never_loads_as_eligible(
    sqlite_engine,
    migrated: None,
) -> None:
    store = SqlResearchEvidenceStore(async_session_factory(sqlite_engine))
    rejected = attestation(eligible=False, strategy_version="rejected-v1")
    assessment = ResearchAssessment(
        False,
        False,
        ("nonpositive_after_cost_oos_expectancy",),
    )
    rejected_hash = content_hash({"assessment": assessment, "attestation": rejected})
    await store.append(rejected, assessment)

    arguments = {
        "strategy_version": "rejected-v1",
        "config_hash": ConfigHash("a" * 64),
        "code_hash": CodeHash("b" * 64),
        "as_of": NOW,
    }
    assert await store.get_eligible(rejected_hash, **arguments) is None
    assert await store.get_eligible("f" * 64, **arguments) is None


@pytest.mark.asyncio
async def test_strategy_config_or_code_drift_fails_closed(
    sqlite_engine,
    migrated: None,
) -> None:
    store = SqlResearchEvidenceStore(async_session_factory(sqlite_engine))
    accepted = attestation(eligible=True, strategy_version="accepted-v1")
    assessment = ResearchAssessment(True, True, ())
    evidence_hash = content_hash({"assessment": assessment, "attestation": accepted})
    await store.append(accepted, assessment)

    mismatches = (
        ("accepted-v2", ConfigHash("a" * 64), CodeHash("b" * 64)),
        ("accepted-v1", ConfigHash("e" * 64), CodeHash("b" * 64)),
        ("accepted-v1", ConfigHash("a" * 64), CodeHash("e" * 64)),
    )
    for strategy_version, config_hash, code_hash in mismatches:
        with pytest.raises(PersistenceDataError, match="does not match"):
            await store.get_eligible(
                evidence_hash,
                strategy_version=strategy_version,
                config_hash=config_hash,
                code_hash=code_hash,
                as_of=NOW,
            )


@pytest.mark.asyncio
async def test_rejects_tampered_eligible_evidence_hash(
    sqlite_engine,
    migrated: None,
) -> None:
    factory = async_session_factory(sqlite_engine)
    async with factory.begin() as session:
        session.add(
            ResearchAcceptanceEvidenceRow(
                id="tampered",
                strategy_version="accepted-v1",
                eligible=True,
                config_hash="a" * 64,
                code_hash="b" * 64,
                research_manifest_hash="c" * 64,
                report_hash="d" * 64,
                evidence_hash="e" * 64,
                reason_codes_json="[]",
                observed_at=NOW,
            )
        )

    store = SqlResearchEvidenceStore(factory)
    with pytest.raises(PersistenceDataError, match="evidence hash"):
        await store.get_eligible(
            "e" * 64,
            strategy_version="accepted-v1",
            config_hash=ConfigHash("a" * 64),
            code_hash=CodeHash("b" * 64),
            as_of=NOW,
        )


@pytest.mark.asyncio
async def test_duplicate_evidence_hash_is_rejected(
    sqlite_engine,
    migrated: None,
) -> None:
    store = SqlResearchEvidenceStore(async_session_factory(sqlite_engine))
    accepted = attestation(eligible=True, strategy_version="accepted-v1")
    assessment = ResearchAssessment(True, True, ())
    await store.append(accepted, assessment)

    with pytest.raises(IntegrityError):
        await store.append(accepted, assessment)


@pytest.mark.asyncio
async def test_future_dated_eligible_evidence_fails_closed(
    sqlite_engine,
    migrated: None,
) -> None:
    store = SqlResearchEvidenceStore(async_session_factory(sqlite_engine))
    accepted = attestation(eligible=True, strategy_version="accepted-v1")
    assessment = ResearchAssessment(True, True, ())
    evidence_hash = content_hash({"assessment": assessment, "attestation": accepted})
    await store.append(accepted, assessment)

    with pytest.raises(PersistenceDataError, match="future-dated"):
        await store.get_eligible(
            evidence_hash,
            strategy_version="accepted-v1",
            config_hash=ConfigHash("a" * 64),
            code_hash=CodeHash("b" * 64),
            as_of=NOW - timedelta(microseconds=1),
        )


def test_persisted_eligibility_rejects_an_arbitrary_wrapper_hash() -> None:
    accepted = attestation(eligible=True, strategy_version="accepted-v1")

    with pytest.raises(PersistenceDataError, match="hash is invalid"):
        from trading_bot.persistence.research import PersistedStrategyEligibility

        PersistedStrategyEligibility(accepted, "e" * 64)


def test_database_rejects_mutation_and_replace_of_research_evidence(
    alembic_config: Config,
    database_path,
) -> None:
    command.upgrade(alembic_config, "head")
    assessment = ResearchAssessment(True, True, ())
    accepted = attestation(eligible=True, strategy_version="accepted-v1")
    evidence_hash = content_hash({"assessment": assessment, "attestation": accepted})
    connection = sqlite3.connect(database_path)
    with closing(connection):
        connection.execute(
            """
            INSERT INTO research_acceptance_evidence (
                id, strategy_version, eligible, config_hash, code_hash,
                research_manifest_hash, report_hash, evidence_hash,
                reason_codes_json, observed_at
            ) VALUES (
                'accepted', 'accepted-v1', 1, ?, ?, ?, ?, ?, '[]',
                '2026-07-26T12:00:00.000000Z'
            )
            """,
            ("a" * 64, "b" * 64, "c" * 64, "d" * 64, evidence_hash),
        )
        connection.commit()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE research_acceptance_evidence SET strategy_version = 'changed'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM research_acceptance_evidence")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                """
                INSERT OR REPLACE INTO research_acceptance_evidence (
                    id, strategy_version, eligible, config_hash, code_hash,
                    research_manifest_hash, report_hash, evidence_hash,
                    reason_codes_json, observed_at
                ) VALUES (
                    'replacement', 'accepted-v1', 1, ?, ?, ?, ?, ?, '[]',
                    '2026-07-26T12:00:00.000000Z'
                )
                """,
                ("a" * 64, "b" * 64, "c" * 64, "d" * 64, evidence_hash),
            )
