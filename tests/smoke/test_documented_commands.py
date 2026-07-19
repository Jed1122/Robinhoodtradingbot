from pathlib import Path


def test_documented_commands_exist() -> None:
    readme = Path("README.md").read_text()
    assert "codex mcp add robinhood-trading --url https://agent.robinhood.com/mcp/trading" in readme
    assert "uv run python scripts/verify_robinhood_equity_reads.py" in readme
    assert "make shadow-smoke" in readme
    assert "make shadow" in readme


def test_secret_values_are_not_documented() -> None:
    template = Path(".env.example").read_text()
    for name in (
        "ROBINHOOD_MCP_OAUTH_STORE_DIR",
        "ROBINHOOD_CRYPTO_API_KEY_FILE",
        "ROBINHOOD_CRYPTO_PRIVATE_KEY_FILE",
    ):
        assert f"{name}=\n" in template
