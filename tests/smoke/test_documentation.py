from pathlib import Path


def test_required_docs_and_disclosures_exist() -> None:
    required = [
        "risk-policy.md",
        "live-activation.md",
        "threat-model.md",
        "incident-response.md",
        "disaster-recovery.md",
        "operations-runbook.md",
        "final-implementation-report.md",
    ]
    for name in required:
        assert Path("docs", name).read_text().strip()
    final = Path("docs/final-implementation-report.md").read_text()
    assert "No live order was placed during development" in final
    assert "profit" in final.lower()
