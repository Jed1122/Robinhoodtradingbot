"""Validated encrypted-record metadata and one-owner official OAuth store lease."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata, ProtectedResourceMetadata

from trading_bot.brokers.robinhood_mcp_transport import OFFICIAL_MCP_ENDPOINT
from trading_bot.clock import require_utc

# Public provider URL, never a credential.
TOKEN_ENDPOINT = "https://api.robinhood.com/oauth2/token/"  # nosec B105
AUTHORIZATION_ENDPOINT = "https://robinhood.com/oauth"
REGISTRATION_ENDPOINT = "https://agent.robinhood.com/oauth/trading/register"
AS_METADATA_URL = "https://agent.robinhood.com/.well-known/oauth-authorization-server"
RESOURCE_METADATA_URL = (
    "https://agent.robinhood.com/.well-known/oauth-protected-resource/mcp/trading"
)
LIFECYCLE_FIELD = "_trading_bot_oauth_lifecycle"


def _check(value: bool) -> None:
    if not value:
        raise ValueError("official OAuth lifecycle invalid")


def validate_metadata(authorization: Mapping[str, Any], protected: Mapping[str, Any]) -> None:
    """Exact currently reviewed provider contract, including the path-bearing issuer."""
    for name, expected in {
        "issuer": OFFICIAL_MCP_ENDPOINT,
        "authorization_endpoint": AUTHORIZATION_ENDPOINT,
        "token_endpoint": TOKEN_ENDPOINT,
        "registration_endpoint": REGISTRATION_ENDPOINT,
        "scopes_supported": ["internal"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }.items():
        _check(authorization.get(name) == expected)
    for name, expected in {
        "resource": OFFICIAL_MCP_ENDPOINT,
        "authorization_servers": [OFFICIAL_MCP_ENDPOINT],
        "scopes_supported": ["internal"],
        "bearer_methods_supported": ["header"],
    }.items():
        _check(protected.get(name) == expected)
    OAuthMetadata.model_validate(dict(authorization))
    ProtectedResourceMetadata.model_validate(dict(protected))


def validate_public_client(
    client: OAuthClientInformationFull, *, client_id: str, redirect_uri: str
) -> None:
    _check(type(client_id) is str and bool(client_id) and client.client_id == client_id)
    _check(client.issuer == OFFICIAL_MCP_ENDPOINT)
    # OAuth public-client method identifier; secrets are explicitly prohibited.
    _check(client.token_endpoint_auth_method == "none" and client.client_secret is None)  # nosec B105
    _check(client.scope in {None, "internal"})
    _check([str(value) for value in (client.redirect_uris or [])] == [redirect_uri])


def _json(value: Mapping[str, Any]) -> bytes:
    encoded = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    _check(len(encoded) <= 65536)
    return encoded


@dataclass(frozen=True, slots=True)
class OAuthLifecycle:
    generation: str
    state: str
    flow: str
    client_id: str
    request_started_at: datetime
    response_received_at: datetime | None
    expires_in: int | None
    expires_at: datetime | None
    last_observed_at: datetime
    authorization_json: bytes
    protected_json: bytes

    def __post_init__(self) -> None:
        _check(
            type(self.generation) is str
            and re.fullmatch("[0-9a-f]{32}", self.generation) is not None
        )
        _check(
            self.state
            in {
                "active",
                "refresh_pending",
                "resource_validation_pending",
                "reauthorization_required",
            }
        )
        _check(self.flow in {"authorization_code", "explicit_refresh", "automatic_refresh"})
        _check(type(self.client_id) is str and 1 <= len(self.client_id) <= 4096)
        start = require_utc(self.request_started_at)
        last = require_utc(self.last_observed_at)
        _check(last >= start)
        _check(type(self.authorization_json) is bytes and type(self.protected_json) is bytes)
        _check(len(self.authorization_json) <= 65536 and len(self.protected_json) <= 65536)
        validate_metadata(json.loads(self.authorization_json), json.loads(self.protected_json))
        if self.state == "active":
            _check(type(self.expires_in) is int and 1 <= self.expires_in <= 31536000)
            _check(self.response_received_at is not None and self.expires_at is not None)
            if (
                self.response_received_at is None
                or self.expires_at is None
                or self.expires_in is None
            ):
                raise ValueError("official OAuth lifecycle invalid")
            received, expiry = require_utc(self.response_received_at), require_utc(self.expires_at)
            _check(start <= received <= last and expiry > received)
            _check(
                expiry
                == start + timedelta(seconds=self.expires_in - min(30, self.expires_in // 10))
            )
        else:
            _check(
                self.expires_in is None
                and self.expires_at is None
                and self.response_received_at is None
            )

    @classmethod
    def pending(
        cls,
        *,
        client_id: str,
        authorization: Mapping[str, Any],
        protected: Mapping[str, Any],
        at: datetime,
        flow: str,
    ) -> Self:
        return cls(
            uuid.uuid4().hex,
            "refresh_pending",
            flow,
            client_id,
            at,
            None,
            None,
            None,
            at,
            _json(authorization),
            _json(protected),
        )

    def activate(self, *, received_at: datetime, expires_in: object) -> Self:
        # Validate raw JSON before OAuthToken's integer coercion can hide invalid input.
        _check(type(expires_in) is int and 1 <= expires_in <= 31536000)
        if not isinstance(expires_in, int):
            raise ValueError("official OAuth lifecycle invalid")
        return replace(
            self,
            state="active",
            response_received_at=received_at,
            expires_in=expires_in,
            last_observed_at=received_at,
            expires_at=self.request_started_at
            + timedelta(seconds=expires_in - min(30, expires_in // 10)),
        )

    def observe(self, now: datetime) -> Self:
        _check(require_utc(now) >= self.last_observed_at)
        return replace(self, last_observed_at=now)

    def validate_client(self, client: OAuthClientInformationFull, redirect_uri: str) -> None:
        validate_public_client(client, client_id=self.client_id, redirect_uri=redirect_uri)

    def to_record(self) -> dict[str, Any]:
        return {
            "version": 1,
            "generation": self.generation,
            "state": self.state,
            "flow": self.flow,
            "client_id": self.client_id,
            "request_started_at": self.request_started_at.isoformat(),
            "response_received_at": None
            if self.response_received_at is None
            else self.response_received_at.isoformat(),
            "expires_in": self.expires_in,
            "expires_at": None if self.expires_at is None else self.expires_at.isoformat(),
            "last_observed_at": self.last_observed_at.isoformat(),
            "authorization": json.loads(self.authorization_json),
            "protected": json.loads(self.protected_json),
        }

    @classmethod
    def from_record(cls, value: object) -> Self:
        try:
            _check(type(value) is dict)
            if not isinstance(value, dict):
                raise ValueError("official OAuth lifecycle invalid")
            _check(
                set(value)
                == {
                    "version",
                    "generation",
                    "state",
                    "flow",
                    "client_id",
                    "request_started_at",
                    "response_received_at",
                    "expires_in",
                    "expires_at",
                    "last_observed_at",
                    "authorization",
                    "protected",
                }
            )
            _check(type(value["version"]) is int and value["version"] == 1)
            return cls(
                value["generation"],
                value["state"],
                value["flow"],
                value["client_id"],
                datetime.fromisoformat(value["request_started_at"]),
                None
                if value["response_received_at"] is None
                else datetime.fromisoformat(value["response_received_at"]),
                value["expires_in"],
                None
                if value["expires_at"] is None
                else datetime.fromisoformat(value["expires_at"]),
                datetime.fromisoformat(value["last_observed_at"]),
                _json(value["authorization"]),
                _json(value["protected"]),
            )
        except Exception:
            raise ValueError("official OAuth lifecycle invalid") from None


class PrivateOAuthStoreLease:
    """Nonblocking POSIX lease held before secret loading through connection closure.

    Cooperating processes on this host share the same lock inode. Copying the store
    to another host does not extend this exclusion guarantee.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._fd = -1

    def __enter__(self) -> Self:
        if self._fd >= 0:
            raise RuntimeError("OAuth store lease already entered")
        try:
            _check(
                self._fd == -1 and self._root.resolve() == self._root and self._root.is_absolute()
            )
            directory = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                info = os.fstat(directory)
                _check(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700)
                self._fd = os.open(
                    "connection.lock",
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=directory,
                )
            finally:
                os.close(directory)
            info = os.fstat(self._fd)
            _check(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_nlink == 1
            )
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self
        except Exception:
            if self._fd >= 0:
                os.close(self._fd)
                self._fd = -1
            raise RuntimeError("OAuth store unavailable or already owned") from None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1
