"""Operator-side Ed25519 signing; runtime modules never import private keys."""

import base64
from pathlib import Path

from nacl.signing import SigningKey

from trading_bot.authorization.models import (
    ActivationPayload,
    SignedActivationArtifact,
    canonical_payload,
)


def sign_activation(
    payload: ActivationPayload, signing_key: SigningKey
) -> SignedActivationArtifact:
    signature = signing_key.sign(canonical_payload(payload)).signature
    return SignedActivationArtifact(payload, base64.b64encode(signature).decode("ascii"))


def load_signing_key(path: str | Path, *, service_host: bool) -> SigningKey:
    """Load a private seed only on an operator host from an exact mode-0600 file."""
    if service_host:
        raise PermissionError("signing is forbidden on the service host")
    key_path = Path(path)
    if key_path.stat().st_mode & 0o777 != 0o600:
        raise PermissionError("signing key file must use mode 0600")
    seed = key_path.read_bytes()
    if len(seed) != 32:
        raise ValueError("signing key seed must contain exactly 32 bytes")
    return SigningKey(seed)
