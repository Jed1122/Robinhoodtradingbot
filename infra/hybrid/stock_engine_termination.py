"""Uncomposed scoped worker signals; acknowledgement never establishes termination.

No controller, retry, removal, deadline renewal, broker or credential operation.
Both daemon exchanges share one five-second budget and a locked root store.
"""

import time
from typing import NoReturn

from infra.hybrid.stock_attempts import AttemptSnapshot, AttemptStore, _integer, _timestamp
from infra.hybrid.stock_container import API_VERSION, _object
from infra.hybrid.stock_engine import _connection, _remaining
from infra.hybrid.stock_engine_mutation import _ERRORS, _production_store, _response
from infra.hybrid.stock_release import _exact

_IO_SECONDS = 5.0


def _deny() -> NoReturn:
    raise ValueError("stock_engine_termination_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


def _owned_running(raw: bytes, target: AttemptSnapshot) -> None:
    value = _object(raw)
    attempt = target.attempt
    _require(
        value["Id"] == target.container_id
        and value["Image"] == attempt.image_digest
        and value["Name"] == "/hybrid-stock-research-" + attempt.attempt_id
        and value["Platform"] == "linux"
    )
    _require(type(value["RestartCount"]) is int and value["RestartCount"] == 0)
    _require(
        _exact(
            value["Config"]["Labels"],
            {
                "org.hybrid.stock.managed": "stock-research",
                "org.hybrid.stock.release": attempt.release_id,
                "org.hybrid.stock.attempt": attempt.attempt_id,
            },
        )
    )
    _require(
        value["HostConfig"]["AutoRemove"] is False
        and _exact(value["HostConfig"]["RestartPolicy"], {"Name": "no", "MaximumRetryCount": 0})
    )
    state = value["State"]
    _require(
        type(state) is dict
        and set(state)
        == {
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
    )
    _require(state["Status"] == "running" and state["Running"] is True)
    _require(all(state[key] is False for key in ("Paused", "Restarting", "OOMKilled", "Dead")))
    _require(
        _integer(state["Pid"], 1) and type(state["ExitCode"]) is int and state["ExitCode"] == 0
    )
    _require(type(state["Error"]) is str and state["Error"] == "")
    _timestamp(state["StartedAt"])
    _require(state["FinishedAt"] == "0001-01-01T00:00:00Z")


class StockEngineTerminator:
    """Fresh identity-checked TERM/KILL dispatch for a persisted active start only."""

    @staticmethod
    def _exchange(signal: str, store: AttemptStore) -> None:
        try:
            deadline = time.monotonic() + _IO_SECONDS
            _production_store(store)
            _require(type(signal) is str and signal in {"TERM", "KILL"})
            target = store.cleanup_target()
            if target.container_id is None:
                _deny()
            prefix = "/v" + API_VERSION + "/containers/" + target.container_id
            inspection = (
                "GET " + prefix + "/json HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n"
            ).encode("ascii")
            _remaining(deadline)
            with _connection(deadline) as peer:
                peer.settimeout(_remaining(deadline))
                peer.sendall(inspection)
                raw = _response(peer, deadline, 200)
            _owned_running(raw, target)
            request = (
                "POST "
                + prefix
                + "/kill?signal="
                + signal
                + " HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
            ).encode("ascii")
            _remaining(deadline)
            with _connection(deadline) as peer:
                _require(store.snapshot() == target)
                peer.settimeout(_remaining(deadline))
                peer.sendall(request)
                _require(not _response(peer, deadline, 204))
                _remaining(deadline)
        except _ERRORS:
            _deny()

    def signal_active(self, store: AttemptStore, signal: str) -> None:
        self._exchange(signal, store)
