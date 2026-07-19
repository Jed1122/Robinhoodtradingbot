from trading_bot.risk import run_risk_self_test


def test_risk_self_test_passes_all_named_vectors_deterministically() -> None:
    first = run_risk_self_test()
    second = run_risk_self_test()
    assert first.successful
    assert tuple(case.name for case in first.cases) == (
        "reject_stale_quote",
        "reject_overexposure",
        "allow_safe_micro_order",
        "reject_kill_switch",
    )
    assert first.evidence_hash == second.evidence_hash
