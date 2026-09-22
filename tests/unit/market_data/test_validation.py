from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.domain import DataHash, InstrumentId, Quote, TimestampSource
from trading_bot.market_data import (
    MarketDataValidationPolicy,
    MarketDataValidator,
    RejectedMarketData,
    ValidatingMarketDataProvider,
)

NOW = datetime(2026, 7, 17, tzinfo=UTC)
INSTRUMENT = InstrumentId("AAPL")


def quote(**overrides: object) -> Quote:
    values: dict[str, object] = {
        "instrument_id": INSTRUMENT,
        "observed_at": NOW - timedelta(seconds=1),
        "bid": Decimal("100"),
        "ask": Decimal("101"),
        "last": Decimal("100.5"),
        "source": "fixture",
        "data_hash": DataHash("a" * 64),
        "freshness_verified": True,
        "timestamp_source": TimestampSource.PROVIDER,
    }
    values.update(overrides)
    return Quote(**values)  # type: ignore[arg-type]


def validator() -> MarketDataValidator:
    return MarketDataValidator(MarketDataValidationPolicy(Decimal("5"), Decimal("10")))


def test_invalid_quote_identity_and_freshness_are_rejected() -> None:
    wrong = quote(instrument_id=InstrumentId("WRONG"), observed_at=NOW - timedelta(seconds=6))
    result = validator().validate_quote(
        wrong, expected_instrument=INSTRUMENT, now=NOW, previous=None
    )
    assert result.value is None
    assert {event.code for event in result.events} == {"instrument_mismatch", "stale_quote"}


def test_executable_quote_requires_provider_timestamp() -> None:
    untrusted = quote(freshness_verified=False, timestamp_source=TimestampSource.LOCAL_RECEIPT)
    result = validator().validate_quote(
        untrusted, expected_instrument=INSTRUMENT, now=NOW, previous=None, executable=True
    )
    assert result.value is None
    assert "nonexecutable_quote" in {event.code for event in result.events}


def test_unconfirmed_price_anomaly_is_rejected() -> None:
    result = validator().validate_quote(
        quote(last=Decimal("120")),
        expected_instrument=INSTRUMENT,
        now=NOW,
        previous=quote(),
    )
    assert result.value is None
    assert result.events[0].code == "unconfirmed_price_anomaly"


class FixedClock:
    def now(self) -> datetime:
        return NOW


class Inner:
    async def get_quote(self, instrument_id: InstrumentId) -> Quote:
        return quote(observed_at=NOW - timedelta(seconds=6))


class Sink:
    events = ()

    async def append_all(self, events: tuple) -> None:
        self.events = events


@pytest.mark.asyncio
async def test_rejection_is_journaled_before_exception() -> None:
    sink = Sink()
    provider = ValidatingMarketDataProvider(Inner(), validator(), sink, FixedClock())  # type: ignore[arg-type]
    with pytest.raises(RejectedMarketData):
        await provider.get_quote(INSTRUMENT)
    assert sink.events and sink.events[0].code == "stale_quote"
