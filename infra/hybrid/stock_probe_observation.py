"""Pure supplied probe ownership/lifetimes; never dispatches or grants authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn

from infra.hybrid.stock_container import _object, _require
from infra.hybrid.stock_prestart import _ERRORS, _TIMESTAMP, _hex
from infra.hybrid.stock_probe_profile import probe_name
from infra.hybrid.stock_release import _exact

_ZERO = "0001-01-01T00:00:00Z"
_STATE_KEYS = {
    "Status",
    "Running",
    "Paused",
    "Restarting",
    "OOMKilled",
    "Dead",
    "Pid",
    "ExitCode",
    "Error",
    "StartedAt",
    "FinishedAt",
}


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    probe_id: str
    container_id: str
    image_digest: str
    status: str
    pid: int
    exit_code: int
    oom_killed: bool
    error_present: bool
    container_started_at: str
    container_finished_at: str


def _deny() -> NoReturn:
    raise ValueError("stock_probe_observation_unavailable") from None


def _lifetime(value: Any) -> str:
    _require(type(value) is str)
    if value != _ZERO:
        _require(_TIMESTAMP.fullmatch(value) is not None)
        _require(datetime.fromisoformat(value).year >= 1970)
    # The original string preserves all nine fractional digits. Wall-clock ordering
    # is not scoped cleanup authority and is not compared through datetime's truncation.
    return str(value)


def observe_probe(
    raw: bytes, *, probe_id: str, container_id: str, image_digest: str
) -> ProbeObservation:
    """Read copied facts only; strict prestart and durable transport fences are separate."""
    try:
        name = probe_name(probe_id)
        _require(_hex(container_id))
        _require(
            type(image_digest) is str
            and re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is not None
        )
        value = _object(raw)
        _require(value["Id"] == container_id and value["Image"] == image_digest)
        _require(value["Name"] == "/" + name and value["Platform"] == "linux")
        _require(type(value["RestartCount"]) is int and value["RestartCount"] == 0)
        _require(
            _exact(
                value["Config"]["Labels"],
                {
                    "org.hybrid.stock.managed": "stock-configuration-probe",
                    "org.hybrid.stock.probe": probe_id,
                },
            )
        )
        _require(value["HostConfig"]["AutoRemove"] is False)
        _require(
            _exact(value["HostConfig"]["RestartPolicy"], {"Name": "no", "MaximumRetryCount": 0})
        )
        state = value["State"]
        _require(type(state) is dict and set(state) == _STATE_KEYS)
        status = state["Status"]
        _require(type(status) is str and status in ("created", "running", "exited", "dead"))
        for key in ("Running", "Paused", "Restarting", "OOMKilled", "Dead"):
            _require(type(state[key]) is bool)
        _require(state["Running"] == (status == "running") and state["Dead"] == (status == "dead"))
        _require(state["Paused"] is False and state["Restarting"] is False)
        pid, exit_code = state["Pid"], state["ExitCode"]
        _require(type(pid) is int and 0 <= pid <= 2**31 - 1)
        _require((pid > 0) if status == "running" else pid == 0)
        _require(type(exit_code) is int and 0 <= exit_code <= 255)
        _require(type(state["Error"]) is str and len(state["Error"]) <= 4096)
        started, finished = _lifetime(state["StartedAt"]), _lifetime(state["FinishedAt"])
        if status == "created":
            _require(started == _ZERO)
        elif status in ("running", "exited"):
            _require(started != _ZERO)
        if status == "exited":
            _require(finished != _ZERO)
        return ProbeObservation(
            probe_id,
            container_id,
            image_digest,
            status,
            pid,
            exit_code,
            state["OOMKilled"],
            bool(state["Error"]),
            started,
            finished,
        )
    except _ERRORS:
        _deny()
