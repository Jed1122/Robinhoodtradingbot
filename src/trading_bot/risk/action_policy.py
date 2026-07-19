"""Fail-closed broker action matrix for every runtime state."""

from dataclasses import dataclass
from enum import StrEnum

from trading_bot.clock import DomainValidationError
from trading_bot.domain import RuntimeState


class BrokerAction(StrEnum):
    NEW_ENTRY = "new_entry"
    REDUCE_EXPOSURE = "reduce_exposure"
    CANCEL_KNOWN_ENTRY = "cancel_known_entry"
    CANCEL_PROTECTIVE_EXIT = "cancel_protective_exit"


@dataclass(frozen=True, slots=True)
class ActionContext:
    lease_valid: bool
    account_authenticated: bool
    order_owned: bool
    broker_state_current: bool
    cancellation_reduces_risk: bool
    replacement_is_deterministic: bool
    explicit_operator_action: bool
    last_reconciled_state: RuntimeState | None

    def __post_init__(self) -> None:
        for name, value in (
            ("lease_valid", self.lease_valid),
            ("account_authenticated", self.account_authenticated),
            ("order_owned", self.order_owned),
            ("broker_state_current", self.broker_state_current),
            ("cancellation_reduces_risk", self.cancellation_reduces_risk),
            ("replacement_is_deterministic", self.replacement_is_deterministic),
            ("explicit_operator_action", self.explicit_operator_action),
        ):
            if type(value) is not bool:
                raise DomainValidationError(f"{name} must be a boolean")
        if (
            self.last_reconciled_state is not None
            and type(self.last_reconciled_state) is not RuntimeState
        ):
            raise DomainValidationError("last_reconciled_state must be a RuntimeState or None")


@dataclass(frozen=True, slots=True)
class ActionDecision:
    allowed: bool
    reason: str


def is_action_allowed(
    state: RuntimeState,
    action: BrokerAction,
    context: ActionContext,
) -> ActionDecision:
    """Return a total, conservative decision for one of the 24 matrix cells."""

    if type(state) is not RuntimeState or type(action) is not BrokerAction:
        raise DomainValidationError("state and action must use canonical enums")
    if type(context) is not ActionContext:
        raise DomainValidationError("context must be an ActionContext")
    if not context.account_authenticated:
        return ActionDecision(False, "account_not_authenticated")

    if action in {BrokerAction.NEW_ENTRY, BrokerAction.REDUCE_EXPOSURE}:
        if not context.lease_valid:
            return ActionDecision(False, "live_lease_invalid")
        if action is BrokerAction.NEW_ENTRY:
            allowed = state is RuntimeState.RUNNING_LIVE
        else:
            allowed = state in {RuntimeState.RUNNING_LIVE, RuntimeState.ENTRY_BLOCKED}
        return ActionDecision(allowed, "allowed" if allowed else "runtime_state_blocks_write")

    safe_cancel = (
        context.order_owned and context.broker_state_current and context.cancellation_reduces_risk
    )
    if not safe_cancel:
        return ActionDecision(False, "cancel_attestation_incomplete")

    if action is BrokerAction.CANCEL_PROTECTIVE_EXIT:
        allowed = state is RuntimeState.RUNNING_LIVE and (
            context.replacement_is_deterministic or context.explicit_operator_action
        )
        return ActionDecision(allowed, "allowed" if allowed else "protective_exit_preserved")

    allowed = state in {
        RuntimeState.RUNNING_LIVE,
        RuntimeState.ENTRY_BLOCKED,
        RuntimeState.PAUSED,
        RuntimeState.KILL_SWITCH_ACTIVE,
        RuntimeState.RECONCILIATION_REQUIRED,
    }
    if state is RuntimeState.SHUTTING_DOWN:
        allowed = context.last_reconciled_state is not None
    return ActionDecision(allowed, "allowed" if allowed else "entry_cancel_not_justified")


__all__ = ["ActionContext", "ActionDecision", "BrokerAction", "is_action_allowed"]
