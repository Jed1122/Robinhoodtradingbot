import json
import os
import stat
import subprocess
from pathlib import Path


def test_live_readiness_fails_closed_without_operator_inputs() -> None:
    env = os.environ.copy()
    for name in (
        "LIVE_TRADING_ENABLED",
        "ROBINHOOD_CRYPTO_API_KEY_FILE",
        "ROBINHOOD_CRYPTO_PRIVATE_KEY_FILE",
        "TRADING_BOT_AUTH_VERIFY_KEY_FILE",
        "TRADING_BOT_ACCOUNT_ALLOWLIST_FILE",
        "TRADING_BOT_AUTH_SIGNING_KEY_FILE",
        "ROBINHOOD_MCP_OAUTH_STORE_DIR",
    ):
        env.pop(name, None)
    result = subprocess.run(
        ["uv", "run", "python", "scripts/live_readiness.py"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ready"] is False
    assert payload["status"] == "blocked_fail_closed"


def test_live_readiness_accepts_minimal_operator_controlled_files(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["LIVE_TRADING_ENABLED"] = "true"
    for name in (
        "ROBINHOOD_CRYPTO_API_KEY_FILE",
        "ROBINHOOD_CRYPTO_PRIVATE_KEY_FILE",
        "TRADING_BOT_AUTH_VERIFY_KEY_FILE",
        "TRADING_BOT_ACCOUNT_ALLOWLIST_FILE",
    ):
        path = tmp_path / name.lower()
        path.write_text("operator-supplied\n")
        path.chmod(0o600)
        env[name] = str(path)
    mcp_store = tmp_path / "mcp-oauth"
    mcp_store.mkdir()
    mcp_store.chmod(0o700)
    env["ROBINHOOD_MCP_OAUTH_STORE_DIR"] = str(mcp_store)
    env.pop("TRADING_BOT_AUTH_SIGNING_KEY_FILE", None)
    result = subprocess.run(
        ["uv", "run", "python", "scripts/live_readiness.py"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ready"] is True
    assert {check["name"] for check in payload["checks"]} >= {
        "configuration",
        "ROBINHOOD_CRYPTO_API_KEY_FILE",
        "ROBINHOOD_MCP_OAUTH_STORE_DIR",
        "TRADING_BOT_AUTH_SIGNING_KEY_FILE",
    }
    for name in (
        "ROBINHOOD_CRYPTO_API_KEY_FILE",
        "ROBINHOOD_CRYPTO_PRIVATE_KEY_FILE",
    ):
        assert stat.S_IMODE(Path(env[name]).stat().st_mode) == 0o600


def test_live_readiness_rejects_insecure_mcp_oauth_store(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["LIVE_TRADING_ENABLED"] = "true"
    for name in (
        "ROBINHOOD_CRYPTO_API_KEY_FILE",
        "ROBINHOOD_CRYPTO_PRIVATE_KEY_FILE",
        "TRADING_BOT_AUTH_VERIFY_KEY_FILE",
        "TRADING_BOT_ACCOUNT_ALLOWLIST_FILE",
    ):
        path = tmp_path / name.lower()
        path.write_text("operator-supplied\n")
        path.chmod(0o600)
        env[name] = str(path)
    mcp_store = tmp_path / "mcp-oauth"
    mcp_store.mkdir()
    mcp_store.chmod(0o755)
    env["ROBINHOOD_MCP_OAUTH_STORE_DIR"] = str(mcp_store)
    env.pop("TRADING_BOT_AUTH_SIGNING_KEY_FILE", None)
    result = subprocess.run(
        ["uv", "run", "python", "scripts/live_readiness.py"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    mcp_check = next(
        check for check in payload["checks"] if check["name"] == "ROBINHOOD_MCP_OAUTH_STORE_DIR"
    )
    assert mcp_check["ok"] is False
    assert "more permissive" in mcp_check["detail"]
