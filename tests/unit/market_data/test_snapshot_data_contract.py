"""Independent synthetic-only contract tests for offline snapshot selection."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.domain import BarInterval, InstrumentId
from trading_bot.market_data.bundle_models import (
    BundleError,
    BundleLimits,
    InstrumentMapping,
    SnapshotSettings,
    SourceCapture,
)
from trading_bot.market_data.bundle_normalize import assemble_bundle
from trading_bot.market_data.bundle_verify import verify_bundle
from trading_bot.market_data.recording import canonical_json
from trading_bot.market_data.snapshot_loader import BundleSnapshotLoader
from trading_bot.strategies import FeaturePipeline

START = datetime(2026, 4, 1, tzinfo=UTC)
END = START + timedelta(days=2)
FIRST = InstrumentId("SYNTH-A")
SECOND = InstrumentId("SYNTH-B")
LIMITS = BundleLimits(131072, 65536, 1048576, 1000, 16)
SETTINGS = SnapshotSettings(BarInterval.ONE_DAY, START, 2)


def _rows(instrument: InstrumentId = FIRST) -> list[dict]:
    slots = [
        {"starts_at": START + timedelta(days=index), "ends_at": START + timedelta(days=index + 1)}
        for index in range(2)
    ]
    rows: list[dict] = [
        {
            "kind": "baseline",
            "available_at": START,
            "price_basis": None,
            "value": {
                "instrument_id": instrument,
                "coverage_start": START,
                "effective_at": START,
                "announced_at": START,
                "included": True,
            },
        }
    ]
    for index, slot in enumerate(slots):
        rows.append(
            {
                "kind": "bar",
                "available_at": slot["ends_at"],
                "price_basis": "unadjusted",
                "value": {
                    "instrument_id": instrument,
                    "interval": "one_day",
                    **slot,
                    "open": str(10 + index),
                    "high": str(11 + index),
                    "low": str(9 + index),
                    "close": str(10 + index),
                    "volume": "100",
                    "source": "synthetic-contract",
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
                    "instrument_id": instrument,
                    "record_kind": kind,
                    "interval": "one_day" if kind == "bar" else None,
                    "starts_at": START,
                    "ends_at": END,
                    "state": "complete",
                    "expected_slots": slots if kind == "bar" else [],
                },
            }
        )
    return rows


def _source(
    instrument: InstrumentId = FIRST,
    *,
    rows: list[dict] | None = None,
    source_id: str = "synthetic-contract",
    limitation_codes: tuple[str, ...] = (),
) -> SourceCapture:
    selected = deepcopy(_rows(instrument) if rows is None else rows)
    for row in selected:
        if row["kind"] == "bar":
            row["value"]["source"] = source_id
    body = canonical_json({"schema": "synthetic-market-v1", "records": selected}).encode()
    return SourceCapture(
        source_id,
        "synthetic",
        (instrument,),
        tuple(sorted({row["kind"] for row in selected})),
        START,
        END,
        END,
        None,
        limitation_codes,
        body,
    )


def _loader(
    *,
    sources: tuple[SourceCapture, ...] | None = None,
    mappings: tuple[InstrumentMapping, ...] | None = None,
    settings: SnapshotSettings = SETTINGS,
) -> BundleSnapshotLoader:
    package = assemble_bundle(
        sources=(_source(),) if sources is None else sources,
        instruments=(InstrumentMapping(FIRST, "SYNA"),) if mappings is None else mappings,
        limits=LIMITS,
    )
    return BundleSnapshotLoader(verify_bundle(package, limits=LIMITS), settings=settings)


def _membership(
    instrument: InstrumentId,
    *,
    included: bool,
    effective_at: datetime,
    announced_at: datetime,
    available_at: datetime,
) -> dict:
    return {
        "kind": "membership",
        "available_at": available_at,
        "price_basis": None,
        "value": {
            "instrument_id": instrument,
            "effective_at": effective_at,
            "announced_at": announced_at,
            "included": included,
        },
    }


def _future_source() -> SourceCapture:
    rows = _rows()
    shift = END - START
    for row in rows:
        row["available_at"] += shift
        value = row["value"]
        for field in ("starts_at", "ends_at", "coverage_start", "effective_at", "announced_at"):
            if field in value:
                value[field] += shift
        for slot in value.get("expected_slots", ()):
            slot["starts_at"] += shift
            slot["ends_at"] += shift
    source = _source(rows=rows, source_id="synthetic-future")
    return replace(
        source,
        requested_start=END,
        requested_end=END + shift,
        collected_at=END + shift,
        limitation_codes=("future_synthetic_only",),
    )


@pytest.mark.asyncio
async def test_two_instruments_preserve_requested_order_and_exact_values() -> None:
    loader = _loader(
        sources=(_source(), _source(SECOND, source_id="synthetic-second")),
        mappings=(InstrumentMapping(FIRST, "SYNA"), InstrumentMapping(SECOND, "SYNB")),
    )
    snapshot = await loader.load((SECOND, FIRST), END)
    assert tuple(history.instrument_id for history in snapshot.histories) == (SECOND, FIRST)
    assert tuple(bar.close for bar in snapshot.histories[0].bars) == (
        Decimal("10"),
        Decimal("11"),
    )
    assert all(history.spread_percentage is None for history in snapshot.histories)
    assert snapshot.data_hash != (await loader.load((FIRST, SECOND), END)).data_hash


@pytest.mark.asyncio
async def test_baseline_and_membership_events_obey_both_visibility_clocks() -> None:
    rows = _rows()
    rows.append(
        _membership(
            FIRST,
            included=False,
            effective_at=START + timedelta(hours=1),
            announced_at=START,
            available_at=START,
        )
    )
    with pytest.raises(BundleError, match=r"^snapshot_not_member$"):
        await _loader(sources=(_source(rows=rows),)).load((FIRST,), END)

    rows.append(
        _membership(
            FIRST,
            included=True,
            effective_at=START + timedelta(hours=2),
            announced_at=END,
            available_at=END,
        )
    )
    assert len((await _loader(sources=(_source(rows=rows),)).load((FIRST,), END)).histories) == 1
    for visibility_field in ("available_at", "announced_at"):
        hidden = deepcopy(rows)
        container = hidden[-1] if visibility_field == "available_at" else hidden[-1]["value"]
        container[visibility_field] = END + timedelta(microseconds=1)
        with pytest.raises(BundleError, match=r"^snapshot_not_member$"):
            await _loader(sources=(_source(rows=hidden),)).load((FIRST,), END)


@pytest.mark.asyncio
async def test_explicit_baseline_exclusion_denies_instead_of_shrinking_universe() -> None:
    rows = _rows(SECOND)
    rows[0]["value"]["included"] = False
    loader = _loader(
        sources=(_source(), _source(SECOND, rows=rows, source_id="synthetic-excluded")),
        mappings=(InstrumentMapping(FIRST, "SYNA"), InstrumentMapping(SECOND, "SYNB")),
    )
    with pytest.raises(BundleError, match=r"^snapshot_not_member$"):
        await loader.load((FIRST, SECOND), END)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("late_bar", "snapshot_records_unavailable"),
        ("gap", "snapshot_coverage_missing"),
        ("unknown", "snapshot_coverage_missing"),
        ("late_coverage", "snapshot_coverage_missing"),
        ("missing_baseline", "snapshot_membership_missing"),
        ("late_baseline", "snapshot_membership_missing"),
        ("excluded", "snapshot_not_member"),
        ("interpolated", "snapshot_interpolated"),
        ("adjusted", "snapshot_price_basis_unsupported"),
        ("unknown_basis", "snapshot_price_basis_unsupported"),
    ],
)
async def test_incomplete_or_unsupported_selected_data_is_denied(
    mutation: str, reason: str
) -> None:
    rows = _rows()
    if mutation == "late_bar":
        rows[1]["available_at"] = END + timedelta(seconds=1)
    elif mutation in {"gap", "unknown"}:
        rows[3]["value"].update(state=mutation, expected_slots=[])
    elif mutation == "late_coverage":
        rows[3]["available_at"] = END + timedelta(seconds=1)
    elif mutation == "missing_baseline":
        rows.pop(0)
    elif mutation == "late_baseline":
        rows[0]["available_at"] = END + timedelta(seconds=1)
    elif mutation == "excluded":
        rows[0]["value"]["included"] = False
    elif mutation == "interpolated":
        rows[1]["value"]["interpolated"] = True
    else:
        rows[1]["price_basis"] = "adjusted" if mutation == "adjusted" else "unknown"
    with pytest.raises(BundleError, match=rf"^{reason}$"):
        await _loader(sources=(_source(rows=rows),)).load((FIRST,), END)


@pytest.mark.asyncio
async def test_insufficient_history_is_denied_without_padding() -> None:
    loader = _loader(settings=replace(SETTINGS, minimum_bars=3))
    with pytest.raises(BundleError, match=r"^snapshot_history_insufficient$"):
        await loader.load((FIRST,), END)


@pytest.mark.asyncio
async def test_complete_no_action_coverage_is_a_valid_unadjusted_control() -> None:
    snapshot = await _loader().load((FIRST,), END)
    assert tuple(bar.close for bar in snapshot.histories[0].bars) == (
        Decimal("10"),
        Decimal("11"),
    )
    assert all(not bar.interpolated for bar in snapshot.histories[0].bars)


@pytest.mark.asyncio
@pytest.mark.parametrize("action_type", ["split", "dividend"])
@pytest.mark.parametrize("published_in_future", [False, True])
async def test_effective_corporate_action_is_denied_even_if_published_later(
    action_type: str, published_in_future: bool
) -> None:
    rows = _rows()
    published = END + timedelta(days=1) if published_in_future else START
    rows.append(
        {
            "kind": "corporate_action",
            "available_at": published,
            "price_basis": None,
            "value": {
                "instrument_id": FIRST,
                "action_type": action_type,
                "effective_date": START.date(),
                "announced_at": published,
                "split_ratio": "2" if action_type == "split" else None,
                "cash_amount": "0.25" if action_type == "dividend" else None,
            },
        }
    )
    with pytest.raises(BundleError, match=r"^snapshot_action_unsupported$"):
        await _loader(sources=(_source(rows=rows),)).load((FIRST,), END)


@pytest.mark.asyncio
async def test_disjoint_future_source_does_not_change_earlier_snapshot_or_features() -> None:
    original = _loader()
    extended = _loader(sources=(_source(), _future_source()))
    assert original.bundle_hash != extended.bundle_hash
    before = await original.load((FIRST,), END)
    after = await extended.load((FIRST,), END)
    assert before == after
    pipeline = FeaturePipeline(short_window=2, long_window=3)
    assert pipeline.compute(before.histories[0], as_of=END) == pipeline.compute(
        after.histories[0], as_of=END
    )
    assert all(bar.ends_at <= END for bar in after.histories[0].bars)


@pytest.mark.asyncio
async def test_selected_source_identity_change_changes_hash_not_prices() -> None:
    original = await _loader().load((FIRST,), END)
    changed = await _loader(
        sources=(_source(limitation_codes=("synthetic_selected_note",)),)
    ).load((FIRST,), END)
    assert original.data_hash != changed.data_hash
    assert tuple(bar.close for bar in original.histories[0].bars) == tuple(
        bar.close for bar in changed.histories[0].bars
    )
