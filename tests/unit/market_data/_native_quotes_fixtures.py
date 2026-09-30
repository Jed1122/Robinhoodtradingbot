"""Fabricated DBN quote bytes only; not licensed data or economic evidence."""

import hashlib
import importlib
from datetime import date
from types import SimpleNamespace

import pytest

dbn = pytest.importorskip("databento_dbn")
zstd = pytest.importorskip("zstandard")
START = 1704153600000000000
END = 1704240000000000000
STAMP = 1704205800000000000
SYMBOL = "SPY   240119C00475000"


def module(name):
    try:
        return importlib.import_module("trading_bot.market_data.databento_" + name)
    except ModuleNotFoundError:
        pytest.fail("native quote module is not implemented: " + name)


def request(*, underlying=False):
    return module("quote_models").NativeQuoteRequest(
        "XNAS.ITCH" if underlying else "OPRA.PILLAR",
        "mbp-1" if underlying else "cmbp-1",
        "raw_symbol",
        ("SPY",) if underlying else (SYMBOL,),
        START,
        END,
    )


def record(
    *,
    underlying=False,
    bid=1000000001,
    ask=1200000003,
    stamp=STAMP,
    recv=STAMP + 1,
    flags=128,
    action="A",
    sequence=1,
    **changes,
):
    values = dict(
        publisher_id=2 if underlying else 30,
        instrument_id=42,
        ts_event=stamp,
        ts_recv=recv,
        price=1000000001,
        size=2,
        action=dbn.Action(action),
        side=dbn.Side.NONE if action == "R" else dbn.Side.BID,
        flags=flags,
        ts_in_delta=0,
    )
    if underlying:
        values.update(
            depth=0,
            sequence=sequence,
            levels=dbn.BidAskPair(bid_px=bid, ask_px=ask, bid_sz=2, ask_sz=3, bid_ct=1, ask_ct=1),
        )
        factory = dbn.MBP1Msg
    else:
        values.update(
            rtype=dbn.RType.CMBP_1,
            levels=dbn.ConsolidatedBidAskPair(
                bid_px=bid, ask_px=ask, bid_sz=2, ask_sz=3, bid_pb=20, ask_pb=22
            ),
        )
        factory = dbn.CMBP1Msg
    values.update(changes)
    return bytes(factory(**values))


def native(records=None, *, underlying=False, version=3, metadata_changes=None):
    symbol = "SPY" if underlying else SYMBOL
    values = dict(
        dataset="XNAS.ITCH" if underlying else "OPRA.PILLAR",
        schema=dbn.Schema.MBP_1 if underlying else dbn.Schema.CMBP_1,
        stype_in=dbn.SType.RAW_SYMBOL,
        stype_out=dbn.SType.INSTRUMENT_ID,
        start=START,
        end=END,
        symbols=[symbol],
        version=version,
        mappings=[
            SimpleNamespace(
                raw_symbol=symbol,
                intervals=[
                    SimpleNamespace(
                        start_date=date(2024, 1, 2), end_date=date(2024, 1, 3), symbol="42"
                    )
                ],
            )
        ],
    )
    values.update(metadata_changes or {})
    return dbn.Metadata(**values).encode() + b"".join(
        [record(underlying=underlying)] if records is None else records
    )


def compressed(records=None, **kwargs):
    return zstd.ZstdCompressor(write_checksum=True).compress(native(records, **kwargs))


def scan(body=None, *, underlying=False, limits=None):
    from io import BytesIO

    from trading_bot.market_data.databento_native_io import DefinitionLimits

    if body is None:
        body = compressed(underlying=underlying)
    rows = []
    profile = module("quotes").scan_quotes(
        BytesIO(body),
        expected=request(underlying=underlying),
        expected_sha256=hashlib.sha256(body).hexdigest(),
        limits=limits or DefinitionLimits(),
        consume=rows.append,
    )
    return profile, rows
