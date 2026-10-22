"""Streaming stock envelope tests; all recipient keys and plaintext are fictional."""

import hashlib
import importlib
import io
import math
import tracemalloc
from dataclasses import asdict
from pathlib import Path

import pytest
from nacl import bindings as sodium
from nacl.public import PrivateKey, PublicKey, SealedBox

PREFIX = b"STOCKBKP\x01"
HEADER_BYTES = 113
CHUNK_BYTES = 1_048_576
MESSAGE = sodium.crypto_secretstream_xchacha20poly1305_TAG_MESSAGE
FINAL = sodium.crypto_secretstream_xchacha20poly1305_TAG_FINAL


def module():
    path = Path(__file__).resolve().parents[3] / "src/trading_bot/runtime/stock_backup_crypto.py"
    assert path.is_file(), "Streaming stock backup encryption is not implemented"
    return importlib.import_module("trading_bot.runtime.stock_backup_crypto")


@pytest.fixture
def keys():
    private = PrivateKey(bytes(range(32)))
    return bytes(private.public_key), bytes(private)


def encrypted(data, keys, **kwargs):
    output = io.BytesIO()
    result = module().encrypt_stream(io.BytesIO(data), output, keys[0], **kwargs)
    return output.getvalue(), result


def fixture_stream(keys, messages, *, authenticated=True):
    """Independent producer using the primary library, never implementation helpers."""
    stream_key = b"\x11" * 32
    state = sodium.crypto_secretstream_xchacha20poly1305_state()
    stream_header = sodium.crypto_secretstream_xchacha20poly1305_init_push(state, stream_key)
    sealed = SealedBox(PublicKey(keys[0])).encrypt(stream_key)
    header = PREFIX + sealed + stream_header
    frames = []
    for index, (data, tag) in enumerate(messages):
        length = (len(data) + 17).to_bytes(4, "big")
        ad = header + index.to_bytes(8, "big") + length if authenticated else None
        body = sodium.crypto_secretstream_xchacha20poly1305_push(state, data, ad=ad, tag=tag)
        frames.append(length + body)
    return header, frames


def test_round_trip_has_only_sanitized_data_receipt_fields(keys):
    data = b"fictional\x00\xff"
    body, result = encrypted(data, keys)
    output = io.BytesIO()
    recovered = module().decrypt_stream(io.BytesIO(body), output, keys[1])
    assert output.getvalue() == data
    assert recovered == result
    assert asdict(result) == {
        "version": 1,
        "plaintext_bytes": 11,
        "ciphertext_bytes": len(body),
        "plaintext_sha256": hashlib.sha256(data).hexdigest(),
        "ciphertext_sha256": hashlib.sha256(body).hexdigest(),
    }


@pytest.mark.parametrize(
    "size", [0, 1, CHUNK_BYTES - 1, CHUNK_BYTES, CHUNK_BYTES + 1, 2 * CHUNK_BYTES + 19]
)
def test_empty_and_chunk_boundaries_round_trip_with_exact_framing(keys, size):
    data = b"a" * size
    body, result = encrypted(data, keys)
    recovered = io.BytesIO()
    module().decrypt_stream(io.BytesIO(body), recovered, keys[1])
    assert recovered.getvalue() == data
    assert result.ciphertext_bytes == 113 + size + 21 * (math.ceil(size / CHUNK_BYTES) + 1)


def test_primary_library_independently_authenticates_every_emitted_frame(keys):
    data = b"x" * (CHUNK_BYTES + 3)
    body, _ = encrypted(data, keys)
    assert body[:9] == PREFIX
    stream_key = SealedBox(PrivateKey(keys[1])).decrypt(body[9:89])
    state = sodium.crypto_secretstream_xchacha20poly1305_state()
    sodium.crypto_secretstream_xchacha20poly1305_init_pull(state, body[89:113], stream_key)
    offset = 113
    observed = []
    for index in range(3):
        length = body[offset : offset + 4]
        offset += 4
        size = int.from_bytes(length, "big")
        plain, tag = sodium.crypto_secretstream_xchacha20poly1305_pull(
            state, body[offset : offset + size], ad=body[:113] + index.to_bytes(8, "big") + length
        )
        observed.append((plain, tag))
        offset += size
    assert observed == [(b"x" * CHUNK_BYTES, MESSAGE), (b"xxx", MESSAGE), (b"", FINAL)]
    assert offset == len(body)


def test_independently_created_canonical_envelope_decrypts(keys):
    header, frames = fixture_stream(keys, [(b"independent", MESSAGE), (b"", FINAL)])
    output = io.BytesIO()
    receipt = module().decrypt_stream(io.BytesIO(header + b"".join(frames)), output, keys[1])
    assert output.getvalue() == b"independent" and receipt.plaintext_bytes == 11


def test_fresh_random_stream_keys_headers_and_ephemeral_boxes_change_ciphertext(keys):
    first, a = encrypted(b"identical fictional data", keys)
    second, b = encrypted(b"identical fictional data", keys)
    assert first[9:89] != second[9:89] and first[89:113] != second[89:113]
    assert a.plaintext_sha256 == b.plaintext_sha256 and a.ciphertext_sha256 != b.ciphertext_sha256


class ShortReader(io.BytesIO):
    def read(self, size=-1):
        assert 0 < size <= CHUNK_BYTES + 17
        return super().read(min(size, 4093))


class ShortWriter(io.BytesIO):
    def write(self, data):
        return super().write(data[:773])


def test_short_reads_and_writes_work_without_closing_caller_streams(keys):
    source, destination = ShortReader(b"z" * (CHUNK_BYTES + 7)), ShortWriter()
    encrypted_receipt = module().encrypt_stream(source, destination, keys[0])
    restored = ShortWriter()
    decrypted_receipt = module().decrypt_stream(
        ShortReader(destination.getvalue()), restored, keys[1]
    )
    assert restored.getvalue() == b"z" * (CHUNK_BYTES + 7)
    assert decrypted_receipt == encrypted_receipt
    assert not source.closed and not destination.closed and not restored.closed


def test_encryption_finalizes_at_first_source_eof_without_reading_again(keys):
    class Ends:
        calls = 0

        def read(self, size):
            self.calls += 1
            if self.calls == 1:
                return b"prefix"
            if self.calls == 2:
                return b""
            raise AssertionError("the first EOF must finalize the stream")

    source, cipher, plain = Ends(), io.BytesIO(), io.BytesIO()
    module().encrypt_stream(source, cipher, keys[0])
    module().decrypt_stream(io.BytesIO(cipher.getvalue()), plain, keys[1])
    assert plain.getvalue() == b"prefix" and source.calls == 2


@pytest.mark.parametrize("offset", [0, 8, 9, 40, 88, 89, 112, 117, -1])
def test_tampered_magic_version_sealed_key_header_or_chunks_are_denied(keys, offset):
    body, _ = encrypted(b"fictional", keys)
    changed = bytearray(body)
    changed[offset] ^= 1
    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
        module().decrypt_stream(io.BytesIO(bytes(changed)), io.BytesIO(), keys[1])


@pytest.mark.parametrize("length", [0, 1, 8, 9, 88, 89, 112, 113, 114, 116, 120, -1])
def test_truncated_envelopes_and_final_frames_are_denied(keys, length):
    body, _ = encrypted(b"fictional", keys)
    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
        module().decrypt_stream(io.BytesIO(body[:length]), io.BytesIO(), keys[1])


@pytest.mark.parametrize(
    "mutation", ["drop_first", "drop_middle", "drop_final", "reorder", "duplicate", "append"]
)
def test_dropped_reordered_duplicated_or_trailing_frames_are_denied(keys, mutation):
    header, frames = fixture_stream(
        keys,
        [
            (b"a" * CHUNK_BYTES, MESSAGE),
            (b"b" * CHUNK_BYTES, MESSAGE),
            (b"c", MESSAGE),
            (b"", FINAL),
        ],
    )
    changed = {
        "drop_first": frames[1:],
        "drop_middle": frames[:1] + frames[2:],
        "drop_final": frames[:-1],
        "reorder": [frames[1], frames[0], *frames[2:]],
        "duplicate": [frames[0], *frames],
        "append": [*frames, b"\x00"],
    }[mutation]
    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
        module().decrypt_stream(io.BytesIO(header + b"".join(changed)), io.BytesIO(), keys[1])


@pytest.mark.parametrize("length", [0, 16, 17, CHUNK_BYTES + 18, 2**32 - 1])
def test_invalid_or_tampered_frame_lengths_fail_before_large_reads(keys, length):
    body, _ = encrypted(b"data", keys)
    changed = body[:113] + length.to_bytes(4, "big") + body[117:]
    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
        module().decrypt_stream(ShortReader(changed), io.BytesIO(), keys[1])


@pytest.mark.parametrize(
    "messages",
    [
        [(b"", MESSAGE), (b"", FINAL)],
        [(b"a", MESSAGE), (b"b", MESSAGE), (b"", FINAL)],
        [(b"data", FINAL)],
        [(b"a", sodium.crypto_secretstream_xchacha20poly1305_TAG_PUSH), (b"", FINAL)],
        [(b"a", sodium.crypto_secretstream_xchacha20poly1305_TAG_REKEY), (b"", FINAL)],
    ],
)
def test_authenticated_but_noncanonical_frames_are_denied(keys, messages):
    header, frames = fixture_stream(keys, messages)
    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
        module().decrypt_stream(io.BytesIO(header + b"".join(frames)), io.BytesIO(), keys[1])


def test_entire_header_is_authenticated_even_when_sealed_key_wraps_same_key(keys):
    header, frames = fixture_stream(keys, [(b"data", MESSAGE), (b"", FINAL)])
    replacement = SealedBox(PublicKey(keys[0])).encrypt(b"\x11" * 32)
    changed = header[:9] + replacement + header[89:] + b"".join(frames)
    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
        module().decrypt_stream(io.BytesIO(changed), io.BytesIO(), keys[1])


def test_secretstream_without_envelope_additional_authentication_is_denied(keys):
    header, frames = fixture_stream(keys, [(b"data", MESSAGE), (b"", FINAL)], authenticated=False)
    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
        module().decrypt_stream(io.BytesIO(header + b"".join(frames)), io.BytesIO(), keys[1])


def test_wrong_private_recipient_cannot_decrypt(keys):
    body, _ = encrypted(b"data", keys)
    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
        module().decrypt_stream(io.BytesIO(body), io.BytesIO(), b"\xff" * 32)


@pytest.mark.parametrize("key", [None, True, "x" * 32, bytearray(32), b"", b"x" * 31, b"x" * 33])
@pytest.mark.parametrize("operation", ["encrypt_stream", "decrypt_stream"])
def test_recipient_requires_exact_raw_key_bytes(keys, key, operation):
    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
        getattr(module(), operation)(io.BytesIO(), io.BytesIO(), key)


def test_low_order_recipient_key_is_rejected(keys):
    output = io.BytesIO()
    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
        module().encrypt_stream(io.BytesIO(b"data"), output, b"\x00" * 32)
    assert output.getvalue() == b""


@pytest.mark.parametrize("limit", [None, True, 1.0, "1", 0, -1, 2_147_483_649])
@pytest.mark.parametrize("operation", ["encrypt_stream", "decrypt_stream"])
def test_byte_limit_requires_a_bounded_positive_integer(keys, limit, operation):
    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
        getattr(module(), operation)(io.BytesIO(), io.BytesIO(), keys[0], max_bytes=limit)


def test_plaintext_limit_is_enforced_in_both_directions(keys):
    body, _ = encrypted(b"abc", keys, max_bytes=3)
    for operation, data, key in [
        ("encrypt_stream", b"abc", keys[0]),
        ("decrypt_stream", body, keys[1]),
    ]:
        output = io.BytesIO()
        with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
            getattr(module(), operation)(io.BytesIO(data), output, key, max_bytes=2)
        if operation == "decrypt_stream":
            assert len(output.getvalue()) <= 2


@pytest.mark.parametrize(
    "returned",
    [None, True, "text", bytearray(b"a"), b"x" * (CHUNK_BYTES + 18)],
    ids=["none", "boolean", "text", "mutable-bytes", "oversized"],
)
@pytest.mark.parametrize("operation", ["encrypt_stream", "decrypt_stream"])
def test_invalid_binary_read_results_are_sanitized(keys, returned, operation):
    class Reader:
        def read(self, size):
            return returned

    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
        getattr(module(), operation)(Reader(), io.BytesIO(), keys[0])


@pytest.mark.parametrize("returned", [None, True, "1", -1, 0, 2_147_483_648])
@pytest.mark.parametrize("operation", ["encrypt_stream", "decrypt_stream"])
def test_invalid_short_write_results_are_sanitized(keys, returned, operation):
    class Writer:
        def write(self, data):
            return returned

    body, _ = encrypted(b"data", keys)
    data, key = (b"data", keys[0]) if operation == "encrypt_stream" else (body, keys[1])
    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
        getattr(module(), operation)(io.BytesIO(data), Writer(), key)


@pytest.mark.parametrize("operation", ["encrypt_stream", "decrypt_stream"])
def test_streams_must_have_distinct_binary_io_interfaces(keys, operation):
    same = io.BytesIO()
    for source, destination in [(None, io.BytesIO()), (io.BytesIO(), object()), (same, same)]:
        with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
            getattr(module(), operation)(source, destination, keys[0])


@pytest.mark.parametrize("boundary", ["read", "write"])
@pytest.mark.parametrize("operation", ["encrypt_stream", "decrypt_stream"])
def test_io_failure_never_emits_a_receipt_or_private_diagnostics(keys, capsys, boundary, operation):
    class Broken:
        def read(self, size):
            raise OSError("fictional private key /tmp/secret details")

        def write(self, data):
            raise OSError("fictional private key /tmp/secret details")

    body, _ = encrypted(b"data", keys)
    source = io.BytesIO(b"data" if operation == "encrypt_stream" else body)
    destination = io.BytesIO()
    if boundary == "read":
        source = Broken()
    else:
        destination = Broken()
    key = keys[0] if operation == "encrypt_stream" else keys[1]
    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$") as caught:
        getattr(module(), operation)(source, destination, key)
    assert caught.value.__cause__ is None
    assert capsys.readouterr() == ("", "")


def test_large_generated_source_keeps_memory_and_requests_bounded(keys):
    class Generated:
        remaining = 32 * CHUNK_BYTES

        def read(self, size):
            assert 0 < size <= CHUNK_BYTES
            length = min(size, self.remaining)
            self.remaining -= length
            return b"a" * length

    class Discard:
        def write(self, data):
            assert len(data) <= CHUNK_BYTES + 17
            return len(data)

    api = module()
    tracemalloc.start()
    try:
        receipt = api.encrypt_stream(Generated(), Discard(), keys[0])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert receipt.plaintext_bytes == 32 * CHUNK_BYTES and peak < 10 * CHUNK_BYTES


def test_decryption_memory_stays_bounded_when_destination_discards_plaintext(keys):
    body, _ = encrypted(b"a" * (32 * CHUNK_BYTES), keys)

    class Discard:
        def write(self, data):
            assert len(data) <= CHUNK_BYTES
            return len(data)

    source = io.BytesIO(body)
    api = module()
    tracemalloc.start()
    try:
        receipt = api.decrypt_stream(source, Discard(), keys[1])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert receipt.plaintext_bytes == 32 * CHUNK_BYTES and peak < 10 * CHUNK_BYTES


def test_missing_final_rejects_even_after_authenticated_plaintext_was_staged(keys):
    header, frames = fixture_stream(keys, [(b"verified-prefix", MESSAGE), (b"", FINAL)])
    output = io.BytesIO()
    with pytest.raises(ValueError, match=r"^stock_backup_crypto_unavailable$"):
        module().decrypt_stream(io.BytesIO(header + frames[0]), output, keys[1])
    assert output.getvalue() == b"verified-prefix"
