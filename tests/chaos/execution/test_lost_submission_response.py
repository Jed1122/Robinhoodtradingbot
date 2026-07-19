from pathlib import Path


def test_transport_exception_is_persisted_as_ambiguous() -> None:
    source = Path("src/trading_bot/execution/service.py").read_text()
    assert "SubmissionOutcome.AMBIGUOUS" in source
    assert "OrderEvent.BROKER_AMBIGUOUS" in source
    state_machine = Path("src/trading_bot/domain/order_state_machine.py").read_text()
    assert "OrderState.UNKNOWN_REQUIRES_RECONCILIATION" in state_machine
