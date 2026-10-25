"""Closed snapshot validation policies; legacy callers retain full replay."""

from typing import Final, Literal

FULL_REPLAY_V1: Final = "full_replay_v1"
RECOVERY_INTEGRITY_V1: Final = "recovery_integrity_v1"

type SnapshotValidationPolicy = Literal["full_replay_v1", "recovery_integrity_v1"]
