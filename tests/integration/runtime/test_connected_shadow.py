from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from mcp.shared.auth import OAuthToken

from tests.integration.brokers.test_robinhood_equity_read import (
    accounts_response,
    portfolio_response,
)
from trading_bot.brokers.robinhood_equity_evidence import EXPECTED_TOOL_ARGUMENTS
from trading_bot.brokers.robinhood_equity_mapping import account_fingerprint
from trading_bot.brokers.robinhood_mcp_schema_gate import DeclaredMcpTool, JsonValue
from trading_bot.brokers.robinhood_mcp_sdk import (
    OAUTH_FLOW_TIMEOUT_SECONDS,
    ROBINHOOD_MCP_OAUTH_SCOPE,
    EncryptedFileTokenStorage,
)
from trading_bot.brokers.robinhood_mcp_transport import McpToolResult
from trading_bot.monitoring.promotion import PromotionObservation
from trading_bot.persistence.base import PersistenceConfigurationError
from trading_bot.persistence.migrations import migrate_sqlite_ledger
from trading_bot.runtime import connected_shadow
from trading_bot.runtime.connected_shadow import (
    ConnectedShadowNotReady,
    ConnectedShadowProbe,
    ConnectedShadowProbeConfig,
    bootstrap_read_only_oauth,
    write_account_fingerprint,
)

NOW = datetime(2026, 7, 21, 18, tzinfo=UTC)
ACCOUNT = "synthetic-agentic-account"


class FixedClock:
    def now(self) -> datetime:
        return NOW


def declarations() -> tuple[DeclaredMcpTool, ...]:
    return tuple(
        DeclaredMcpTool.create(
            name,
            "synthetic read declaration",
            {
                "type": "object",
                "properties": {key: {} for key in sorted(properties)},
                "required": sorted(required),
            },
            {"type": "object"},
        )
        for name, (properties, required) in sorted(EXPECTED_TOOL_ARGUMENTS.items())
    )


class ReadOnlySession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, JsonValue]]] = []
        self.responses: Mapping[str, JsonValue] = {
            "get_accounts": accounts_response(ACCOUNT),
            "get_portfolio": portfolio_response(),
            "get_equity_positions": {
                "data": {"positions": [], "next": None},
                "guide": "synthetic-read-shape",
            },
            "get_equity_orders": {
                "data": {"orders": [], "next": None},
                "guide": "synthetic-read-shape",
            },
        }

    async def list_tools(self) -> tuple[DeclaredMcpTool, ...]:
        return declarations()

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
    ) -> McpToolResult:
        self.calls.append((name, dict(arguments)))
        return McpToolResult((), False, self.responses[name])


class FakeConnection:
    session_value = ReadOnlySession()

    def __init__(self, **kwargs: object) -> None:
        del kwargs
        self.session = self.session_value

    async def __aenter__(self) -> FakeConnection:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args


class FakeOAuthCallback:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


class BootstrapConnection:
    declarations_valid = True
    timeout_seconds: object | None = None

    def __init__(self, **kwargs: object) -> None:
        self._store = Path(str(kwargs["oauth_store_dir"]))
        type(self).timeout_seconds = kwargs.get("timeout_seconds")
        self.session = self

    async def __aenter__(self) -> BootstrapConnection:
        storage = EncryptedFileTokenStorage(self._store)
        await storage.set_tokens(
            OAuthToken(
                access_token="synthetic-access-token",
                scope=ROBINHOOD_MCP_OAUTH_SCOPE,
            )
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def list_tools(self) -> tuple[DeclaredMcpTool, ...]:
        return declarations() if self.declarations_valid else ()

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
    ) -> McpToolResult:
        assert name == "get_accounts" and arguments == {}
        return McpToolResult((), False, accounts_response(ACCOUNT))


class LoggingBootstrapConnection(BootstrapConnection):
    async def __aenter__(self) -> BootstrapConnection:
        logging.getLogger("mcp.synthetic").critical("synthetic-sensitive-oauth-value")
        return await super().__aenter__()


class ObservationStore:
    def __init__(self) -> None:
        self.items: list[PromotionObservation] = []

    async def append(self, value: PromotionObservation) -> bool:
        self.items.append(value)
        return True


@pytest.mark.asyncio
async def test_connected_probe_uses_only_authenticated_reads_and_records_ineligible_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    oauth = tmp_path / "oauth"
    oauth.mkdir(mode=0o700)
    oauth.chmod(0o700)
    store = ObservationStore()
    session = ReadOnlySession()
    FakeConnection.session_value = session
    monkeypatch.setattr(connected_shadow, "RobinhoodMcpSdkConnection", FakeConnection)
    probe = ConnectedShadowProbe(
        config=ConnectedShadowProbeConfig(
            expected_account_fingerprint=account_fingerprint(ACCOUNT),
            config_hash="a" * 64,
            code_hash="b" * 64,
            account_equity_ceiling=Decimal("150"),
            maximum_quote_age=timedelta(seconds=5),
            recent_order_lookback=timedelta(days=1),
            market_history_lookback=timedelta(days=100),
        ),
        oauth_store_dir=oauth,
        observations=store,  # type: ignore[arg-type]
        clock=FixedClock(),
    )

    result = await probe.run()

    assert result.persisted
    assert result.broker_health_healthy
    assert result.zero_state_reconciliation_clean
    assert not result.market_probe_complete
    assert not result.observation.eligible
    assert result.observation.reason_codes == (
        "strategy_ineligible",
        "live_data_invalid",
        "outcomes_incomplete",
    )
    assert result.observation.runtime_scope_valid
    assert store.items == [result.observation]
    assert {name for name, _ in session.calls} <= set(EXPECTED_TOOL_ARGUMENTS)
    assert not any(name.startswith(("review_", "place_", "cancel_")) for name, _ in session.calls)


def test_account_fingerprint_writer_rejects_symlinked_parent(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)

    with pytest.raises(ConnectedShadowNotReady, match="service-owned directory"):
        write_account_fingerprint(linked / "fingerprint", "a" * 64)


def test_runtime_migration_rejects_dangling_ledger_symlink(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.db"
    redirected = tmp_path / "redirected.db"
    ledger.symlink_to(redirected)

    with pytest.raises(PersistenceConfigurationError, match="regular file"):
        migrate_sqlite_ledger(
            ledger,
            alembic_ini=tmp_path / "unreached.ini",
            migrations_dir=tmp_path / "unreached-migrations",
        )

    assert not redirected.exists()


def test_oauth_bootstrap_commits_credentials_and_fingerprint_together(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    destination = parent / "oauth"
    fingerprint = destination / "account-fingerprint"
    BootstrapConnection.declarations_valid = True
    BootstrapConnection.timeout_seconds = None
    monkeypatch.setattr(connected_shadow, "LoopbackOAuthCallback", FakeOAuthCallback)
    monkeypatch.setattr(
        connected_shadow,
        "RobinhoodMcpSdkConnection",
        BootstrapConnection,
    )

    result = bootstrap_read_only_oauth(
        oauth_store=destination,
        account_fingerprint_file=fingerprint,
    )

    assert result["status"] == "oauth_bootstrap_complete"
    assert BootstrapConnection.timeout_seconds == OAUTH_FLOW_TIMEOUT_SECONDS
    assert destination.is_dir()
    assert fingerprint.is_file()
    assert (destination / "tokens.json.box").is_file()


def test_oauth_bootstrap_discards_staged_token_when_validation_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    destination = parent / "oauth"
    BootstrapConnection.declarations_valid = False
    monkeypatch.setattr(connected_shadow, "LoopbackOAuthCallback", FakeOAuthCallback)
    monkeypatch.setattr(
        connected_shadow,
        "RobinhoodMcpSdkConnection",
        BootstrapConnection,
    )

    with pytest.raises(ConnectedShadowNotReady, match="failed closed"):
        bootstrap_read_only_oauth(
            oauth_store=destination,
            account_fingerprint_file=destination / "account-fingerprint",
        )

    assert not destination.exists()
    assert tuple(parent.iterdir()) == ()


def test_oauth_bootstrap_suppresses_dependency_logs_and_restores_logging(
    monkeypatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:  # type: ignore[no-untyped-def]
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    destination = parent / "oauth"
    previous_disable_level = logging.root.manager.disable
    BootstrapConnection.declarations_valid = True
    monkeypatch.setattr(connected_shadow, "LoopbackOAuthCallback", FakeOAuthCallback)
    monkeypatch.setattr(
        connected_shadow,
        "RobinhoodMcpSdkConnection",
        LoggingBootstrapConnection,
    )

    bootstrap_read_only_oauth(
        oauth_store=destination,
        account_fingerprint_file=destination / "account-fingerprint",
    )

    assert "synthetic-sensitive-oauth-value" not in caplog.text
    assert logging.root.manager.disable == previous_disable_level
