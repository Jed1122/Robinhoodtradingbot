import importlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from mcp.shared.auth import OAuthClientInformationFull

NOW = datetime(2026, 10, 21, 16, tzinfo=UTC)
RESOURCE = "https://agent.robinhood.com/mcp/trading"
TOKEN = "https://api.robinhood.com/oauth2/token/"


def metadata():
    return {
        "issuer": RESOURCE,
        "authorization_endpoint": "https://robinhood.com/oauth",
        "token_endpoint": TOKEN,
        "registration_endpoint": "https://agent.robinhood.com/oauth/trading/register",
        "scopes_supported": ["internal"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "response_types_supported": ["code"],
    }


def protected():
    return {
        "resource": RESOURCE,
        "authorization_servers": [RESOURCE],
        "scopes_supported": ["internal"],
        "bearer_methods_supported": ["header"],
    }


def client():
    return OAuthClientInformationFull(
        client_id="fictional-client",
        issuer=RESOURCE,
        redirect_uris=["http://127.0.0.1:18765/callback"],
        token_endpoint_auth_method="none",
        scope="internal",
    )


def pending():
    m = importlib.import_module("trading_bot.brokers.robinhood_oauth_lifecycle")
    return m.OAuthLifecycle.pending(
        client_id="fictional-client",
        authorization=metadata(),
        protected=protected(),
        at=NOW,
        flow="explicit_refresh",
    )


def test_active_lifetime_roundtrip_never_extends_on_restart():
    record = pending().activate(received_at=NOW + timedelta(seconds=2), expires_in=900)
    m = importlib.import_module("trading_bot.brokers.robinhood_oauth_lifecycle")
    restored = m.OAuthLifecycle.from_record(json.loads(json.dumps(record.to_record())))
    seen = restored.observe(NOW + timedelta(seconds=100))
    assert seen.expires_at == NOW + timedelta(seconds=870)
    assert seen.expires_at == record.expires_at
    seen.validate_client(client(), "http://127.0.0.1:18765/callback")


@pytest.mark.parametrize("value", [None, False, True, "900", 900.0, 0, -1, 31536001])
def test_raw_lifetime_never_coerced(value):
    with pytest.raises(ValueError):
        pending().activate(received_at=NOW, expires_in=value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("issuer", "https://agent.robinhood.com"),
        ("token_endpoint", "https://agent.robinhood.com/token"),
        ("token_endpoint", TOKEN + "other"),
        ("scopes_supported", ["internal", "write"]),
        ("token_endpoint_auth_methods_supported", ["client_secret_post"]),
        ("code_challenge_methods_supported", ["plain"]),
    ],
)
def test_metadata_mismatch_denied(field, value):
    m = importlib.import_module("trading_bot.brokers.robinhood_oauth_lifecycle")
    data = metadata()
    data[field] = value
    with pytest.raises(ValueError):
        m.OAuthLifecycle.pending(
            client_id="fictional-client",
            authorization=data,
            protected=protected(),
            at=NOW,
            flow="explicit_refresh",
        )


@pytest.mark.parametrize("change", ["issuer", "client", "redirect", "secret", "clock", "expiry"])
def test_binding_and_clock_fail_closed(change):
    r = pending().activate(received_at=NOW + timedelta(seconds=2), expires_in=900)
    c = client()
    if change == "clock":
        with pytest.raises(ValueError):
            r.observe(NOW - timedelta(seconds=1))
        return
    if change == "expiry":
        with pytest.raises(ValueError):
            pending().activate(received_at=NOW + timedelta(seconds=901), expires_in=900)
        return
    if change == "issuer":
        c.issuer = None
    if change == "client":
        c.client_id = "other"
    if change == "redirect":
        c.redirect_uris = ["http://127.0.0.1:9999/callback"]
    if change == "secret":
        c.client_secret = "fictional-secret"
    with pytest.raises(ValueError):
        r.validate_client(c, "http://127.0.0.1:18765/callback")


def test_lease_excludes_second_owner_and_preserves_lock_inode(tmp_path):
    m = importlib.import_module("trading_bot.brokers.robinhood_oauth_lifecycle")
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    with m.PrivateOAuthStoreLease(root):
        inode = (root / "connection.lock").stat().st_ino
        with pytest.raises(RuntimeError), m.PrivateOAuthStoreLease(root):
            pass
    with m.PrivateOAuthStoreLease(root):
        assert (root / "connection.lock").stat().st_ino == inode


@pytest.mark.parametrize("kind", ["symlink", "public", "hardlink"])
def test_lease_rejects_unsafe_lockfile(tmp_path, kind):
    m = importlib.import_module("trading_bot.brokers.robinhood_oauth_lifecycle")
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    file = root / "connection.lock"
    if kind == "symlink":
        file.symlink_to(tmp_path / "missing")
    else:
        file.write_text("")
        file.chmod(0o644 if kind == "public" else 0o600)
        if kind == "hardlink":
            (tmp_path / "extra").hardlink_to(file)
    with pytest.raises(RuntimeError), m.PrivateOAuthStoreLease(root):
        pass


@pytest.mark.asyncio
async def test_lifecycle_and_tokens_are_one_encrypted_generation(tmp_path):
    from mcp.shared.auth import OAuthToken

    from trading_bot.brokers.robinhood_mcp_sdk import (
        EncryptedFileTokenStorage,
        initialize_private_oauth_store,
    )

    root = initialize_private_oauth_store(tmp_path / "store")
    storage = EncryptedFileTokenStorage(root)
    record = pending().activate(received_at=NOW + timedelta(seconds=1), expires_in=900)
    token = OAuthToken(
        access_token="fictional-access",
        refresh_token="fictional-refresh",
        expires_in=900,
        scope="internal",
    )
    await storage.set_tokens_with_lifecycle(token, record)
    reopened = EncryptedFileTokenStorage(root)
    assert await reopened.get_tokens() == token
    assert await reopened.get_lifecycle() == record
    assert b"fictional" not in (root / "tokens.json.box").read_bytes()
    with pytest.raises(RuntimeError):
        await reopened.set_tokens(token)


@pytest.mark.asyncio
async def test_pending_generation_cannot_be_loaded_as_usable_tokens(tmp_path):
    from mcp.shared.auth import OAuthToken

    from trading_bot.brokers.robinhood_mcp_sdk import (
        EncryptedFileTokenStorage,
        initialize_private_oauth_store,
    )

    storage = EncryptedFileTokenStorage(initialize_private_oauth_store(tmp_path / "store"))
    await storage.set_tokens_with_lifecycle(
        OAuthToken(access_token="fictional-access", scope="internal"), pending()
    )
    with pytest.raises(RuntimeError):
        await storage.get_tokens()
    assert (await storage.get_lifecycle()).state == "refresh_pending"
