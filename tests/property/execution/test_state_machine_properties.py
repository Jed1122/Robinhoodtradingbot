"""Property invariants for order state transitions."""

from contextlib import suppress

from hypothesis import given, settings
from hypothesis import strategies as st

from trading_bot.domain import OrderEvent, OrderState
from trading_bot.execution import InvalidOrderTransition, transition

TERMINAL_STATES = (
    OrderState.RISK_REJECTED,
    OrderState.REJECTED,
    OrderState.FILLED,
    OrderState.CANCELED,
    OrderState.EXPIRED,
)


@given(
    terminal=st.sampled_from(TERMINAL_STATES),
    events=st.lists(st.sampled_from(tuple(OrderEvent)), max_size=50),
)
@settings(deadline=None, max_examples=150)
def test_terminal_states_are_absorbing_under_any_event_sequence(
    terminal: OrderState, events: list[OrderEvent]
) -> None:
    state = terminal

    for event in events:
        with suppress(InvalidOrderTransition):
            state = transition(state, event)

    assert state is terminal


@given(
    state=st.sampled_from(tuple(OrderState)),
    event=st.sampled_from(tuple(OrderEvent)),
)
@settings(deadline=None, max_examples=300)
def test_transition_is_deterministic(state: OrderState, event: OrderEvent) -> None:
    try:
        first = transition(state, event)
    except InvalidOrderTransition:
        try:
            transition(state, event)
        except InvalidOrderTransition:
            return
        raise AssertionError("an invalid transition became valid") from None

    assert transition(state, event) is first


@given(events=st.lists(st.sampled_from(tuple(OrderEvent)), max_size=50))
@settings(deadline=None, max_examples=150)
def test_risk_rejected_never_reaches_submission(events: list[OrderEvent]) -> None:
    state = OrderState.RISK_REJECTED

    for event in events:
        with suppress(InvalidOrderTransition):
            state = transition(state, event)

    assert state is OrderState.RISK_REJECTED


@given(
    state=st.sampled_from(tuple(OrderState)),
    event=st.sampled_from(tuple(OrderEvent)),
)
@settings(deadline=None, max_examples=300)
def test_invalid_event_cannot_mutate_caller_state(state: OrderState, event: OrderEvent) -> None:
    original = state

    try:
        state = transition(state, event)
    except InvalidOrderTransition:
        assert state is original
