"""Only synthetic local data; never use this helper to construct promotion evidence."""

from datetime import UTC, datetime, timedelta

from trading_bot.domain import InstrumentId
from trading_bot.market_data.bundle_models import BundleLimits, InstrumentMapping, SourceCapture
from trading_bot.market_data.recording import canonical_json

START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(days=2)
ID = InstrumentId("SYNTH")
LIMITS = BundleLimits(131072, 65536, 1048576, 1000, 16)


def fixture_rows() -> list[dict]:
    slots = tuple(
        {"starts_at": START + timedelta(days=i), "ends_at": START + timedelta(days=i + 1)}
        for i in range(2)
    )
    rows = [
        {
            "kind": "baseline",
            "available_at": START,
            "price_basis": None,
            "value": {
                "instrument_id": ID,
                "coverage_start": START,
                "effective_at": START,
                "announced_at": START,
                "included": True,
            },
        }
    ]
    for slot in slots:
        rows.append(
            {
                "kind": "bar",
                "available_at": slot["ends_at"],
                "price_basis": "unadjusted",
                "value": {
                    "instrument_id": ID,
                    "interval": "one_day",
                    **slot,
                    "open": "10",
                    "high": "11",
                    "low": "9",
                    "close": "10",
                    "volume": "100",
                    "source": "fixture",
                    "interpolated": False,
                },
            }
        )
    for kind in ("bar", "membership", "corporate_action"):
        rows.append(
            {
                "kind": "coverage",
                "available_at": START,
                "price_basis": None,
                "value": {
                    "instrument_id": ID,
                    "record_kind": kind,
                    "interval": "one_day" if kind == "bar" else None,
                    "starts_at": START,
                    "ends_at": END,
                    "state": "complete",
                    "expected_slots": slots if kind == "bar" else (),
                },
            }
        )
    return rows


def fixture_sources(*, rows: list[dict] | None = None) -> tuple[SourceCapture, ...]:
    records = fixture_rows() if rows is None else rows
    body = canonical_json({"schema": "synthetic-market-v1", "records": records}).encode()
    kinds = tuple(sorted({row["kind"] for row in records}))
    return (SourceCapture("fixture", "synthetic", (ID,), kinds, START, END, END, None, (), body),)


def fixture_package():
    from trading_bot.market_data.bundle_normalize import assemble_bundle

    return assemble_bundle(
        sources=fixture_sources(), instruments=(InstrumentMapping(ID, "SYNTH"),), limits=LIMITS
    )
