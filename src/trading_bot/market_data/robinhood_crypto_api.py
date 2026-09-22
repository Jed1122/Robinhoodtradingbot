"""Official Crypto market-data adapter with timestamped two-sided executable estimates."""

from datetime import date, datetime
from decimal import Decimal

import httpx

from trading_bot.brokers.robinhood_crypto_api import CryptoRequester
from trading_bot.brokers.robinhood_crypto_mapping import (
    map_best_bid_ask,
    map_trading_pair,
)
from trading_bot.brokers.robinhood_crypto_schemas import (
    BestBidAskResponse,
    EstimatedPriceDto,
    EstimatedPriceResponse,
    TradingPairsResponse,
)
from trading_bot.brokers.robinhood_crypto_transport import RetryClass
from trading_bot.clock import Clock
from trading_bot.domain import (
    AssetClass,
    Bar,
    BarInterval,
    CorporateAction,
    DataHash,
    EarningsEvent,
    Instrument,
    InstrumentId,
    MarketClock,
    Quote,
    SpreadEstimate,
    TimestampSource,
)
from trading_bot.market_data import (
    MarketDataCapability,
    MarketDataCapabilityError,
    content_hash,
)

_MICROSECONDS = Decimal("1000000")


def _seconds(first: datetime, second: datetime) -> Decimal:
    delta = second - first
    return (
        Decimal((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds)
        / _MICROSECONDS
    )


class RobinhoodCryptoMarketData:
    capabilities = (
        MarketDataCapability.INFORMATIONAL_QUOTE,
        MarketDataCapability.EXECUTABLE_QUOTE,
        MarketDataCapability.INSTRUMENT_METADATA,
        MarketDataCapability.SPREAD_ESTIMATE,
    )

    def __init__(
        self,
        transport: CryptoRequester,
        clock: Clock,
        *,
        maximum_quote_age_seconds: Decimal = Decimal("5"),
        maximum_cross_response_skew_seconds: Decimal = Decimal("2"),
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._maximum_age = maximum_quote_age_seconds
        self._maximum_skew = maximum_cross_response_skew_seconds

    async def _get(self, path: str, *, query: tuple[tuple[str, str], ...]) -> httpx.Response:
        response = await self._transport.request(
            "GET", path, query=query, retry_class=RetryClass.READ_SAFE
        )
        response.raise_for_status()
        return response

    async def get_quote(self, instrument_id: InstrumentId) -> Quote:
        response = await self._get(
            "/api/v2/crypto/marketdata/best_bid_ask/", query=(("symbol", instrument_id),)
        )
        parsed = BestBidAskResponse.model_validate_json(response.content)
        if len(parsed.results) != 1:
            raise MarketDataCapabilityError("expected one bid/ask result")
        return map_best_bid_ask(
            parsed.results[0],
            received_at=self._clock.now(),
            data_hash=content_hash(parsed.model_dump(mode="json")),
        )

    async def _estimate(
        self, instrument_id: InstrumentId, quantity: Decimal, side: str
    ) -> tuple[EstimatedPriceDto, DataHash]:
        response = await self._get(
            "/api/v2/crypto/trading/estimated_price/",
            query=(("quantity", str(quantity)), ("side", side), ("symbol", instrument_id)),
        )
        parsed = EstimatedPriceResponse.model_validate_json(response.content)
        if len(parsed.results) != 1:
            raise MarketDataCapabilityError("expected one estimate")
        value = parsed.results[0]
        if value.symbol != instrument_id or value.side != side or value.quantity != quantity:
            raise MarketDataCapabilityError("estimated-price response identity mismatch")
        return value, content_hash(parsed.model_dump(mode="json"))

    async def get_executable_quote(self, instrument_id: InstrumentId, quantity: Decimal) -> Quote:
        sell, sell_hash = await self._estimate(instrument_id, quantity, "sell")
        buy, buy_hash = await self._estimate(instrument_id, quantity, "buy")
        now = self._clock.now()
        if any(
            _seconds(value.timestamp, now) < 0 or _seconds(value.timestamp, now) > self._maximum_age
            for value in (sell, buy)
        ):
            raise MarketDataCapabilityError("estimated price is stale")
        if abs(_seconds(sell.timestamp, buy.timestamp)) > self._maximum_skew:
            raise MarketDataCapabilityError("estimated-price responses exceed timestamp skew")
        if sell.estimated_price > buy.estimated_price:
            raise MarketDataCapabilityError("estimated executable market is crossed")
        pair_hash = content_hash((sell_hash, buy_hash))
        return Quote(
            instrument_id,
            max(sell.timestamp, buy.timestamp),
            sell.estimated_price,
            buy.estimated_price,
            None,
            "robinhood_crypto_estimated_price_pair",
            pair_hash,
            True,
            TimestampSource.PROVIDER,
        )

    async def get_bars(
        self, instrument_id: InstrumentId, interval: BarInterval, start: datetime, end: datetime
    ) -> tuple[Bar, ...]:
        raise MarketDataCapabilityError("official Crypto v2 bars are not documented")

    async def get_market_clock(self, asset_class: AssetClass) -> MarketClock:
        if asset_class is not AssetClass.CRYPTO:
            raise MarketDataCapabilityError("Crypto provider cannot supply another asset class")
        now = self._clock.now()
        return MarketClock(
            asset_class, "robinhood_crypto", now, True, False, False, False, None, None
        )

    async def get_corporate_actions(
        self, instrument_id: InstrumentId, start: date, end: date
    ) -> tuple[CorporateAction, ...]:
        raise MarketDataCapabilityError("Crypto corporate actions are unsupported")

    async def get_earnings_calendar(
        self, instrument_ids: tuple[InstrumentId, ...], start: date, end: date
    ) -> tuple[EarningsEvent, ...]:
        raise MarketDataCapabilityError("Crypto earnings are unsupported")

    async def get_instrument_metadata(self, instrument_id: InstrumentId) -> Instrument:
        response = await self._get(
            "/api/v2/crypto/trading/trading_pairs/", query=(("symbol", instrument_id),)
        )
        parsed = TradingPairsResponse.model_validate_json(response.content)
        if len(parsed.results) != 1:
            raise MarketDataCapabilityError("expected one trading pair")
        return map_trading_pair(
            parsed.results[0],
            observed_at=self._clock.now(),
            data_hash=content_hash(parsed.model_dump(mode="json")),
        )

    async def get_spread_estimate(self, instrument_id: InstrumentId) -> SpreadEstimate:
        quote = await self.get_quote(instrument_id)
        midpoint = (quote.bid + quote.ask) / 2
        return SpreadEstimate(
            instrument_id,
            quote.observed_at,
            quote.ask - quote.bid,
            (quote.ask - quote.bid) * 100 / midpoint,
            quote.data_hash,
        )


__all__ = ["RobinhoodCryptoMarketData"]
