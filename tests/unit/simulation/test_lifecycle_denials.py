"""Adversarial coverage for existing lifecycle input and conservation guards."""

from dataclasses import replace
from decimal import Decimal

import pytest

from trading_bot.domain import DataHash
from trading_bot.execution.partial_fills import apply_fill
from trading_bot.simulation import lifecycle_accounting
from trading_bot.simulation.lifecycle_codec import lifecycle_hash
from trading_bot.simulation.lifecycle_models import LifecycleSnapshot, LifecycleValidationError

from ._lifecycle_fixtures import execution, make_request


def _snapshot() -> LifecycleSnapshot:
    r = make_request()
    return LifecycleSnapshot(
        r.order,
        r.position,
        r.cash,
        Decimal(0),
        r.order.requested_quantity,
        r.submitted,
        DataHash("d" * 64),
    )


@pytest.mark.parametrize("kind", ["", False, None])
def test_lifecycle_hash_requires_nonempty_exact_string_kind(kind: object) -> None:
    with pytest.raises(LifecycleValidationError, match="lifecycle_hash_invalid"):
        lifecycle_hash(kind, {})


@pytest.mark.parametrize("invalid_snapshot", [False, True])
def test_fill_accounting_rejects_untyped_inputs(invalid_snapshot: bool) -> None:
    initial = object() if invalid_snapshot else _snapshot()
    fill = execution("fill", 2, "0.25").fill if invalid_snapshot else object()
    with pytest.raises(LifecycleValidationError, match="lifecycle_input_invalid"):
        lifecycle_accounting.apply_lifecycle_fill(initial, fill)


def test_inconsistent_fill_helper_cannot_override_checked_cash_conservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = _snapshot()
    fill = execution("fill", 2, "0.25").fill
    application = apply_fill(position=initial.position, order=initial.order, fill=fill)
    inconsistent = replace(application, cash_delta=Decimal("1"))
    monkeypatch.setattr(lifecycle_accounting, "apply_fill", lambda **kwargs: inconsistent)
    with pytest.raises(LifecycleValidationError, match="lifecycle_accounting_invalid"):
        lifecycle_accounting.apply_lifecycle_fill(initial, fill)
    assert initial.cash == Decimal("1000")
    assert initial.position.quantity == 0
