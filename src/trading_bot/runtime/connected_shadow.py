"""Write-incapable broker-connected shadow preflight and evidence probe."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from trading_bot.brokers.robinhood_equity_evidence import (
    authenticated_equity_manifest,
    validate_read_tool_declarations,
)
from trading_bot.brokers.robinhood_equity_mapping import account_fingerprint
from trading_bot.brokers.robinhood_equity_mcp import build_equity_read_adapter
from trading_bot.brokers.robinhood_equity_schemas import AccountsResultDto
from trading_bot.brokers.robinhood_mcp_sdk import (
    OAUTH_FLOW_TIMEOUT_SECONDS,
    READ_ONLY_EQUITY_MCP_TOOLS,
    LoopbackOAuthCallback,
    RobinhoodMcpSdkConnection,
    initialize_private_oauth_store,
)
from trading_bot.brokers.robinhood_mcp_transport import (
    OFFICIAL_MCP_ENDPOINT,
    RobinhoodMcpTransport,
)
from trading_bot.clock import Clock, SystemClock
from trading_bot.config import LoadedConfig
from trading_bot.domain import AssetClass, BarInterval, ExecutionMode, InstrumentId
from trading_bot.market_data import content_hash
from trading_bot.market_data.robinhood_equity_mcp import RobinhoodEquityMarketData
from trading_bot.monitoring.promotion import (
    PromotionEvaluator,
    PromotionIdentity,
    PromotionObservation,
    PromotionStage,
)
from trading_bot.persistence import async_session_factory, create_engine
from trading_bot.persistence.migrations import migrate_sqlite_ledger
from trading_bot.persistence.promotion import (
    SqlPromotionEvidenceStore,
    SqlPromotionObservationStore,
)

_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PROBE_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}\Z")
_MICROSECONDS_PER_SECOND = Decimal("1000000")
_DEPENDENCY_LOG_DISABLE_LEVEL = logging.CRITICAL


class ConnectedShadowNotReady(RuntimeError):
    pass


@contextmanager
def _suppress_untrusted_dependency_logs() -> Iterator[None]:
    """Keep OAuth, HTTP, and MCP internals out of the one-shot operator channel."""

    previous_level = logging.root.manager.disable
    logging.disable(_DEPENDENCY_LOG_DISABLE_LEVEL)
    try:
        yield
    finally:
        logging.disable(previous_level)


def _seconds(value: object) -> timedelta:
    if type(value) is not Decimal:
        raise TypeError("duration must be an exact Decimal")
    microseconds = value * _MICROSECONDS_PER_SECOND
    if microseconds != microseconds.to_integral_value():
        raise ValueError("duration exceeds microsecond precision")
    return timedelta(microseconds=int(microseconds))


@dataclass(frozen=True, slots=True)
class ConnectedShadowProbeConfig:
    expected_account_fingerprint: str
    config_hash: str
    code_hash: str
    account_equity_ceiling: Decimal
    maximum_quote_age: timedelta
    recent_order_lookback: timedelta
    market_history_lookback: timedelta
    strategy_version: str = "equity-research-pending"
    probe_instrument: InstrumentId | None = None

    def __post_init__(self) -> None:
        for name in ("expected_account_fingerprint", "config_hash", "code_hash"):
            value = getattr(self, name)
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{name} must be lowercase SHA-256 hex")
        if self.account_equity_ceiling <= 0:
            raise ValueError("account_equity_ceiling must be positive")
        for name in (
            "maximum_quote_age",
            "recent_order_lookback",
            "market_history_lookback",
        ):
            if getattr(self, name) <= timedelta(0):
                raise ValueError(f"{name} must be positive")
        if not self.strategy_version.strip():
            raise ValueError("strategy_version must be nonempty")


@dataclass(frozen=True, slots=True)
class ConnectedShadowProbeResult:
    observation: PromotionObservation
    persisted: bool
    broker_health_healthy: bool
    zero_state_reconciliation_clean: bool
    market_probe_complete: bool


def read_account_fingerprint(path: str | Path) -> str:
    source = Path(path)
    try:
        metadata = source.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise ConnectedShadowNotReady(
                "account fingerprint must be a service-owned regular file"
            )
        if metadata.st_mode & 0o077:
            raise ConnectedShadowNotReady("account fingerprint file must use mode 0600 or stricter")
        value = source.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise ConnectedShadowNotReady("account fingerprint file is unavailable") from exc
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ConnectedShadowNotReady("account fingerprint file is invalid")
    return value


def write_account_fingerprint(path: str | Path, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ConnectedShadowNotReady("account fingerprint is invalid")
    destination = Path(path)
    try:
        parent = destination.parent
        metadata = parent.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise ConnectedShadowNotReady(
                "account fingerprint parent must be a service-owned directory"
            )
        if metadata.st_mode & 0o022:
            raise ConnectedShadowNotReady(
                "account fingerprint parent cannot be group or world writable"
            )
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{destination.name}.",
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, f"{value}\n".encode("ascii"))
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        raise ConnectedShadowNotReady("account fingerprint could not be persisted") from exc


def deployment_code_hash(image_digest: str) -> str:
    if _IMAGE_DIGEST.fullmatch(image_digest) is None:
        raise ConnectedShadowNotReady("connected shadow requires an immutable image digest")
    return hashlib.sha256(f"oci-image:{image_digest}".encode()).hexdigest()


class ConnectedShadowProbe:
    def __init__(
        self,
        *,
        config: ConnectedShadowProbeConfig,
        oauth_store_dir: str | Path,
        observations: SqlPromotionObservationStore,
        clock: Clock,
    ) -> None:
        self._config = config
        self._oauth_store_dir = Path(oauth_store_dir)
        self._observations = observations
        self._clock = clock

    async def run(self) -> ConnectedShadowProbeResult:
        started_at = self._clock.now()
        async with RobinhoodMcpSdkConnection(
            oauth_store_dir=self._oauth_store_dir,
        ) as connection:
            declarations = await connection.session.list_tools()
            provider_evidence_hash = str(validate_read_tool_declarations(declarations))
            transport = RobinhoodMcpTransport(
                connection.session,
                endpoint=OFFICIAL_MCP_ENDPOINT,
                oauth_store_dir=self._oauth_store_dir,
                allowed_tools=READ_ONLY_EQUITY_MCP_TOOLS,
            )
            broker = build_equity_read_adapter(
                authenticated_equity_manifest(),
                transport,
                clock=self._clock,
                expected_account_fingerprint=self._config.expected_account_fingerprint,
            )
            market = RobinhoodEquityMarketData(
                transport,
                self._clock,
                maximum_quote_age=self._config.maximum_quote_age,
            )

            health = await broker.health_check()
            if not health.healthy:
                raise ConnectedShadowNotReady("authenticated equity reads are unhealthy")
            accounts = await broker.get_accounts()
            if len(accounts) != 1:
                raise ConnectedShadowNotReady("allowlisted account identity is not unique")
            account = accounts[0]
            identity_verified = (
                account_fingerprint(account.account_id) == self._config.expected_account_fingerprint
            )
            if not identity_verified or account.restricted:
                raise ConnectedShadowNotReady("allowlisted account is unavailable or restricted")
            if account.equity > self._config.account_equity_ceiling:
                raise ConnectedShadowNotReady("account equity exceeds the configured ceiling")

            positions = await broker.get_positions(account.account_id)
            open_orders = await broker.get_open_orders(account.account_id)
            recent_orders = await broker.get_recent_orders(
                account.account_id,
                started_at - self._config.recent_order_lookback,
            )
            fills = await broker.get_fills(
                account.account_id,
                started_at - self._config.recent_order_lookback,
            )
            buying_power = await broker.get_buying_power(account.account_id, AssetClass.EQUITY)
            zero_state_clean = bool(
                not positions
                and not open_orders
                and not recent_orders
                and not fills
                and buying_power == account.buying_power_for(AssetClass.EQUITY)
                and account.equity == account.cash
                and account.cash == buying_power
            )

            market_hashes: tuple[str, ...] = ()
            market_probe_complete = False
            if self._config.probe_instrument is not None:
                instrument = self._config.probe_instrument
                tradability = await market.get_tradability(
                    account.account_id,
                    account_type="individual",
                    instrument_id=instrument,
                )
                bars = await market.get_bars(
                    instrument,
                    BarInterval.ONE_DAY,
                    started_at - self._config.market_history_lookback,
                    started_at,
                )
                if not bars:
                    raise ConnectedShadowNotReady("market probe returned no historical bars")
                market_hashes = (
                    str(tradability.data_hash),
                    *(str(item.data_hash) for item in bars),
                )
                market_probe_complete = True

        completed_at = self._clock.now()
        strategy_eligibility_hash = str(
            content_hash(
                {
                    "code_hash": self._config.code_hash,
                    "config_hash": self._config.config_hash,
                    "eligible": False,
                    "strategy_version": self._config.strategy_version,
                }
            )
        )
        identity = PromotionIdentity(
            account_fingerprint=self._config.expected_account_fingerprint,
            provider_evidence_hash=provider_evidence_hash,
            strategy_version=self._config.strategy_version,
            strategy_eligibility_hash=strategy_eligibility_hash,
            config_hash=self._config.config_hash,
            code_hash=self._config.code_hash,
        )
        data_hash = str(
            content_hash(
                {
                    "account_data_hash": account.data_hash,
                    "broker_health": health.healthy,
                    "market_hashes": market_hashes,
                    "order_count": len(open_orders) + len(recent_orders),
                    "position_count": len(positions),
                    "zero_state_reconciliation_clean": zero_state_clean,
                }
            )
        )
        cycle_id = str(
            content_hash(
                {
                    "completed_at": completed_at,
                    "identity": identity,
                    "started_at": started_at,
                    "type": "connected_shadow_preflight",
                }
            )
        )
        observation = PromotionObservation.create(
            stage=PromotionStage.SHADOW,
            cycle_id=cycle_id,
            identity=identity,
            started_at=started_at,
            completed_at=completed_at,
            data_hash=data_hash,
            identity_verified=identity_verified,
            provider_evidence_verified=True,
            strategy_eligible=False,
            authenticated_reads=True,
            data_validated=market_probe_complete,
            outcomes_complete=False,
            reconciliation_clean=zero_state_clean,
            fixture_data=False,
            runtime_scope_valid=True,
            order_state_known=not open_orders and not recent_orders,
        )
        persisted = await self._observations.append(observation)
        return ConnectedShadowProbeResult(
            observation=observation,
            persisted=persisted,
            broker_health_healthy=health.healthy,
            zero_state_reconciliation_clean=zero_state_clean,
            market_probe_complete=market_probe_complete,
        )


def run_connected_shadow_once(
    *,
    loaded: LoadedConfig,
    repository_root: str | Path,
    oauth_store: str | Path,
    account_fingerprint_file: str | Path,
    ledger: str | Path,
    image_digest: str,
    probe_symbol: str | None,
) -> dict[str, object]:
    """Run one authenticated read-only probe and return only sanitized status."""

    config = loaded.config
    if (
        config.mode is not ExecutionMode.SHADOW
        or config.live_trading_enabled
        or not config.runtime.start_paused
        or not config.equities.enabled
        or config.crypto.enabled
    ):
        raise ConnectedShadowNotReady("connected shadow configuration is unsafe")
    if probe_symbol is not None and _PROBE_SYMBOL.fullmatch(probe_symbol) is None:
        raise ConnectedShadowNotReady("connected shadow probe symbol is invalid")

    previous_umask = os.umask(0o077)
    engine = None
    try:
        root = Path(repository_root).resolve(strict=True)
        probe_config = ConnectedShadowProbeConfig(
            expected_account_fingerprint=read_account_fingerprint(account_fingerprint_file),
            config_hash=str(loaded.config_hash),
            code_hash=deployment_code_hash(image_digest),
            account_equity_ceiling=config.portfolio.live_account_equity_ceiling_usd,
            maximum_quote_age=_seconds(config.freshness.max_executable_quote_age_seconds),
            recent_order_lookback=timedelta(seconds=config.runtime.remainder_order_max_age_seconds),
            market_history_lookback=timedelta(days=config.equity_strategies.maximum_holding_bars),
            probe_instrument=(None if probe_symbol is None else InstrumentId(probe_symbol)),
        )
        database_url = migrate_sqlite_ledger(
            ledger,
            alembic_ini=root / "alembic.ini",
            migrations_dir=root / "migrations",
        )
        engine = create_engine(database_url)
        session_factory = async_session_factory(engine)
        observations = SqlPromotionObservationStore(session_factory)
        promotion_evidence = SqlPromotionEvidenceStore(session_factory)
        clock = SystemClock()
        probe = ConnectedShadowProbe(
            config=probe_config,
            oauth_store_dir=oauth_store,
            observations=observations,
            clock=clock,
        )

        async def run_probe() -> dict[str, object]:
            try:
                result = await probe.run()
                durable = await observations.list_for_identity(result.observation.identity)
                evaluated_at = clock.now()
                progress = PromotionEvaluator(config.promotion).evaluate(
                    stage=PromotionStage.SHADOW,
                    identity=result.observation.identity,
                    observations=durable,
                    now=evaluated_at,
                )
                attestation = await promotion_evidence.persist(
                    progress,
                    evaluated_at=evaluated_at,
                    expires_at=evaluated_at + _seconds(config.freshness.max_preflight_age_seconds),
                )
                return {
                    "authenticated_reads": result.observation.authenticated_reads,
                    "broker_health": result.broker_health_healthy,
                    "calendar_clock_started": progress.evidence.calendar_days > 0,
                    "evidence_hash": result.observation.evidence_hash,
                    "evidence_eligible": result.observation.eligible,
                    "ineligible_reasons": result.observation.reason_codes,
                    "live_enabled": False,
                    "market_probe_complete": result.market_probe_complete,
                    "persisted": result.persisted,
                    "promotion_evidence_hash": attestation.evidence_hash,
                    "promotion_eligible": attestation.eligible,
                    "status": "connected_shadow_nonpromotable",
                    "write_capabilities_present": False,
                    "zero_state_reconciliation": result.zero_state_reconciliation_clean,
                }
            finally:
                if engine is not None:
                    await engine.dispose()

        with _suppress_untrusted_dependency_logs():
            return asyncio.run(run_probe())
    except ConnectedShadowNotReady:
        raise
    except Exception as exc:
        raise ConnectedShadowNotReady("connected shadow probe failed closed") from exc
    finally:
        os.umask(previous_umask)


def bootstrap_read_only_oauth(
    *,
    oauth_store: str | Path,
    account_fingerprint_file: str | Path,
) -> dict[str, object]:
    """Stage a trading-capable OAuth credential for the write-incapable client."""

    previous_umask = os.umask(0o077)
    staging: Path | None = None
    try:
        destination = Path(oauth_store)
        fingerprint_destination = Path(account_fingerprint_file)
        if not destination.is_absolute() or not fingerprint_destination.is_absolute():
            raise ConnectedShadowNotReady("OAuth bootstrap paths must be absolute")
        if fingerprint_destination != destination / "account-fingerprint":
            raise ConnectedShadowNotReady(
                "account fingerprint must be committed inside the OAuth store"
            )
        parent = destination.parent
        try:
            parent_metadata = parent.lstat()
        except OSError as exc:
            raise ConnectedShadowNotReady("OAuth bootstrap parent is unavailable") from exc
        if not stat.S_ISDIR(parent_metadata.st_mode) or parent_metadata.st_uid != os.geteuid():
            raise ConnectedShadowNotReady(
                "OAuth bootstrap parent must be a service-owned directory"
            )
        if parent_metadata.st_mode & 0o077:
            raise ConnectedShadowNotReady("OAuth bootstrap parent must use mode 0700 or stricter")
        if destination.exists() or destination.is_symlink():
            raise ConnectedShadowNotReady("OAuth bootstrap destination must not already exist")
        try:
            staging = Path(
                tempfile.mkdtemp(
                    dir=parent,
                    prefix=f".{destination.name}.bootstrap.",
                )
            )
            os.chmod(staging, 0o700)
        except OSError as exc:
            raise ConnectedShadowNotReady("OAuth bootstrap staging failed") from exc
        store = initialize_private_oauth_store(staging)

        async def authorize() -> dict[str, object]:
            callback = LoopbackOAuthCallback()
            await callback.start()
            try:
                async with RobinhoodMcpSdkConnection(
                    oauth_store_dir=store,
                    callback=callback,
                    timeout_seconds=OAUTH_FLOW_TIMEOUT_SECONDS,
                ) as connection:
                    declarations = await connection.session.list_tools()
                    evidence_hash = validate_read_tool_declarations(declarations)
                    result = await connection.session.call_tool("get_accounts", {})
                    if result.is_error or result.structured_content is None:
                        raise ConnectedShadowNotReady("authenticated accounts read failed")
                    try:
                        accounts = AccountsResultDto.model_validate(result.structured_content)
                    except ValidationError:
                        raise ConnectedShadowNotReady(
                            "authenticated accounts response shape changed"
                        ) from None
                    candidates = tuple(
                        item
                        for item in accounts.data.accounts
                        if item.agentic_allowed
                        and item.type == "cash"
                        and item.brokerage_account_type == "individual"
                        and item.state == "active"
                        and not item.deactivated
                        and not item.permanently_deactivated
                    )
                    if len(candidates) != 1:
                        raise ConnectedShadowNotReady(
                            "exactly one active individual cash Agentic account is required"
                        )
                    write_account_fingerprint(
                        store / "account-fingerprint",
                        account_fingerprint(candidates[0].account_number),
                    )
                    return {
                        "account_fingerprint_written": True,
                        "provider_evidence_hash": evidence_hash,
                        "read_tools_verified": len(declarations),
                        "status": "oauth_bootstrap_complete",
                    }
            finally:
                await callback.close()

        with _suppress_untrusted_dependency_logs():
            result = asyncio.run(authorize())
        try:
            os.replace(store, destination)
        except OSError as exc:
            raise ConnectedShadowNotReady("OAuth bootstrap commit failed") from exc
        staging = None
        return result
    except ConnectedShadowNotReady:
        raise
    except Exception as exc:
        raise ConnectedShadowNotReady("OAuth bootstrap failed closed") from exc
    finally:
        cleanup_error: OSError | None = None
        if staging is not None:
            try:
                shutil.rmtree(staging)
            except OSError as exc:
                cleanup_error = exc
        os.umask(previous_umask)
        if cleanup_error is not None:
            raise ConnectedShadowNotReady(
                "OAuth bootstrap staging could not be removed"
            ) from cleanup_error


__all__ = [
    "ConnectedShadowNotReady",
    "ConnectedShadowProbe",
    "ConnectedShadowProbeConfig",
    "ConnectedShadowProbeResult",
    "bootstrap_read_only_oauth",
    "deployment_code_hash",
    "read_account_fingerprint",
    "run_connected_shadow_once",
    "write_account_fingerprint",
]
