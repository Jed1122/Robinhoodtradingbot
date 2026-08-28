from pathlib import Path


def test_container_is_nonroot_and_paused() -> None:
    text = Path("Dockerfile").read_text()
    assert "USER 10001:10001" in text and '"--paused"' in text
    assert "COPY configs /app/configs" in text
    assert "HEALTHCHECK" in text
    assert '"serve"' in text


def test_docker_context_excludes_local_work_products() -> None:
    ignored = set(Path(".dockerignore").read_text().splitlines())

    assert {
        ".git",
        ".venv",
        "**/__pycache__",
        "**/.mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
        ".coverage",
        "htmlcov",
        "dist",
        ".superpowers",
    } <= ignored
