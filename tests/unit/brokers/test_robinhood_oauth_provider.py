import importlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from trading_bot.brokers.robinhood_mcp_sdk import (
    EncryptedFileTokenStorage,
    initialize_private_oauth_store,
)
from trading_bot.brokers.robinhood_oauth_lifecycle import (
    OFFICIAL_MCP_ENDPOINT,
    TOKEN_ENDPOINT,
    OAuthLifecycle,
)

NOW = datetime(2026, 10, 21, 16, tzinfo=UTC)


def safe_transport(handler):
    m = importlib.import_module("trading_bot.brokers.robinhood_oauth_provider")
    return m.PinnedOAuthTransport(httpx.MockTransport(handler))


def authmeta():
    return {
        "issuer": OFFICIAL_MCP_ENDPOINT,
        "authorization_endpoint": "https://robinhood.com/oauth",
        "token_endpoint": TOKEN_ENDPOINT,
        "registration_endpoint": "https://agent.robinhood.com/oauth/trading/register",
        "scopes_supported": ["internal"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "response_types_supported": ["code"],
    }


def resource():
    return {
        "resource": OFFICIAL_MCP_ENDPOINT,
        "authorization_servers": [OFFICIAL_MCP_ENDPOINT],
        "scopes_supported": ["internal"],
        "bearer_methods_supported": ["header"],
    }


async def provider(tmp_path, *, expired=True, legacy=False):
    m = importlib.import_module("trading_bot.brokers.robinhood_oauth_provider")
    s = EncryptedFileTokenStorage(initialize_private_oauth_store(tmp_path / "store"))
    c = OAuthClientInformationFull(
        client_id="fixture-client",
        issuer=OFFICIAL_MCP_ENDPOINT,
        redirect_uris=["http://127.0.0.1:18765/callback"],
        token_endpoint_auth_method="none",
        scope="internal",
    )
    await s.set_client_info(c)
    t = OAuthToken(
        access_token="fixture-old-access",
        refresh_token="fixture-old-refresh",
        expires_in=900,
        scope="internal",
    )
    if legacy:
        await s.set_tokens(t)
    else:
        await s.set_tokens_with_lifecycle(
            t,
            OAuthLifecycle.pending(
                client_id=c.client_id,
                authorization=authmeta(),
                protected=resource(),
                at=NOW,
                flow="authorization_code",
            ).activate(received_at=NOW, expires_in=900),
        )
    p = m.LifecycleOAuthClientProvider(
        OFFICIAL_MCP_ENDPOINT,
        OAuthClientMetadata(
            redirect_uris=c.redirect_uris, token_endpoint_auth_method="none", scope="internal"
        ),
        s,
        clock=lambda: NOW + timedelta(seconds=901 if expired else 10),
    )
    p._monotonic = lambda: 0.0
    return p, s


@pytest.mark.asyncio
async def test_expired_generation_refreshes_once_to_exact_endpoint_then_persists(tmp_path):
    p, s = await provider(tmp_path)
    calls = []

    def handler(request):
        calls.append(request)
        if str(request.url) == TOKEN_ENDPOINT:
            assert "fixture-old-refresh" in request.content.decode()
            return httpx.Response(
                200,
                json={
                    "access_token": "fixture-new-access",
                    "refresh_token": "fixture-new-refresh",
                    "expires_in": 900,
                    "token_type": "Bearer",
                    "scope": "internal",
                },
            )
        assert str(request.url) == OFFICIAL_MCP_ENDPOINT
        assert request.headers["Authorization"] == "Bearer fixture-new-access"
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(
        auth=p, transport=safe_transport(handler), follow_redirects=False
    ) as c:
        assert (await c.get(OFFICIAL_MCP_ENDPOINT)).status_code == 200
    assert len(calls) == 2
    assert (await s.get_tokens()).refresh_token == "fixture-new-refresh"
    r = await s.get_lifecycle()
    assert r.state == "active" and r.flow == "automatic_refresh"
    assert r.expires_at == NOW + timedelta(seconds=1771)


@pytest.mark.asyncio
async def test_legacy_401_never_discovers_registers_refreshes_or_opens_browser(tmp_path):
    p, s = await provider(tmp_path, legacy=True)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(401, headers={"WWW-Authenticate": "Bearer"})

    with pytest.raises(RuntimeError):
        async with httpx.AsyncClient(auth=p, transport=safe_transport(handler)) as c:
            await c.get(OFFICIAL_MCP_ENDPOINT)
    assert calls == [OFFICIAL_MCP_ENDPOINT]
    assert await s.get_lifecycle() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["timeout", "bad_scope", "bad_expiry", "redirect", "invalid_grant", "empty_refresh"]
)
async def test_failed_refresh_blocks_reuse_and_never_retries(tmp_path, failure, capsys):
    p, s = await provider(tmp_path)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if failure == "timeout":
            raise httpx.ReadTimeout("fixture-secret-provider-text")
        if failure == "redirect":
            return httpx.Response(307, headers={"Location": TOKEN_ENDPOINT + "other"})
        if failure == "invalid_grant":
            return httpx.Response(
                400,
                json={
                    "error": "invalid_grant",
                    "error_description": "fixture-secret-provider-text",
                },
            )
        d = {
            "access_token": "fixture-secret-new-access",
            "refresh_token": "new",
            "expires_in": 900,
            "token_type": "Bearer",
            "scope": "internal",
        }
        if failure == "bad_scope":
            d["scope"] = "internal write"
        if failure == "bad_expiry":
            d["expires_in"] = True
        if failure == "empty_refresh":
            d["refresh_token"] = ""
        return httpx.Response(200, json=d)

    with pytest.raises(Exception) as e:
        async with httpx.AsyncClient(
            auth=p, transport=safe_transport(handler), follow_redirects=True
        ) as c:
            await c.get(OFFICIAL_MCP_ENDPOINT)
    assert "fixture-secret" not in str(e.value)
    assert "fixture-secret" not in capsys.readouterr().out
    assert calls == [TOKEN_ENDPOINT]
    assert (await s.get_lifecycle()).state in {"refresh_pending", "reauthorization_required"}
    with pytest.raises(RuntimeError):
        await s.get_tokens()


@pytest.mark.asyncio
async def test_successful_refresh_omission_retains_bound_refresh_credential(tmp_path):
    p, s = await provider(tmp_path)

    def handler(request):
        if str(request.url) == TOKEN_ENDPOINT:
            return httpx.Response(
                200, json={"access_token": "new", "expires_in": 900, "token_type": "Bearer"}
            )
        return httpx.Response(200)

    async with httpx.AsyncClient(auth=p, transport=safe_transport(handler)) as c:
        await c.get(OFFICIAL_MCP_ENDPOINT)
    assert (await s.get_tokens()).refresh_token == "fixture-old-refresh"


@pytest.mark.asyncio
async def test_unexpected_401_allows_only_one_refresh_and_read_retry(tmp_path):
    p, _s = await provider(tmp_path, expired=False)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == TOKEN_ENDPOINT:
            return httpx.Response(
                200,
                json={
                    "access_token": "new",
                    "refresh_token": "new",
                    "expires_in": 900,
                    "token_type": "Bearer",
                },
            )
        return httpx.Response(401)

    with pytest.raises(RuntimeError):
        async with httpx.AsyncClient(auth=p, transport=safe_transport(handler)) as c:
            await c.get(OFFICIAL_MCP_ENDPOINT)
    assert calls == [OFFICIAL_MCP_ENDPOINT, TOKEN_ENDPOINT, OFFICIAL_MCP_ENDPOINT]


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
@pytest.mark.parametrize("status", [401, 403])
async def test_post_refresh_rejection_is_durable_across_new_provider(tmp_path, expired, status):
    p, storage = await provider(tmp_path, expired=expired)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == TOKEN_ENDPOINT:
            return httpx.Response(
                200,
                json={
                    "access_token": "fixture-rotated-access",
                    "refresh_token": "fixture-rotated-refresh",
                    "expires_in": 900,
                    "token_type": "Bearer",
                },
            )
        # The first401 triggers one refresh; the rotated generation is rejected.
        return httpx.Response(401 if len(calls) == 1 and not expired else status)

    with pytest.raises(RuntimeError):
        async with httpx.AsyncClient(auth=p, transport=safe_transport(handler)) as client:
            await client.get(OFFICIAL_MCP_ENDPOINT)
    record = await storage.get_lifecycle()
    assert record.state == "reauthorization_required"
    assert record.expires_at is None
    before = len(calls)
    m = importlib.import_module("trading_bot.brokers.robinhood_oauth_provider")
    fresh = m.LifecycleOAuthClientProvider(
        OFFICIAL_MCP_ENDPOINT,
        p.context.client_metadata,
        storage,
        clock=lambda: NOW + timedelta(seconds=902),
    )
    with pytest.raises(RuntimeError):
        async with httpx.AsyncClient(auth=fresh, transport=safe_transport(handler)) as client:
            await client.get(OFFICIAL_MCP_ENDPOINT)
    assert len(calls) == before


@pytest.mark.asyncio
async def test_refreshed_resource_request_is_quarantined_before_dispatch(tmp_path):
    p, storage = await provider(tmp_path)

    async def handler(request):
        if str(request.url) == TOKEN_ENDPOINT:
            return httpx.Response(
                200,
                json={
                    "access_token": "fixture-new",
                    "expires_in": 900,
                    "token_type": "Bearer",
                },
            )
        assert (await storage.get_lifecycle()).state == "resource_validation_pending"
        with pytest.raises(RuntimeError):
            await storage.get_tokens()
        return httpx.Response(200)

    async with httpx.AsyncClient(auth=p, transport=safe_transport(handler)) as client:
        assert (await client.get(OFFICIAL_MCP_ENDPOINT)).status_code == 200
    assert (await storage.get_lifecycle()).state == "active"


@pytest.mark.asyncio
async def test_failed_durable_denial_leaves_quarantine_not_reusable_token(tmp_path, monkeypatch):
    p, storage = await provider(tmp_path)
    original = storage.set_tokens_with_lifecycle

    async def persist(tokens, lifecycle):
        if lifecycle is not None and lifecycle.state == "reauthorization_required":
            raise OSError("fixture private filesystem error")
        await original(tokens, lifecycle)

    monkeypatch.setattr(storage, "set_tokens_with_lifecycle", persist)

    def handler(request):
        if str(request.url) == TOKEN_ENDPOINT:
            return httpx.Response(
                200,
                json={
                    "access_token": "fixture-new",
                    "expires_in": 900,
                    "token_type": "Bearer",
                },
            )
        return httpx.Response(401)

    with pytest.raises(RuntimeError, match="failed safely"):
        async with httpx.AsyncClient(auth=p, transport=safe_transport(handler)) as client:
            await client.get(OFFICIAL_MCP_ENDPOINT)
    assert (await storage.get_lifecycle()).state == "resource_validation_pending"
    with pytest.raises(RuntimeError):
        await storage.get_tokens()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 429, 500, 503])
async def test_uncertain_first_resource_response_preserves_nonreusable_generation(tmp_path, status):
    p, storage = await provider(tmp_path)

    def handler(request):
        if str(request.url) == TOKEN_ENDPOINT:
            return httpx.Response(
                200,
                json={
                    "access_token": "fixture-new",
                    "expires_in": 900,
                    "token_type": "Bearer",
                },
            )
        return httpx.Response(status)

    with pytest.raises(RuntimeError):
        async with httpx.AsyncClient(auth=p, transport=safe_transport(handler)) as client:
            await client.get(OFFICIAL_MCP_ENDPOINT)
    assert (await storage.get_lifecycle()).state == "resource_validation_pending"
    with pytest.raises(RuntimeError):
        await storage.get_tokens()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 503])
async def test_second_rotated_generation_is_independently_quarantined(tmp_path, status):
    p, storage = await provider(tmp_path)
    current = [NOW + timedelta(seconds=901)]
    p._clock = lambda: current[0]
    refreshes = []
    observed = []

    async def handler(request):
        if str(request.url) == TOKEN_ENDPOINT:
            refreshes.append(request)
            return httpx.Response(
                200,
                json={
                    "access_token": "fixture-new-" + str(len(refreshes)),
                    "expires_in": 900,
                    "token_type": "Bearer",
                },
            )
        observed.append((len(refreshes), (await storage.get_lifecycle()).state))
        return httpx.Response(200 if len(refreshes) == 1 else status)

    async with httpx.AsyncClient(auth=p, transport=safe_transport(handler)) as client:
        assert (await client.get(OFFICIAL_MCP_ENDPOINT)).status_code == 200
        current[0] = NOW + timedelta(seconds=1802)
        with pytest.raises(RuntimeError):
            await client.get(OFFICIAL_MCP_ENDPOINT)
    assert observed == [(1, "resource_validation_pending"), (2, "resource_validation_pending")]
    assert (await storage.get_lifecycle()).state == (
        "resource_validation_pending" if status == 503 else "reauthorization_required"
    )
    with pytest.raises(RuntimeError):
        await storage.get_tokens()


@pytest.mark.asyncio
async def test_automatic_rotation_is_not_reusable_before_any_resource_send(tmp_path):
    p, storage = await provider(tmp_path)
    await p._initialize()
    await p._refresh_token()
    response = httpx.Response(
        200,
        request=httpx.Request("POST", TOKEN_ENDPOINT),
        json={
            "access_token": "fixture-new",
            "expires_in": 900,
            "token_type": "Bearer",
        },
    )
    await p._handle_refresh_response(response)
    assert (await storage.get_lifecycle()).state == "resource_validation_pending"
    with pytest.raises(RuntimeError):
        await storage.get_tokens()


@pytest.mark.asyncio
async def test_active_generation_403_denies_without_refresh_and_persists(tmp_path):
    p, storage = await provider(tmp_path, expired=False)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(403)

    with pytest.raises(RuntimeError):
        async with httpx.AsyncClient(auth=p, transport=safe_transport(handler)) as client:
            await client.get(OFFICIAL_MCP_ENDPOINT)
    assert calls == [OFFICIAL_MCP_ENDPOINT]
    assert (await storage.get_lifecycle()).state == "reauthorization_required"
    with pytest.raises(RuntimeError):
        await storage.get_tokens()


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_existing_generation_cannot_be_rebound_before_refresh(tmp_path, explicit):
    p, s = await provider(tmp_path, expired=False)
    await p._initialize()
    original = await s.get_lifecycle()
    p.context.client_info.client_id = "fixture-other-client"
    with pytest.raises(ValueError):
        if explicit:
            await p.prepare_explicit_refresh(authmeta(), resource())
        else:
            await p._refresh_token()
    assert await s.get_lifecycle() == original


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "body"),
    [
        (OFFICIAL_MCP_ENDPOINT, b"grant_type=refresh_token&refresh_token=fixture-secret"),
        (TOKEN_ENDPOINT, b"grant_type=refresh_token&client_secret="),
    ],
)
async def test_form_mime_case_and_blank_secret_do_not_bypass_transport_guard(url, body):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200)

    with pytest.raises(RuntimeError):
        async with httpx.AsyncClient(transport=safe_transport(handler)) as client:
            await client.post(
                url,
                headers={"Content-Type": "Application/X-Www-Form-Urlencoded ; charset=ascii"},
                content=body,
            )
    assert calls == []


@pytest.mark.asyncio
async def test_bearer_never_sent_to_different_url(tmp_path):
    p, _s = await provider(tmp_path, expired=False)
    calls = []
    with pytest.raises(RuntimeError):
        async with httpx.AsyncClient(
            auth=p, transport=safe_transport(lambda r: calls.append(r))
        ) as c:
            await c.get("https://example.test/steal")
    assert calls == []


@pytest.mark.asyncio
async def test_clock_rollback_after_later_read_denies_before_send_and_survives_restart(tmp_path):
    p, s = await provider(tmp_path, expired=False)
    current = [NOW + timedelta(seconds=10)]
    p._clock = lambda: current[0]
    p._monotonic = lambda: 0.0
    calls = []
    async with httpx.AsyncClient(
        auth=p, transport=safe_transport(lambda r: calls.append(str(r.url)) or httpx.Response(200))
    ) as c:
        await c.get(OFFICIAL_MCP_ENDPOINT)
        current[0] = NOW + timedelta(seconds=800)
        await c.get(OFFICIAL_MCP_ENDPOINT)
        current[0] = NOW + timedelta(seconds=100)
        with pytest.raises(RuntimeError):
            await c.get(OFFICIAL_MCP_ENDPOINT)
    assert len(calls) == 2
    assert (await s.get_lifecycle()).last_observed_at == NOW + timedelta(seconds=800)


@pytest.mark.asyncio
async def test_monotonic_elapsed_expiry_cannot_be_extended_by_stalled_wall_clock(tmp_path):
    p, _s = await provider(tmp_path, expired=False)
    mono = [0.0]
    p._monotonic = lambda: mono[0]
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == TOKEN_ENDPOINT:
            return httpx.Response(
                200,
                json={
                    "access_token": "new",
                    "refresh_token": "new",
                    "expires_in": 900,
                    "token_type": "Bearer",
                },
            )
        return httpx.Response(200)

    async with httpx.AsyncClient(auth=p, transport=safe_transport(handler)) as c:
        await c.get(OFFICIAL_MCP_ENDPOINT)
        mono[0] = 901.0
        await c.get(OFFICIAL_MCP_ENDPOINT)
    assert calls == [OFFICIAL_MCP_ENDPOINT, TOKEN_ENDPOINT, OFFICIAL_MCP_ENDPOINT]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["secret_method", "secret", "redirect"])
async def test_public_client_binding_denied_before_browser_callback(tmp_path, bad):
    p, _s = await provider(tmp_path, expired=False)
    await p._initialize()
    if bad == "secret_method":
        p.context.client_info.token_endpoint_auth_method = "client_secret_post"
    if bad == "secret":
        p.context.client_info.client_secret = "fixture-secret"
    if bad == "redirect":
        p.context.client_info.redirect_uris = ["http://127.0.0.1:9999/callback"]
    calls = []

    async def opened(url):
        calls.append("browser")

    async def callback():
        calls.append("callback")
        return "fixture-code", "state"

    p.context.redirect_handler = opened
    p.context.callback_handler = callback
    with pytest.raises(ValueError):
        await p._perform_authorization_code_grant()
    assert calls == []


@pytest.mark.asyncio
async def test_actual_transport_denies_refresh_form_at_resource_endpoint():
    calls = []
    async with httpx.AsyncClient(
        transport=safe_transport(lambda r: calls.append(r) or httpx.Response(200))
    ) as c:
        with pytest.raises(RuntimeError):
            await c.post(
                OFFICIAL_MCP_ENDPOINT,
                data={"grant_type": "refresh_token", "refresh_token": "fixture-secret"},
            )
    assert calls == []


@pytest.mark.asyncio
async def test_total_token_response_budget_closes_trickled_body(tmp_path):
    import asyncio

    p, s = await provider(tmp_path)
    closed = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(20):
                await asyncio.sleep(0.01)
                yield b" "

        async def aclose(self):
            closed.append(True)

    m = importlib.import_module("trading_bot.brokers.robinhood_oauth_provider")
    inner = httpx.MockTransport(lambda r: httpx.Response(200, stream=Stream()))
    with pytest.raises(RuntimeError):
        async with httpx.AsyncClient(
            auth=p, transport=m.PinnedOAuthTransport(inner, operation_timeout_seconds=0.03)
        ) as c:
            await c.get(OFFICIAL_MCP_ENDPOINT)
    assert closed
    assert (await s.get_lifecycle()).state == "refresh_pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["resource", "secret_method", "secret", "redirect"])
async def test_fresh_interactive_contract_denied_before_registration_or_callback(tmp_path, bad):
    m = importlib.import_module("trading_bot.brokers.robinhood_oauth_provider")
    storage = EncryptedFileTokenStorage(initialize_private_oauth_store(tmp_path / "fresh"))
    callbacks = []
    calls = []

    async def opened(url):
        callbacks.append("browser")

    async def callback():
        callbacks.append("callback")
        return "code", "state"

    p = m.LifecycleOAuthClientProvider(
        OFFICIAL_MCP_ENDPOINT,
        OAuthClientMetadata(
            redirect_uris=["http://127.0.0.1:18765/callback"],
            token_endpoint_auth_method="none",
            scope="internal",
        ),
        storage,
        redirect_handler=opened,
        callback_handler=callback,
        clock=lambda: NOW,
    )

    def handler(request):
        url = str(request.url)
        calls.append((request.method, url))
        if url == OFFICIAL_MCP_ENDPOINT:
            return httpx.Response(
                401,
                headers={
                    "WWW-Authenticate": f'Bearer resource_metadata="{m.RESOURCE_METADATA_URL}"'
                },
            )
        if url == m.RESOURCE_METADATA_URL:
            data = resource()
            if bad == "resource":
                data["resource"] = "https://agent.robinhood.com/"
            return httpx.Response(200, json=data)
        if request.method == "GET":
            return httpx.Response(200, json=authmeta())
        if url == m.REGISTRATION_ENDPOINT:
            data = {
                "client_id": "fixture-client",
                "redirect_uris": ["http://127.0.0.1:18765/callback"],
                "token_endpoint_auth_method": "none",
                "scope": "internal",
            }
            if bad == "secret_method":
                data["token_endpoint_auth_method"] = "client_secret_post"
            if bad == "secret":
                data["client_secret"] = "fixture-secret"
            if bad == "redirect":
                data["redirect_uris"] = ["http://127.0.0.1:9999/callback"]
            return httpx.Response(201, json=data)
        raise AssertionError("unexpected network boundary")

    with pytest.raises(RuntimeError):
        async with httpx.AsyncClient(auth=p, transport=safe_transport(handler)) as c:
            await c.get(OFFICIAL_MCP_ENDPOINT)
    assert callbacks == []
    assert ("POST", TOKEN_ENDPOINT) not in calls
    if bad == "resource":
        assert ("POST", m.REGISTRATION_ENDPOINT) not in calls
