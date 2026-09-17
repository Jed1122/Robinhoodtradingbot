from copy import deepcopy
from dataclasses import replace
from datetime import timedelta, timezone
from decimal import Decimal

import pytest

from tests.unit.market_data._bundle_fixtures import (
    END,
    ID,
    LIMITS,
    START,
    fixture_rows,
    fixture_sources,
)
from trading_bot.domain import BarInterval
from trading_bot.market_data.bundle_models import BundleError, InstrumentMapping, SnapshotSettings
from trading_bot.market_data.bundle_normalize import assemble_bundle
from trading_bot.market_data.bundle_verify import verify_bundle
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.market_data.snapshot_loader import BundleSnapshotLoader
from trading_bot.strategies import FeaturePipeline

SETTINGS = SnapshotSettings(BarInterval.ONE_DAY, START, 2)


def loader_for(rows=None, *, sources=None, mappings=None, settings=SETTINGS):
    package = assemble_bundle(
        sources=fixture_sources(rows=rows) if sources is None else sources,
        instruments=(InstrumentMapping(ID, "SYNTH"),) if mappings is None else mappings,
        limits=LIMITS,
    )
    return BundleSnapshotLoader(verify_bundle(package, limits=LIMITS), settings=settings)


@pytest.mark.asyncio
async def test_completed_bars_baseline_and_exact_hash_preimages() -> None:
    loader = loader_for()
    snapshot = await loader.load((ID,), END)
    assert snapshot == await loader.load((ID,), END)
    assert snapshot.as_of == END
    (history,) = snapshot.histories
    assert history.instrument_id == ID
    assert history.spread_percentage is None
    assert tuple(bar.close for bar in history.bars) == (Decimal("10"), Decimal("10"))
    assert tuple(bar.ends_at for bar in history.bars) == (START + timedelta(days=1), END)
    bundle = verify_bundle(
        assemble_bundle(
            sources=fixture_sources(), instruments=(InstrumentMapping(ID, "SYNTH"),), limits=LIMITS
        ),
        limits=LIMITS,
    )
    rows = bundle.envelope.records
    assert history.data_hash == content_hash(
        {
            "domain": "bundle-history-v1",
            "instrument_id": ID,
            "as_of": END,
            "settings": SETTINGS,
            "bars": (rows[1].record_hash, rows[2].record_hash),
            "membership": (rows[0].record_hash,),
            "coverage": (rows[3].record_hash, rows[5].record_hash, rows[4].record_hash),
            "classification": "synthetic",
            "limitations": loader.limitation_codes,
        }
    )
    assert snapshot.data_hash == content_hash(
        {
            "domain": "bundle-snapshot-v1",
            "as_of": END,
            "settings": SETTINGS,
            "universe": (ID,),
            "histories": (history.data_hash,),
        }
    )
    assert loader.bundle_hash == bundle.envelope.bundle_hash


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "universe,as_of",
    [
        ((), END),
        ([ID], END),
        ((ID, ID), END),
        (("MISSING",), END),
        ((ID,), END.replace(tzinfo=None)),
        ((ID,), END.astimezone(timezone(timedelta(hours=1)))),
        ((ID,), START),
        ((True,), END),
    ],
)
async def test_invalid_query_is_bounded(universe, as_of) -> None:
    with pytest.raises(BundleError, match=r"^snapshot_query_invalid$"):
        await loader_for().load(universe, as_of)


@pytest.mark.asyncio
async def test_minimum_history_is_not_padded_or_truncated() -> None:
    with pytest.raises(BundleError, match=r"^snapshot_history_insufficient$"):
        await loader_for(settings=replace(SETTINGS, minimum_bars=3)).load((ID,), END)
    with pytest.raises(BundleError, match=r"^snapshot_history_insufficient$"):
        await loader_for().load((ID,), START + timedelta(days=1))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,reason",
    [
        ("gap", "snapshot_coverage_missing"),
        ("unknown", "snapshot_coverage_missing"),
        ("unavailable_coverage", "snapshot_coverage_missing"),
        ("late_bar", "snapshot_records_unavailable"),
        ("interpolated", "snapshot_interpolated"),
        ("adjusted", "snapshot_price_basis_unsupported"),
        ("unknown_basis", "snapshot_price_basis_unsupported"),
        ("missing_baseline", "snapshot_membership_missing"),
        ("late_baseline", "snapshot_membership_missing"),
        ("late_baseline_announcement", "snapshot_membership_missing"),
        ("excluded_baseline", "snapshot_not_member"),
    ],
)
async def test_query_denials_do_not_reclassify_fixture(change, reason) -> None:
    rows = fixture_rows()
    if change in ("gap", "unknown"):
        rows[3]["value"].update(state=change, expected_slots=())
    elif change == "unavailable_coverage":
        rows[4]["available_at"] = END + timedelta(seconds=1)
    elif change == "late_bar":
        rows[1]["available_at"] = END + timedelta(seconds=1)
    elif change == "interpolated":
        rows[1]["value"]["interpolated"] = True
    elif change in ("adjusted", "unknown_basis"):
        rows[1]["price_basis"] = "unknown" if change == "unknown_basis" else "adjusted"
    elif change == "missing_baseline":
        rows.pop(0)
    elif change == "late_baseline":
        rows[0]["available_at"] = END + timedelta(seconds=1)
    elif change == "late_baseline_announcement":
        rows[0]["value"]["announced_at"] = END + timedelta(seconds=1)
    else:
        rows[0]["value"]["included"] = False
    with pytest.raises(BundleError, match=f"^{reason}$"):
        await loader_for(rows).load((ID,), END)


@pytest.mark.asyncio
async def test_interval_mismatch_has_no_inferred_coverage() -> None:
    with pytest.raises(BundleError, match=r"^snapshot_coverage_missing$"):
        await loader_for(settings=replace(SETTINGS, interval=BarInterval.ONE_HOUR)).load((ID,), END)


def event(*, included, effective_at, announced_at, available_at):
    return {
        "kind": "membership",
        "available_at": available_at,
        "price_basis": None,
        "value": {
            "instrument_id": ID,
            "effective_at": effective_at,
            "announced_at": announced_at,
            "included": included,
        },
    }


@pytest.mark.asyncio
async def test_membership_removal_reinclusion_and_visibility() -> None:
    rows = fixture_rows()
    rows.append(
        event(
            included=False,
            effective_at=START + timedelta(hours=1),
            announced_at=START,
            available_at=START,
        )
    )
    with pytest.raises(BundleError, match=r"^snapshot_not_member$"):
        await loader_for(rows).load((ID,), END)
    rows.append(
        event(
            included=True,
            effective_at=START + timedelta(hours=2),
            announced_at=END,
            available_at=END,
        )
    )
    assert len((await loader_for(rows).load((ID,), END)).histories) == 1
    for field in ("available_at", "announced_at"):
        changed = deepcopy(rows)
        target = changed[-1] if field == "available_at" else changed[-1]["value"]
        target[field] = END + timedelta(microseconds=1)
        with pytest.raises(BundleError, match=r"^snapshot_not_member$"):
            await loader_for(changed).load((ID,), END)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["split", "dividend"])
@pytest.mark.parametrize("future", [False, True])
async def test_effective_action_is_conservative_denial_even_if_known_later(kind, future) -> None:
    rows = fixture_rows()
    published = END + timedelta(days=1) if future else START
    rows.append(
        {
            "kind": "corporate_action",
            "available_at": published,
            "price_basis": None,
            "value": {
                "instrument_id": ID,
                "action_type": kind,
                "effective_date": START.date(),
                "announced_at": published,
                "split_ratio": "2" if kind == "split" else None,
                "cash_amount": "0.25" if kind == "dividend" else None,
            },
        }
    )
    with pytest.raises(BundleError, match=r"^snapshot_action_unsupported$"):
        await loader_for(rows).load((ID,), END)


def future_capture():
    source = fixture_sources()[0]
    rows = fixture_rows()
    shift = END - START
    for row in rows:
        row["available_at"] += shift
        value = row["value"]
        for key in ("starts_at", "ends_at", "effective_at", "announced_at", "coverage_start"):
            if key in value:
                value[key] += shift
        for slot in value.get("expected_slots", ()):
            slot["starts_at"] += shift
            slot["ends_at"] += shift
    return replace(
        source,
        requested_start=END,
        requested_end=END + shift,
        collected_at=END + shift,
        limitation_codes=("future_fixture_only",),
        raw_bytes=canonical_json({"schema": "synthetic-market-v1", "records": rows}).encode(),
    )


@pytest.mark.asyncio
async def test_disjoint_future_capture_preserves_earlier_snapshot_and_feature_hashes() -> None:
    original = loader_for()
    extended = loader_for(sources=(*fixture_sources(), future_capture()))
    assert original.bundle_hash != extended.bundle_hash
    first, later_bundle_same_time = await original.load((ID,), END), await extended.load((ID,), END)
    assert first == later_bundle_same_time
    pipeline = FeaturePipeline(short_window=2, long_window=3)
    assert pipeline.compute(first.histories[0], as_of=END) == pipeline.compute(
        later_bundle_same_time.histories[0], as_of=END
    )
    later = await extended.load((ID,), END + timedelta(days=2))
    assert later.data_hash != first.data_hash
    assert len(later.histories[0].bars) == 4  # Minimum 2 must not truncate complete history.
    assert all(bar.ends_at <= END for bar in first.histories[0].bars)


@pytest.mark.asyncio
async def test_two_instrument_requested_order_and_no_silent_shrinking() -> None:
    rows = fixture_rows()
    for row in rows:
        row["value"]["instrument_id"] = "SECOND"
    second = replace(fixture_sources(rows=rows)[0], instrument_ids=("SECOND",))
    mappings = (InstrumentMapping(ID, "SYNTH"), InstrumentMapping("SECOND", "SECOND"))
    loader = loader_for(sources=(*fixture_sources(), second), mappings=mappings)
    snapshot = await loader.load(("SECOND", ID), END)
    assert tuple(history.instrument_id for history in snapshot.histories) == ("SECOND", ID)
    assert snapshot.data_hash != (await loader.load((ID, "SECOND"), END)).data_hash
    rows[0]["value"]["included"] = False
    excluded = replace(fixture_sources(rows=rows)[0], instrument_ids=("SECOND",))
    with pytest.raises(BundleError, match=r"^snapshot_not_member$"):
        await loader_for(sources=(*fixture_sources(), excluded), mappings=mappings).load(
            (ID, "SECOND"), END
        )


@pytest.mark.asyncio
async def test_unknown_future_window_does_not_deny_earlier_query() -> None:
    source = future_capture()
    import json

    wire = json.loads(source.raw_bytes)
    for row in wire["records"]:
        if row["kind"] == "coverage":
            row["value"].update(state="unknown", expected_slots=[])
    future = replace(source, raw_bytes=canonical_json(wire).encode())
    loader = loader_for(sources=(*fixture_sources(), future))
    assert len((await loader.load((ID,), END)).histories[0].bars) == 2
    with pytest.raises(BundleError, match=r"^snapshot_coverage_missing$"):
        await loader.load((ID,), END + timedelta(days=1))


@pytest.mark.asyncio
async def test_selected_source_change_alters_snapshot_identity_without_changing_prices() -> None:
    original = loader_for()
    source = replace(fixture_sources()[0], limitation_codes=("selected_fixture_note",))
    changed = loader_for(sources=(source,))
    before, after = await original.load((ID,), END), await changed.load((ID,), END)
    assert before.data_hash != after.data_hash
    assert tuple(bar.close for bar in before.histories[0].bars) == tuple(
        bar.close for bar in after.histories[0].bars
    )


@pytest.mark.asyncio
async def test_late_past_bar_is_not_replaced_by_a_completed_future_capture() -> None:
    rows = fixture_rows()
    rows[1]["available_at"] = END + timedelta(days=1)
    loader = loader_for(sources=(*fixture_sources(rows=rows), future_capture()))
    with pytest.raises(BundleError, match=r"^snapshot_records_unavailable$"):
        await loader.load((ID,), END)


@pytest.mark.asyncio
async def test_explicit_coverage_hole_cannot_be_inferred_from_retained_bars() -> None:
    rows = fixture_rows()
    coverage = rows[4]
    middle = START + timedelta(days=1)
    rows[4] = {**coverage, "value": {**coverage["value"], "ends_at": middle}}
    rows.append(
        {**coverage, "value": {**coverage["value"], "starts_at": middle + timedelta(seconds=1)}}
    )
    with pytest.raises(BundleError, match=r"^snapshot_coverage_missing$"):
        await loader_for(rows).load((ID,), END)
