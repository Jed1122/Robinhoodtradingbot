from pathlib import Path


def test_execution_service_persists_review_before_final_risk() -> None:
    source = Path("src/trading_bot/execution/service.py").read_text()
    review_write = source.index("add_review(review_id, review)")
    final_risk_write = source.index("final_context =", review_write)
    assert review_write < final_risk_write
