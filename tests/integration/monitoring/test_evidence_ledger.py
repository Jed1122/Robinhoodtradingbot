from trading_bot.monitoring.promotion import EvidenceLedger


def test_duplicate_evidence_does_not_count() -> None:
    ledger = EvidenceLedger()
    assert ledger.append_unique("a" * 64)
    assert not ledger.append_unique("a" * 64)
