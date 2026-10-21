"""Executable isolated hybrid runtime. Credentials never enter command arguments."""

import argparse
import asyncio
import json
import os
import secrets
import stat
import sys
from decimal import Decimal
from pathlib import Path
from typing import cast

from trading_bot.config import LoadedConfig, load_config
from trading_bot.config.hybrid import HybridAppConfig
from trading_bot.hybrid.models import Account
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.hybrid_journal import HybridJournal
from trading_bot.persistence.migrations import migrate_sqlite_ledger


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
    ):
        raise ValueError("state directory must be owned by this user with mode 0700")


def read_token(path: Path) -> str:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
    ):
        raise ValueError("dashboard token file must be a private owned regular file")
    if metadata.st_size > 256:
        raise ValueError("invalid dashboard token file")
    with path.open() as handle:
        token = handle.read().strip()
    if len(token) < 32 or any(character.isspace() for character in token):
        raise ValueError("invalid dashboard token file")
    return token


def configuration(root: Path) -> LoadedConfig:
    return load_config(
        root / "base.yaml",
        root / "hybrid/paper.yaml",
        root / "hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=root / "hybrid/policy.yaml",
    )


async def _initialize(url: str, loaded: LoadedConfig) -> None:
    config = cast(HybridAppConfig, loaded.config)
    engine = create_engine(url)
    try:
        owner = HybridJournal(async_session_factory(engine), str(loaded.config_hash))
        capital = config.hybrid.starting_capital_usd
        await owner.change(
            "genesis",
            "initialize",
            {"capital": str(capital)},
            lambda _: Account(
                starting_capital=capital,
                cash=capital,
                high_watermark=capital,
                daily_reference=capital,
                weekly_reference=capital,
            ),
        )
    finally:
        await engine.dispose()


async def _report(url: str, loaded: LoadedConfig) -> None:
    from trading_bot.hybrid.api import snapshot

    engine = create_engine(url)
    try:
        state = await HybridJournal(async_session_factory(engine), str(loaded.config_hash)).read()
        print(json.dumps(snapshot(state, cast(HybridAppConfig, loaded.config).hybrid), indent=2))
    finally:
        await engine.dispose()


async def _import_research(url: str, loaded: LoadedConfig, path: Path) -> None:
    import hashlib
    from datetime import UTC, datetime

    from trading_bot.hybrid.inputs import ResearchInputs, present_research

    if path.stat().st_size > 500000:
        raise ValueError("research file exceeds bounds")
    raw = path.read_bytes()
    bundle = ResearchInputs.model_validate_json(raw)
    present_research(bundle, datetime.now(UTC))
    engine = create_engine(url)
    try:
        owner = HybridJournal(async_session_factory(engine), str(loaded.config_hash))
        digest = hashlib.sha256(raw).hexdigest()
        await owner.change(
            "research:" + digest,
            "research",
            {"input_hash": digest},
            lambda account: Account.model_validate(
                account.model_dump() | {"research_json": bundle.model_dump_json()}
            ),
        )
    finally:
        await engine.dispose()


async def _fetch_sec(
    url: str, loaded: LoadedConfig, symbol: str, cik: str, user_agent: str
) -> None:
    """Explicit bounded public-source fetch; no brokerage credentials involved."""
    import hashlib
    from datetime import UTC, datetime

    import httpx

    from trading_bot.hybrid.inputs import ResearchInputs
    from trading_bot.research.hybrid_sources import PublicResearchClient

    now = datetime.now(UTC)

    def fetch():  # type: ignore[no-untyped-def]
        transport = httpx.HTTPTransport(retries=0, trust_env=False)
        client = PublicResearchClient(transport, sec_user_agent=user_agent)
        return client.sec_facts(symbol, cik, now)

    facts = await asyncio.to_thread(fetch)
    bundle = ResearchInputs(
        provider="sec_public", source_reference=f"sec-{symbol}", received_at=now, facts=facts
    )
    encoded = bundle.model_dump_json()
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    engine = create_engine(url)
    try:
        owner = HybridJournal(async_session_factory(engine), str(loaded.config_hash))
        await owner.change(
            "research:" + digest,
            "research",
            {"input_hash": digest},
            lambda a: Account.model_validate(a.model_dump() | {"research_json": encoded}),
        )
    finally:
        await engine.dispose()


async def _replay(url: str, loaded: LoadedConfig, path: Path) -> None:
    from trading_bot.hybrid.scenario import Scenario, replay

    if path.stat().st_size > 500000:
        raise ValueError("scenario exceeds bounds")
    scenario = Scenario.model_validate_json(path.read_bytes())
    engine = create_engine(url)
    try:
        owner = HybridJournal(async_session_factory(engine), str(loaded.config_hash))
        state = await owner.read()
        if state.kill_switch:
            raise ValueError("kill switch blocks scenarios")
        # An explicit --experimental scenario is the only CLI replay entry point.
        await owner.change(
            "experimental-scenario-start",
            "control",
            {"experimental": True},
            lambda a: Account.model_validate(a.model_dump() | {"paused": False}),
        )
        await replay(
            scenario, cast(HybridAppConfig, loaded.config).hybrid, await owner.read(), owner=owner
        )
    finally:
        await engine.dispose()


async def _compare(
    url: str, loaded: LoadedConfig, symbol: str, slip: Decimal, fee: Decimal, operating: Decimal
) -> None:
    import hashlib

    from trading_bot.hybrid.inputs import ResearchInputs
    from trading_bot.research.hybrid_backtest import compare_exit_models

    engine = create_engine(url)
    try:
        owner = HybridJournal(async_session_factory(engine), str(loaded.config_hash))
        account = await owner.read()
        if account.research_json is None:
            raise ValueError("import source-labeled research prices first")
        bundle = ResearchInputs.model_validate_json(account.research_json)
        if symbol not in bundle.prices:
            raise ValueError("symbol not present in imported prices")
        result = compare_exit_models(
            bundle.prices[symbol],
            starting_capital=account.starting_capital,
            slippage_bps=slip,
            fee_per_order=fee,
            operating_cost_per_bar=operating,
            tax_rate=cast(HybridAppConfig, loaded.config).hybrid.tax_rate,
        )
        encoded = json.dumps(result, sort_keys=True, allow_nan=False)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        await owner.change(
            "comparison:" + digest,
            "research",
            {"comparison_hash": digest},
            lambda a: Account.model_validate(a.model_dump() | {"comparisons_json": encoded}),
        )
        print(encoded)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hybrid equity experimental runtime; live disabled"
    )
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--config-root", type=Path, default=Path("configs"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("report")
    research_import = commands.add_parser("import-research")
    research_import.add_argument("--input", type=Path, required=True)
    sec = commands.add_parser("fetch-sec")
    sec.add_argument("--symbol", required=True)
    sec.add_argument("--cik", required=True)
    sec.add_argument(
        "--user-agent",
        required=True,
        help="SEC-compliant application identification and contact; no credentials",
    )
    replay_parser = commands.add_parser("replay")
    replay_parser.add_argument("--input", type=Path, required=True)
    replay_parser.add_argument("--experimental", action="store_true", required=True)
    comparison = commands.add_parser("compare-exits")
    comparison.add_argument("--symbol", required=True)
    comparison.add_argument("--slippage-bps", type=Decimal, required=True)
    comparison.add_argument("--fee", type=Decimal, required=True)
    comparison.add_argument("--operating-per-bar", type=Decimal, required=True)
    serve = commands.add_parser("serve")
    serve.add_argument(
        "--host",
        choices=("127.0.0.1", "0.0.0.0"),  # nosec B104
        default="127.0.0.1",
    )
    serve.add_argument("--container-loopback-publish", action="store_true")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--dashboard-dir", type=Path, default=Path("dashboard/dist"))
    serve.add_argument(
        "--stock-export-dir", type=Path, help="Separate read-only stock dashboard projection mount"
    )
    args = parser.parse_args()
    try:
        _private_directory(args.state_dir)
        loaded = configuration(args.config_root)
        from trading_bot.logging import _install_logging_settings, configure_logging

        _install_logging_settings(loaded.config.logging, loaded.safety_envelope.logging)
        configure_logging("INFO")
        state_dir = args.state_dir.resolve()
        ledger = state_dir / "ledger.db"
        token_path = state_dir / "dashboard.token"
        if args.command == "init":
            if (
                ledger.exists()
                or token_path.exists()
                or ledger.is_symlink()
                or token_path.is_symlink()
            ):
                raise ValueError("initialization refuses to overwrite existing state")
            fd = os.open(token_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(secrets.token_urlsafe(48) + "\n")
            url = migrate_sqlite_ledger(
                ledger, alembic_ini="alembic.ini", migrations_dir="migrations"
            )
            asyncio.run(_initialize(url, loaded))
            print("Initialized private experimental account; live trading disabled.")
            return
        if not ledger.is_file():
            raise ValueError("initialize the isolated account first")
        # Validate existing permissions and schema before composing the service.
        url = migrate_sqlite_ledger(ledger, alembic_ini="alembic.ini", migrations_dir="migrations")
        if args.command == "import-research":
            asyncio.run(_import_research(url, loaded, args.input))
            print("Imported declared research inputs; qualification remains false.")
            return
        if args.command == "fetch-sec":
            asyncio.run(_fetch_sec(url, loaded, args.symbol, args.cik, args.user_agent))
            print("Fetched public SEC facts; source qualification remains false.")
            return
        if args.command == "replay":
            asyncio.run(_replay(url, loaded, args.input))
            print("Experimental scenario journaled; no broker calls or promotion.")
            return
        if args.command == "compare-exits":
            asyncio.run(
                _compare(
                    url, loaded, args.symbol, args.slippage_bps, args.fee, args.operating_per_bar
                )
            )
            return
        if args.command == "report":
            asyncio.run(_report(url, loaded))
            return
        import uvicorn

        from trading_bot.hybrid.api import build_hybrid_app
        from trading_bot.monitoring.api import AdminBindPolicy

        AdminBindPolicy.validate(args.host, args.container_loopback_publish)
        engine = create_engine(url)
        owner = HybridJournal(async_session_factory(engine), str(loaded.config_hash))
        stock_reader = None
        if args.stock_export_dir is not None:
            from trading_bot.runtime.stock_dashboard_export import StockDashboardReader

            root = args.config_root
            stock_loaded = load_config(
                root / "base.yaml",
                root / "hybrid/paper.yaml",
                root / "hybrid/safety-envelope.yaml",
                os.environ,
                hybrid_policy_path=root / "hybrid/policy.yaml",
                stock_research_policy_path=root / "hybrid/stock-research.yaml",
                stock_worker_policy_path=root / "hybrid/stock-worker.yaml",
            )
            stock_reader = StockDashboardReader(root=args.stock_export_dir, loaded=stock_loaded)
        app = build_hybrid_app(
            owner,
            cast(HybridAppConfig, loaded.config).hybrid,
            read_token(token_path),
            static_dir=args.dashboard_dir,
            run_worker=True,
            stock_research_reader=stock_reader,
        )
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            access_log=False,
            log_config=None,
            server_header=False,
        )
    except (ValueError, OSError, RuntimeError):
        print(
            "Hybrid runtime denied: verify private paths, configuration, and state.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
