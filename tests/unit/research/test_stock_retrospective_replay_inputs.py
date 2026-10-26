"""Whole fictional native originals; never retained actual market observations."""

import hashlib
import importlib
import importlib.util
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.unit.research import test_stock_monetary_admission as cash
from tests.unit.research import test_stock_replay_schedule as schedules
from trading_bot.market_data.stock_split_comparison import parse_stock_split_series
from trading_bot.research import stock_monetary_admission as admission
from trading_bot.research import stock_replay_schedule as schedule

D = Decimal
MODULE = "trading_bot.research.stock_retrospective_replay_inputs"


def api():
    assert importlib.util.find_spec(MODULE) is not None, "retrospective input boundary missing"
    return importlib.import_module(MODULE)


def fictional_sources(*, prices=None, volume=500000, packets=None, dividend=False):
    native = schedules.native.__wrapped__()
    days = [s.session_date for s in native.sessions]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cash, "_dates", lambda count: days[:count])
        events = [cash._event("AXP", "fictional-earned", days[201], days[202])] if dividend else []
        request = cash._request(706, events=events)
    slots = []
    for slot in request.slots:
        series = []
        for old in (slot.raw, slot.split):
            obj = json.loads(old.original_content_json)
            rows = obj["data"]["results"][0]["bars"]
            for i, row in enumerate(rows):
                value = D(100) + D(i) / 10
                if prices and old.request.symbol in prices:
                    value = D(prices[old.request.symbol][i])
                row.update(
                    open_price=str(value),
                    high_price=str(value + 1),
                    low_price=str(value - 1),
                    close_price=str(value),
                    volume=volume[i] if isinstance(volume, tuple) else volume,
                )
            body = json.dumps(obj, separators=(",", ":")).encode()
            series.append(
                parse_stock_split_series(
                    body,
                    expected_sha256=hashlib.sha256(body).hexdigest(),
                    request=old.request,
                    received_at=old.received_at,
                )
            )
        slots.append(replace(slot, raw=series[0], split=series[1]))
    request = cash._rebind(request, slots=tuple(slots))
    monetary = admission.prepare_retrospective_monetary_inputs(request)
    assert type(monetary) is admission.PreparedRetrospectiveMonetaryInputs
    packets = (
        packets
        if packets is not None
        else (
            schedules.packet(schedule),
            schedules.packet(schedule, "cns", start=days[0], end=schedules.date(2026, 12, 31)),
        )
    )
    timed = schedule.prepare_retrospective_replay_schedule(
        request.calendar, source_packets=packets, rule=schedule.RetrospectiveScheduleRule()
    )
    return monetary, timed


def prepared(*, annual=(), **kwargs):
    m = api()
    monetary, timed = fictional_sources(**kwargs)
    return m.prepare_retrospective_replay_inputs(
        m.RetrospectiveReplayRequest(
            monetary, timed, tuple(annual), m.RetrospectiveReplayConvention()
        )
    )


def test_separate_raw_signal_native_volume_views_and_no_scripted_asset():
    m = api()
    result = prepared()
    assert type(result) is m.PreparedRetrospectiveReplayInputs
    assert result.status == "conditionally_prepared"
    assert len(result.assets) == 9 and result.price_session_count == 706
    assert len(result.calendar) == 720
    asset = result.assets[0]
    assert asset.symbol == "AXP" and asset.role == "stock_candidate"
    assert asset.accounting_bars[200].close == D(120)
    assert asset.signal_bars[200].close == D(120)
    assert asset.native_volume[200] == 500000 and type(asset.native_volume[200]) is int
    assert asset.native_interpolated[200] is None
    assert asset.native_quote_currency is None and asset.interpreted_account_currency == "USD"
    for name in ("signals", "bars", "sector", "earnings_clear", "available_at"):
        assert not hasattr(asset, name)
    assert result.assets[-1].role == "passive_comparison"


def test_full56_and_eight_long_term_slots_never_disappear():
    result = prepared()
    assert len(result.full_constrained_cases) == 56
    assert all(x.evaluation_status == "unavailable" for x in result.full_constrained_cases)
    assert tuple(s for s, _ in result.long_term_quality_slots) == cash.SYMBOLS[:8]
    assert len(result.families) == 7
    assert result.convention.membership_available_at == datetime(2024, 2, 16, tzinfo=UTC)
    assert "liquidity" not in " ".join(result.convention.omitted_screens)


def test_source_heavy_hash_is_fresh_and_whole_source_bound():
    m = api()
    result = prepared()
    original = result.request.monetary.request.slots[0].raw
    altered = replace(original, original_content_json=original.original_content_json + b" ")
    slot = replace(result.request.monetary.request.slots[0], raw=altered)
    request = replace(
        result.request.monetary.request, slots=(slot, *result.request.monetary.request.slots[1:])
    )
    with pytest.raises(ValueError):
        forged = replace(result.request.monetary, request=request)
        m.prepare_retrospective_replay_inputs(replace(result.request, monetary=forged))


def test_changed_equal_clock_leaf_is_rejected_by_compact_window():
    m = api()
    result = prepared()
    panel = result._panel
    asset = panel.assets[0]
    row = replace(asset.signal_bars[200], close=D(999))
    changed = replace(asset, signal_bars=(*asset.signal_bars[:200], row, *asset.signal_bars[201:]))
    bad = replace(panel, assets=(changed, *panel.assets[1:]))
    with pytest.raises(ValueError):
        m._check_panel_window(bad, first=199, last=200)


def test_native_integer_volume_and_calendar_key_are_committed():
    m = api()
    result = prepared()
    panel = result._panel
    asset = panel.assets[0]
    changed = replace(
        asset, native_volume=(*asset.native_volume[:200], 1, *asset.native_volume[201:])
    )
    with pytest.raises(ValueError):
        m._check_panel_window(
            replace(panel, assets=(changed, *panel.assets[1:])), first=200, last=200
        )
    cal = replace(panel.calendar[200], opens_at=panel.calendar[199].opens_at)
    with pytest.raises(ValueError):
        m._check_panel_window(
            replace(panel, calendar=(*panel.calendar[:200], cal, *panel.calendar[201:])),
            first=200,
            last=200,
        )


def test_missing_padding_is_typed_unavailable_without_filling_prices():
    m = api()
    monetary, timed = fictional_sources(packets=())
    result = m.prepare_retrospective_replay_inputs(
        m.RetrospectiveReplayRequest(monetary, timed, (), m.RetrospectiveReplayConvention())
    )
    assert type(result) is m.UnavailableRetrospectiveReplayInputs
    assert result.status == "unavailable"
    assert len(result.assets) == 9 and len(result.full_constrained_cases) == 56
    assert result.price_session_count == 706


def test_supplemental_axp_annual_does_not_claim_peer_or_allocator_coverage():
    from tests.unit.research.test_stock_annual_policy import annual

    result = prepared(annual=(annual(),))
    assert result.supplemental_annual_symbols == ("AXP",)
    assert len(result.long_term_quality_slots) == 8
    assert all(
        reason == "quality_stock_allocator_unavailable"
        for _, reason in result.long_term_quality_slots
    )
    assert result.request.monetary.cases[3].signal_inputs_status == "unavailable"


def test_public_prepared_view_cannot_be_treated_as_cached_source_validation():
    m = api()
    result = prepared()
    asset = replace(result.assets[0], native_volume=(1,) * 706)
    object.__setattr__(result, "assets", (asset, *result.assets[1:]))
    with pytest.raises(ValueError):
        m.revalidate_retrospective_replay_inputs(result)


@pytest.mark.parametrize(
    "flag",
    [
        "qualified",
        "source_qualified",
        "strategy_qualified",
        "investment_eligible",
        "trading_enabled",
        "live_authorized",
        "full_task5_complete",
    ],
)
def test_authority_is_permanently_false(flag):
    m = api()
    result = prepared()
    assert getattr(result, flag) is False
    with pytest.raises((TypeError, ValueError)):
        replace(result, **{flag: True})
    object.__setattr__(result, flag, True)
    with pytest.raises(ValueError):
        m.revalidate_retrospective_replay_inputs(result)
