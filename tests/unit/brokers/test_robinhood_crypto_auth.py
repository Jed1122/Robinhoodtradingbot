import base64
from pathlib import Path

import pytest
from nacl.signing import SigningKey
from pydantic import SecretBytes, SecretStr

from trading_bot.brokers.robinhood_crypto_auth import (
    CryptoCredentialMaterial,
    FileCryptoCredentialProvider,
    sign_crypto_request,
)


def credentials() -> CryptoCredentialMaterial:
    return CryptoCredentialMaterial(SecretStr("api-key"), SecretBytes(b"1" * 32))


def test_signer_uses_exact_query_and_body_bytes() -> None:
    value = credentials()
    headers = sign_crypto_request(
        credentials=value,
        timestamp_seconds=1_800_000_000,
        method="POST",
        path_with_query="/api/v2/crypto/trading/orders/?account_number=RHC1",
        body=b'{"symbol":"BTC-USD"}',
    )
    message = (
        b"api-key1800000000/api/v2/crypto/trading/orders/?account_number=RHC1"
        b"POST"
        b'{"symbol":"BTC-USD"}'
    )
    SigningKey(b"1" * 32).verify_key.verify(message, base64.b64decode(headers.x_signature))


def test_credential_repr_is_redacted() -> None:
    assert "api-key" not in repr(credentials())
    assert "111111" not in repr(credentials())


def test_file_provider_requires_private_service_owned_files(tmp_path: Path) -> None:
    api = tmp_path / "api"
    private = tmp_path / "private"
    api.write_text("api-key\n")
    private.write_bytes(base64.b64encode(b"1" * 32) + b"\n")
    api.chmod(0o600)
    private.chmod(0o600)
    value = FileCryptoCredentialProvider(
        {
            "ROBINHOOD_CRYPTO_API_KEY_FILE": str(api),
            "ROBINHOOD_CRYPTO_PRIVATE_KEY_FILE": str(private),
        }
    ).load()
    assert value.api_key.get_secret_value() == "api-key"
    api.chmod(0o640)
    with pytest.raises(PermissionError):
        FileCryptoCredentialProvider(
            {
                "ROBINHOOD_CRYPTO_API_KEY_FILE": str(api),
                "ROBINHOOD_CRYPTO_PRIVATE_KEY_FILE": str(private),
            }
        ).load()
