"""A stale leader can never renew after a higher fencing token is issued."""

from pathlib import Path


def test_execution_lease_uses_immediate_transaction_and_conditional_fence() -> None:
    source = (Path(__file__).parents[2] / "src/trading_bot/persistence/lease.py").read_text()
    assert 'text("BEGIN IMMEDIATE")' in source
    assert "ExecutionLeaseRow.fencing_token == lease.fencing_token" in source
    assert "row.fencing_token + 1" in source
