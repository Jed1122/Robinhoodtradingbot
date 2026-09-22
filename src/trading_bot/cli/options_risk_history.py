"""Offline loss-history rehearsal. Only disposable private SQLite databases are written.

No existing ledger path is accepted, no ambient credentials are read, and no live owner
or broker is constructed. A simulated restart is engineering evidence only.
"""

import asyncio
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import SQLAlchemyError

from trading_bot.config import LoadedConfig, load_config
from trading_bot.domain import AccountId
from trading_bot.market_data.bundle_codec import _json, _mapping, _time
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.bundle_store import _open_root, _read
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.lease import LeaseRepository
from trading_bot.persistence.models import AccountRow
from trading_bot.persistence.options_risk import OptionsRiskJournal, decode_point
from trading_bot.risk.options_loss_history import OptionsLossPoint, evaluate_options_loss_history

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
_ROOT = Path(__file__).resolve().parents[3]
_LIMITS = BundleLimits(
    max_envelope_bytes=1048576,
    max_blob_bytes=1048576,
    max_total_bytes=1048576,
    max_records=50000,
    max_json_depth=12,
)
_MAX_POINTS = 1000  # Work bound for the quadratic rehearsal, not a trading-policy limit.


@dataclass
class _ReplayClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def _load(directory: Path) -> LoadedConfig:
    return load_config(
        directory / "base.yaml",
        directory / "options/simulation.yaml",
        directory / "safety-envelope.yaml",
        {},
    )


def _read_fixture(path: Path) -> tuple[tuple[OptionsLossPoint, ...], datetime]:
    directory = _open_root(path.parent, _ROOT)
    try:
        body = _read(directory, path.name, _LIMITS.max_blob_bytes)
    finally:
        os.close(directory)
    root = _mapping(
        _json(body, max_bytes=_LIMITS.max_blob_bytes, limits=_LIMITS),
        {"schema", "source_kind", "points", "as_of"},
    )
    if root["schema"] != "options-risk-rehearsal-v1" or root["source_kind"] != "synthetic":
        raise ValueError("unsupported risk rehearsal")
    values = root["points"]
    if type(values) is not list or not 1 <= len(values) <= _MAX_POINTS:
        raise ValueError("bounded risk history required")
    return tuple(decode_point(canonical_json(p)) for p in values), _time(root["as_of"])


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
        journal = OptionsRiskJournal(factory, clock, loaded, max_events=_MAX_POINTS)
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
            async_session_factory(restarted), clock, loaded, max_events=_MAX_POINTS
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


def _rehearse(
    loaded: LoadedConfig, points: tuple[OptionsLossPoint, ...], as_of: datetime
) -> dict[str, object]:
    # Validate the whole closed input before even creating the disposable database.
    evaluate_options_loss_history(loaded, points, as_of=as_of)
    with TemporaryDirectory(prefix="options-risk-rehearsal-") as directory:
        url = "sqlite+aiosqlite:///" + str(Path(directory) / "ledger.sqlite3")
        migrations = Config()
        migrations.set_main_option("script_location", str(_ROOT / "migrations"))
        migrations.set_main_option("sqlalchemy.url", url)
        command.upgrade(migrations, "head")
        return asyncio.run(_round_trip(url, loaded, points, as_of))


def _emit(report: dict[str, object]) -> None:
    typer.echo(canonical_json(report))
    losses = report["losses"]
    assert isinstance(losses, dict)
    if any(
        reason in losses["entry_reasons"]
        for reason in ("risk_history_incomplete", "risk_observation_stale", "outside_session")
    ):
        raise typer.Exit(2)


def _denied() -> None:
    typer.echo(canonical_json({"status": "denied", "reason": "risk_history_input_invalid"}))
    raise typer.Exit(1)


@app.command("demo")
def demo(config_dir: Annotated[Path, typer.Option()] = Path("configs")) -> None:
    """Rehearse a fabricated loss then deposit, including database close/reopen recovery."""
    try:
        loaded = _load(config_dir)
        opening = datetime(2026, 9, 18, 13, 30, tzinfo=UTC)
        first = OptionsLossPoint(
            "initial",
            AccountId("synthetic:risk-demo"),
            str(loaded.config_hash),
            opening,
            "2026-09-18",
            opening,
            opening.replace(hour=20, minute=0),
            None,
            Decimal(100),
            Decimal(0),
            "a" * 64,
            True,
        )
        loss = replace(
            first,
            event_id="loss",
            observed_at=opening + timedelta(seconds=1),
            liquidation_equity=Decimal(89),
        )
        deposit = replace(
            loss,
            event_id="deposit",
            observed_at=opening + timedelta(seconds=2),
            liquidation_equity=Decimal(1089),
            cumulative_external_flows=Decimal(1000),
        )
        report = _rehearse(loaded, (first, loss, deposit), deposit.observed_at)
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError, SQLAlchemyError):
        _denied()
        return
    _emit(report)


@app.command("replay-file")
def replay_file(
    input_path: Annotated[Path, typer.Argument()],
    config_dir: Annotated[Path, typer.Option()] = Path("configs"),
) -> None:
    """Read a private bounded synthetic fixture and verify a disposable journal restart."""
    try:
        loaded = _load(config_dir)
        points, as_of = _read_fixture(input_path)
        report = _rehearse(loaded, points, as_of)
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError, SQLAlchemyError):
        _denied()
        return
    _emit(report)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
