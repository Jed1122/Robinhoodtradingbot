from pathlib import Path


def test_container_is_nonroot_and_paused() -> None:
    text = Path("Dockerfile").read_text()
    assert "USER 10001:10001" in text and '"--paused"' in text
