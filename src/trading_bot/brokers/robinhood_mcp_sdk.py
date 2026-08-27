"""Standalone MCP SDK composition with encrypted OAuth state and allowed reads."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import stat
import tempfile
import webbrowser
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import AsyncExitStack
from datetime import timedelta
from pathlib import Path
from types import TracebackType
from typing import Self, cast
from urllib.parse import parse_qs, urlsplit

import httpx
from mcp import ClientSession, types
from mcp.client.auth import OAuthClientProvider
from mcp.client.auth.utils import extract_field_from_www_auth, extract_scope_from_www_auth
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)
from nacl.exceptions import CryptoError
from nacl.secret import SecretBox
from nacl.utils import random as random_bytes
from pydantic import AnyUrl

from trading_bot.brokers.robinhood_equity_evidence import EXPECTED_TOOL_ARGUMENTS
from trading_bot.brokers.robinhood_mcp_schema_gate import DeclaredMcpTool, JsonValue
from trading_bot.brokers.robinhood_mcp_transport import (
    OFFICIAL_MCP_ENDPOINT,
    McpToolResult,
    McpToolSession,
)

READ_ONLY_EQUITY_MCP_TOOLS = frozenset(EXPECTED_TOOL_ARGUMENTS)
ROBINHOOD_MCP_OAUTH_SCOPE = "internal"
OAUTH_FLOW_TIMEOUT_SECONDS = 300.0
OAUTH_CALLBACK_HOST = "127.0.0.1"
OAUTH_CALLBACK_PORT = 18765
OAUTH_CALLBACK_PATH = "/callback"
_OAUTH_STATE_VALUE = re.compile(r"[A-Za-z0-9._~-]{16,4096}\Z")
_OAUTH_CODE_VALUE = re.compile(r"[\x21-\x7e]{1,4096}\Z")

_KEY_FILE = "oauth-store.key"
_TOKENS_FILE = "tokens.json.box"
_CLIENT_FILE = "client.json.box"
_SCOPE_PROOF_FIELD = "_trading_bot_scope_contract"
_SCOPE_PROOF_VALUE = f"{ROBINHOOD_MCP_OAUTH_SCOPE}:v1"


class OAuthStoreError(RuntimeError):
    pass


class McpSdkConnectionError(RuntimeError):
    pass


class PinnedScopeOAuthClientProvider(OAuthClientProvider):
    """MCP OAuth provider that rejects every scope change before external use."""

    @staticmethod
    def _require_exact_advertised_scope(
        scopes: list[str] | None,
        source: str,
    ) -> None:
        if scopes is not None and scopes != [ROBINHOOD_MCP_OAUTH_SCOPE]:
            raise McpSdkConnectionError(f"{source} is outside the pinned OAuth scope")

    def _discard_outside_scope_state(self) -> tuple[bool, bool]:
        current_tokens = self.context.current_tokens
        tokens_discarded = current_tokens is not None and current_tokens.scope not in {
            None,
            ROBINHOOD_MCP_OAUTH_SCOPE,
        }
        if tokens_discarded:
            self.context.clear_tokens()
        client_info = self.context.client_info
        client_discarded = client_info is not None and client_info.scope not in {
            None,
            ROBINHOOD_MCP_OAUTH_SCOPE,
        }
        if client_discarded:
            self.context.client_info = None
        return tokens_discarded, client_discarded

    def _require_pinned_scope_contract(self) -> None:
        if self.context.client_metadata.scope != ROBINHOOD_MCP_OAUTH_SCOPE:
            raise McpSdkConnectionError("effective OAuth scope changed from the pinned contract")
        tokens_discarded, client_discarded = self._discard_outside_scope_state()
        if tokens_discarded:
            raise McpSdkConnectionError("current OAuth token is outside the pinned scope")
        if client_discarded:
            raise McpSdkConnectionError("current OAuth client is outside the pinned scope")
        protected = self.context.protected_resource_metadata
        if protected is not None:
            self._require_exact_advertised_scope(
                protected.scopes_supported,
                "protected-resource metadata",
            )
        authorization = self.context.oauth_metadata
        if authorization is not None:
            self._require_exact_advertised_scope(
                authorization.scopes_supported,
                "authorization-server metadata",
            )

    @staticmethod
    def _require_safe_challenge(response: httpx.Response) -> None:
        if (
            response.status_code == 403
            and extract_field_from_www_auth(response, "error") == "insufficient_scope"
        ):
            raise McpSdkConnectionError("OAuth scope step-up is disabled")
        challenge_scope = extract_scope_from_www_auth(response)
        if challenge_scope is not None and challenge_scope != ROBINHOOD_MCP_OAUTH_SCOPE:
            raise McpSdkConnectionError("OAuth challenge is outside the pinned scope")

    async def _validate_resource_match(self, prm: ProtectedResourceMetadata) -> None:
        self._require_exact_advertised_scope(
            prm.scopes_supported,
            "protected-resource metadata",
        )
        await super()._validate_resource_match(prm)

    async def _perform_authorization_code_grant(self) -> tuple[str, str]:
        self._require_pinned_scope_contract()
        return await super()._perform_authorization_code_grant()

    async def _initialize(self) -> None:
        await super()._initialize()
        self._require_pinned_scope_contract()

    async def _handle_token_response(self, response: httpx.Response) -> None:
        try:
            await super()._handle_token_response(response)
            self._require_pinned_scope_contract()
        except BaseException:
            self.context.clear_tokens()
            raise

    async def _handle_refresh_response(self, response: httpx.Response) -> bool:
        try:
            refreshed = await super()._handle_refresh_response(response)
            self._require_pinned_scope_contract()
        except BaseException:
            self.context.clear_tokens()
            raise
        return refreshed

    async def async_auth_flow(
        self,
        request: httpx.Request,
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """Guard each delegated request before it can leave the process."""

        self._require_pinned_scope_contract()
        delegated = super().async_auth_flow(request)
        try:
            try:
                outgoing = await anext(delegated)
            except StopAsyncIteration:
                return
            while True:
                self._require_pinned_scope_contract()
                response = yield outgoing
                self._require_safe_challenge(response)
                try:
                    outgoing = await delegated.asend(response)
                except StopAsyncIteration:
                    return
        finally:
            self._discard_outside_scope_state()
            await delegated.aclose()


def _validate_private_directory(path: Path) -> None:
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise OAuthStoreError("OAuth store must be a service-owned directory")
    if metadata.st_mode & 0o077:
        raise OAuthStoreError("OAuth store directory must use mode 0700 or stricter")


def _validate_private_file(path: Path) -> None:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise OAuthStoreError("OAuth state must be a service-owned regular file")
    if metadata.st_mode & 0o077:
        raise OAuthStoreError("OAuth state files must use mode 0600 or stricter")


def initialize_private_oauth_store(path: str | Path) -> Path:
    """Create the private store and encryption key without contacting a provider."""

    store = Path(path)
    try:
        if store.exists() or store.is_symlink():
            _validate_private_directory(store)
        else:
            store.mkdir(mode=0o700, parents=True, exist_ok=False)
        os.chmod(store, 0o700)
        _validate_private_directory(store)
        key_path = store / _KEY_FILE
        if not key_path.exists():
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(key_path, flags, 0o600)
            try:
                os.write(descriptor, random_bytes(SecretBox.KEY_SIZE))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        _validate_private_file(key_path)
    except OSError as exc:
        raise OAuthStoreError("unable to initialize private OAuth store") from exc
    return store


class EncryptedFileTokenStorage:
    """MCP TokenStorage using authenticated encryption and private atomic files."""

    def __init__(self, store: str | Path) -> None:
        self._store = Path(store)
        _validate_private_directory(self._store)
        key_path = self._store / _KEY_FILE
        _validate_private_file(key_path)
        key = key_path.read_bytes()
        if len(key) != SecretBox.KEY_SIZE:
            raise OAuthStoreError("OAuth encryption key has an invalid length")
        self._box = SecretBox(key)

    def _read(self, name: str) -> dict[str, object] | None:
        path = self._store / name
        if not path.exists():
            return None
        _validate_private_file(path)
        try:
            plaintext = self._box.decrypt(path.read_bytes())
            value: object = json.loads(plaintext)
        except (CryptoError, OSError, UnicodeDecodeError, ValueError) as exc:
            raise OAuthStoreError("encrypted OAuth state is invalid") from exc
        if type(value) is not dict:
            raise OAuthStoreError("encrypted OAuth state has an invalid shape")
        return value

    def _write(self, name: str, value: Mapping[str, object]) -> None:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        ciphertext = bytes(self._box.encrypt(encoded))
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._store,
            prefix=f".{name}.",
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, ciphertext)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary, self._store / name)
            _validate_private_file(self._store / name)
        except OSError as exc:
            raise OAuthStoreError("unable to persist encrypted OAuth state") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)

    async def get_tokens(self) -> OAuthToken | None:
        value = self._read(_TOKENS_FILE)
        if value is None:
            return None
        if value.pop(_SCOPE_PROOF_FIELD, None) != _SCOPE_PROOF_VALUE:
            raise OAuthStoreError("stored OAuth token lacks pinned-scope provenance")
        try:
            tokens = OAuthToken.model_validate(value)
        except ValueError as exc:
            raise OAuthStoreError("stored OAuth token shape is invalid") from exc
        if tokens.scope not in {None, ROBINHOOD_MCP_OAUTH_SCOPE}:
            raise OAuthStoreError("stored OAuth token scope is outside the pinned contract")
        return tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        if type(tokens) is not OAuthToken:
            raise TypeError("tokens must be OAuthToken")
        if tokens.scope not in {None, ROBINHOOD_MCP_OAUTH_SCOPE}:
            raise OAuthStoreError("OAuth token scope is outside the pinned contract")
        value = tokens.model_dump(mode="json", exclude_none=True)
        value[_SCOPE_PROOF_FIELD] = _SCOPE_PROOF_VALUE
        self._write(_TOKENS_FILE, value)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        value = self._read(_CLIENT_FILE)
        if value is None:
            return None
        if value.pop(_SCOPE_PROOF_FIELD, None) != _SCOPE_PROOF_VALUE:
            raise OAuthStoreError("stored OAuth client lacks pinned-scope provenance")
        try:
            client_info = OAuthClientInformationFull.model_validate(value)
        except ValueError as exc:
            raise OAuthStoreError("stored OAuth client shape is invalid") from exc
        if client_info.scope not in {None, ROBINHOOD_MCP_OAUTH_SCOPE}:
            raise OAuthStoreError("stored OAuth client scope is outside the pinned contract")
        return client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        if type(client_info) is not OAuthClientInformationFull:
            raise TypeError("client_info must be OAuthClientInformationFull")
        if client_info.scope not in {None, ROBINHOOD_MCP_OAUTH_SCOPE}:
            raise OAuthStoreError("OAuth client scope is outside the pinned contract")
        value = client_info.model_dump(mode="json", exclude_none=True)
        value[_SCOPE_PROOF_FIELD] = _SCOPE_PROOF_VALUE
        self._write(_CLIENT_FILE, value)


def _as_json(value: object) -> JsonValue:
    if value is None or type(value) in {str, int, bool}:
        return cast(JsonValue, value)
    if type(value) is list:
        return [_as_json(item) for item in value]
    if type(value) is dict and all(type(key) is str for key in value):
        return {str(key): _as_json(item) for key, item in value.items()}
    raise McpSdkConnectionError("MCP value is outside the reviewed JSON representation")


class SchemaOnlyMcpClientSession:
    """Expose only complete tools/list discovery from an initialized SDK session."""

    __slots__ = ("__list_tools",)

    def __init__(self, session: ClientSession) -> None:
        self.__list_tools = session.list_tools

    async def list_tools(
        self,
        cursor: str | None = None,
        *,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListToolsResult:
        if cursor is not None:
            if params is not None:
                raise ValueError("tools/list cursor must use exactly one argument form")
            params = types.PaginatedRequestParams(cursor=cursor)
        if params is None:
            return await self.__list_tools()
        return await self.__list_tools(params=params)


class ReadOnlyMcpClientSession(McpToolSession):
    """Narrow adapter that rejects every non-read tool before the SDK call."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def list_tools(self) -> tuple[DeclaredMcpTool, ...]:
        cursor: str | None = None
        observed_cursors: set[str] = set()
        collected: list[DeclaredMcpTool] = []
        for _ in range(32):
            result = (
                await self._session.list_tools()
                if cursor is None
                else await self._session.list_tools(
                    params=types.PaginatedRequestParams(cursor=cursor)
                )
            )
            for tool in result.tools:
                if tool.name not in READ_ONLY_EQUITY_MCP_TOOLS:
                    continue
                collected.append(
                    DeclaredMcpTool.create(
                        tool.name,
                        tool.description,
                        _as_json(tool.inputSchema),
                        None if tool.outputSchema is None else _as_json(tool.outputSchema),
                    )
                )
            cursor = result.nextCursor
            if cursor is None:
                names = tuple(item.name for item in collected)
                if len(names) != len(set(names)):
                    raise McpSdkConnectionError("MCP tools/list contains duplicate read tools")
                return tuple(sorted(collected, key=lambda item: item.name))
            if cursor in observed_cursors:
                raise McpSdkConnectionError("MCP tools/list pagination repeated a cursor")
            observed_cursors.add(cursor)
        raise McpSdkConnectionError("MCP tools/list exceeded the reviewed page limit")

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, JsonValue],
    ) -> McpToolResult:
        if name not in READ_ONLY_EQUITY_MCP_TOOLS:
            raise PermissionError("MCP tool is outside the read-only allowlist")
        properties, required = EXPECTED_TOOL_ARGUMENTS[name]
        keys = frozenset(arguments)
        if not required <= keys or not keys <= properties:
            raise ValueError("MCP read arguments violate the reviewed contract")
        result = await self._session.call_tool(name, dict(arguments))
        structured = (
            None if result.structuredContent is None else _as_json(result.structuredContent)
        )
        return McpToolResult((), bool(result.isError), structured)


class LoopbackOAuthCallback:
    """One-use localhost callback; authorization codes are never printed or persisted."""

    def __init__(
        self,
        *,
        open_browser: Callable[[str], bool] = webbrowser.open,
        timeout_seconds: float = OAUTH_FLOW_TIMEOUT_SECONDS,
    ) -> None:
        if type(timeout_seconds) not in {float, int} or timeout_seconds <= 0:
            raise ValueError("OAuth callback timeout must be positive")
        self._open_browser = open_browser
        self._timeout_seconds = float(timeout_seconds)
        self._server: asyncio.AbstractServer | None = None
        self._result: asyncio.Future[tuple[str, str | None]] | None = None
        self._expected_state: str | None = None

    @property
    def redirect_uri(self) -> str:
        return f"http://{OAUTH_CALLBACK_HOST}:{OAUTH_CALLBACK_PORT}{OAUTH_CALLBACK_PATH}"

    async def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("OAuth callback server is already running")
        loop = asyncio.get_running_loop()
        self._result = loop.create_future()
        self._expected_state = None
        try:
            self._server = await asyncio.start_server(
                self._handle,
                OAUTH_CALLBACK_HOST,
                OAUTH_CALLBACK_PORT,
                limit=8192,
            )
        except OSError as exc:
            raise McpSdkConnectionError("OAuth callback port is unavailable") from exc

    async def close(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.close()
            await server.wait_closed()
        result = self._result
        self._result = None
        self._expected_state = None
        if result is not None and not result.done():
            result.cancel()

    async def redirect_handler(self, authorization_url: str) -> None:
        if self._server is None or self._result is None:
            raise McpSdkConnectionError("OAuth callback server is not running")
        try:
            values = parse_qs(urlsplit(authorization_url).query, strict_parsing=True)
            states = values.get("state", ())
            scopes = values.get("scope", ())
            if (
                len(states) != 1
                or _OAUTH_STATE_VALUE.fullmatch(states[0]) is None
                or scopes != [ROBINHOOD_MCP_OAUTH_SCOPE]
            ):
                raise ValueError
        except (TypeError, ValueError):
            raise McpSdkConnectionError("OAuth authorization request is invalid") from None
        if self._expected_state is not None:
            raise McpSdkConnectionError("OAuth authorization redirect was repeated")
        self._expected_state = states[0]
        if not self._open_browser(authorization_url):
            self._expected_state = None
            raise McpSdkConnectionError("unable to open the OAuth authorization browser")

    async def callback_handler(self) -> tuple[str, str | None]:
        result = self._result
        if result is None:
            raise McpSdkConnectionError("OAuth callback server is not running")
        try:
            return await asyncio.wait_for(
                asyncio.shield(result),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            raise McpSdkConnectionError("OAuth callback timed out") from None

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        result = self._result
        status = "400 Bad Request"
        message = b"Authorization failed. You may close this window."
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
            first_line = request.split(b"\r\n", 1)[0].decode("ascii")
            method, target, version = first_line.split(" ")
            parsed = urlsplit(target)
            values = parse_qs(parsed.query, strict_parsing=True)
            codes = values.get("code", ())
            states = values.get("state", ())
            expected_state = self._expected_state
            if (
                method == "GET"
                and version == "HTTP/1.1"
                and parsed.path == OAUTH_CALLBACK_PATH
                and len(codes) == 1
                and len(states) == 1
                and _OAUTH_CODE_VALUE.fullmatch(codes[0]) is not None
                and expected_state is not None
                and hmac.compare_digest(states[0], expected_state)
                and result is not None
                and not result.done()
            ):
                result.set_result((codes[0], expected_state))
                status = "200 OK"
                message = b"Authorization complete. You may close this window."
            elif (
                method == "GET"
                and version == "HTTP/1.1"
                and parsed.path == OAUTH_CALLBACK_PATH
                and len(values.get("error", ())) == 1
                and len(states) == 1
                and expected_state is not None
                and hmac.compare_digest(states[0], expected_state)
                and result is not None
                and not result.done()
            ):
                result.set_exception(McpSdkConnectionError("OAuth authorization was declined"))
        except (ValueError, UnicodeDecodeError, asyncio.IncompleteReadError, TimeoutError):
            pass
        finally:
            response = (
                f"HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\n"
                f"Content-Length: {len(message)}\r\nConnection: close\r\n\r\n"
            ).encode() + message
            writer.write(response)
            try:
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()


class RobinhoodMcpSdkConnection:
    """Lifecycle owner for official Streamable HTTP, OAuth, and MCP session state."""

    def __init__(
        self,
        *,
        oauth_store_dir: str | Path,
        endpoint: str = OFFICIAL_MCP_ENDPOINT,
        callback: LoopbackOAuthCallback | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if endpoint != OFFICIAL_MCP_ENDPOINT:
            raise ValueError("only the official Robinhood Trading MCP endpoint is allowed")
        self._endpoint = endpoint
        self._store_dir = Path(oauth_store_dir)
        self._callback = callback
        self._timeout_seconds = timeout_seconds
        self._stack: AsyncExitStack | None = None
        self._read_only: ReadOnlyMcpClientSession | None = None
        self._schema_only: SchemaOnlyMcpClientSession | None = None

    async def __aenter__(self) -> Self:
        if self._stack is not None:
            raise RuntimeError("MCP connection is already entered")
        _validate_private_directory(self._store_dir)
        storage = EncryptedFileTokenStorage(self._store_dir)
        callback_uri = (
            self._callback.redirect_uri
            if self._callback is not None
            else f"http://{OAUTH_CALLBACK_HOST}:{OAUTH_CALLBACK_PORT}{OAUTH_CALLBACK_PATH}"
        )
        provider = PinnedScopeOAuthClientProvider(
            self._endpoint,
            OAuthClientMetadata(
                redirect_uris=[AnyUrl(callback_uri)],
                # OAuth public clients use PKCE and intentionally have no client secret.
                token_endpoint_auth_method="none",  # nosec B106
                scope=ROBINHOOD_MCP_OAUTH_SCOPE,
                client_name="Robinhood write-incapable shadow client",
                software_id="robinhood-multi-asset-trading-system",
                software_version="0.1.0",
            ),
            storage,
            redirect_handler=(None if self._callback is None else self._callback.redirect_handler),
            callback_handler=(None if self._callback is None else self._callback.callback_handler),
            timeout=OAUTH_FLOW_TIMEOUT_SECONDS,
        )
        stack = AsyncExitStack()
        self._stack = stack
        try:
            client = await stack.enter_async_context(
                httpx.AsyncClient(
                    auth=provider,
                    follow_redirects=True,
                    timeout=httpx.Timeout(self._timeout_seconds),
                )
            )
            read_stream, write_stream, _ = await stack.enter_async_context(
                streamable_http_client(
                    self._endpoint,
                    http_client=client,
                    terminate_on_close=True,
                )
            )
            session = await stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=self._timeout_seconds),
                )
            )
            await session.initialize()
            self._read_only = ReadOnlyMcpClientSession(session)
            self._schema_only = SchemaOnlyMcpClientSession(session)
        except BaseException:
            await stack.aclose()
            self._stack = None
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        stack = self._stack
        self._stack = None
        self._read_only = None
        self._schema_only = None
        if stack is not None:
            await stack.aclose()

    @property
    def session(self) -> ReadOnlyMcpClientSession:
        if self._read_only is None:
            raise RuntimeError("MCP connection is not initialized")
        return self._read_only

    @property
    def schema_session(self) -> SchemaOnlyMcpClientSession:
        if self._schema_only is None:
            raise RuntimeError("MCP connection is not initialized")
        return self._schema_only


class RobinhoodMcpSchemaConnection:
    """OAuth connection exposing tools/list without any tool invocation method."""

    __slots__ = ("__connection", "__session")

    def __init__(
        self,
        *,
        oauth_store_dir: str | Path,
        endpoint: str = OFFICIAL_MCP_ENDPOINT,
        callback: LoopbackOAuthCallback | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.__connection = RobinhoodMcpSdkConnection(
            oauth_store_dir=oauth_store_dir,
            endpoint=endpoint,
            callback=callback,
            timeout_seconds=timeout_seconds,
        )
        self.__session: SchemaOnlyMcpClientSession | None = None

    async def __aenter__(self) -> Self:
        connection = await self.__connection.__aenter__()
        self.__session = connection.schema_session
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.__session = None
        await self.__connection.__aexit__(exc_type, exc, traceback)

    @property
    def session(self) -> SchemaOnlyMcpClientSession:
        if self.__session is None:
            raise RuntimeError("MCP connection is not initialized")
        return self.__session


async def bootstrap_oauth(
    oauth_store_dir: str | Path,
    *,
    callback_factory: Callable[[], LoopbackOAuthCallback] = LoopbackOAuthCallback,
) -> tuple[DeclaredMcpTool, ...]:
    """Perform one explicit browser OAuth flow and return only sanitized declarations."""

    store = initialize_private_oauth_store(oauth_store_dir)
    callback = callback_factory()
    await callback.start()
    try:
        async with RobinhoodMcpSdkConnection(
            oauth_store_dir=store,
            callback=callback,
            timeout_seconds=OAUTH_FLOW_TIMEOUT_SECONDS,
        ) as connection:
            return await connection.session.list_tools()
    finally:
        await callback.close()


__all__ = [
    "OAUTH_FLOW_TIMEOUT_SECONDS",
    "READ_ONLY_EQUITY_MCP_TOOLS",
    "ROBINHOOD_MCP_OAUTH_SCOPE",
    "EncryptedFileTokenStorage",
    "LoopbackOAuthCallback",
    "McpSdkConnectionError",
    "OAuthStoreError",
    "PinnedScopeOAuthClientProvider",
    "ReadOnlyMcpClientSession",
    "RobinhoodMcpSchemaConnection",
    "RobinhoodMcpSdkConnection",
    "SchemaOnlyMcpClientSession",
    "bootstrap_oauth",
    "initialize_private_oauth_store",
]
