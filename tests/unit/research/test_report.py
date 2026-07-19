from trading_bot.research.report import (
    ResearchAttempt,
    ResearchRunRecord,
    build_research_report,
    render_json,
    render_markdown,
)


def test_report_contains_rejected_attempts_and_disclaimer() -> None:
    run = ResearchRunRecord(
        "run-1",
        "strategy-v1",
        "a" * 64,
        "b" * 64,
        "c" * 64,
        (("fees", "0.1"),),
        (("window", ("20", "30")),),
        ("survivorship unknown",),
    )
    report = build_research_report(
        run,
        attempts=(
            ResearchAttempt("momentum", "d" * 64, "accepted", (), None),
            ResearchAttempt("mean_reversion", "e" * 64, "rejected", ("negative_oos",), None),
        ),
    )
    assert {attempt.status for attempt in report.attempts} == {"accepted", "rejected"}
    assert "do not guarantee" in render_markdown(report)
    assert render_json(report) == render_json(report)
