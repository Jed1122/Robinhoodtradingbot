"""Fictional conditional shared-ledger cases; no actual historical results."""

import importlib
import importlib.util
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.unit.research.test_stock_retrospective_replay_inputs import prepared
from trading_bot.research import stock_economic_replay as legacy
from trading_bot.research import stock_monetary_admission as admission
from trading_bot.research.stock_operating_costs import ModeledOperatingCostPlan

D = Decimal
MODULE = "trading_bot.research.stock_retrospective_replay"


def api():
    assert importlib.util.find_spec(MODULE) is not None, "retrospective shared-kernel entry missing"
    return importlib.import_module(MODULE)


def spec(m, family="trend", *, method="principal", profile="passive_75_SPY_baseline"):
    return m.RetrospectiveCaseSpec(
        family,
        legacy.StockEconomicReplayProtocol(exit_method=method, slippage_bps=D(0), fee_usd=D(".01")),
        ModeledOperatingCostPlan("fictional-zero", ()),
        profile,
    )


def begin(*, data=None, family="trend", method="principal"):
    m = api()
    data = prepared() if data is None else data
    return m.begin_retrospective_economic_replay(data, cases=(spec(m, family, method=method),))


def advance(state):
    return api().advance_retrospective_economic_session(state, session_index=state.next_session)


def test_distinct_entry_uses_one_paused_ledger_and_individual_stocks():
    state = begin()
    core = state.cases[0].core
    assert not isinstance(core.inputs, legacy.StockEconomicReplayInputs)
    assert not any(isinstance(a, legacy.ModeledAsset) for a in core.inputs.assets)
    state = advance(state)
    account = state.cases[0].core.book.account
    assert account.paused is True
    assert any(lot.sleeve == "tactical" for lot in account.lots)
    assert any(lot.symbol == "SPY" and lot.sleeve == "long_term" for lot in account.lots)
    assert all(lot.symbol != "SPY" for lot in account.lots if lot.sleeve == "tactical")
    assert account.cash >= 0 and account.tax_reserve >= 0
    assert len(state.full_constrained_cases) == 56 and len(state.long_term_quality_slots) == 8


def test_public_fictional_entry_rejects_retrospective_input():
    data = prepared()
    with pytest.raises(ValueError):
        legacy.begin_stock_economic_replay(data, legacy.StockEconomicReplayProtocol())
    state = begin(data=data)
    with pytest.raises(ValueError):
        legacy.advance_stock_economic_session(state.cases[0].core, session_index=200)


def test_prior20_volume_proxy_does_not_use_uncompleted_entry_volume():
    api()
    volumes = (1,) * 200 + (1000000000,) * 506
    data = prepared(volume=volumes)
    state = advance(begin(data=data))
    assert state.cases[0].core.book.account.lots == ()
    assert any(
        r.reason == "conditional_price_or_liquidity_screen" for r in state.cases[0].core.records
    )


def test_price_below10_blocks_even_when_dollar_volume_is_large():
    api()
    data = prepared(prices={s: ("9",) * 706 for s in admission._SYMBOLS}, volume=100000000)
    state = advance(begin(data=data))
    assert state.cases[0].core.book.account.lots == ()


def test_no_source_parsing_during_steps_or_per_case(monkeypatch):
    m = api()
    data = prepared()
    state = m.begin_retrospective_economic_replay(data, cases=(spec(m), spec(m, "breakout")))
    old = admission.parse_stock_split_series
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return old(*args, **kwargs)

    monkeypatch.setattr(admission, "parse_stock_split_series", counted)
    state = advance(advance(state))
    assert calls == [] and state.next_session == 202


def test_missing_families_and_long_term_variant_are_unavailable_not_cash_success():
    m = api()
    state = m.begin_retrospective_economic_replay(
        prepared(),
        cases=(
            spec(m, "pead"),
            spec(m, "revision_momentum"),
            spec(m, profile="quality_stock_variant"),
        ),
    )
    assert len(state.cases) == 3
    assert all(c.core is None and c.unavailable_reasons for c in state.cases)
    assert len(state.families) == 7 and len(state.long_term_quality_slots) == 8


def test_checkpoint_is_inert_and_resume_reconstructs_same_owned_state():
    m = api()
    data = prepared()
    state = advance(advance(begin(data=data)))
    checkpoint = m.checkpoint_retrospective_economic_replay(state)
    with pytest.raises(ValueError):
        advance(checkpoint)
    resumed = m.resume_retrospective_economic_replay(checkpoint, fresh_inputs=data)
    assert resumed.evidence_hash == state.evidence_hash
    assert advance(resumed).evidence_hash == advance(state).evidence_hash
    with pytest.raises(ValueError):
        m.resume_retrospective_economic_replay(
            replace(checkpoint, state_hash="0" * 64), fresh_inputs=data
        )


def test_changed_panel_leaf_and_next_session_cannot_bypass_owned_state():
    m = api()
    state = begin()
    panel = state.panel
    a = panel.assets[0]
    bar = replace(a.signal_bars[200], close=D(999))
    changed = replace(a, signal_bars=(*a.signal_bars[:200], bar, *a.signal_bars[201:]))
    bad = replace(panel, assets=(changed, *panel.assets[1:]))
    with pytest.raises(ValueError):
        m.advance_retrospective_economic_session(replace(state, panel=bad), session_index=200)
    with pytest.raises(ValueError):
        m.advance_retrospective_economic_session(
            replace(state, next_session=706), session_index=706
        )


@pytest.mark.parametrize(
    "method,reason", [("principal", "principal"), ("partial", "partial_first"), ("trailing", None)]
)
def test_three_exit_methods_use_same_source_bound_accounting(method, reason):
    api()
    path = ("100",) * 150 + ("101",) * 51 + ("117",) * 505
    data = prepared(prices={**{s: path for s in admission._SYMBOLS[:8]}, "SPY": ("100",) * 706})
    state = begin(data=data, method=method)
    for _ in range(3):
        state = advance(state)
    sales = [r for r in state.cases[0].core.records if r.side == "sell" and r.outcome == "filled"]
    if reason:
        orders = state.cases[0].core.book.account.orders
        assert sales and any(
            reason in (next(o for o in orders if o.id == r.order_id).threshold or "") for r in sales
        )
        assert all(r.proceeds != r.realized_gain for r in sales)
    else:
        assert sales == []


def test_compact_settlement_lookup_cannot_be_replaced_after_source_admission():
    state = begin()
    panel = state.panel
    object.__setattr__(
        panel,
        "settlement_at",
        (*panel.settlement_at[:200], panel.calendar[200].opens_at, *panel.settlement_at[201:]),
    )
    with pytest.raises(ValueError):
        advance(state)


def test_unknown_dividend_funding_cannot_be_replaced_by_convenient_cash_date():
    api()
    state = advance(begin(data=prepared(dividend=True)))
    panel = state.panel
    event = panel.dividends[0]
    assert dict(panel.dividend_available_at)[event.id] is None
    object.__setattr__(panel, "dividend_available_at", ((event.id, panel.calendar[203].opens_at),))
    with pytest.raises(ValueError):
        advance(state)


def test_annual_context_cannot_be_replaced_independently_of_owned_source_root():
    from tests.unit.research.test_stock_annual_policy import annual
    from trading_bot.research.hybrid_policies import _compile_annual_policy_inventory

    api()
    state = begin(data=prepared(annual=(annual(),)), family="quality_momentum")
    with pytest.raises(ValueError):
        advance(replace(state, annual=_compile_annual_policy_inventory(())))


def test_replaced_annual_context_and_matching_summary_still_require_source_binding():
    from tests.unit.research.test_stock_annual_policy import annual
    from trading_bot.research.hybrid_policies import _compile_annual_policy_inventory

    api()
    state = begin(data=prepared(annual=(annual(),)), family="quality_momentum")
    foreign = _compile_annual_policy_inventory(())
    with pytest.raises(ValueError):
        advance(replace(state, annual=foreign, annual_root=foreign.root))


def test_capital_recycles_after_filled_sale_settlement_and_new_signal():
    api()
    axp = ("100",) * 150 + ("101",) * 51 + ("100.1",) * 6 + ("101",) * 499
    data = prepared(prices={**{s: ("100",) * 706 for s in admission._SYMBOLS}, "AXP": axp})
    state = begin(data=data)
    while state.next_session <= 208:
        state = advance(state)
    core = state.cases[0].core
    buys = [
        r for r in core.records if r.symbol == "AXP" and r.side == "buy" and r.outcome == "filled"
    ]
    sales = [
        r for r in core.records if r.symbol == "AXP" and r.side == "sell" and r.outcome == "filled"
    ]
    assert len(buys) == 2 and sales
    assert sales[0].settlement_at < buys[1].at
    assert buys[0].order_id != buys[1].order_id
    assert core.book.account.cash >= core.book.account.tax_reserve


def test_operating_cost_loss_keeps_unchanged_sticky_entry_suspension():
    from trading_bot.research.stock_operating_costs import ModeledOperatingCharge

    m = api()
    data = prepared()
    plan = ModeledOperatingCostPlan(
        "fictional12",
        (ModeledOperatingCharge("cost", data.calendar[200].opens_at, "hosting", D(12)),),
    )
    chosen = replace(spec(m), operating_cost_plan=plan)
    state = m.begin_retrospective_economic_replay(data, cases=(chosen,))
    state = advance(state)
    core = state.cases[0].core
    assert core.book.account.tactical_suspended is True
    assert not any(lot.sleeve == "tactical" for lot in core.book.account.lots)
    assert core.cost_marks[0].paid_total == 12
    assert core.cost_marks[0].net_equity == core.cost_marks[0].gross_equity


def test_final_native_close_has_no_padded_execution_and_requires_fresh_sources():
    from trading_bot.research.stock_monetary_metrics import (
        MetricUnavailableSlot,
        MonetaryMetricRegistration,
        monetary_native_calendar_hash,
        summarize_retrospective_monetary_result,
    )

    m = api()
    data = prepared(prices={s: ("100",) * 706 for s in admission._SYMBOLS})
    state = begin(data=data)
    # Fictional controller identity bindings are frozen before this existing run.
    metric_registration = MonetaryMetricRegistration(
        state.source_root,
        tuple(case.spec_hash for case in state.cases),
        "c" * 40,
        "d" * 40,
        "e" * 64,
        monetary_native_calendar_hash(data.calendar),
        (MetricUnavailableSlot("benchmarks_and_inference", "not_registered"),),
    )
    while state.next_session < 706:
        state = advance(state)
    result = m.finish_retrospective_economic_replay(state, fresh_inputs=data)
    assert result.full_task5_complete is result.live_authorized is False
    assert result.state.next_session == 706
    assert all(r.session_index <= 705 for r in state.cases[0].core.records)
    metrics = summarize_retrospective_monetary_result(
        result, fresh_inputs=data, registration=metric_registration
    )
    assert (
        metrics.full_task5_complete is metrics.live_authorized is False
        and len(metrics.full_constrained_cases) == 56
        and len(metrics.long_term_quality_slots) == 8
        and tuple(
            (row.name, row.expected_mark_count, row.expected_return_count)
            for row in metrics.cases[0].segments
        )
        == (("full", 507, 506), ("train", 239, 238), ("late", 269, 268))
        and metrics.cases[0].policy_coverage.expected_audit_slots == 4056
        and metrics.cases[0].policy_coverage.expected_executable_slots == 4048
    )
    with pytest.raises(ValueError):
        advance(state)
    original = data.request.monetary.request.slots[0].raw
    object.__setattr__(original, "original_content_json", original.original_content_json + b" ")
    with pytest.raises(ValueError):
        m.finish_retrospective_economic_replay(state, fresh_inputs=data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("membership_available_at", datetime(2099, 1, 1, tzinfo=UTC)),
        ("omitted_screens", ()),
        ("liquidity", "unapproved_bypass"),
    ],
)
def test_compiled_convention_cannot_change_without_source_rejection(field, value):
    state = begin()
    object.__setattr__(state.panel.convention, field, value)
    with pytest.raises(ValueError):
        _ = state.evidence_hash
    with pytest.raises(ValueError):
        advance(state)


@pytest.mark.parametrize(
    "field,value",
    [
        ("constraint_status", (("sector_cap", "verified_pass"),)),
        ("native_quote_currency", "USD"),
        ("interpreted_account_currency", "EUR"),
        ("role", "passive_comparison"),
    ],
)
def test_report_and_behavior_asset_metadata_is_source_bound(field, value):
    state = begin()
    changed = replace(state.panel.assets[0])
    object.__setattr__(changed, field, value)
    object.__setattr__(state.panel, "assets", (changed, *state.panel.assets[1:]))
    with pytest.raises(ValueError):
        _ = state.evidence_hash
    with pytest.raises(ValueError):
        advance(state)


def test_next_native_calendar_row_is_checked_before_policy_projection():
    from datetime import timedelta

    state = begin()
    old = state.panel.calendar[201]
    changed = replace(old, opens_at=old.opens_at + timedelta(minutes=1))
    object.__setattr__(
        state.panel, "calendar", (*state.panel.calendar[:201], changed, *state.panel.calendar[202:])
    )
    with pytest.raises(ValueError):
        advance(state)


def test_retrospective_frame_only_consumes_proved_window_and_next_native_calendar():
    m = api()
    state = begin()
    case = state.cases[0]
    frame = m._frame(state.panel, case.spec, 453, state.annual)
    assert tuple(s.index for s in frame.request.sessions) == tuple(range(201, 455))
    final = m._frame(state.panel, case.spec, 705, state.annual)
    assert max(s.index for s in final.request.sessions) == 705
    assert max(o.session_index for o in final.request.observations) == 705


def test_next_calendar_proof_does_not_consume_future_price_or_volume():
    m = api()
    state = begin()
    old = state.panel.assets[0]
    changed = replace(
        old,
        signal_bars=(
            *old.signal_bars[:201],
            replace(old.signal_bars[201], close=D(999)),
            *old.signal_bars[202:],
        ),
    )
    object.__setattr__(state.panel, "assets", (changed, *state.panel.assets[1:]))
    frame = m._frame(state.panel, state.cases[0].spec, 200, state.annual)
    assert max(o.session_index for o in frame.request.observations) == 200


@pytest.mark.parametrize("index", [0, 199, 200])
def test_state_queries_reject_calendar_metadata_already_consumed_by_last_frame(index):
    from datetime import timedelta

    state = begin()
    changed = replace(
        state.panel.calendar[index],
        opens_at=state.panel.calendar[index].opens_at + timedelta(minutes=1),
    )
    object.__setattr__(
        state.panel,
        "calendar",
        (*state.panel.calendar[:index], changed, *state.panel.calendar[index + 1 :]),
    )
    with pytest.raises(ValueError):
        _ = state.evidence_hash
