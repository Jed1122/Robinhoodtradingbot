"""Immutable receipt-ordered observations, not an authenticated or qualified source.

Provider timestamps do not determine local visibility. Monotonic clocks belong
to one capture only; predecessor metadata never establishes continuity.
"""

from dataclasses import dataclass, field
from typing import Literal

from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.market_data.alpaca_observations import MAX_FRAME_ROWS, AlpacaStreamObservation

MAX_CAPTURE_OBSERVATIONS = 10000
MAX_CAPTURE_FRAMES = 10000
_MAX_INTEGER = 2**63 - 1


class AlpacaCaptureValueError(ValueError):
    def __init__(self) -> None:
        super().__init__("alpaca_observation_capture_invalid")


def _check(value: bool) -> None:
    if not value:
        raise AlpacaCaptureValueError()


def _clock(value: int) -> None:
    _check(type(value) is int and 0 <= value <= _MAX_INTEGER)


@dataclass(frozen=True, slots=True, repr=False)
class AlpacaObservationFrame:
    frame_index: int
    receipt_sha256: str
    body_sha256: str
    received_at_ns: int
    received_monotonic_ns: int
    observations: tuple[AlpacaStreamObservation, ...]

    def __post_init__(self) -> None:
        try:
            _clock(self.frame_index)
            _check(self.frame_index < MAX_CAPTURE_FRAMES)
            _require_sha256_hex(self.receipt_sha256, "receipt")
            _require_sha256_hex(self.body_sha256, "body")
            _clock(self.received_at_ns)
            _clock(self.received_monotonic_ns)
            _check(type(self.observations) is tuple and len(self.observations) <= MAX_FRAME_ROWS)
            for index, observation in enumerate(self.observations):
                _check(type(observation) is AlpacaStreamObservation)
                observation.__post_init__()
                _check(
                    observation.frame_index == self.frame_index
                    and observation.row_index == index
                    and observation.body_sha256 == self.body_sha256
                    and observation.received_at_ns == self.received_at_ns
                )
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise AlpacaCaptureValueError() from None


@dataclass(frozen=True, slots=True, repr=False)
class AlpacaObservationCapture:
    result_hash: str
    plan_hash: str
    code_revision: str
    config_hash: str
    started_at_ns: int
    finished_at_ns: int
    collection_window: tuple[int, int] | None
    predecessor_result_hash: str | None
    termination: str
    frames: tuple[AlpacaObservationFrame, ...]
    source_qualified: Literal[False] = field(default=False, init=False)
    execution_enabled: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        try:
            for value in (self.result_hash, self.plan_hash, self.config_hash):
                _require_sha256_hex(value, "capture")
            _check(
                type(self.code_revision) is str
                and len(self.code_revision) == 40
                and all(c in "0123456789abcdef" for c in self.code_revision)
            )
            if self.predecessor_result_hash is not None:
                _require_sha256_hex(self.predecessor_result_hash, "predecessor")
            _clock(self.started_at_ns)
            _clock(self.finished_at_ns)
            _check(self.started_at_ns <= self.finished_at_ns)
            if self.collection_window is not None:
                _check(type(self.collection_window) is tuple and len(self.collection_window) == 2)
                start, end = self.collection_window
                _clock(start)
                _clock(end)
                _check(start <= end)
            _check(
                type(self.termination) is str
                and self.termination
                in (
                    "frame_limit",
                    "duration_limit",
                    "duration_limit_unverified",
                    "byte_limit_unretained_frame",
                    "capture_failed",
                )
            )
            _check(type(self.frames) is tuple and len(self.frames) <= MAX_CAPTURE_FRAMES)
            count = 0
            last_utc, last_mono = self.started_at_ns, 0
            hashes: set[str] = set()
            for index, frame in enumerate(self.frames):
                _check(type(frame) is AlpacaObservationFrame)
                frame.__post_init__()
                _check(frame.frame_index == index and frame.receipt_sha256 not in hashes)
                _check(last_utc <= frame.received_at_ns <= self.finished_at_ns)
                _check(last_mono <= frame.received_monotonic_ns)
                if self.collection_window is not None:
                    _check(
                        self.collection_window[0]
                        <= frame.received_monotonic_ns
                        <= self.collection_window[1]
                    )
                count += len(frame.observations)
                _check(count <= MAX_CAPTURE_OBSERVATIONS)
                hashes.add(frame.receipt_sha256)
                last_utc, last_mono = frame.received_at_ns, frame.received_monotonic_ns
            _check(
                self.source_qualified is False
                and self.execution_enabled is False
                and self.evidence_promotable is False
            )
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            raise AlpacaCaptureValueError() from None

    def visible_frames(
        self, *, received_at_ns: int, received_monotonic_ns: int
    ) -> tuple[AlpacaObservationFrame, ...]:
        """Select receipts visible under both caller-supplied clocks; never event time."""
        self.__post_init__()
        _clock(received_at_ns)
        _clock(received_monotonic_ns)
        return tuple(
            frame
            for frame in self.frames
            if frame.received_at_ns <= received_at_ns
            and frame.received_monotonic_ns <= received_monotonic_ns
        )
