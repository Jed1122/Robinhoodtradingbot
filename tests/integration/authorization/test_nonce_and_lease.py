from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from nacl.signing import SigningKey
from sqlalchemy import func, select

from trading_bot.authorization import (
    ActivationPayload,
    InvalidAuthorization,
    VerificationContext,
    consume_activation,
    sign_activation,
)
from trading_bot.domain import AccountId, CodeHash, ConfigHash, DataHash, ExecutionMode
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.authorization import SqlAuthorizationStore
from trading_bot.persistence.models import (
    AccountRow,
    LiveAuthorizationRow,
    LiveLeaseRow,
    PromotionEvidenceRow,
    UsedNonceRow,
)

NOW = datetime(2026, 7, 17, tzinfo=UTC)
HASHES = tuple(str(index) * 64 for index in range(1, 7))
ROOT = Path(__file__).parents[3]


def payload() -> ActivationPayload:
    return ActivationPayload(
        "authorization-1",
        "nonce-1",
        AccountId("account-1"),
        ExecutionMode.MICRO_LIVE,
        Decimal("100"),
        HASHES[0],
        HASHES[1],
        ConfigHash(HASHES[2]),
        CodeHash(HASHES[3]),
        HASHES[4],
        HASHES[5],
        NOW,
        NOW + timedelta(minutes=15),
    )


def context() -> VerificationContext:
    value = payload()
    return VerificationContext(
        value.account_id,
        value.stage,
        value.config_hash,
        value.code_hash,
        value.preflight_hash,
        value.acknowledgement_hash,
        value.strategy_eligibility_hash,
        value.promotion_evidence_hash,
        Decimal("100"),
    )


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'authorization.sqlite3'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return url


@pytest.mark.asyncio
async def test_activation_nonce_is_one_time_and_lease_is_atomic(database_url: str) -> None:
    url = database_url
    engine = create_engine(url)
    factory = async_session_factory(engine)
    value = payload()
    async with factory.begin() as session:
        session.add(
            AccountRow(
                id=value.account_id,
                provider="fixture",
                provider_account_id="external",
                account_type="cash",
                provider_state="active",
                equity=Decimal("100"),
                cash=Decimal("100"),
                equity_buying_power=Decimal("100"),
                crypto_buying_power=Decimal("100"),
                prediction_buying_power=None,
                restricted=False,
                observed_at=NOW,
                data_hash=DataHash("a" * 64),
                config_hash=value.config_hash,
                code_hash=value.code_hash,
            )
        )
        session.add(
            PromotionEvidenceRow(
                id="promotion-1",
                stage=value.stage.value,
                eligible=True,
                evidence_hash=value.promotion_evidence_hash,
                reason_codes_json="[]",
                evaluated_at=NOW,
                expires_at=NOW + timedelta(days=1),
            )
        )
    key = SigningKey.generate()
    artifact = sign_activation(value, key)
    store = SqlAuthorizationStore(factory)
    lease = await consume_activation(
        artifact, store, verify_key=key.verify_key, now=NOW, context=context()
    )
    assert lease.expires_at == NOW + timedelta(hours=8)
    with pytest.raises(InvalidAuthorization, match="already used"):
        await consume_activation(
            artifact, store, verify_key=key.verify_key, now=NOW, context=context()
        )
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(LiveAuthorizationRow)) == 1
        assert await session.scalar(select(func.count()).select_from(UsedNonceRow)) == 1
        assert await session.scalar(select(func.count()).select_from(LiveLeaseRow)) == 1
    await engine.dispose()
