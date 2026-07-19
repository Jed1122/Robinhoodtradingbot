from pathlib import Path


def test_ci_has_no_live_secrets_and_actions_are_pinned() -> None:
    text = Path(".github/workflows/ci.yml").read_text()
    assert "ROBINHOOD_" not in text and "@v" not in text
