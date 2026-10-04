"""Owner-private local observation sink; deliberately no broker transport."""

import os
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from trading_bot.market_data.alpaca_native import parse_timestamp_ns
from trading_bot.market_data.alpaca_observations import parse_alpaca_observation_frame
from trading_bot.market_data.bundle_codec import _array, _digest, _mapping, _string
from trading_bot.market_data.bundle_store import _open_root, _publish, _read
from trading_bot.market_data.recording import canonical_json
from trading_bot.research.etf_execution_receipts import (
    MAX_BODY_BYTES,
    MAX_EVENTS,
    MAX_SOURCE_BYTES,
    EtfReceiptError,
    _check,
    _decode,
    _integer,
    link_execution_receipts,
    source_digest,
    validate_clock_session,
    validate_receipt_payload,
)


class EtfExecutionReceiptRecorder:
    """Samples its own clock receipts; provenance remains a declaration.

    Caller is the execution owner, not a broker adapter. This records events the
    owner observes; it cannot submit, authenticate or attest an actual order.
    Failures latch until close. Restart always requires a fresh session.
    """

    def __init__(
        self,
        root: Path,
        repository_root: Path,
        *,
        code_revision: str,
        maximum_quote_age_ns: int,
        utc_now: Callable[[], datetime],
        monotonic_ns: Callable[[], int],
        provenance: str = "paper",
        nonce: str | None = None,
    ) -> None:
        self._descriptor = -1
        self._failed = False
        self._utc_now, self._monotonic_ns = utc_now, monotonic_ns
        self._sources: dict[str, int] = {}
        self._receipts: list[str] = []
        self._receipt_bytes = 0
        self._frames = 0
        self._last_utc = self._last_mono = 0
        try:
            utc, mono = self._sample()
            self._session = canonical_json(
                {
                    "schema": "etf-execution-clock-session-v1",
                    "nonce": secrets.token_hex(32) if nonce is None else nonce,
                    "provenance": provenance,
                    "code_revision": code_revision,
                    "started_at": utc,
                    "started_monotonic_ns": mono,
                    "maximum_quote_age_ns": maximum_quote_age_ns,
                    "evidence_promotable": False,
                }
            ).encode()
            validate_clock_session(self._session)
            self._session_hash = source_digest(self._session)
            self._descriptor = _open_root(root, repository_root)
            marker = os.open(
                self._session_hash + ".execution-attempt",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=self._descriptor,
            )
            try:
                os.fchmod(marker, 0o600)
                os.fsync(marker)
            finally:
                os.close(marker)
            os.fsync(self._descriptor)
            _publish(self._descriptor, self._session_hash + ".source", self._session)
        except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
            self._failed = True
            self.close()
            raise EtfReceiptError() from None

    def _sample(self) -> tuple[str, int]:
        now = self._utc_now()
        _check(type(now) is datetime and now.utcoffset() == timedelta(0))
        utc = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
        ns, mono = parse_timestamp_ns(utc), _integer(self._monotonic_ns())
        _check(ns >= self._last_utc and mono >= self._last_mono)
        self._last_utc, self._last_mono = ns, mono
        return utc, mono

    def _available(self) -> None:
        _check(not self._failed and self._descriptor >= 0)

    def retain_source(self, body: bytes) -> str:
        try:
            self._available()
            digest = source_digest(body)
            total = sum(self._sources.values()) + (0 if digest in self._sources else len(body))
            _check(total <= MAX_SOURCE_BYTES and len(self._sources) < MAX_EVENTS)
            _publish(self._descriptor, digest + ".source", body)
            self._sources[digest] = len(body)
            return digest
        except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
            self._failed = True
            raise EtfReceiptError() from None

    def record(self, kind: str, payload: dict[str, object]) -> str:
        try:
            self._available()
            _check(len(self._receipts) < MAX_EVENTS)
            # A canonical copy prevents later caller mutation of a stored payload.
            checked = validate_receipt_payload(kind, _decode(canonical_json(payload).encode()))
            for key in ("source_hash", "terms_hash", "body_sha256"):
                if key in checked:
                    _check(checked[key] in self._sources)
            utc, mono = self._sample()
            if kind == "alpaca_frame":
                _check(checked["frame_index"] == self._frames)
                parse_alpaca_observation_frame(
                    _read(
                        self._descriptor,
                        _string(checked["body_sha256"]) + ".source",
                        MAX_BODY_BYTES,
                    ),
                    frame_index=self._frames,
                    received_at_ns=parse_timestamp_ns(utc),
                )
            body = canonical_json(
                {
                    "schema": "etf-execution-receipt-v1",
                    "session_hash": self._session_hash,
                    "sequence": len(self._receipts),
                    "previous_hash": self._receipts[-1] if self._receipts else None,
                    "kind": kind,
                    "received_at": utc,
                    "received_monotonic_ns": mono,
                    "payload": checked,
                }
            ).encode()
            _check(self._receipt_bytes + len(body) <= MAX_SOURCE_BYTES)
            digest = source_digest(body)
            _publish(self._descriptor, digest + ".source", body)
            self._receipts.append(digest)
            self._receipt_bytes += len(body)
            self._frames += kind == "alpaca_frame"
            return digest
        except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
            self._failed = True
            raise EtfReceiptError() from None

    def checkpoint(self) -> str:
        try:
            self._available()
            receipts = tuple(
                _read(self._descriptor, h + ".source", MAX_BODY_BYTES) for h in self._receipts
            )
            sources = {
                h: _read(self._descriptor, h + ".source", MAX_BODY_BYTES) for h in self._sources
            }
            link_execution_receipts(self._session, receipts, sources)
            body = canonical_json(
                {
                    "schema": "etf-execution-receipt-checkpoint-v1",
                    "session_hash": self._session_hash,
                    "receipt_hashes": self._receipts,
                    "source_hashes": sorted(self._sources),
                    "evidence_promotable": False,
                }
            ).encode()
            digest = source_digest(body)
            _publish(self._descriptor, digest + ".source", body)
            return digest
        except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError):
            self._failed = True
            raise EtfReceiptError() from None

    def close(self) -> None:
        if self._descriptor >= 0:
            descriptor, self._descriptor = self._descriptor, -1
            os.close(descriptor)


def _hashes(value: object) -> list[str]:
    values = _array(value)
    _check(len(values) <= MAX_EVENTS)
    hashes = [str(_digest(item)) for item in values]
    _check(len(hashes) == len(set(hashes)))
    return hashes


def read_execution_receipts(
    root: Path, manifest_hash: str, repository_root: Path
) -> dict[str, object]:
    descriptor = -1
    try:
        _digest(manifest_hash)
        descriptor = _open_root(root, repository_root)

        def read(digest: str) -> bytes:
            body = _read(descriptor, digest + ".source", MAX_BODY_BYTES)
            _check(source_digest(body) == digest)
            return body

        manifest = _mapping(
            _decode(read(manifest_hash)),
            {"schema", "session_hash", "receipt_hashes", "source_hashes", "evidence_promotable"},
        )
        _check(
            manifest["schema"] == "etf-execution-receipt-checkpoint-v1"
            and manifest["evidence_promotable"] is False
        )
        session = read(str(_digest(manifest["session_hash"])))
        receipt_hashes = _hashes(manifest["receipt_hashes"])
        source_hashes = _hashes(manifest["source_hashes"])
        receipts: list[bytes] = []
        sources: dict[str, bytes] = {}
        total = 0
        for digest in receipt_hashes:
            body = read(digest)
            total += len(body)
            _check(total <= MAX_SOURCE_BYTES)
            receipts.append(body)
        total = 0
        for digest in source_hashes:
            body = read(digest)
            total += len(body)
            _check(total <= MAX_SOURCE_BYTES)
            sources[digest] = body
        result = link_execution_receipts(session, tuple(receipts), sources)
        result["checkpoint_hash"] = manifest_hash
        result["clock_session_hash"] = manifest["session_hash"]
        result["retained_source_bytes"] = total
        # The caller may copy only these referenced original bytes privately.
        result["reference_hashes"] = cast(list[str], result["reference_hashes"])
        return result
    except (ValueError, TypeError, ArithmeticError, OSError, RuntimeError, KeyError):
        raise EtfReceiptError() from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
