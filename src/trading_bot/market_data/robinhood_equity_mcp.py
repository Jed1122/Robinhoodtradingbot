"""Authenticated Robinhood Trading MCP equity quote and historical reads."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from trading_bot.brokers.robinhood_equity_mapping import (
    EquityMappingError,
    EquityTradability,
    map_historical_result,
    map_quote,
    map_tradability,
    utc_text,
)
from trading_bot.brokers.robinhood_equity_schemas import (
    EquityHistoricalsResultDto,
    EquityQuotesResultDto,
    EquityTradabilityResultDto,
)
from trading_bot.brokers.robinhood_mcp_schema_gate import JsonValue
from trading_bot.brokers.robinhood_mcp_transport import RobinhoodMcpTransport
from trading_bot.clock import Clock, require_utc
from trading_bot.domain import (
    AccountId,
    AssetClass,
    Bar,
    BarInterval,
    CorporateAction,
    EarningsEvent,
    Instrument,
    InstrumentId,
    MarketClock,
    Quote,
    SpreadEstimate,
)
from trading_bot.market_data import MarketDataCapability, MarketDataCapabilityError, content_hash

ModelT = TypeVar("ModelT", bound=BaseModel)

_PROVIDER_INTERVAL = {
    BarInterval.ONE_MINUTE: "minute",
    BarInterval.FIVE_MINUTE: "5minute",
    BarInterval.ONE_HOUR: "hour",
    BarInterval.FOUR_HOUR: "4hour",
    BarInterval.ONE_DAY: "day",
}


class RobinhoodEquityMarketData:
    capabilities = (
        MarketDataCapability.INFORMATIONAL_QUOTE,
        MarketDataCapability.BARS,
        MarketDataCapability.SPREAD_ESTIMATE,
    )

    def __init__(
        self,
        transport: RobinhoodMcpTransport,
        clock: Clock,
        *,
        maximum_quote_age: timedelta,
    ) -> None:
        if maximum_quote_age <= timedelta(0):
            raise ValueError("maximum_quote_age must be positive")
        self._transport = transport
        self._clock = clock
        self._maximum_quote_age = maximum_quote_age

    async def _call(
        self,
        tool_name: str,
        arguments: dict[str, JsonValue],
        model: type[ModelT],
    ) -> ModelT:
        result = await self._transport.call_tool(tool_name, arguments)
        if result.is_error or result.structured_content is None:
            raise MarketDataCapabilityError("MCP market read returned no structured content")
        try:
            return model.model_validate(result.structured_content)
        except ValidationError:
            raise MarketDataCapabilityError("MCP market response shape is incompatible") from None

    async def get_quote(self, instrument_id: InstrumentId) -> Quote:
        response = await self._call(
            "get_equity_quotes",
            {"symbols": [str(instrument_id)]},
            EquityQuotesResultDto,
        )
        if response.data.closes_error is not None or len(response.data.results) != 1:
            raise MarketDataCapabilityError("expected one complete equity quote result")
        digest = content_hash(response.model_dump(mode="json"))
        try:
            return map_quote(
                response.data.results[0].quote,
                instrument_id=instrument_id,
                received_at=self._clock.now(),
                data_hash=digest,
                maximum_age=self._maximum_quote_age,
            )
        except EquityMappingError as exc:
            raise MarketDataCapabilityError("equity quote validation failed") from exc

    async def get_executable_quote(
        self,
        instrument_id: InstrumentId,
        quantity: Decimal,
    ) -> Quote:
        del instrument_id, quantity
        raise MarketDataCapabilityError("Trading MCP quote reads are not execution estimates")

    async def get_bars(
        self,
        instrument_id: InstrumentId,
        interval: BarInterval,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]:
        start = require_utc(start)
        end = require_utc(end)
        if start >= end:
            raise MarketDataCapabilityError("historical start must precede end")
        response = await self._call(
            "get_equity_historicals",
            {
                "adjustment_type": "split",
                "bounds": "regular",
                "end_time": utc_text(end),
                "interval": _PROVIDER_INTERVAL[interval],
                "start_time": utc_text(start),
                "symbols": [str(instrument_id)],
            },
            EquityHistoricalsResultDto,
        )
        if response.data.not_found or len(response.data.results) != 1:
            raise MarketDataCapabilityError("expected one equity historical result")
        digest = content_hash(response.model_dump(mode="json"))
        try:
            return map_historical_result(
                response.data.results[0],
                instrument_id=instrument_id,
                interval=interval,
                data_hash=digest,
            )
        except EquityMappingError as exc:
            raise MarketDataCapabilityError("equity historical validation failed") from exc

    async def get_tradability(
        self,
        account_id: AccountId,
        *,
        account_type: str,
        instrument_id: InstrumentId,
    ) -> EquityTradability:
        response = await self._call(
            "get_equity_tradability",
            {
                "account_number": str(account_id),
                "symbols": [str(instrument_id)],
            },
            EquityTradabilityResultDto,
        )
        digest = content_hash(response.model_dump(mode="json"))
        try:
            return map_tradability(
                response,
                symbol=str(instrument_id),
                account_type=account_type,
                observed_at=self._clock.now(),
                data_hash=digest,
            )
        except EquityMappingError as exc:
            raise MarketDataCapabilityError("equity tradability validation failed") from exc

    async def get_market_clock(self, asset_class: AssetClass) -> MarketClock:
        del asset_class
        raise MarketDataCapabilityError("Trading MCP market-clock mapping is not verified")

    async def get_corporate_actions(
        self,
        instrument_id: InstrumentId,
        start: date,
        end: date,
    ) -> tuple[CorporateAction, ...]:
        del instrument_id, start, end
        raise MarketDataCapabilityError("Trading MCP corporate actions are not verified")

    async def get_earnings_calendar(
        self,
        instrument_ids: tuple[InstrumentId, ...],
        start: date,
        end: date,
    ) -> tuple[EarningsEvent, ...]:
        del instrument_ids, start, end
        raise MarketDataCapabilityError("Trading MCP earnings mapping is not verified")

    async def get_instrument_metadata(self, instrument_id: InstrumentId) -> Instrument:
        del instrument_id
        raise MarketDataCapabilityError("Trading MCP tick-size metadata is not verified")

    async def get_spread_estimate(self, instrument_id: InstrumentId) -> SpreadEstimate:
        quote = await self.get_quote(instrument_id)
        midpoint = (quote.bid + quote.ask) / 2
        return SpreadEstimate(
            instrument_id=instrument_id,
            observed_at=quote.observed_at,
            absolute=quote.ask - quote.bid,
            percentage=(quote.ask - quote.bid) * 100 / midpoint,
            data_hash=quote.data_hash,
        )


__all__ = ["RobinhoodEquityMarketData"]
