"""Exercise existing fail-closed guards exposed by the strict branch-only gate."""

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.execution._fixtures import NOW, make_intent, make_review
from trading_bot.domain import (
    DomainValidationError,
    ExecutionMode,
    OrderPurpose,
    OrderState,
    RuntimeState,
)
from trading_bot.execution.recovery import RecoveryService
from trading_bot.execution.review import OrderReviewService, review_is_fresh
from trading_bot.execution.service import ExecutionResult, ExecutionService
from trading_bot.risk.action_policy import ActionContext, BrokerAction, is_action_allowed
from trading_bot.risk.kill_switch import FileKillSwitch, KillSwitchClearRequest


class Clock:
    def now(self):
        return NOW


def service(**changes):
    values = dict(
        review=OrderReviewService(object()),
        place=object(),
        pretrade=object(),
        context_loader=object(),
        uow_factory=lambda: None,
        exclusion=object(),
        mode=ExecutionMode.SIMULATION,
        provider="synthetic",
        clock=Clock(),
    )
    values.update(changes)
    return ExecutionService(**values)


@pytest.mark.parametrize(
    "changes",
    [
        {"review": object()},
        {"mode": "simulation"},
        {"provider": ""},
        {"clock": object()},
        {"uow_factory": None},
    ],
)
def test_execution_constructor_rejects_invalid_capability_context(changes) -> None:
    with pytest.raises(DomainValidationError):
        service(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"intent_id": ""},
        {"state": "filled"},
        {"reason_code": ""},
        {"correlation_id": ""},
        {"review_id": ""},
        {"submission_attempt_id": ""},
        {"broker_order": object()},
    ],
)
def test_execution_result_never_accepts_ambiguous_identity(changes) -> None:
    values = dict(
        intent_id="synthetic",
        state=OrderState.REJECTED,
        reason_code="test",
        correlation_id="synthetic",
        review_id=None,
        submission_attempt_id=None,
        broker_order=None,
    )
    with pytest.raises(DomainValidationError):
        ExecutionResult(**{**values, **changes})


async def test_execution_and_review_reject_wrong_record_types_before_any_work() -> None:
    with pytest.raises(DomainValidationError):
        await service().execute(object())
    with pytest.raises(DomainValidationError):
        service()._validate_evaluation(object(), make_intent(), expected_check_count=24)
    with pytest.raises(DomainValidationError):
        review_is_fresh(object(), NOW)
    with pytest.raises(DomainValidationError):
        review_is_fresh(make_review(make_intent()), "now")


def context() -> ActionContext:
    return ActionContext(True, True, True, True, True, True, False, RuntimeState.PAUSED)


def test_action_policy_checks_canonical_inputs_and_authentication() -> None:
    with pytest.raises(DomainValidationError):
        replace(context(), lease_valid=1)
    with pytest.raises(DomainValidationError):
        replace(context(), last_reconciled_state="paused")
    for state, action, ctx in (
        ("paused", BrokerAction.NEW_ENTRY, context()),
        (RuntimeState.PAUSED, "new_entry", context()),
        (RuntimeState.PAUSED, BrokerAction.NEW_ENTRY, object()),
    ):
        with pytest.raises(DomainValidationError):
            is_action_allowed(state, action, ctx)
    denied = is_action_allowed(
        RuntimeState.RUNNING_LIVE,
        BrokerAction.NEW_ENTRY,
        replace(context(), account_authenticated=False),
    )
    assert not denied.allowed
    assert denied.reason == "account_not_authenticated"


def test_kill_switch_rejects_structured_invalid_state_and_empty_requests(tmp_path: Path) -> None:
    path = tmp_path / "synthetic-kill.json"
    switch = FileKillSwitch(path, clock=Clock())
    with pytest.raises(DomainValidationError):
        switch.activate("")
    with pytest.raises(DomainValidationError):
        switch.clear(object())
    assert not switch.clear(KillSwitchClearRequest(False, True, True, "verified")).active
    path.write_text(json.dumps({"active": False, "reason": "wrong", "changed_at": "now"}))
    assert switch.status().active
    assert not switch.status().state_valid


@pytest.mark.parametrize(
    ("purpose", "filled", "owned", "accepted", "expected_calls"),
    [
        (OrderPurpose.PROTECTIVE_EXIT, "0", True, True, 0),
        (OrderPurpose.ENTRY, "1", True, True, 0),
        (OrderPurpose.ENTRY, "0", False, True, 0),
        (OrderPurpose.ENTRY, "0", True, False, 1),
    ],
)
async def test_recovery_preserves_protection_and_requires_confirmed_safe_cancel(
    purpose,
    filled,
    owned,
    accepted,
    expected_calls,
) -> None:
    class Read:
        async def get_accounts(self):
            return (SimpleNamespace(account_id="synthetic-account"),)

    class Cancel:
        calls = 0

        async def cancel_known_order(self, account_id, order_id):
            self.calls += 1
            return SimpleNamespace(accepted=accepted)

    class Reconcile:
        async def reconcile(self, account_id):
            return SimpleNamespace(clean=True)

    class Local:
        async def unfilled_entry_orders(self, account_id):
            return (
                SimpleNamespace(
                    purpose=purpose,
                    filled_quantity=Decimal(filled),
                    broker_order_id="synthetic-order",
                ),
            )

    cancel = Cancel()
    recovery = RecoveryService(
        Read(), cancel, Reconcile(), Local(), replace(context(), order_owned=owned)
    )
    result = await recovery.recover("synthetic-account")
    assert result.state is RuntimeState.PAUSED
    assert result.canceled_order_ids == ()
    assert cancel.calls == expected_calls
    with pytest.raises(RuntimeError, match="account identity"):
        await recovery.recover("wrong-account")
