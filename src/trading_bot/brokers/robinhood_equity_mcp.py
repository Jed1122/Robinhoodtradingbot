"""Read-only Robinhood Trading MCP equity broker adapter."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from trading_bot.brokers.robinhood_equity_mapping import (
    account_fingerprint,
    ensure_authenticated_empty_collection,
    map_account,
    mapping_ready,
)
from trading_bot.brokers.robinhood_equity_schemas import (
    AccountsResultDto,
    EquityAccountDto,
    OrdersResultDto,
    PortfolioResultDto,
    PositionsResultDto,
)
from trading_bot.brokers.robinhood_mcp_schema_gate import JsonValue
from trading_bot.brokers.robinhood_mcp_transport import RobinhoodMcpTransport
from trading_bot.capabilities.models import CapabilityManifest, EvidenceLevel
from trading_bot.clock import Clock
from trading_bot.domain import (
    AccountId,
    AccountSnapshot,
    AssetClass,
    BrokerHealth,
    BrokerOrder,
    Fill,
    Position,
)
from trading_bot.market_data import content_hash

REQUIRED_EQUITY_READ_OPERATIONS = (
    "get_accounts",
    "get_portfolio",
    "get_equity_positions",
    "get_equity_orders",
    "get_equity_quotes",
    "get_equity_tradability",
    "get_equity_historicals",
)


class CapabilityNotVerified(RuntimeError):
    pass


class EquityReadError(RuntimeError):
    """Sanitized connected-read failure that never embeds provider content."""


ModelT = TypeVar("ModelT", bound=BaseModel)


class RobinhoodEquityReadAdapter:
    """BrokerRead implementation with no review, placement, or cancel capability."""

    def __init__(
        self,
        transport: RobinhoodMcpTransport,
        clock: Clock,
        *,
        expected_account_fingerprint: str,
    ) -> None:
        if len(expected_account_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in expected_account_fingerprint
        ):
            raise ValueError("expected account fingerprint must be lowercase SHA-256 hex")
        self._transport = transport
        self._clock = clock
        self._expected_account_fingerprint = expected_account_fingerprint

    async def _call(
        self,
        tool_name: str,
        arguments: dict[str, JsonValue],
        model: type[ModelT],
    ) -> ModelT:
        result = await self._transport.call_tool(tool_name, arguments)
        if result.is_error or result.structured_content is None:
            raise EquityReadError("MCP read did not return reviewed structured content")
        try:
            return model.model_validate(result.structured_content)
        except ValidationError:
            raise EquityReadError("MCP read response shape is incompatible") from None

    async def _selected_account(self) -> EquityAccountDto:
        response = await self._call("get_accounts", {}, AccountsResultDto)
        matches = tuple(
            item
            for item in response.data.accounts
            if account_fingerprint(item.account_number) == self._expected_account_fingerprint
        )
        if len(matches) != 1:
            raise EquityReadError("allowlisted account identity is not unique")
        account = matches[0]
        if not account.agentic_allowed:
            raise EquityReadError("allowlisted account is not available to the connected agent")
        return account

    async def _snapshot(self) -> AccountSnapshot:
        account = await self._selected_account()
        portfolio = await self._call(
            "get_portfolio",
            {"account_number": account.account_number},
            PortfolioResultDto,
        )
        digest = content_hash(
            {
                "account": account.model_dump(mode="json"),
                "portfolio": portfolio.model_dump(mode="json"),
            }
        )
        return map_account(
            account,
            portfolio,
            observed_at=self._clock.now(),
            data_hash=digest,
        )

    async def get_accounts(self) -> tuple[AccountSnapshot, ...]:
        return (await self._snapshot(),)

    async def get_account_state(self, account_id: AccountId) -> AccountSnapshot:
        self._require_account(account_id)
        snapshot = await self._snapshot()
        if snapshot.account_id != account_id:
            raise EquityReadError("allowlisted account identity changed")
        return snapshot

    def _require_account(self, account_id: AccountId) -> None:
        if account_fingerprint(account_id) != self._expected_account_fingerprint:
            raise EquityReadError("requested account is not allowlisted")

    async def get_positions(self, account_id: AccountId) -> tuple[Position, ...]:
        self._require_account(account_id)
        response = await self._call(
            "get_equity_positions",
            {"account_number": str(account_id)},
            PositionsResultDto,
        )
        ensure_authenticated_empty_collection(
            response.data.positions,
            collection_name="equity positions",
            next_page=response.data.next,
        )
        return ()

    async def _orders(
        self,
        account_id: AccountId,
        *,
        since: datetime | None = None,
    ) -> tuple[BrokerOrder, ...]:
        self._require_account(account_id)
        arguments: dict[str, JsonValue] = {"account_number": str(account_id)}
        if since is not None:
            arguments["created_at_gte"] = since.isoformat().replace("+00:00", "Z")
        response = await self._call("get_equity_orders", arguments, OrdersResultDto)
        ensure_authenticated_empty_collection(
            response.data.orders,
            collection_name="equity orders",
            next_page=response.data.next,
        )
        return ()

    async def get_open_orders(self, account_id: AccountId) -> tuple[BrokerOrder, ...]:
        return await self._orders(account_id)

    async def get_recent_orders(
        self,
        account_id: AccountId,
        since: datetime,
    ) -> tuple[BrokerOrder, ...]:
        return await self._orders(account_id, since=since)

    async def get_fills(self, account_id: AccountId, since: datetime) -> tuple[Fill, ...]:
        await self._orders(account_id, since=since)
        return ()

    async def get_buying_power(
        self,
        account_id: AccountId,
        asset_class: AssetClass,
    ) -> Decimal:
        if asset_class is not AssetClass.EQUITY:
            raise EquityReadError("equity adapter supplies only equity buying power")
        return (await self.get_account_state(account_id)).buying_power_for(asset_class)

    async def health_check(self) -> BrokerHealth:
        try:
            account = await self._snapshot()
            await self.get_positions(account.account_id)
            await self.get_open_orders(account.account_id)
        except Exception:
            return BrokerHealth(False, self._clock.now(), None, ("equity_mcp_read_unhealthy",))
        return BrokerHealth(True, self._clock.now(), None, ())


def build_equity_read_adapter(
    manifest: CapabilityManifest,
    transport: RobinhoodMcpTransport | None,
    *,
    clock: Clock | None = None,
    expected_account_fingerprint: str | None = None,
) -> RobinhoodEquityReadAdapter:
    for operation in REQUIRED_EQUITY_READ_OPERATIONS:
        try:
            record = manifest.find(provider="robinhood-trading", operation=operation)
        except LookupError:
            raise CapabilityNotVerified(f"{operation} requires schema-declared evidence") from None
        if not record.satisfies(EvidenceLevel.SCHEMA_DECLARED):
            raise CapabilityNotVerified(f"{operation} requires schema-declared evidence")
        if not record.satisfies(EvidenceLevel.AUTHENTICATED_READ_VERIFIED):
            raise CapabilityNotVerified(
                f"{operation} requires authenticated-read-verified evidence"
            )
    if not mapping_ready():
        raise CapabilityNotVerified("authenticated response mapping evidence is unavailable")
    if transport is None or clock is None or expected_account_fingerprint is None:
        raise CapabilityNotVerified("connected read composition is incomplete")
    return RobinhoodEquityReadAdapter(
        transport,
        clock,
        expected_account_fingerprint=expected_account_fingerprint,
    )


__all__ = [
    "REQUIRED_EQUITY_READ_OPERATIONS",
    "CapabilityNotVerified",
    "EquityReadError",
    "RobinhoodEquityReadAdapter",
    "build_equity_read_adapter",
]
