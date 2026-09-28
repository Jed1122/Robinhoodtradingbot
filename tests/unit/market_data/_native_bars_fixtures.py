"""Fabricated DBN observations only; never provider data or historical evidence."""

import hashlib
import importlib
from datetime import date
from types import SimpleNamespace

import pytest

dbn = pytest.importorskip("databento_dbn")
zstd = pytest.importorskip("zstandard")
START = 1704153600000000000
END = 1705881600000000000
STAMP = 1704205800000000000
MINUTE = 60_000_000_000
PRICES = (100000000000, 102000000000, 99000000000, 101000000000)


def models():
    try:
        return importlib.import_module("trading_bot.market_data.databento_bar_models")
    except ModuleNotFoundError:
        pytest.fail("native bar models are not implemented")


def api():
    try:
        return importlib.import_module("trading_bot.market_data.databento_bars")
    except ModuleNotFoundError:
        pytest.fail("native bar scanner is not implemented")


def native_record(*, stamp=STAMP, prices=PRICES, instrument_id=42, publisher_id=2, volume=100):
    return bytes(
        dbn.OHLCVMsg(
            rtype=dbn.RType.OHLCV_1M,
            publisher_id=publisher_id,
            instrument_id=instrument_id,
            ts_event=stamp,
            open=prices[0],
            high=prices[1],
            low=prices[2],
            close=prices[3],
            volume=volume,
        )
    )


def native_bytes(*, version=1, count=1, prices=PRICES, metadata_changes=None, records=None):
    metadata = {
        "dataset": "XNAS.ITCH",
        "schema": dbn.Schema.OHLCV_1M,
        "stype_in": dbn.SType.RAW_SYMBOL,
        "stype_out": dbn.SType.INSTRUMENT_ID,
        "start": START,
        "end": END,
        "symbols": ["SPY"],
        "version": version,
        "mappings": [
            SimpleNamespace(
                raw_symbol="SPY",
                intervals=[
                    SimpleNamespace(
                        start_date=date(2024, 1, 2),
                        end_date=date(2024, 1, 22),
                        symbol="42",
                    )
                ],
            )
        ],
    }
    metadata.update(metadata_changes or {})
    payload = (
        b"".join(native_record(stamp=STAMP + i * MINUTE, prices=prices) for i in range(count))
        if records is None
        else b"".join(records)
    )
    return dbn.Metadata(**metadata).encode() + payload


def bar_fixture(*, version=1, count=1, prices=PRICES):
    body = zstd.ZstdCompressor(write_checksum=True).compress(
        native_bytes(version=version, count=count, prices=prices)
    )
    return body, models().NativeBarRequest(START, END), hashlib.sha256(body).hexdigest()
