from pathlib import Path


def test_pending_and_unknown_submission_states_cannot_transition_to_prepare_again() -> None:
    source = Path("src/trading_bot/domain/order_state_machine.py").read_text()
    pending_section = source[source.index("OrderState.SUBMISSION_PENDING") :]
    assert "OrderEvent.PREPARE_SUBMISSION" not in pending_section.split("},", 1)[0]
    assert "UNKNOWN_REQUIRES_RECONCILIATION" in source
