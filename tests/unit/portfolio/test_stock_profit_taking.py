"""Short fictional profit-reduction proposals; no account, broker or actual returns."""

import importlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from trading_bot.portfolio.stock_holding import (
    StockHoldingLot,
    StockHoldingMandate,
    StockHoldingPrice,
    StockSaleCostAssumptions,
)

D = Decimal
ZERO = D(0)
NOW = datetime(2026, 10, 26, 20, tzinfo=UTC)
FIRST = datetime(2026, 10, 1, 13, 35, tzinfo=UTC)


def api():
    try:
        return importlib.import_module("trading_bot.portfolio.stock_profit_taking")
    except ModuleNotFoundError:
        pytest.fail("source-bound tactical profit helper missing")


def mandate(sleeve="tactical"):
    return StockHoldingMandate("episode-1", "instrument-1", "ALFA", sleeve, FIRST, "a" * 64)


def origin(**changes):
    values = dict(
        episode_id="episode-1",
        instrument_id="instrument-1",
        symbol="ALFA",
        designated_cash=D(1000),
        original_quantity=D(10),
        information_at=FIRST,
        source_hash="b" * 64,
    )
    values.update(changes)
    return api().StockProfitOrigin(**values)


def lot(quantity="10", basis="1000", lot_id="lot-1", at=FIRST):
    return StockHoldingLot(
        lot_id, "episode-1", "instrument-1", "ALFA", D(quantity), D(basis), at, "c" * 64
    )


def price(value="120", at=NOW):
    return StockHoldingPrice("instrument-1", "ALFA", D(value), at, at, "e" * 64)


def state(*, initial=None, progress=(), pending=ZERO, **changes):
    initial = origin() if initial is None else initial
    values = dict(
        episode_id="episode-1",
        instrument_id="instrument-1",
        symbol="ALFA",
        origin_hash=initial.evidence_hash,
        information_at=NOW - timedelta(minutes=1),
        received_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        source_hash="d" * 64,
        pending_exit_quantity=pending,
        progress=progress,
    )
    values.update(changes)
    return api().StockProfitExitState(**values)


def progress(method="principal", target="1", filled="1", fill_ids=("actual-fill-1",)):
    return api().StockProfitMethodProgress(
        method=method, target_quantity=D(target), filled_quantity=D(filled), fill_ids=fill_ids
    )


def propose(**changes):
    values = dict(
        method="principal",
        remaining_lots=(lot(),),
        origin=origin(),
        state=state(),
        price=price(),
        costs=StockSaleCostAssumptions(D(0), D(0), "f" * 64),
        fractional_eligible=True,
        reviewed_at=NOW,
        tax_rate=D(".25"),
        disposal_method="fifo_estimate",
    )
    values.update(changes)
    return api().propose_stock_profit_reduction(mandate(), **values)


def test_principal_1000_to_1200_sells_excess_value_not_fake_200_realized_profit():
    result = propose()
    assert result.status == "proposed" and result.quantity == D("1.666666")
    assert result.estimated_gross_proceeds == D("199.99992")
    assert result.estimated_net_proceeds == result.estimated_gross_proceeds
    assert result.disposed_basis == D("166.6666")
    assert result.estimated_realized_gain == D("33.33332")
    assert result.estimated_tax_reserve == D("8.33333")
    assert result.remaining_basis == D("833.3334")
    assert result.remaining_unrealized_gain == D("166.66668")
    assert (
        not result.cash_credited and not result.execution_authorized and not result.live_authorized
    )
    assert result.indicative_estimates_only is True
    assert len(result.evidence_hash) == 64


@pytest.mark.parametrize(
    "method,value,quantity",
    (
        ("partial_first", "112.5", "2.5"),
        ("partial_second", "120", "2.5"),
        ("partial_first", "112.49", "0"),
        ("partial_second", "119.99", "0"),
    ),
)
def test_partial_methods_have_distinct_thresholds_and_original_quantity_targets(
    method, value, quantity
):
    result = propose(method=method, price=price(value))
    assert result.quantity == D(quantity)
    assert result.status == ("hold" if quantity == "0" else "proposed")


def test_actual_partial_progress_caps_retry_and_proposal_does_not_complete_state():
    tracked = state(progress=(progress("partial_first", "2.5", "1"),))
    result = propose(method="partial_first", remaining_lots=(lot("9", "900"),), state=tracked)
    assert result.status == "proposed" and result.quantity == D("1.5")
    assert tracked.progress[0].filled_quantity == 1
    assert tracked.progress[0].target_quantity == D("2.5")


def test_actual_completed_threshold_cannot_repeat():
    result = propose(remaining_lots=(lot("9", "900"),), state=state(progress=(progress(),)))
    assert result.status == "hold" and result.quantity == 0
    assert "method_completed_by_actual_fills" in result.reason_codes


@pytest.mark.parametrize("pending,status", ((D(1), "hold"), (None, "unavailable")))
def test_pending_or_unknown_exit_state_blocks_new_overlapping_proposal(pending, status):
    result = propose(state=state(pending=pending))
    assert result.status == status
    assert result.quantity in (None, D(0))


def test_fifo_multiple_lots_use_actual_basis_and_keep_holding_dates():
    initial = origin(information_at=FIRST + timedelta(days=1))
    result = propose(
        origin=initial,
        state=state(initial=initial),
        remaining_lots=(
            lot("8", "900", "later", FIRST + timedelta(days=1)),
            lot("2", "100", "earlier"),
        ),
    )
    assert result.quantity == D("1.666666") and result.disposed_basis == D("83.3333")
    assert result.estimated_realized_gain == D("116.66662")
    assert len(result.lot_slices) == 1 and result.lot_slices[0].lot_id == "earlier"
    assert result.lot_slices[0].acquired_at == FIRST
    assert result.lot_slices[0].calendar_holding_days == 25
    assert "fifo_estimate_not_broker_lot_selection" in result.limitations


def test_slippage_and_fee_are_subtracted_once_and_tax_is_on_gain():
    result = propose(costs=StockSaleCostAssumptions(D(100), D(1), "f" * 64))
    assert result.estimated_net_proceeds == D("196.9999208")
    assert result.estimated_realized_gain == D("30.3333208")
    assert result.estimated_tax_reserve == D("7.5833302")
    assert result.remaining_basis == D("833.3334")


def test_unknown_tax_is_not_zero_and_disposal_method_is_explicit():
    result = propose(tax_rate=None)
    assert result.status == "proposed" and result.estimated_tax_reserve is None
    result = propose(disposal_method="unknown")
    assert result.status == "unavailable" and result.disposed_basis is None


@pytest.mark.parametrize(
    "missing", ("origin", "state", "remaining_lots", "price", "costs", "fractional_eligible")
)
def test_missing_required_owned_information_never_becomes_zero(missing):
    result = propose(**{missing: None})
    assert result.status == "unavailable" and result.quantity is None


def test_fractional_false_floors_whole_quantity_and_dust_is_explicit_hold():
    assert propose(fractional_eligible=False).quantity == 1
    initial = origin(designated_cash=D(100), original_quantity=D(1))
    result = propose(
        origin=initial,
        state=state(initial=initial),
        remaining_lots=(lot("1", "100"),),
        fractional_eligible=False,
    )
    assert result.status == "hold" and result.quantity == 0


def test_long_term_has_no_automatic_profit_cut():
    values = dict(
        method="principal",
        remaining_lots=(lot(),),
        origin=origin(),
        state=state(),
        price=price(),
        costs=StockSaleCostAssumptions(D(0), D(0), "f" * 64),
        fractional_eligible=True,
        reviewed_at=NOW,
        disposal_method="fifo_estimate",
    )
    result = api().propose_stock_profit_reduction(mandate("long_term"), **values)
    assert result.status == "hold" and result.quantity == 0
    assert "long_term_no_automatic_profit_cut" in result.reason_codes


def test_sourced_trend_reduction_can_estimate_a_loss_without_negative_tax_reserve():
    result = propose(
        method="trend", price=price("90"), peak_price=price("150", NOW - timedelta(days=2))
    )
    assert result.status == "proposed" and result.quantity == 10
    assert result.estimated_realized_gain == -100 and result.estimated_tax_reserve == 0
    assert propose(method="trend").status == "unavailable"


@pytest.mark.parametrize(
    "change",
    (
        "foreign",
        "duplicate",
        "future",
        "stale_price",
        "stale_state",
        "origin_reset",
        "duplicate_fill",
        "overfilled",
    ),
)
def test_bad_ownership_clocks_or_actual_fill_progress_are_rejected(change):
    changes = {}
    if change == "foreign":
        changes["remaining_lots"] = (replace(lot(), episode_id="other"),)
    elif change == "duplicate":
        changes["remaining_lots"] = (lot(), lot())
    elif change == "future":
        changes["price"] = price(at=NOW + timedelta(seconds=1))
    elif change == "stale_price":
        changes["price"] = price(at=NOW - timedelta(hours=3))
    elif change == "stale_state":
        changes["state"] = state(
            information_at=NOW - timedelta(hours=3),
            received_at=NOW - timedelta(hours=3),
            expires_at=NOW - timedelta(hours=1),
        )
    elif change == "origin_reset":
        changes["origin"] = origin(
            designated_cash=D(1200), original_quantity=D(12), source_hash="1" * 64
        )
    elif change == "duplicate_fill":
        changes.update(
            remaining_lots=(lot("8", "800"),),
            state=state(progress=(progress(), progress("partial_first"))),
        )
    else:
        changes["state"] = state(progress=(progress(target="1", filled="2"),))
    with pytest.raises(ValueError):
        propose(**changes)


def test_context_and_scope_flags_are_deterministic_and_guarded():
    expected = propose()
    with localcontext() as ctx:
        ctx.prec, ctx.rounding, ctx.capitals = 3, ROUND_DOWN, 0
        result = propose()
    assert result == expected and result.evidence_hash == expected.evidence_hash
    object.__setattr__(result, "live_authorized", True)
    with pytest.raises(ValueError):
        _ = result.evidence_hash


def test_fifo_slices_cross_lots_without_overlap_and_do_not_follow_input_order():
    initial = origin(information_at=FIRST + timedelta(days=1))
    rows = (lot("8", "900", "later", FIRST + timedelta(days=1)), lot("2", "100", "earlier"))
    result = propose(
        origin=initial, state=state(initial=initial), remaining_lots=rows, price=price("150")
    )
    assert result.quantity == D("3.333333")
    assert result.disposed_basis == D("249.9999625")
    assert result.estimated_realized_gain == D("249.9999875")
    assert [(x.lot_id, x.quantity) for x in result.lot_slices] == [
        ("earlier", D(2)),
        ("later", D("1.333333")),
    ]
    again = propose(
        origin=initial,
        state=state(initial=initial),
        remaining_lots=tuple(reversed(rows)),
        price=price("150"),
    )
    assert again.lot_slices == result.lot_slices


def test_contribution_origin_update_requires_new_bound_state_and_preserves_completed_fills():
    updated = origin(
        designated_cash=D(1200),
        original_quantity=D(12),
        information_at=NOW - timedelta(minutes=2),
        source_hash="1" * 64,
    )
    rows = (lot("9", "900"), lot("2", "200", "contribution", NOW - timedelta(minutes=3)))
    with pytest.raises(ValueError):
        propose(
            origin=updated,
            remaining_lots=rows,
            state=state(progress=(progress(),)),
            price=price("150"),
        )
    carried = state(initial=updated, progress=(progress(),))
    result = propose(origin=updated, remaining_lots=rows, state=carried, price=price("150"))
    assert result.status == "hold" and "method_completed_by_actual_fills" in result.reason_codes


def test_partial_progress_cap_also_rounds_down_subincrement_tail():
    tracked = state(progress=(progress("partial_first", "2.5", "1.0000005"),))
    result = propose(
        method="partial_first", remaining_lots=(lot("8.9999995", "899.99995"),), state=tracked
    )
    assert result.quantity == D("1.499999")
    assert result.quantity <= D("2.5") - tracked.progress[0].filled_quantity


@pytest.mark.parametrize("value", (1, D("1.01"), D("-.01")))
def test_tax_assumption_must_be_explicit_decimal_fraction(value):
    with pytest.raises(ValueError):
        propose(tax_rate=value)


def test_zero_tax_assumption_is_explicit_and_not_an_inferred_rate():
    result = propose(tax_rate=D(0))
    assert (
        result.status == "proposed" and result.tax_rate == 0 and result.estimated_tax_reserve == 0
    )


@pytest.mark.parametrize("value", (1, "true", 0))
def test_fractional_eligibility_never_coerces_bool_like_values(value):
    with pytest.raises(ValueError):
        propose(fractional_eligible=value)


@pytest.mark.parametrize(
    "change",
    ("zero_trigger", "zero_trail", "wrong_peak_owner", "future_peak", "too_many_owned_shares"),
)
def test_policy_gaps_peak_scope_and_quantity_ceiling_do_not_create_reductions(change):
    if change == "zero_trigger":
        changes = {"policy": api().StockProfitPolicy(principal_trigger_pct=D(0))}
    elif change == "zero_trail":
        changes = {"policy": api().StockProfitPolicy(trailing_pct=D(0))}
    elif change == "wrong_peak_owner":
        changes = {
            "method": "trend",
            "peak_price": replace(price("150", NOW - timedelta(days=1)), instrument_id="foreign"),
        }
    elif change == "future_peak":
        changes = {"method": "trend", "peak_price": price("150", NOW + timedelta(seconds=1))}
    else:
        changes = {"remaining_lots": (lot("11", "1100"),)}
    with pytest.raises(ValueError):
        propose(**changes)


def test_high_costs_and_nonpositive_disposal_gains_are_not_called_profit():
    result = propose(costs=StockSaleCostAssumptions(D(0), D(300), "f" * 64))
    assert result.status == "unavailable" and result.estimated_realized_gain is None
    result = propose(remaining_lots=(lot(basis="2000"),))
    assert result.status == "hold" and result.quantity == 0
    assert "nonpositive_estimated_disposal_gain" in result.reason_codes


def test_known_flat_episode_has_no_sale_fee_or_new_estimated_gain():
    result = propose(remaining_lots=(), price=None, costs=None)
    assert result.status == "hold" and result.quantity == 0
    assert result.estimated_net_proceeds is result.estimated_realized_gain is None


@pytest.mark.parametrize("method", ("partial_first", "partial_second"))
@pytest.mark.parametrize("filled,remaining,expected", (("2.5", "7.5", "0"), ("1", "9", "1.5")))
def test_partial_cumulative_policy_quota_cannot_be_enlarged_by_supplied_target(
    method, filled, remaining, expected
):
    actual = state(progress=(progress(method, "10", filled),))
    result = propose(
        method=method, remaining_lots=(lot(remaining, str(D(remaining) * 100)),), state=actual
    )
    assert result.quantity == D(expected)
    assert result.status == ("hold" if expected == "0" else "proposed")
    assert actual.progress[0].filled_quantity == D(filled)
    assert result.completed_threshold_created is False


def test_partial_contribution_preserves_original_method_target_and_actual_fill_progress():
    updated = origin(
        designated_cash=D(1200),
        original_quantity=D(12),
        information_at=NOW - timedelta(minutes=2),
        source_hash="1" * 64,
    )
    actual = state(initial=updated, progress=(progress("partial_first", "2.5", "1"),))
    rows = (lot("9", "900"), lot("2", "200", "new-cash", NOW - timedelta(minutes=3)))
    result = propose(method="partial_first", origin=updated, state=actual, remaining_lots=rows)
    assert result.quantity == D("1.5")
    assert actual.progress[0].filled_quantity == 1 and actual.progress[0].target_quantity == D(
        "2.5"
    )
