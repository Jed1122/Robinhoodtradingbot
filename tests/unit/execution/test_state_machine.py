"""Contract tests for the deterministic order state machine."""

import traceback
from enum import StrEnum
from itertools import product
from typing import Final

import pytest

import trading_bot.execution as execution_package
import trading_bot.execution.state_machine as state_machine_module
from trading_bot.domain import OrderEvent, OrderState
from trading_bot.execution import InvalidOrderTransition, transition

EXPECTED_TRANSITIONS: Final[dict[tuple[OrderState, OrderEvent], OrderState]] = {
    (OrderState.PROPOSED, OrderEvent.RISK_DENY): OrderState.RISK_REJECTED,
    (OrderState.PROPOSED, OrderEvent.RISK_ALLOW): OrderState.RISK_APPROVED,
    (OrderState.PROPOSED, OrderEvent.EXPIRE): OrderState.EXPIRED,
    (OrderState.RISK_APPROVED, OrderEvent.REQUEST_REVIEW): OrderState.REVIEW_REQUESTED,
    (OrderState.RISK_APPROVED, OrderEvent.EXPIRE): OrderState.EXPIRED,
    (OrderState.REVIEW_REQUESTED, OrderEvent.REVIEW_ACCEPTED): OrderState.REVIEWED,
    (OrderState.REVIEW_REQUESTED, OrderEvent.REVIEW_REJECTED): OrderState.REJECTED,
    (OrderState.REVIEW_REQUESTED, OrderEvent.EXPIRE): OrderState.EXPIRED,
    (OrderState.REVIEWED, OrderEvent.FINAL_RISK_DENY): OrderState.RISK_REJECTED,
    (OrderState.REVIEWED, OrderEvent.PREPARE_SUBMISSION): OrderState.SUBMISSION_PENDING,
    (OrderState.REVIEWED, OrderEvent.EXPIRE): OrderState.EXPIRED,
    (OrderState.SUBMISSION_PENDING, OrderEvent.BROKER_ACCEPTED): OrderState.SUBMITTED,
    (OrderState.SUBMISSION_PENDING, OrderEvent.BROKER_REJECTED): OrderState.REJECTED,
    (
        OrderState.SUBMISSION_PENDING,
        OrderEvent.BROKER_AMBIGUOUS,
    ): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    (OrderState.SUBMITTED, OrderEvent.PARTIAL_FILL): OrderState.PARTIALLY_FILLED,
    (OrderState.SUBMITTED, OrderEvent.FILL): OrderState.FILLED,
    (OrderState.SUBMITTED, OrderEvent.REQUEST_CANCEL): OrderState.CANCEL_PENDING,
    (OrderState.SUBMITTED, OrderEvent.BROKER_EXPIRED): OrderState.EXPIRED,
    (
        OrderState.SUBMITTED,
        OrderEvent.RECONCILIATION_DRIFT,
    ): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    (OrderState.PARTIALLY_FILLED, OrderEvent.PARTIAL_FILL): OrderState.PARTIALLY_FILLED,
    (OrderState.PARTIALLY_FILLED, OrderEvent.FILL): OrderState.FILLED,
    (OrderState.PARTIALLY_FILLED, OrderEvent.REQUEST_CANCEL): OrderState.CANCEL_PENDING,
    (OrderState.PARTIALLY_FILLED, OrderEvent.BROKER_EXPIRED): OrderState.EXPIRED,
    (
        OrderState.PARTIALLY_FILLED,
        OrderEvent.RECONCILIATION_DRIFT,
    ): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    (OrderState.CANCEL_PENDING, OrderEvent.CANCEL_CONFIRMED): OrderState.CANCELED,
    (
        OrderState.CANCEL_PENDING,
        OrderEvent.CANCEL_REJECTED,
    ): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    (OrderState.CANCEL_PENDING, OrderEvent.PARTIAL_FILL): OrderState.CANCEL_PENDING,
    (OrderState.CANCEL_PENDING, OrderEvent.FILL): OrderState.FILLED,
    (OrderState.CANCEL_PENDING, OrderEvent.BROKER_EXPIRED): OrderState.EXPIRED,
    (
        OrderState.CANCEL_PENDING,
        OrderEvent.RECONCILIATION_DRIFT,
    ): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    (
        OrderState.CANCEL_PENDING,
        OrderEvent.BROKER_AMBIGUOUS,
    ): OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
    (
        OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
        OrderEvent.RECONCILE_SUBMITTED,
    ): OrderState.SUBMITTED,
    (
        OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
        OrderEvent.RECONCILE_PARTIAL,
    ): OrderState.PARTIALLY_FILLED,
    (
        OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
        OrderEvent.RECONCILE_FILLED,
    ): OrderState.FILLED,
    (
        OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
        OrderEvent.RECONCILE_CANCELED,
    ): OrderState.CANCELED,
    (
        OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
        OrderEvent.RECONCILE_REJECTED,
    ): OrderState.REJECTED,
    (
        OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
        OrderEvent.RECONCILE_EXPIRED,
    ): OrderState.EXPIRED,
}

TERMINAL_STATES: Final = frozenset(
    {
        OrderState.RISK_REJECTED,
        OrderState.REJECTED,
        OrderState.FILLED,
        OrderState.CANCELED,
        OrderState.EXPIRED,
    }
)


@pytest.mark.parametrize(
    ("current", "event"),
    tuple(product(tuple(OrderState), tuple(OrderEvent))),
)
def test_exact_transition_matrix(current: OrderState, event: OrderEvent) -> None:
    expected = EXPECTED_TRANSITIONS.get((current, event))

    if expected is None:
        with pytest.raises(InvalidOrderTransition):
            transition(current, event)
    else:
        assert transition(current, event) is expected


def test_transition_contract_has_exact_expected_size() -> None:
    assert len(OrderState) == 14
    assert len(OrderEvent) == 24
    assert len(EXPECTED_TRANSITIONS) == 37


def test_terminal_states_have_no_outgoing_transition() -> None:
    for terminal, event in product(TERMINAL_STATES, tuple(OrderEvent)):
        with pytest.raises(InvalidOrderTransition):
            transition(terminal, event)


def test_local_expiry_is_limited_to_pre_submission_states() -> None:
    expirable = {
        OrderState.PROPOSED,
        OrderState.RISK_APPROVED,
        OrderState.REVIEW_REQUESTED,
        OrderState.REVIEWED,
    }

    for state in OrderState:
        if state in expirable:
            assert transition(state, OrderEvent.EXPIRE) is OrderState.EXPIRED
        else:
            with pytest.raises(InvalidOrderTransition):
                transition(state, OrderEvent.EXPIRE)


def test_broker_expiry_is_limited_to_known_active_orders() -> None:
    broker_expirable = {
        OrderState.SUBMITTED,
        OrderState.PARTIALLY_FILLED,
        OrderState.CANCEL_PENDING,
    }

    for state in OrderState:
        if state in broker_expirable:
            assert transition(state, OrderEvent.BROKER_EXPIRED) is OrderState.EXPIRED
        else:
            with pytest.raises(InvalidOrderTransition):
                transition(state, OrderEvent.BROKER_EXPIRED)


def test_active_order_drift_requires_explicit_reconciliation() -> None:
    for active in (
        OrderState.SUBMITTED,
        OrderState.PARTIALLY_FILLED,
        OrderState.CANCEL_PENDING,
    ):
        assert (
            transition(active, OrderEvent.RECONCILIATION_DRIFT)
            is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
        )


def test_unknown_state_accepts_only_reconciliation_outcomes() -> None:
    reconciliation_events = {
        OrderEvent.RECONCILE_SUBMITTED,
        OrderEvent.RECONCILE_PARTIAL,
        OrderEvent.RECONCILE_FILLED,
        OrderEvent.RECONCILE_CANCELED,
        OrderEvent.RECONCILE_REJECTED,
        OrderEvent.RECONCILE_EXPIRED,
    }

    for event in OrderEvent:
        if event in reconciliation_events:
            assert (
                transition(OrderState.UNKNOWN_REQUIRES_RECONCILIATION, event)
                is EXPECTED_TRANSITIONS[(OrderState.UNKNOWN_REQUIRES_RECONCILIATION, event)]
            )
        else:
            with pytest.raises(InvalidOrderTransition):
                transition(OrderState.UNKNOWN_REQUIRES_RECONCILIATION, event)


def test_submission_pending_requires_a_broker_outcome() -> None:
    allowed = {
        OrderEvent.BROKER_ACCEPTED,
        OrderEvent.BROKER_REJECTED,
        OrderEvent.BROKER_AMBIGUOUS,
    }

    for event in OrderEvent:
        if event in allowed:
            assert (
                transition(OrderState.SUBMISSION_PENDING, event)
                is EXPECTED_TRANSITIONS[(OrderState.SUBMISSION_PENDING, event)]
            )
        else:
            with pytest.raises(InvalidOrderTransition):
                transition(OrderState.SUBMISSION_PENDING, event)


def test_cancel_pending_partial_fill_preserves_cancel_intent() -> None:
    assert (
        transition(OrderState.CANCEL_PENDING, OrderEvent.PARTIAL_FILL) is OrderState.CANCEL_PENDING
    )
    assert transition(OrderState.CANCEL_PENDING, OrderEvent.FILL) is OrderState.FILLED
    assert (
        transition(OrderState.CANCEL_PENDING, OrderEvent.CANCEL_REJECTED)
        is OrderState.UNKNOWN_REQUIRES_RECONCILIATION
    )


def test_all_states_are_reachable_from_proposed() -> None:
    reachable = {OrderState.PROPOSED}
    while True:
        discovered = {
            target
            for (source, _event), target in EXPECTED_TRANSITIONS.items()
            if source in reachable
        }
        if discovered <= reachable:
            break
        reachable.update(discovered)

    assert reachable == set(OrderState)


def test_transition_table_uses_every_event_and_only_terminals_are_sinks() -> None:
    used_events = {event for (_state, event) in EXPECTED_TRANSITIONS}
    states_with_outgoing = {state for (state, _event) in EXPECTED_TRANSITIONS}

    assert used_events == set(OrderEvent)
    assert set(OrderState) - states_with_outgoing == set(TERMINAL_STATES)


class _ForeignState(StrEnum):
    PROPOSED = "proposed"


class _ForeignEvent(StrEnum):
    RISK_ALLOW = "risk_allow"


class _StringSubclass(str):
    pass


@pytest.mark.parametrize(
    ("current", "event"),
    [
        ("proposed", OrderEvent.RISK_ALLOW),
        (OrderState.PROPOSED, "risk_allow"),
        (_StringSubclass("proposed"), OrderEvent.RISK_ALLOW),
        (OrderState.PROPOSED, _StringSubclass("risk_allow")),
        (_ForeignState.PROPOSED, OrderEvent.RISK_ALLOW),
        (OrderState.PROPOSED, _ForeignEvent.RISK_ALLOW),
        (OrderEvent.RISK_ALLOW, OrderState.PROPOSED),
        (None, OrderEvent.RISK_ALLOW),
        (OrderState.PROPOSED, None),
        (False, OrderEvent.RISK_ALLOW),
        (OrderState.PROPOSED, True),
        (object(), OrderEvent.RISK_ALLOW),
        (OrderState.PROPOSED, object()),
    ],
)
def test_transition_rejects_noncanonical_runtime_types(current: object, event: object) -> None:
    with pytest.raises(InvalidOrderTransition) as error:
        transition(current, event)  # type: ignore[arg-type]

    assert error.value.args == ("order transition is not allowed",)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


class _HostileInput:
    def __repr__(self) -> str:
        raise AssertionError("repr must not be called")

    def __str__(self) -> str:
        raise AssertionError("str must not be called")

    def __hash__(self) -> int:
        raise AssertionError("hash must not be called")

    def __eq__(self, other: object) -> bool:
        raise AssertionError("equality must not be called")


def test_invalid_input_is_not_rendered_hashed_or_compared() -> None:
    hostile = _HostileInput()

    with pytest.raises(InvalidOrderTransition) as error:
        transition(hostile, hostile)  # type: ignore[arg-type]

    assert error.value.args == ("order transition is not allowed",)


@pytest.mark.parametrize(
    ("current", "event"),
    [
        (OrderState.RISK_REJECTED, OrderEvent.PREPARE_SUBMISSION),
        ("proposed", OrderEvent.RISK_ALLOW),
    ],
)
def test_invalid_transition_suppresses_an_active_exception_chain(
    current: object, event: OrderEvent
) -> None:
    secret_marker = "never-render-this-secret-marker"

    with pytest.raises(InvalidOrderTransition) as error:
        try:
            raise RuntimeError(secret_marker)
        except RuntimeError:
            transition(current, event)  # type: ignore[arg-type]

    rendered = "".join(traceback.format_exception(error.value))
    assert error.value.__suppress_context__
    assert secret_marker not in rendered


def test_transition_mapping_is_private_and_runtime_immutable() -> None:
    assert not hasattr(state_machine_module, "TRANSITIONS")

    with pytest.raises(TypeError):
        state_machine_module._TRANSITIONS[
            (OrderState.RISK_REJECTED, OrderEvent.PREPARE_SUBMISSION)
        ] = OrderState.SUBMITTED  # type: ignore[index]

    with pytest.raises(InvalidOrderTransition):
        transition(OrderState.RISK_REJECTED, OrderEvent.PREPARE_SUBMISSION)


def test_public_exports_are_minimal() -> None:
    expected = ["InvalidOrderTransition", "transition"]

    assert execution_package.__all__ == expected
    assert state_machine_module.__all__ == expected
