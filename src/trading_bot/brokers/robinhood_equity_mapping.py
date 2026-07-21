"""Authenticated-shape-backed Robinhood Trading MCP equity mappings."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from trading_bot.brokers.robinhood_equity_schemas import (
    EquityAccountDto,
    EquityBarDto,
    EquityHistoricalResultDto,
    EquityQuoteDto,
    EquityTradabilityResultDto,
    PortfolioResultDto,
)
from trading_bot.clock import require_utc
from trading_bot.domain import (
    AccountId,
    AccountSnapshot,
    AssetBuyingPower,
    AssetClass,
    Bar,
    BarInterval,
    DataHash,
    DomainValidationError,
    InstrumentId,
    Quote,
    TimestampSource,
    parse_decimal,
)

AUTHENTICATED_SHAPE_SHA256 = "27b009a26d590d74a12eed0e933ddb302ce623f06f44fc05270992e17df8825f"
AUTHENTICATED_SHAPE_PATH = (
    Path(__file__).parent / "schema_snapshots/robinhood_equity_mcp.authenticated_shapes.json"
)
VERIFIED_EQUITY_FIELDS: tuple[str, ...] = (
    "get_accounts.data.accounts[].account_number",
    "get_accounts.data.accounts[].agentic_allowed",
    "get_accounts.data.accounts[].brokerage_account_type",
    "get_accounts.data.accounts[].deactivated",
    "get_accounts.data.accounts[].permanently_deactivated",
    "get_accounts.data.accounts[].state",
    "get_accounts.data.accounts[].type",
    "get_portfolio.data.buying_power.buying_power",
    "get_portfolio.data.buying_power.display_currency",
    "get_portfolio.data.buying_power.unleveraged_buying_power",
    "get_portfolio.data.cash",
    "get_portfolio.data.currency",
    "get_portfolio.data.total_value",
    "get_equity_positions.data.positions(empty)",
    "get_equity_orders.data.orders(empty)",
    "get_equity_quotes.data.results[].quote",
    "get_equity_tradability.data.results[]",
    "get_equity_historicals.data.results[].bars[]",
)


class EquityMappingError(RuntimeError):
    """Raised when a provider value violates the authenticated mapping contract."""


class UnverifiedNonemptyShape(EquityMappingError):
    """Raised for row shapes not observed in the funded account's authenticated probe."""


@dataclass(frozen=True, slots=True)
class EquityTradability:
    symbol: str
    provider_state: str
    tradeable: bool
    fractional_tradeable: bool
    account_type_tradability: str
    observed_at: datetime
    data_hash: DataHash


def _canonical_shape_payload(artifact: dict[str, object]) -> bytes:
    payload = dict(artifact)
    payload.pop("shape_sha256", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def mapping_ready(path: Path = AUTHENTICATED_SHAPE_PATH) -> bool:
    try:
        artifact: object = json.loads(path.read_text(encoding="utf-8"))
        if type(artifact) is not dict:
            return False
        shape_hash = artifact.get("shape_sha256")
        if shape_hash != AUTHENTICATED_SHAPE_SHA256:
            return False
        if artifact.get("contains_account_data") is not False:
            return False
        observed = hashlib.sha256(_canonical_shape_payload(artifact)).hexdigest()
        tools = artifact.get("tools")
        return (
            observed == AUTHENTICATED_SHAPE_SHA256
            and type(tools) is dict
            and {
                "get_accounts",
                "get_portfolio",
                "get_equity_positions",
                "get_equity_orders",
                "get_equity_quotes",
                "get_equity_tradability",
                "get_equity_historicals",
            }
            <= set(tools)
        )
    except (OSError, TypeError, ValueError):
        return False


def account_fingerprint(account_id: AccountId | str) -> str:
    value = str(account_id)
    if not value:
        raise EquityMappingError("account identity is empty")
    return hashlib.sha256(value.encode()).hexdigest()


def _decimal(value: str, field_name: str, *, nonnegative: bool = True) -> Decimal:
    try:
        parsed = parse_decimal(value)
    except DomainValidationError as exc:
        raise EquityMappingError(f"{field_name} is not an exact decimal") from exc
    if nonnegative and parsed < 0:
        raise EquityMappingError(f"{field_name} cannot be negative")
    return parsed


def _timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return require_utc(parsed)
    except (TypeError, ValueError) as exc:
        raise EquityMappingError(f"{field_name} is not an aware UTC timestamp") from exc


def map_account(
    account: EquityAccountDto,
    portfolio: PortfolioResultDto,
    *,
    observed_at: datetime,
    data_hash: DataHash,
) -> AccountSnapshot:
    observed_at = require_utc(observed_at)
    if account.type != "cash" or account.brokerage_account_type != "individual":
        raise EquityMappingError(
            "connected shadow supports only the reviewed individual cash account"
        )
    values = portfolio.data
    buying_power = values.buying_power
    if values.currency != "USD" or buying_power.display_currency != "USD":
        raise EquityMappingError("connected shadow supports only USD portfolio values")
    spendable = _decimal(buying_power.buying_power, "buying_power")
    unleveraged = _decimal(buying_power.unleveraged_buying_power, "unleveraged_buying_power")
    if spendable != unleveraged:
        raise EquityMappingError("cash-account buying power unexpectedly contains leverage")
    restricted = bool(
        account.state != "active"
        or account.deactivated
        or account.permanently_deactivated
        or not account.agentic_allowed
    )
    return AccountSnapshot(
        account_id=AccountId(account.account_number),
        provider_state=account.state,
        equity=_decimal(values.total_value, "total_value"),
        cash=_decimal(values.cash, "cash"),
        buying_power=(AssetBuyingPower(AssetClass.EQUITY, spendable),),
        restricted=restricted,
        observed_at=observed_at,
        data_hash=data_hash,
    )


def ensure_authenticated_empty_collection(
    rows: list[dict[str, object] | None],
    *,
    collection_name: str,
    next_page: str | None,
) -> None:
    if rows or next_page is not None:
        raise UnverifiedNonemptyShape(
            f"{collection_name} nonempty or paginated row shape requires authenticated review"
        )


def map_quote(
    dto: EquityQuoteDto,
    *,
    instrument_id: InstrumentId,
    received_at: datetime,
    data_hash: DataHash,
    maximum_age: timedelta,
) -> Quote:
    received_at = require_utc(received_at)
    if dto.symbol != str(instrument_id):
        raise EquityMappingError("quote symbol identity changed")
    if not dto.has_traded or dto.state != "active":
        raise EquityMappingError("quote instrument is not actively traded")
    bid_at = _timestamp(dto.venue_bid_time, "venue_bid_time")
    ask_at = _timestamp(dto.venue_ask_time, "venue_ask_time")
    observed_at = max(bid_at, ask_at)
    if observed_at > received_at or received_at - min(bid_at, ask_at) > maximum_age:
        raise EquityMappingError("two-sided quote is stale or future-dated")
    last = _decimal(dto.last_trade_price, "last_trade_price")
    last_at = _timestamp(dto.venue_last_trade_time, "venue_last_trade_time")
    if (
        dto.last_non_reg_trade_price is not None
        and dto.venue_last_non_reg_trade_time is not None
        and _timestamp(dto.venue_last_non_reg_trade_time, "venue_last_non_reg_trade_time") > last_at
    ):
        last = _decimal(dto.last_non_reg_trade_price, "last_non_reg_trade_price")
    return Quote(
        instrument_id=instrument_id,
        observed_at=observed_at,
        bid=_decimal(dto.bid_price, "bid_price"),
        ask=_decimal(dto.ask_price, "ask_price"),
        last=last,
        source="robinhood_trading_mcp",
        data_hash=data_hash,
        freshness_verified=True,
        timestamp_source=TimestampSource.PROVIDER,
    )


_INTERVALS: dict[tuple[str, BarInterval], timedelta] = {
    ("minute", BarInterval.ONE_MINUTE): timedelta(minutes=1),
    ("5minute", BarInterval.FIVE_MINUTE): timedelta(minutes=5),
    ("hour", BarInterval.ONE_HOUR): timedelta(hours=1),
    ("4hour", BarInterval.FOUR_HOUR): timedelta(hours=4),
    ("day", BarInterval.ONE_DAY): timedelta(days=1),
}


def map_bar(
    dto: EquityBarDto,
    *,
    instrument_id: InstrumentId,
    interval: BarInterval,
    provider_interval: str,
    data_hash: DataHash,
) -> Bar:
    duration = _INTERVALS.get((provider_interval, interval))
    if duration is None:
        raise EquityMappingError("historical interval identity changed")
    starts_at = _timestamp(dto.begins_at, "begins_at")
    if dto.session not in {None, "reg"}:
        raise EquityMappingError("connected shadow accepts regular-session bars only")
    return Bar(
        instrument_id=instrument_id,
        interval=interval,
        starts_at=starts_at,
        ends_at=starts_at + duration,
        open=_decimal(dto.open_price, "open_price"),
        high=_decimal(dto.high_price, "high_price"),
        low=_decimal(dto.low_price, "low_price"),
        close=_decimal(dto.close_price, "close_price"),
        volume=Decimal(dto.volume),
        source="robinhood_trading_mcp",
        data_hash=data_hash,
        interpolated=dto.interpolated,
    )


def map_historical_result(
    result: EquityHistoricalResultDto,
    *,
    instrument_id: InstrumentId,
    interval: BarInterval,
    data_hash: DataHash,
) -> tuple[Bar, ...]:
    if result.symbol != str(instrument_id) or result.bounds != "regular":
        raise EquityMappingError("historical response identity changed")
    bars = tuple(
        map_bar(
            item,
            instrument_id=instrument_id,
            interval=interval,
            provider_interval=result.interval,
            data_hash=data_hash,
        )
        for item in result.bars
    )
    if tuple(item.starts_at for item in bars) != tuple(sorted(item.starts_at for item in bars)):
        raise EquityMappingError("historical bars are not time ordered")
    if len({item.starts_at for item in bars}) != len(bars):
        raise EquityMappingError("historical bars contain duplicate timestamps")
    return bars


def map_tradability(
    result: EquityTradabilityResultDto,
    *,
    symbol: str,
    account_type: str,
    observed_at: datetime,
    data_hash: DataHash,
) -> EquityTradability:
    if result.data.not_found:
        raise EquityMappingError("tradability symbol was not found")
    matches = tuple(item for item in result.data.results if item.symbol == symbol)
    if len(matches) != 1:
        raise EquityMappingError("tradability symbol identity is not unique")
    item = matches[0]
    account_matches = tuple(
        value
        for value in (item.account_type_tradabilities or [])
        if value.account_type == account_type
    )
    if len(account_matches) != 1:
        raise EquityMappingError("account-type tradability is not unique")
    provider_state = item.state or "unknown"
    return EquityTradability(
        symbol=symbol,
        provider_state=provider_state,
        tradeable=(
            item.tradeable
            and provider_state == "active"
            and account_matches[0].account_type_tradability == "tradable"
        ),
        fractional_tradeable=item.fractional_tradability == "tradable",
        account_type_tradability=account_matches[0].account_type_tradability,
        observed_at=require_utc(observed_at),
        data_hash=data_hash,
    )


def utc_text(value: datetime) -> str:
    return require_utc(value).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "AUTHENTICATED_SHAPE_PATH",
    "AUTHENTICATED_SHAPE_SHA256",
    "VERIFIED_EQUITY_FIELDS",
    "EquityMappingError",
    "EquityTradability",
    "UnverifiedNonemptyShape",
    "account_fingerprint",
    "ensure_authenticated_empty_collection",
    "map_account",
    "map_historical_result",
    "map_quote",
    "map_tradability",
    "mapping_ready",
    "utc_text",
]
