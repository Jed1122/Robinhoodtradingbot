"""Disposable synthetic database rehearsal; never accepts an existing database path."""

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import SQLAlchemyError

from trading_bot.config import LoadedConfig
from trading_bot.market_data.recording import content_hash
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.lease import LeaseRepository
from trading_bot.persistence.models import AccountRow
from trading_bot.persistence.options_risk import OptionsRiskJournal
from trading_bot.risk.options_loss_history import OptionsLossPoint, evaluate_options_loss_history

MAX_REHEARSAL_POINTS = 1000  # Work bound, not a trading-policy threshold.


@dataclass
class _ReplayClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


async def _round_trip(
    url: str, loaded: LoadedConfig, points: tuple[OptionsLossPoint, ...], as_of: datetime
) -> dict[str, object]:
    first = points[0]
    clock = _ReplayClock(first.observed_at)
    engine = create_engine(url)
    try:
        factory = async_session_factory(engine)
        async with factory.begin() as session:
            session.add(
                AccountRow(
                    id=first.account_id,
                    provider="synthetic",
                    provider_account_id="synthetic",
                    account_type="cash",
                    provider_state="paused",
                    equity=first.liquidation_equity,
                    cash=first.liquidation_equity,
                    equity_buying_power=Decimal(0),
                    crypto_buying_power=Decimal(0),
                    prediction_buying_power=None,
                    restricted=True,
                    observed_at=first.observed_at,
                    data_hash=first.source_hash,
                    config_hash=str(loaded.config_hash),
                    code_hash=str(content_hash("synthetic-risk-rehearsal-v1")),
                )
            )
        leases = LeaseRepository(factory, clock)
        journal = OptionsRiskJournal(factory, clock, loaded, max_events=MAX_REHEARSAL_POINTS)
        head = "0" * 64
        for point in points:
            clock.value = point.observed_at
            lease = await leases.acquire(first.account_id, owner="offline-risk-rehearsal")
            head = await journal.append(lease, point, expected_head=head)
            await leases.release(lease)
        clock.value = as_of
        before = await journal.snapshot(first.account_id)
    finally:
        await engine.dispose()
    restarted = create_engine(url)
    try:
        after = await OptionsRiskJournal(
            async_session_factory(restarted), clock, loaded, max_events=MAX_REHEARSAL_POINTS
        ).snapshot(first.account_id)
    finally:
        await restarted.dispose()
    if before != after or after.report is None:
        raise RuntimeError("risk history restart mismatch")
    return {
        "schema": "options-risk-rehearsal-report-v1",
        "status": "paused_synthetic_rehearsal",
        "source_kind": "synthetic",
        "account": "[synthetic account withheld]",
        "config_hash": loaded.config_hash,
        "observation_count": len(after.points),
        "history_hash": after.head_hash,
        "losses": asdict(after.report),
        "paused": True,
        "entry_enabled": False,
        "production_eligible": False,
        "economic_verdict": "ECONOMIC_NO_GO",
        "restart_verified": True,
        "storage": "disposable_private_test_database",
        "limitations": [
            "declared_marks_flows_and_sessions_are_not_authenticated",
            "not_full_pretrade_or_broker_reconciliation",
            "no_live_operator_or_deployment_authority",
        ],
    }


def rehearse_risk_history(
    loaded: LoadedConfig, points: tuple[OptionsLossPoint, ...], as_of: datetime
) -> dict[str, object]:
    # Validate the whole closed input before creating any disposable database.
    evaluate_options_loss_history(loaded, points, as_of=as_of)
    if len(points) > MAX_REHEARSAL_POINTS:
        raise ValueError("risk rehearsal work bound exceeded")
    try:
        with TemporaryDirectory(prefix="options-risk-rehearsal-") as directory:
            url = "sqlite+aiosqlite:///" + str(Path(directory) / "ledger.sqlite3")
            migrations = Config()
            migrations.set_main_option(
                "script_location", str(Path(__file__).resolve().parents[3] / "migrations")
            )
            migrations.set_main_option("sqlalchemy.url", url)
            command.upgrade(migrations, "head")
            return asyncio.run(_round_trip(url, loaded, points, as_of))
    except SQLAlchemyError:
        raise ValueError("risk rehearsal storage failure") from None
