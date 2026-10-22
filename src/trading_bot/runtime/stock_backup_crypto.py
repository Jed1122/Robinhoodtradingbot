"""Bounded, versioned authenticated stock backup streams using pinned PyNaCl.

Callers own both binary streams and their lifetime. A destination can contain
partial ciphertext or plaintext after failure: use an exclusive private staging
destination and never publish it until a complete receipt has been returned and
the caller has flushed, verified and durably committed it. No filesystem,
credential, network, logging, flush or close operation occurs in this codec.

Version 1 is STOCKBKP + byte 1, an 80-byte SealedBox-wrapped random stream key and
a 24-byte secretstream header. Four-byte big-endian frame lengths precede each
ciphertext. Additional authenticated data binds the whole envelope, an eight-byte
frame index and that frame's length. Nonempty MESSAGE frames hold at most 1 MiB;
only the last data frame can be short. A separate empty FINAL frame and immediate
EOF are mandatory. Public-recipient encryption does not authenticate the sender.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import BinaryIO

from nacl import bindings as sodium
from nacl.public import PrivateKey, PublicKey, SealedBox

_PREFIX = b"STOCKBKP\x01"
_SEALED_KEY_BYTES = 80
_HEADER_BYTES = 113
_CHUNK_BYTES = 1_048_576
_OVERHEAD_BYTES = 17
_MAX_BYTES = 2_147_483_648


class StockBackupCryptoError(ValueError):
    """Sanitized failure; the caller must not publish the partial destination."""


@dataclass(frozen=True, slots=True)
class StockBackupCryptoReceipt:
    version: int
    plaintext_bytes: int
    ciphertext_bytes: int
    plaintext_sha256: str
    ciphertext_sha256: str


def _require(condition: bool) -> None:
    if not condition:
        raise StockBackupCryptoError("stock_backup_crypto_unavailable")


def _validate(source: BinaryIO, destination: BinaryIO, key: bytes, maximum: int) -> None:
    _require(type(key) is bytes and len(key) == 32)
    _require(type(maximum) is int and 1 <= maximum <= _MAX_BYTES)
    _require(source is not destination)
    _require(callable(getattr(source, "read", None)))
    _require(callable(getattr(destination, "write", None)))


def _read_bytes(source: BinaryIO, size: int) -> bytes:
    body = source.read(size)
    _require(type(body) is bytes and len(body) <= size)
    return body


def _read_up_to(source: BinaryIO, size: int) -> bytes:
    body = bytearray()
    while len(body) < size:
        part = _read_bytes(source, size - len(body))
        if not part:
            break
        body.extend(part)
    return bytes(body)


def _write_all(destination: BinaryIO, body: bytes) -> None:
    view = memoryview(body)
    offset = 0
    while offset < len(body):
        written = destination.write(view[offset:])
        _require(type(written) is int and 0 < written <= len(body) - offset)
        offset += written


def _limits(maximum: int) -> tuple[int, int]:
    frames = (maximum + _CHUNK_BYTES - 1) // _CHUNK_BYTES + 1
    return frames, _HEADER_BYTES + maximum + frames * (4 + _OVERHEAD_BYTES)


class _CipherWriter:
    def __init__(self, destination: BinaryIO, maximum: int) -> None:
        self.destination = destination
        self.maximum = maximum
        self.count = 0
        self.digest = hashlib.sha256()

    def write(self, body: bytes) -> None:
        _require(self.count + len(body) <= self.maximum)
        _write_all(self.destination, body)
        self.count += len(body)
        self.digest.update(body)


class _CipherReader:
    def __init__(self, source: BinaryIO, maximum: int) -> None:
        self.source = source
        self.maximum = maximum
        self.count = 0
        self.digest = hashlib.sha256()

    def exact(self, size: int) -> bytes:
        _require(self.count + size <= self.maximum)
        body = _read_up_to(self.source, size)
        _require(len(body) == size)
        self.count += size
        self.digest.update(body)
        return body

    def eof(self) -> None:
        _require(_read_bytes(self.source, 1) == b"")


def encrypt_stream(
    source: BinaryIO,
    destination: BinaryIO,
    recipient_public_key: bytes,
    *,
    max_bytes: int = _MAX_BYTES,
) -> StockBackupCryptoReceipt:
    """Encrypt to a raw 32-byte Curve25519 public recipient; never generate a recipient.

    Each call generates an independent random secretstream key and header plus
    the SealedBox ephemeral sender. Streams must be blocking binary interfaces.
    """
    try:
        _validate(source, destination, recipient_public_key, max_bytes)
        maximum_frames, maximum_ciphertext = _limits(max_bytes)
        writer = _CipherWriter(destination, maximum_ciphertext)
        state = sodium.crypto_secretstream_xchacha20poly1305_state()
        stream_key = sodium.crypto_secretstream_xchacha20poly1305_keygen()
        stream_header = sodium.crypto_secretstream_xchacha20poly1305_init_push(state, stream_key)
        sealed = SealedBox(PublicKey(recipient_public_key)).encrypt(stream_key)
        del stream_key
        header = _PREFIX + sealed + stream_header
        _require(len(sealed) == _SEALED_KEY_BYTES and len(header) == _HEADER_BYTES)
        writer.write(header)
        plaintext_bytes = index = 0
        digest = hashlib.sha256()
        source_ended = False
        while True:
            data = (
                b""
                if source_ended
                else _read_up_to(source, min(_CHUNK_BYTES, max_bytes - plaintext_bytes + 1))
            )
            _require(plaintext_bytes + len(data) <= max_bytes)
            source_ended = len(data) < _CHUNK_BYTES
            final = not data
            tag = (
                sodium.crypto_secretstream_xchacha20poly1305_TAG_FINAL
                if final
                else sodium.crypto_secretstream_xchacha20poly1305_TAG_MESSAGE
            )
            _require(index < maximum_frames)
            length = (len(data) + _OVERHEAD_BYTES).to_bytes(4, "big")
            body = sodium.crypto_secretstream_xchacha20poly1305_push(
                state, data, ad=header + index.to_bytes(8, "big") + length, tag=tag
            )
            _require(len(body) == len(data) + _OVERHEAD_BYTES)
            writer.write(length)
            writer.write(body)
            digest.update(data)
            plaintext_bytes += len(data)
            index += 1
            if final:
                return StockBackupCryptoReceipt(
                    1, plaintext_bytes, writer.count, digest.hexdigest(), writer.digest.hexdigest()
                )
    except Exception:
        raise StockBackupCryptoError("stock_backup_crypto_unavailable") from None


def decrypt_stream(
    source: BinaryIO,
    destination: BinaryIO,
    recipient_private_key: bytes,
    *,
    max_bytes: int = _MAX_BYTES,
) -> StockBackupCryptoReceipt:
    """Decrypt with a raw 32-byte private recipient, authenticating FINAL and strict EOF.

    Earlier authenticated plaintext may already be staged when a later frame
    fails. The complete receipt is the only codec success acknowledgement.
    """
    try:
        _validate(source, destination, recipient_private_key, max_bytes)
        maximum_frames, maximum_ciphertext = _limits(max_bytes)
        reader = _CipherReader(source, maximum_ciphertext)
        header = reader.exact(_HEADER_BYTES)
        _require(header[: len(_PREFIX)] == _PREFIX)
        stream_key = SealedBox(PrivateKey(recipient_private_key)).decrypt(header[9:89])
        state = sodium.crypto_secretstream_xchacha20poly1305_state()
        sodium.crypto_secretstream_xchacha20poly1305_init_pull(state, header[89:], stream_key)
        del stream_key
        plaintext_bytes = 0
        digest = hashlib.sha256()
        short_data_seen = False
        for index in range(maximum_frames):
            length = reader.exact(4)
            size = int.from_bytes(length, "big")
            _require(_OVERHEAD_BYTES <= size <= _CHUNK_BYTES + _OVERHEAD_BYTES)
            body = reader.exact(size)
            data, tag = sodium.crypto_secretstream_xchacha20poly1305_pull(
                state, body, ad=header + index.to_bytes(8, "big") + length
            )
            if tag == sodium.crypto_secretstream_xchacha20poly1305_TAG_FINAL:
                _require(not data)
                reader.eof()
                return StockBackupCryptoReceipt(
                    1, plaintext_bytes, reader.count, digest.hexdigest(), reader.digest.hexdigest()
                )
            _require(tag == sodium.crypto_secretstream_xchacha20poly1305_TAG_MESSAGE)
            _require(not short_data_seen and 0 < len(data) <= _CHUNK_BYTES)
            _require(plaintext_bytes + len(data) <= max_bytes)
            _write_all(destination, data)
            digest.update(data)
            plaintext_bytes += len(data)
            short_data_seen = len(data) < _CHUNK_BYTES
        raise StockBackupCryptoError("stock_backup_crypto_unavailable")
    except Exception:
        raise StockBackupCryptoError("stock_backup_crypto_unavailable") from None
