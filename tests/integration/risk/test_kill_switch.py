from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.risk.kill_switch import (
    FileKillSwitch,
    KillSwitchClearRequest,
    KillSwitchError,
)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 17, tzinfo=UTC)


def clear_request() -> KillSwitchClearRequest:
    return KillSwitchClearRequest(False, True, True, "operator_acknowledged_resolution")


def test_activation_is_exclusive_private_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "kill-switch.json"
    switch = FileKillSwitch(path, clock=FixedClock())
    assert switch.activate("drawdown_breach").active
    assert switch.activate("must_not_overwrite").reason == "drawdown_breach"
    assert path.stat().st_mode & 0o777 == 0o600


def test_invalid_file_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "kill-switch.json"
    path.write_text("not-json", encoding="utf-8")
    status = FileKillSwitch(path).status()
    assert status.active
    assert not status.state_valid


def test_clear_requires_all_safety_evidence(tmp_path: Path) -> None:
    switch = FileKillSwitch(tmp_path / "kill-switch.json", clock=FixedClock())
    switch.activate("breach")
    for request in (
        replace(clear_request(), active_breach=True),
        replace(clear_request(), reconciliation_clean=False),
        replace(clear_request(), acknowledged=False),
        replace(clear_request(), reason=""),
    ):
        with pytest.raises(KillSwitchError):
            switch.clear(request)
        assert switch.status().active

    status = switch.clear(clear_request())
    assert not status.active
    assert not switch.status().active
