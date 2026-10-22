"""Strict finite Docker log bodies; no HTTP, container or provider operation."""

import importlib
import json
from pathlib import Path

import pytest
from test_stock_configuration_observation import observation


def module():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_probe_output.py"
    assert path.is_file(), "Bounded inert probe output decoding is missing"
    return importlib.import_module("infra.hybrid.stock_probe_output")


def frame(payload, stream=1):
    return bytes([stream, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


def document():
    return (json.dumps(observation()) + "\n").encode()


def decode(raw):
    return module().decode_probe_output(raw)


def test_complete_stdout_produces_only_the_canonical_observation():
    result = decode(frame(document()))
    assert json.loads(result) == observation()
    assert result.startswith(b'{"config_hash":') and result.endswith(b'"status":"succeeded"}\n')


@pytest.mark.parametrize("split", range(1, len(document())))
def test_every_json_split_across_stdout_frames_is_reassembled(split):
    raw = document()
    assert json.loads(decode(frame(raw[:split]) + frame(raw[split:]))) == observation()


@pytest.mark.parametrize("length", range(1, 8))
def test_incomplete_frame_header_after_valid_output_denies(length):
    with pytest.raises(ValueError, match=r"^stock_probe_output_unavailable$"):
        decode(frame(document()) + frame(b"x")[:length])


def test_incomplete_payload_after_a_successful_json_prefix_denies():
    raw = frame(document()) + frame(b"unexpected")[:-1]
    with pytest.raises(ValueError, match=r"^stock_probe_output_unavailable$"):
        decode(raw)


@pytest.mark.parametrize("stream", [0, 2, 3, 4, 255])
def test_stderr_daemon_error_and_unknown_streams_cannot_bless_stdout(stream):
    raw = frame(document()) + frame(b"unexpected", stream)
    with pytest.raises(ValueError, match=r"^stock_probe_output_unavailable$"):
        decode(raw)


@pytest.mark.parametrize("stream", [2, 3])
def test_even_empty_error_streams_deny(stream):
    with pytest.raises(ValueError, match=r"^stock_probe_output_unavailable$"):
        decode(frame(document()) + frame(b"", stream))


@pytest.mark.parametrize("index", [1, 2, 3])
def test_nonzero_reserved_header_bytes_deny(index):
    raw = bytearray(frame(document()))
    raw[index] = 1
    with pytest.raises(ValueError, match=r"^stock_probe_output_unavailable$"):
        decode(bytes(raw))


@pytest.mark.parametrize("raw", [None, "text", bytearray(b"12345678"), b"", b"\xff" * 8])
def test_invalid_body_types_or_headers_deny(raw):
    with pytest.raises(ValueError, match=r"^stock_probe_output_unavailable$"):
        decode(raw)


def test_declared_payload_cannot_exceed_remaining_body():
    raw = b"\x01\x00\x00\x00\xff\xff\xff\xff" + document()
    with pytest.raises(ValueError, match=r"^stock_probe_output_unavailable$"):
        decode(raw)


def test_maximum_stdout_bytes_are_accepted_but_one_more_denies():
    raw = document()
    assert json.loads(decode(frame(raw + b" " * (4096 - len(raw))))) == observation()
    with pytest.raises(ValueError, match=r"^stock_probe_output_unavailable$"):
        decode(frame(raw + b" " * (4097 - len(raw))))


def test_stdout_limit_applies_across_several_frames():
    raw = frame(document()) + frame(b" " * 2048) + frame(b" " * 2048)
    with pytest.raises(ValueError, match=r"^stock_probe_output_unavailable$"):
        decode(raw)


def test_frame_limit_includes_empty_stdout_frames():
    raw = frame(b"") * 127 + frame(document())
    assert json.loads(decode(raw)) == observation()
    with pytest.raises(ValueError, match=r"^stock_probe_output_unavailable$"):
        decode(frame(b"") + raw)


@pytest.mark.parametrize("raw", [b"x" * 16384, b"x" * 16385])
def test_large_body_cannot_produce_a_configuration_result(raw):
    with pytest.raises(ValueError, match=r"^stock_probe_output_unavailable$"):
        decode(raw)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"\xff",
        b"{}",
        b"[]",
        document() + document(),
        document() + b"unexpected",
        b'{"live_enabled":true,' + document()[1:],
        document().replace(b'"live_enabled": false', b'"live_enabled": 0'),
        document().replace(b'"max_run_seconds": 450', b'"max_run_seconds": NaN'),
        document().replace(b'"max_run_seconds": 450', b'"max_run_seconds": 1e309'),
        document().replace(b'"status": "succeeded"', b'"status": "blocked"'),
        document().replace(b'"schema_version": 1', b'"schema_version": true'),
    ],
)
def test_framing_cannot_promote_malformed_or_unsafe_json(payload):
    with pytest.raises(ValueError, match=r"^stock_probe_output_unavailable$"):
        decode(frame(payload))
