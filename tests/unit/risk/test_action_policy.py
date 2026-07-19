from dataclasses import replace

import pytest

from trading_bot.domain import RuntimeState
from trading_bot.risk.action_policy import (
    ActionContext,
    BrokerAction,
    is_action_allowed,
)


def fully_attested() -> ActionContext:
    return ActionContext(True, True, True, True, True, True, False, RuntimeState.RUNNING_LIVE)


EXPECTED = {
    (state, action): (
        state is RuntimeState.RUNNING_LIVE
        if action is BrokerAction.NEW_ENTRY
        else state in {RuntimeState.RUNNING_LIVE, RuntimeState.ENTRY_BLOCKED}
        if action is BrokerAction.REDUCE_EXPOSURE
        else True
        if action is BrokerAction.CANCEL_KNOWN_ENTRY
        else state is RuntimeState.RUNNING_LIVE
    )
    for state in RuntimeState
    for action in BrokerAction
}


@pytest.mark.parametrize("state", list(RuntimeState))
@pytest.mark.parametrize("action", list(BrokerAction))
def test_runtime_action_matrix_covers_all_24_cells(
    state: RuntimeState, action: BrokerAction
) -> None:
    assert is_action_allowed(state, action, fully_attested()).allowed is EXPECTED[state, action]


def test_cancel_requires_positive_ownership_and_risk_reduction() -> None:
    context = replace(fully_attested(), order_owned=False, cancellation_reduces_risk=False)
    assert not is_action_allowed(
        RuntimeState.KILL_SWITCH_ACTIVE, BrokerAction.CANCEL_KNOWN_ENTRY, context
    ).allowed


def test_cancel_does_not_require_lease_but_reduce_write_does() -> None:
    context = replace(fully_attested(), lease_valid=False)
    assert is_action_allowed(RuntimeState.PAUSED, BrokerAction.CANCEL_KNOWN_ENTRY, context).allowed
    assert not is_action_allowed(
        RuntimeState.ENTRY_BLOCKED, BrokerAction.REDUCE_EXPOSURE, context
    ).allowed


def test_protective_exit_is_never_automatically_cancelled() -> None:
    context = replace(
        fully_attested(), replacement_is_deterministic=False, explicit_operator_action=False
    )
    assert not is_action_allowed(
        RuntimeState.RUNNING_LIVE, BrokerAction.CANCEL_PROTECTIVE_EXIT, context
    ).allowed
