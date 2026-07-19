"""Secret-safe exact-byte Ed25519 authentication for official Crypto v2."""

import base64
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from nacl.signing import SigningKey
from pydantic import SecretBytes, SecretStr

from trading_bot.logging import SecretRegistry


@dataclass(frozen=True, slots=True, repr=False)
class CryptoCredentialMaterial:
    api_key: SecretStr
    private_key_seed: SecretBytes

    def __post_init__(self) -> None:
        if not self.api_key.get_secret_value():
            raise ValueError("Crypto API key cannot be empty")
        if len(self.private_key_seed.get_secret_value()) != 32:
            raise ValueError("Crypto private seed must be exactly 32 bytes")


class CryptoCredentialProvider(Protocol):
    def load(self) -> CryptoCredentialMaterial: ...


class FileCryptoCredentialProvider:
    def __init__(self, environ: Mapping[str, str]) -> None:
        self._environ = environ

    @staticmethod
    def _read_private(path: Path) -> bytes:
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise PermissionError("credential path must be a regular service-owned file")
        if metadata.st_mode & 0o077:
            raise PermissionError("credential file cannot grant group or other permissions")
        value = path.read_bytes()
        return value[:-1] if value.endswith(b"\n") else value

    def load(self) -> CryptoCredentialMaterial:
        if self._environ.get("ROBINHOOD_CRYPTO_API_KEY") or self._environ.get(
            "ROBINHOOD_CRYPTO_PRIVATE_KEY"
        ):
            raise PermissionError("raw Crypto credentials in environment are forbidden")
        api_path = self._environ.get("ROBINHOOD_CRYPTO_API_KEY_FILE")
        private_path = self._environ.get("ROBINHOOD_CRYPTO_PRIVATE_KEY_FILE")
        if not api_path or not private_path:
            raise PermissionError("Crypto credential file paths are required")
        api_key = self._read_private(Path(api_path))
        encoded_seed = self._read_private(Path(private_path))
        registry = SecretRegistry()
        registry.register(api_key)
        registry.register(encoded_seed)
        try:
            seed = base64.b64decode(encoded_seed, validate=True)
        except ValueError:
            raise ValueError("Crypto private seed file is invalid") from None
        registry.register(seed)
        return CryptoCredentialMaterial(SecretStr(api_key.decode("utf-8")), SecretBytes(seed))


@dataclass(frozen=True, slots=True, repr=False)
class SignedHeaders:
    x_api_key: str
    x_signature: str
    x_timestamp: str

    def as_httpx(self) -> dict[str, str]:
        return {
            "x-api-key": self.x_api_key,
            "x-signature": self.x_signature,
            "x-timestamp": self.x_timestamp,
        }


def sign_crypto_request(
    *,
    credentials: CryptoCredentialMaterial,
    timestamp_seconds: int,
    method: Literal["GET", "POST"],
    path_with_query: str,
    body: bytes | None,
) -> SignedHeaders:
    if timestamp_seconds < 0 or not path_with_query.startswith("/"):
        raise ValueError("invalid Crypto signature request metadata")
    message = (
        credentials.api_key.get_secret_value().encode()
        + str(timestamp_seconds).encode()
        + path_with_query.encode()
        + method.encode()
        + (body or b"")
    )
    signature = SigningKey(credentials.private_key_seed.get_secret_value()).sign(message).signature
    return SignedHeaders(
        credentials.api_key.get_secret_value(),
        base64.b64encode(signature).decode("ascii"),
        str(timestamp_seconds),
    )


__all__ = [
    "CryptoCredentialMaterial",
    "CryptoCredentialProvider",
    "FileCryptoCredentialProvider",
    "SignedHeaders",
    "sign_crypto_request",
]
