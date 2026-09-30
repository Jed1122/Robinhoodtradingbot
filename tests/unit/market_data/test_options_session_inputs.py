"""Fabricated session aggregation and evidence boundaries, not a historical calendar."""

import hashlib
import importlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from tests.integration.market_data.test_databento_bar_store import ROOT, batch, config, rehash
from tests.unit.market_data._native_bars_fixtures import dbn, native_record, zstd
from tests.unit.market_data._options_source_fixtures import module, verified_facts
from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from trading_bot.domain import CorporateAction, DataHash, InstrumentId
from trading_bot.domain.options import OptionSession
from trading_bot.market_data.databento_bar_models import NativeBarRequest
from trading_bot.market_data.databento_bar_store import stage_bars, verify_bar_stage
from trading_bot.market_data.databento_batch import DatabentoImportError
from trading_bot.research.options_shortlist_models import (
    ShortlistAction,
    ShortlistCalendarDay,
    ShortlistDiscontinuity,
)

NY = ZoneInfo("America/New_York")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def api():
    try:
        return importlib.import_module("trading_bot.market_data.options_session_inputs")
    except ModuleNotFoundError:
        pytest.fail("verified session assembly is not implemented")


def ns(value):
    delta = value - EPOCH
    return (delta.days * 86400 + delta.seconds) * 10**9 + delta.microseconds * 1000


def session(day, *, closing=16):
    return OptionSession(
        "synthetic-" + day.isoformat(),
        datetime.combine(day, time(9, 30), NY).astimezone(UTC),
        datetime.combine(day, time(closing), NY).astimezone(UTC),
        day,
        "America/New_York",
    )


def case(
    tmp_path,
    *,
    prior_day=date(2024, 1, 2),
    current_day=date(2024, 1, 3),
    closing=16,
    degraded=False,
    undefined=False,
    final_missing=False,
    no_trade=False,
    duplicates=False,
    actions=(),
    omit_role=None,
    mixed_publishers=False,
):
    model = api()
    prior, current = session(prior_day, closing=closing), session(current_day)
    low = datetime.combine(prior_day, time(), UTC)
    high = datetime.combine(current_day + timedelta(days=1), time(), UTC)
    request = NativeBarRequest(ns(low), ns(high))
    first = native_record(stamp=ns(prior.opens_at), prices=(100000000000,) * 4, volume=100)
    last_stamp = prior.closes_at - timedelta(minutes=2 if final_missing else 1)
    final = native_record(
        stamp=ns(last_stamp),
        prices=((2**63 - 1,) * 4 if undefined else (101000000000,) * 4),
        volume=200,
        publisher_id=3 if mixed_publishers else 2,
    )
    after = native_record(
        stamp=ns(prior.closes_at + timedelta(minutes=5)), prices=(999000000000,) * 4, volume=900
    )
    rows = (first, first, final, after) if duplicates else (first, final, after)
    metadata = dbn.Metadata(
        dataset="XNAS.ITCH",
        start=request.start_ns,
        end=request.end_ns,
        stype_in=dbn.SType.RAW_SYMBOL,
        stype_out=dbn.SType.INSTRUMENT_ID,
        schema=dbn.Schema.OHLCV_1M,
        symbols=["SPY"],
        version=3,
        mappings=[
            SimpleNamespace(
                raw_symbol="SPY",
                intervals=[
                    SimpleNamespace(
                        start_date=prior_day, end_date=current_day + timedelta(days=1), symbol="42"
                    )
                ],
            )
        ],
    )
    source = batch(
        tmp_path, payload=zstd.ZstdCompressor().compress(metadata.encode() + b"".join(rows))
    )
    meta = json.loads((source / "metadata.json").read_bytes())
    meta["query"] = request.query()
    (source / "metadata.json").write_text(json.dumps(meta))
    (source / "condition.json").write_text(
        json.dumps(
            [
                {
                    "date": prior_day.isoformat(),
                    "condition": "degraded" if degraded else "available",
                    "last_modified_date": None,
                }
            ]
        )
    )
    rehash(source)
    target = tmp_path / "staged"
    target.mkdir(mode=0o700)
    path = stage_bars(source, target, expected=request, loaded=config(), repository_root=ROOT)
    dataset = verify_bar_stage(path, loaded=config(), repository_root=ROOT)
    days = tuple(
        ShortlistCalendarDay(
            prior_day + timedelta(days=i),
            prior if i == 0 else current if prior_day + timedelta(days=i) == current_day else None,
        )
        for i in range((current_day - prior_day).days + 1)
    )
    reference = model.SessionReferenceInput(current, prior, days, tuple(actions), ())
    native_hashes = tuple(
        sorted({hashlib.sha256(first).hexdigest(), hashlib.sha256(final).hexdigest()})
    )
    facts = {
        "calendar": [{"kind": "calendar", "current": current, "prior": prior, "days": days}],
        "actions": [
            {
                "kind": "actions",
                "start_ns": ns(prior.opens_at),
                "end_ns": ns(current.opens_at),
                "actions": tuple(actions),
            }
        ],
        "bar_publication": [
            {
                "kind": "bar_publication",
                "start_ns": ns(prior.opens_at),
                "end_ns": ns(prior.closes_at),
                "as_of_ns": ns(current.opens_at),
                "coverage": "complete_trade_intervals",
                "native_hashes": native_hashes,
            }
        ],
    }
    if no_trade:
        facts["bar_publication"].append(
            {
                "kind": "no_trade",
                "start_ns": ns(last_stamp + timedelta(minutes=1)),
                "end_ns": ns(prior.closes_at),
                "as_of_ns": ns(current.opens_at),
            }
        )
    if omit_role:
        facts.pop(omit_role)
    descriptor = module("models").PrivateArtifactRef(
        path, dataset.manifest_hash, path.stat().st_size
    )
    _, verification = verified_facts(
        tmp_path / "proof",
        facts,
        start_ns=ns(prior.opens_at),
        end_ns=ns(current.opens_at),
        as_of_ns=ns(current.opens_at),
        manifests=(descriptor,),
    )
    reference = replace(reference, claim_hashes=verification.visible_claim_hashes)
    return SimpleNamespace(
        dataset=dataset,
        reference=reference,
        verification=verification,
        prior=prior,
        current=current,
    )


def assemble(value, *, reference=None, verification=None):
    return api().assemble_session_inputs(
        value.dataset,
        reference or value.reference,
        verification=verification or value.verification,
        loaded=config(),
        repository_root=ROOT,
    )


def test_regular_close_uses_exact_session_not_after_hours(tmp_path):
    value = case(tmp_path)
    result = assemble(value)
    assert result.bar.close == Decimal("101")
    assert result.bar.open == Decimal("100") and result.bar.high == Decimal("101")
    assert result.bar.low == Decimal("100") and result.bar.volume == Decimal("300")
    assert result.bar.ends_at == value.prior.closes_at
    assert result.available_at == value.current.opens_at
    assert (
        result.included_count,
        result.excluded_count,
        result.rejected_count,
        result.duplicate_count,
    ) == (2, 1, 0, 0)
    assert result.reasons == () and result.coverage_label == "source_last_trade"
    assert result.price_basis == "unadjusted" and not result.bar.interpolated


def test_after_hours_exclusion_does_not_clear_degraded_day(tmp_path):
    result = assemble(case(tmp_path, degraded=True))
    assert result.bar is None and "source_coverage_degraded" in result.reasons


@pytest.mark.parametrize(
    "prior,current,closing",
    [
        (date(2024, 3, 8), date(2024, 3, 11), 16),
        (date(2024, 11, 1), date(2024, 11, 4), 16),
        (date(2024, 7, 3), date(2024, 7, 5), 13),
        (date(2024, 1, 2), date(2024, 1, 4), 16),
    ],
)
def test_explicit_calendar_handles_dst_holidays_and_exceptional_closures(
    tmp_path, prior, current, closing
):
    value = case(tmp_path, prior_day=prior, current_day=current, closing=closing)
    result = assemble(value)
    assert result.bar is not None and result.bar.ends_at == value.prior.closes_at


def test_absent_final_minute_requires_exact_no_trade_proof(tmp_path):
    denied_dir, allowed_dir = tmp_path / "denied", tmp_path / "allowed"
    denied_dir.mkdir()
    allowed_dir.mkdir()
    result = assemble(case(denied_dir, final_missing=True))
    assert result.bar is None and "source_close_coverage_unverified" in result.reasons
    assert assemble(case(allowed_dir, final_missing=True, no_trade=True)).bar is not None


@pytest.mark.parametrize(
    "role,reason",
    [
        ("calendar", "calendar_unverified"),
        ("actions", "action_coverage_unverified"),
        ("bar_publication", "bar_publication_unverified"),
    ],
)
def test_missing_role_does_not_gain_assumed_defaults(tmp_path, role, reason):
    result = assemble(case(tmp_path, omit_role=role))
    assert result.bar is None and reason in result.reasons


def test_duplicate_observations_do_not_double_count_volume(tmp_path):
    result = assemble(case(tmp_path, duplicates=True))
    assert result.bar.volume == Decimal("300")
    assert (result.included_count, result.excluded_count, result.duplicate_count) == (2, 1, 1)


def test_undefined_regular_observation_denies_close(tmp_path):
    result = assemble(case(tmp_path, undefined=True))
    assert result.bar is None and result.rejected_count == 1


def test_unbound_reference_mutation_and_claim_substitution_deny(tmp_path):
    value = case(tmp_path)
    mutated = replace(
        value.reference,
        current=replace(value.current, closes_at=value.current.closes_at - timedelta(hours=1)),
    )
    assert assemble(value, reference=mutated).bar is None
    assert (
        assemble(value, reference=replace(value.reference, claim_hashes=(DataHash("0" * 64),))).bar
        is None
    )


@pytest.mark.parametrize("action_type", ["split", "dividend"])
def test_visible_splits_deny_and_dividends_remain_unadjusted_context(tmp_path, action_type):
    announced = datetime(2024, 1, 1, tzinfo=UTC)
    action = CorporateAction(
        InstrumentId("SPY"),
        action_type,
        date(2024, 1, 3),
        announced,
        Decimal("2") if action_type == "split" else None,
        Decimal("1") if action_type == "dividend" else None,
        DataHash("a" * 64),
    )
    value = case(tmp_path, actions=(ShortlistAction(action, announced),))
    result = assemble(value)
    assert (result.bar is None) is (action_type == "split")
    if action_type == "dividend":
        assert result.bar.close == Decimal("101")


def test_mixed_publishers_are_rejected_before_underlying_session_assembly(tmp_path):
    with pytest.raises(DatabentoImportError, match="databento_dbn_invalid"):
        case(tmp_path, mixed_publishers=True)


@pytest.mark.parametrize("kind", ["unknown", "deliverable_change"])
def test_visible_discontinuities_deny_unadjusted_reference(tmp_path, kind):
    announced = datetime(2024, 1, 1, tzinfo=UTC)
    action = ShortlistDiscontinuity("SPY", kind, date(2024, 1, 3), announced, DataHash("b" * 64))
    result = assemble(case(tmp_path, actions=(ShortlistAction(action, announced),)))
    assert result.bar is None and "reference_discontinuity" in result.reasons


def test_future_dividend_revision_does_not_enter_open_reference(tmp_path):
    future = datetime(2024, 1, 3, 15, tzinfo=UTC)
    action = CorporateAction(
        InstrumentId("SPY"),
        "dividend",
        date(2024, 1, 3),
        future,
        None,
        Decimal("1"),
        DataHash("b" * 64),
    )
    result = assemble(case(tmp_path, actions=(ShortlistAction(action, future),)))
    assert result.bar is None and "action_coverage_unverified" in result.reasons


def test_intervening_calendar_day_cannot_be_silently_omitted(tmp_path):
    value = case(tmp_path, prior_day=date(2024, 3, 8), current_day=date(2024, 3, 11))
    reference = replace(
        value.reference,
        calendar_days=(value.reference.calendar_days[0], value.reference.calendar_days[-1]),
    )
    assert "calendar_unverified" in assemble(value, reference=reference).reasons


def test_stale_verification_and_tampered_native_part_fail_closed(tmp_path):
    value = case(tmp_path)
    stale = replace(
        value.verification,
        context=replace(value.verification.context, code_hash=DataHash("0" * 64)),
    )
    assert assemble(value, verification=stale).bar is None
    part = value.dataset.manifest_path.parent.parent / value.dataset.parts[0].path
    part.write_bytes(b"changed")
    assert "source_data_unusable" in assemble(value).reasons
