from pathlib import Path


def test_required_targets_exist() -> None:
    text = Path("Makefile").read_text()
    for target in {
        "setup",
        "test-unit",
        "test-integration",
        "test-chaos",
        "build",
        "deploy",
        "status",
        "logs",
        "backup",
        "restore-test",
    }:
        assert f"{target}:" in text
