from pathlib import Path


def test_container_is_nonroot_and_paused() -> None:
    text = Path("Dockerfile").read_text()
    assert "USER 10001:10001" in text and '"--paused"' in text
    assert "COPY configs /app/configs" in text
    assert "HEALTHCHECK" in text
    assert '"serve"' in text


def test_docker_context_is_an_explicit_release_input_allowlist() -> None:
    patterns = Path(".dockerignore").read_text().splitlines()

    assert patterns == [
        "**",
        "!pyproject.toml",
        "!uv.lock",
        "!alembic.ini",
        "!migrations",
        "!migrations/**",
        "!src",
        "!src/**",
        "!configs",
        "!configs/**",
        "**/__pycache__",
        "**/.mypy_cache",
    ]
