"""Decode complete supplied inert log bodies; no HTTP or execution provenance."""

from infra.hybrid.stock_container import _require
from infra.hybrid.stock_release import normalize_configuration_observation


def decode_probe_output(raw: bytes) -> bytes:
    """Return canonical observation bytes only after complete strict stdout framing.

    The eventual caller must separately prove HTTP completion, owned container
    identity and clean stopped state. Supplied body bytes cannot prove those facts.
    """
    try:
        _require(type(raw) is bytes and 0 < len(raw) <= 16384)
        offset = frames = total = 0
        stdout: list[bytes] = []
        while offset < len(raw):
            _require(len(raw) - offset >= 8)
            header = raw[offset : offset + 8]
            _require(header[:4] == b"\x01\x00\x00\x00")
            size = int.from_bytes(header[4:], "big")
            offset += 8
            end = offset + size
            _require(end <= len(raw))
            frames += 1
            total += size
            _require(frames <= 128 and total <= 4096)
            stdout.append(raw[offset:end])
            offset = end
        return normalize_configuration_observation(b"".join(stdout))
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("stock_probe_output_unavailable") from None
