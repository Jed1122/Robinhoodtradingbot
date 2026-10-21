import importlib
import os
from pathlib import Path

import pytest
from mcp import types
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from trading_bot.brokers.robinhood_mcp_sdk import EncryptedFileTokenStorage


class Callback:
    starts = 0
    closes = 0

    async def start(self):
        type(self).starts += 1

    async def close(self):
        type(self).closes += 1


class Session:
    calls = 0

    async def list_tools(self, **kwargs):
        return types.ListToolsResult(
            tools=[
                types.Tool(name="get_financials", inputSchema={"type": "object"}),
                types.Tool(
                    name="get_equity_orders",
                    inputSchema={
                        "type": "object",
                        "properties": {"agent_initiated": {"type": "boolean"}},
                    },
                ),
                types.Tool(name="place_equity_order", inputSchema={"type": "object"}),
            ]
        )

    async def call_tool(self, *args, **kwargs):
        type(self).calls += 1
        raise AssertionError("bootstrap cannot invoke tools")


class Connection:
    fail = False

    def __init__(self, *, oauth_store_dir, callback, timeout_seconds):
        assert isinstance(callback, Callback)
        assert timeout_seconds > 0
        self.store = Path(oauth_store_dir)
        self.session = Session()

    async def __aenter__(self):
        store = EncryptedFileTokenStorage(self.store)
        await store.set_tokens(
            OAuthToken(
                access_token="fixture-secret-token",
                refresh_token="fixture-secret-refresh",
                scope="internal",
                expires_in=300,
            )
        )
        await store.set_client_info(
            OAuthClientInformationFull(
                client_id="fixture-client",
                redirect_uris=["http://127.0.0.1:18765/callback"],
                token_endpoint_auth_method="none",
                scope="internal",
            )
        )
        if self.fail:
            raise RuntimeError("fixture-secret-token must never appear in output")
        return self

    async def __aexit__(self, *args):
        return None


@pytest.fixture
def bootstrap(tmp_path, monkeypatch):
    module = importlib.import_module("trading_bot.runtime.schema_bootstrap")
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    Connection.fail = False
    Callback.starts = Callback.closes = Session.calls = 0
    monkeypatch.setattr(module, "RobinhoodMcpSchemaConnection", Connection)
    monkeypatch.setattr(module, "LoopbackOAuthCallback", Callback)
    return module, parent


def test_fresh_schema_bootstrap_preserves_complete_schema_without_invoking_tools(bootstrap):
    module, parent = bootstrap
    result = module.bootstrap_schema_oauth(oauth_store=parent / "research")
    assert result["tools_invoked"] is False
    assert result["tool_count"] == 3
    assert result["account_bound"] is False
    assert result["live_enabled"] is False
    assert Session.calls == 0
    assert Callback.starts == Callback.closes == 1
    assert (parent / "research/tools-list.json").is_file()
    assert not (parent / "research/account-fingerprint").exists()
    assert "fixture-secret" not in str(result)
    assert os.stat(parent / "research").st_mode & 0o777 == 0o700
    assert len(list(parent.iterdir())) == 1


def test_bootstrap_failure_cleans_only_new_staging_and_suppresses_secrets(bootstrap, capsys):
    module, parent = bootstrap
    preserved = parent / "existing"
    preserved.mkdir(mode=0o700)
    Connection.fail = True
    with pytest.raises(module.SchemaBootstrapError) as error:
        module.bootstrap_schema_oauth(oauth_store=parent / "research")
    assert "fixture-secret" not in str(error.value)
    assert "fixture-secret" not in capsys.readouterr().out
    assert list(parent.iterdir()) == [preserved]
    assert Callback.starts == Callback.closes == 1


@pytest.mark.parametrize("kind", ["existing", "symlink", "public_parent", "relative"])
def test_bootstrap_denies_unsafe_destinations_before_callback(bootstrap, kind):
    module, parent = bootstrap
    destination = parent / "research"
    if kind == "existing":
        destination.mkdir(mode=0o700)
    if kind == "symlink":
        destination.symlink_to(parent, target_is_directory=True)
    if kind == "public_parent":
        parent.chmod(0o755)
    if kind == "relative":
        destination = Path("relative")
    with pytest.raises(module.SchemaBootstrapError):
        module.bootstrap_schema_oauth(oauth_store=destination)
    assert Callback.starts == 0


def test_cleanup_failure_is_sanitized_and_always_restores_umask(bootstrap, monkeypatch):
    module, parent = bootstrap
    Connection.fail = True

    def broken_cleanup(path):
        raise OSError("fixture-secret-cleanup-message")

    monkeypatch.setattr(module.shutil, "rmtree", broken_cleanup)
    previous = os.umask(0o022)
    try:
        with pytest.raises(module.SchemaBootstrapError) as error:
            module.bootstrap_schema_oauth(oauth_store=parent / "research")
        assert "fixture-secret" not in str(error.value)
        current = os.umask(0o022)
        assert current == 0o022
    finally:
        os.umask(previous)


def test_atomic_publication_never_replaces_a_racing_empty_destination(bootstrap, monkeypatch):
    module, parent = bootstrap
    destination = parent / "research"
    original = module._rename_new_directory
    inode = []

    def race(source, target):
        target.mkdir(mode=0o700)
        inode.append(target.stat().st_ino)
        original(source, target)

    monkeypatch.setattr(module, "_rename_new_directory", race)
    with pytest.raises(module.SchemaBootstrapError):
        module.bootstrap_schema_oauth(oauth_store=destination)
    assert destination.stat().st_ino == inode[0]
    assert list(destination.iterdir()) == []
