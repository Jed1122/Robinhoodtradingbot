from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.unit.domain.test_options import NOW, contract
from tests.unit.reconciliation._options_fixtures import ACCOUNT, fill, order, owned, snapshot
from tests.unit.reconciliation._options_fixtures import (
    offline_observation_boundary as offline_observation_boundary,
)
from trading_bot.domain import AccountId, OrderState, Side
from trading_bot.domain.options_account import (
    ObservedOptionLifecycle,
    ObservedOptionSettlement,
    ObservedSharePosition,
    OptionLifecycleKind,
    OptionsSnapshotSection,
)
from trading_bot.reconciliation.options import reconcile_options

D = Decimal


def reconcile(local=None, broker=None, **changes):
    args = dict(
        account_id=ACCOUNT,
        local=local or snapshot(),
        broker=broker or snapshot(),
        owned_positions=(owned(),),
        as_of=NOW,
        max_age_seconds=D("30"),
        reconciliation_id="check-1",
    )
    args.update(changes)
    return reconcile_options(**args)


def codes(result):
    return {item.code for item in result.differences}


def test_exact_complete_snapshot_reconciles_without_granting_trade_permission():
    result = reconcile()
    assert result.clean and result.differences == ()
    assert result.account_id == ACCOUNT
    assert not hasattr(result, "live_eligible")


@pytest.mark.parametrize(
    "field",
    [
        "equity",
        "settled_cash",
        "buying_power",
        "collateral",
        "reserved_cash",
        "unsettled_receivable",
        "unsettled_payable",
    ],
)
def test_every_cash_component_compares_exactly(field):
    broker = snapshot(cash=replace(snapshot().cash, **{field: D("0.00000001")}))
    assert f"options_cash_{field}_mismatch" in codes(reconcile(broker=broker))


@pytest.mark.parametrize("section", tuple(OptionsSnapshotSection))
def test_missing_page_or_section_is_not_an_empty_complete_account(section):
    broker = snapshot(complete_sections=tuple(x for x in OptionsSnapshotSection if x != section))
    assert "broker_snapshot_incomplete" in codes(reconcile(broker=broker))


@pytest.mark.parametrize("side", ["local", "broker"])
@pytest.mark.parametrize("offset,code", [(-31, "stale"), (1, "future")])
def test_freshness_is_required_on_both_sides(side, offset, code):
    observed = snapshot(observed_at=NOW + timedelta(seconds=offset), orders=(), fills=())
    assert f"{side}_snapshot_{code}" in codes(reconcile(**{side: observed}))


def test_account_substitution_and_history_window_mismatch_fail_closed():
    assert "options_account_mismatch" in codes(
        reconcile(broker=snapshot(account_id=AccountId("other")))
    )
    assert "options_history_window_mismatch" in codes(
        reconcile(broker=snapshot(history_start=NOW - timedelta(hours=1)))
    )


@pytest.mark.parametrize(
    "field,identity",
    [("positions", "position"), ("orders", "order"), ("fills", "fill"), ("contracts", "contract")],
)
def test_duplicates_and_missing_rows_are_detected(field, identity):
    rows = getattr(snapshot(), field)
    assert f"duplicate_broker_options_{identity}_identity" in codes(
        reconcile(broker=snapshot(**{field: rows + rows}))
    )
    assert f"missing_broker_options_{identity}" in codes(reconcile(broker=snapshot(**{field: ()})))


def test_same_wrong_positions_do_not_pass_by_agreement_or_netting():
    bad = snapshot(positions=(replace(snapshot().positions[0], quantity=-1),))
    assert "broker_options_ownership_mismatch" in codes(reconcile(bad, bad))
    assert "local_options_ownership_mismatch" in codes(reconcile(bad, bad))
    assert "ambiguous_options_ownership" in codes(
        reconcile(owned_positions=(owned(), owned(position_id="other")))
    )
    assert "broker_options_ownership_mismatch" in codes(reconcile(owned_positions=()))


@pytest.mark.parametrize("quantity", [D("1"), D("-0.5")])
def test_unexpected_shares_are_incidents_even_when_both_books_agree(quantity):
    bad = snapshot(shares=(ObservedSharePosition("SYN", quantity),))
    assert "broker_unexpected_shares" in codes(reconcile(bad, bad))


@pytest.mark.parametrize(
    "field,code",
    [
        ("pending_exercise", "pending_exercise"),
        ("pending_assignment", "pending_assignment"),
        ("pending_expiration", "pending_expiration"),
    ],
)
def test_pending_lifecycle_is_not_flat_or_settled(field, code):
    bad = snapshot(positions=(replace(snapshot().positions[0], **{field: 1}),))
    assert f"broker_options_{code}" in codes(reconcile(bad, bad))


@pytest.mark.parametrize("kind", tuple(OptionLifecycleKind))
def test_lifecycle_events_require_operator_review(kind):
    bad = snapshot(
        lifecycle=(
            ObservedOptionLifecycle("event-1", contract().contract_id, kind, 1, D("0"), NOW),
        )
    )
    assert f"broker_options_{kind.value}" in codes(reconcile(bad, bad))


def test_negative_cash_unknown_orders_and_unmatched_fills_are_incidents():
    bad = snapshot(
        cash=replace(snapshot().cash, settled_cash=D("-1")),
        orders=(order(state=OrderState.UNKNOWN_REQUIRES_RECONCILIATION),),
        fills=(fill(side=Side.SELL),),
    )
    result = codes(reconcile(bad, bad))
    assert {
        "broker_negative_cash",
        "broker_options_unknown_order",
        "broker_options_fill_leg_mismatch",
        "broker_options_fill_quantity_mismatch",
    } <= result


def test_fill_totals_cannot_disappear_into_identical_snapshots():
    bad = snapshot(fills=())
    assert "broker_options_fill_quantity_mismatch" in codes(reconcile(bad, bad))
    bad = snapshot(fills=(fill(order_id="missing"),))
    assert "broker_options_orphan_fill" in codes(reconcile(bad, bad))


def test_settlement_amount_and_due_time_reconciled_without_inventing_cash():
    obligation = ObservedOptionSettlement(
        "settlement-1", contract().contract_id, D("25"), NOW + timedelta(days=1), False
    )
    good = snapshot(
        settlements=(obligation,), cash=replace(snapshot().cash, unsettled_receivable=D("25"))
    )
    assert reconcile(good, good).clean
    bad = replace(good, settlements=(replace(obligation, due_at=NOW),))
    assert "broker_options_settlement_overdue" in codes(reconcile(bad, bad))
    bad = replace(good, cash=snapshot().cash)
    assert "broker_options_settlement_cash_mismatch" in codes(reconcile(bad, bad))


@pytest.mark.parametrize(
    "change",
    [
        dict(quantity=True),
        dict(quantity=1.5),
        dict(cost_basis=25.0),
        dict(broker_mark=D("NaN")),
        dict(pending_exercise=-1),
    ],
)
def test_position_inputs_are_strict(change):
    with pytest.raises(ValueError):
        replace(snapshot().positions[0], **change)


def test_immutable_tuple_and_utc_boundaries():
    with pytest.raises(FrozenInstanceError):
        snapshot().positions = ()
    for changes in (
        dict(positions=[]),
        dict(observed_at=NOW.replace(tzinfo=None)),
        dict(history_start=NOW + timedelta(days=1)),
        dict(data_hash="bad"),
        dict(complete_sections=("cash",)),
    ):
        with pytest.raises(ValueError):
            snapshot(**changes)


def test_settlement_sums_preserve_subcent_values_under_low_decimal_context():
    from decimal import localcontext

    settlements = (
        ObservedOptionSettlement(
            "large",
            contract().contract_id,
            D("100000000000000000000"),
            NOW + timedelta(days=1),
            False,
        ),
        ObservedOptionSettlement(
            "small", contract().contract_id, D("0.000000001"), NOW + timedelta(days=1), False
        ),
    )
    observed = snapshot(
        settlements=settlements,
        cash=replace(snapshot().cash, unsettled_receivable=D("100000000000000000000.000000001")),
    )
    with localcontext() as context:
        context.prec = 6
        assert reconcile(observed, observed).clean


@pytest.mark.parametrize(
    "state,filled",
    [
        (OrderState.FILLED, 0),
        (OrderState.PARTIALLY_FILLED, 0),
        (OrderState.PARTIALLY_FILLED, 1),
        (OrderState.REJECTED, 1),
        (OrderState.SUBMITTED, 2),
    ],
)
def test_impossible_order_quantity_and_state_are_not_reconciled(state, filled):
    bad = snapshot(orders=(order(state=state, filled_quantity=filled),))
    assert "broker_options_order_quantity_inconsistent" in codes(reconcile(bad, bad))


def test_cancel_request_preserves_fills_and_positions():
    for state in (OrderState.CANCEL_PENDING, OrderState.CANCELED):
        observed = snapshot(orders=(order(quantity=2, state=state),))
        assert reconcile(observed, observed).clean
        assert "broker_options_ownership_mismatch" in codes(
            reconcile(observed, observed, owned_positions=())
        )


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("occurred_at", NOW + timedelta(seconds=1), "broker_options_fill_outside_history"),
        ("occurred_at", NOW - timedelta(seconds=3), "broker_options_fill_outside_order"),
        ("fee", D("0.11"), "options_fill_state_mismatch"),
        ("price", D("0.24"), "options_fill_state_mismatch"),
    ],
)
def test_fill_timing_price_and_fees_are_checked(field, value, code):
    assert code in codes(reconcile(broker=snapshot(fills=(fill(**{field: value}),))))


def test_unknown_contract_duplicate_legs_and_missing_marks_are_incidents():
    bad = snapshot(
        contracts=(),
        orders=(order(legs=order().legs * 2),),
        positions=(replace(snapshot().positions[0], broker_mark=None),),
    )
    assert {
        "broker_options_contract_missing",
        "broker_options_duplicate_order_leg",
        "broker_options_broker_mark_missing",
    } <= codes(reconcile(bad, bad))


@pytest.mark.parametrize(
    "changes",
    [
        dict(local=None),
        dict(broker={}),
        dict(owned_positions=[]),
        dict(max_age_seconds=D("0")),
        dict(account_id=""),
        dict(reconciliation_id="bad\nidentity"),
    ],
)
def test_reconciliation_rejects_malformed_arguments(changes):
    args = dict(
        account_id=ACCOUNT,
        local=snapshot(),
        broker=snapshot(),
        owned_positions=(owned(),),
        as_of=NOW,
        max_age_seconds=D("30"),
        reconciliation_id="one",
    )
    args.update(changes)
    with pytest.raises(ValueError):
        reconcile_options(**args)


def test_observation_format_boundaries_fail_without_coercion():
    from trading_bot.domain.options import PositionEffect
    from trading_bot.domain.options_account import OptionsCash, observation_id, observation_rows

    for identity in ("x" * 256, "bad\x00id"):
        with pytest.raises(ValueError):
            observation_id(identity)
    with pytest.raises(ValueError):
        observation_rows((order(),) * 10_001, type(order()))
    for changes in (
        dict(legs=()),
        dict(legs=order().legs * 5),
        dict(quantity=0),
        dict(net_effect="unknown"),
        dict(updated_at=NOW - timedelta(days=1)),
    ):
        with pytest.raises(ValueError):
            order(**changes)
    for changes in (
        dict(structure=None),
        dict(units=0),
        dict(
            structure=replace(
                owned().structure,
                legs=(
                    replace(owned().structure.legs[0], side=Side.SELL, effect=PositionEffect.CLOSE),
                ),
            )
        ),
    ):
        with pytest.raises(ValueError):
            owned(**changes)
    with pytest.raises(ValueError):
        snapshot(cash={})
    with pytest.raises(ValueError):
        snapshot(complete_sections=(OptionsSnapshotSection.CASH,) * 2)
    with pytest.raises(ValueError):
        OptionsCash(*(D("NaN") for _ in range(7)))


def test_contract_future_order_history_and_negative_non_cash_fields():
    bad = snapshot(
        contracts=(contract(available_at=NOW + timedelta(seconds=1)),),
        orders=(order(created_at=NOW - timedelta(days=2)),),
        cash=replace(snapshot().cash, collateral=D("-1")),
    )
    assert {
        "broker_options_contract_future",
        "broker_options_order_outside_history",
        "broker_negative_collateral",
    } <= codes(reconcile(bad, bad))


def test_unknown_settlement_and_lifecycle_identity_or_time_cannot_reconcile():
    bad = snapshot(
        settlements=(ObservedOptionSettlement("completed", "unknown", D("10"), NOW, True),),
        lifecycle=(
            ObservedOptionLifecycle(
                "event-1",
                "unknown",
                OptionLifecycleKind.ASSIGNMENT,
                1,
                D("0"),
                NOW + timedelta(seconds=1),
            ),
        ),
    )
    assert {"broker_options_contract_missing", "broker_options_lifecycle_outside_history"} <= codes(
        reconcile(bad, bad)
    )


def test_identical_zero_share_observations_are_flat():
    good = snapshot(shares=(ObservedSharePosition("SYN", D("0")),))
    assert reconcile(good, good).clean


@pytest.mark.parametrize(
    "state",
    [
        OrderState.PROPOSED,
        OrderState.RISK_APPROVED,
        OrderState.REVIEW_REQUESTED,
        OrderState.REVIEWED,
        OrderState.SUBMITTED,
    ],
)
def test_pre_submission_and_unfilled_submitted_states_cannot_hide_actual_fills(state):
    bad = snapshot(orders=(order(state=state),))
    assert "broker_options_order_quantity_inconsistent" in codes(reconcile(bad, bad))


def test_partial_complete_package_and_missing_protective_leg_are_distinct():
    from trading_bot.domain.options import OptionLeg, OptionStructure, PositionEffect, StructureKind
    from trading_bot.domain.options_account import ObservedOptionLeg, ObservedOptionPosition

    long, short = (
        contract(),
        contract(
            contract_id="synthetic-short-105", standardized_id="SYN261016C00105000", strike=D("105")
        ),
    )
    structure = OptionStructure(
        StructureKind.DEBIT_VERTICAL,
        (
            OptionLeg(long, Side.BUY, PositionEffect.OPEN, 1),
            OptionLeg(short, Side.SELL, PositionEffect.OPEN, 1),
        ),
    )
    package = owned(structure=structure)
    partial = snapshot(
        contracts=(long, short),
        positions=(
            snapshot().positions[0],
            ObservedOptionPosition(short.contract_id, -1, D("-20"), D("0.20"), 0, 0, 0),
        ),
        orders=(
            order(
                legs=(
                    *order().legs,
                    ObservedOptionLeg(short.contract_id, Side.SELL, PositionEffect.OPEN, 1),
                ),
                quantity=2,
                filled_quantity=1,
                state=OrderState.PARTIALLY_FILLED,
            ),
        ),
        fills=(
            fill(),
            fill(
                fill_id="fill-short", contract_id=short.contract_id, side=Side.SELL, price=D("0.20")
            ),
        ),
    )
    assert reconcile(partial, partial, owned_positions=(package,)).clean
    unmatched = replace(partial, positions=(partial.positions[1],), fills=(partial.fills[1],))
    assert {"broker_options_ownership_mismatch", "broker_options_fill_quantity_mismatch"} <= codes(
        reconcile(unmatched, unmatched, owned_positions=(package,))
    )
