"""Real receipts and fictional closed Engine exchanges; no native daemon access."""

import importlib
import json
import socket
import threading
import time
from contextlib import contextmanager, suppress
from pathlib import Path

import pytest
from test_stock_attempts import encoded, stopped
from test_stock_engine_mutation import CID, opened, prepare_dispatch, response
from test_stock_engine_mutation import scenario as scenario

from infra.hybrid import stock_attempts


def module():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_engine_retirement.py"
    assert path.is_file(), "Closed predecessor retirement transport is not implemented"
    return importlib.import_module("infra.hybrid.stock_engine_retirement")


@contextmanager
def admitted(scenario):
    release = scenario[3]
    with opened(scenario) as store:
        predecessor = store.begin(release)
        prepare_dispatch(store, release)
        store.record_stopped(encoded(stopped(predecessor)))
    with opened(scenario) as store:
        store.record_stopped(encoded(stopped(predecessor)))
        successor = store.begin(release)
        yield store, predecessor, successor


class Engine:
    def __init__(self, replies, on_connect=None):
        self.replies = list(replies)
        self.on_connect = on_connect
        self.requests = []
        self.threads = []

    def connect(self, deadline):
        assert deadline > 0 and self.replies, "Unexpected exchange/retry"
        if self.on_connect is not None:
            self.on_connect(len(self.threads))
        client, server = socket.socketpair()
        reply = self.replies.pop(0)

        def serve():
            with server:
                raw = b""
                while b"\r\n\r\n" not in raw:
                    chunk = server.recv(4096)
                    if not chunk:
                        return
                    raw += chunk
                self.requests.append(raw)
                with suppress(OSError):
                    server.sendall(reply)

        thread = threading.Thread(target=serve)
        self.threads.append(thread)
        thread.start()
        return client

    def install(self, monkeypatch, api):
        monkeypatch.setattr(api, "_connection", self.connect)
        return self

    def join(self):
        for thread in self.threads:
            thread.join(timeout=2)
            assert not thread.is_alive()


def missing(cid=CID):
    return response(404, encoded({"message": "No such container: " + cid}))


def test_retirement_is_owned_stopped_inspection_then_nonforce_full_cid_delete(
    scenario, monkeypatch
):
    api = module()
    root = scenario[1]
    with admitted(scenario) as (store, predecessor, successor):

        def durable_intent(_index):
            assert (root / successor.attempt_id / "removal-intent.json").exists()
            assert not (root / successor.attempt_id / "create.json").exists()

        engine = Engine(
            [response(200, encoded(stopped(predecessor))), response(204)], durable_intent
        )
        engine.install(monkeypatch, api)
        api.StockEngineRetirer().retire_predecessor(store)
        engine.join()
        assert [raw.split(b"\r\n")[0] for raw in engine.requests] == [
            ("GET /v1.52/containers/" + CID + "/json HTTP/1.0").encode(),
            (
                "DELETE /v1.52/containers/" + CID + "?force=false&v=false&link=false HTTP/1.0"
            ).encode(),
        ]
        state = store.snapshot()
        assert state.removal_intent_sha256 and state.removed_sha256
        assert state.create_sha256 is None
        raw = json.loads((root / successor.attempt_id / "removed.json").read_bytes())
        assert raw["evidence_kind"] == "delete_204" and raw["target_container_id"] == CID
        prepare_dispatch(store, scenario[3])


@pytest.mark.parametrize(
    "body",
    [
        encoded({"message": "page not found"}),
        encoded({"message": "No such container: " + "e" * 64}),
        encoded({"message": "No such container: " + CID, "extra": True}),
        b"private diagnostic",
        b"{}",
    ],
)
def test_generic_or_unscoped_404_never_acknowledges_retirement(scenario, monkeypatch, body):
    api = module()
    with admitted(scenario) as (store, _, _):
        engine = Engine([response(404, body)]).install(monkeypatch, api)
        with pytest.raises(ValueError, match=r"^stock_engine_retirement_unavailable$") as error:
            api.StockEngineRetirer().retire_predecessor(store)
        engine.join()
        assert error.value.__cause__ is None and "private" not in str(error.value)
        assert store.snapshot().removed_sha256 is None and len(engine.requests) == 1


def test_owned_historical_404_completes_retirement_without_delete(scenario, monkeypatch):
    api = module()
    with admitted(scenario) as (store, _, successor):
        engine = Engine([missing()]).install(monkeypatch, api)
        api.StockEngineRetirer().retire_predecessor(store)
        engine.join()
        assert len(engine.requests) == 1 and store.snapshot().removed_sha256 is not None
        path = scenario[1] / successor.attempt_id / "removed.json"
        assert json.loads(path.read_bytes())["evidence_kind"] == "inspect_404"


@pytest.mark.parametrize("change", ["running", "cid", "name", "labels", "lifetime", "restart"])
def test_changed_or_nonterminal_predecessor_never_receives_delete(scenario, monkeypatch, change):
    api = module()
    with admitted(scenario) as (store, predecessor, _):
        raw = stopped(predecessor)
        if change == "running":
            raw["State"]["Running"] = True
        elif change == "cid":
            raw["Id"] = "e" * 64
        elif change == "name":
            raw["Name"] = "/unknown"
        elif change == "labels":
            raw["Config"]["Labels"] = {}
        elif change == "lifetime":
            raw["State"]["FinishedAt"] = "2026-10-21T21:01:00Z"
        else:
            raw["RestartCount"] = 1
        engine = Engine([response(200, encoded(raw))]).install(monkeypatch, api)
        with pytest.raises(ValueError, match=r"^stock_engine_retirement_unavailable$"):
            api.StockEngineRetirer().retire_predecessor(store)
        engine.join()
        assert len(engine.requests) == 1 and store.snapshot().removed_sha256 is None


@pytest.mark.parametrize(
    "reply",
    [
        response(409, b"private conflict"),
        missing(),
        response(500, b"private error"),
        response(204, b"x"),
        b"HTTP/1.0 204 OK\r\nContent-Length: 0\r\n\r\nx",
        b"HTTP/1.0 204 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
        b"HTTP/1.0 204 OK\r\nContent-Length: 0\r\ncontent-length: 0\r\n\r\n",
        b"truncated",
    ],
)
def test_uncertain_or_non204_delete_stays_unresolved_without_retry(scenario, monkeypatch, reply):
    api = module()
    with admitted(scenario) as (store, predecessor, _):
        engine = Engine([response(200, encoded(stopped(predecessor))), reply]).install(
            monkeypatch, api
        )
        with pytest.raises(ValueError, match=r"^stock_engine_retirement_unavailable$"):
            api.StockEngineRetirer().retire_predecessor(store)
        engine.join()
        assert len(engine.requests) == 2 and store.snapshot().removed_sha256 is None
        with pytest.raises(ValueError, match=r"^stock_engine_retirement_unavailable$"):
            api.StockEngineRetirer().retire_predecessor(store)
        assert len(engine.threads) == 2


def test_lost_delete_ack_recovers_by_scoped404_and_ends_the_invocation(scenario, monkeypatch):
    api = module()
    with admitted(scenario) as (store, predecessor, successor):
        engine = Engine([response(200, encoded(stopped(predecessor))), b"truncated"]).install(
            monkeypatch, api
        )
        with pytest.raises(ValueError, match=r"^stock_engine_retirement_unavailable$"):
            api.StockEngineRetirer().retire_predecessor(store)
        engine.join()
        assert engine.requests[1].startswith(("DELETE /v1.52/containers/" + CID + "?").encode())
    with opened(scenario) as recovery:
        assert recovery.recovery_snapshot().attempt.attempt_id == successor.attempt_id
        resumed = Engine([missing()]).install(monkeypatch, api)
        api.StockEngineRetirer().retire_predecessor(recovery)
        resumed.join()
        recovery.record_abandoned_before_dispatch()
        with pytest.raises(ValueError, match=r"^stock_attempt_unavailable$"):
            recovery.begin(scenario[3])


def test_no_retirement_target_never_opens_an_engine_connection(scenario, monkeypatch):
    api = module()
    with opened(scenario) as store:
        store.begin(scenario[3])
        monkeypatch.setattr(api, "_connection", lambda deadline: pytest.fail("Unexpected target"))
        with pytest.raises(ValueError, match=r"^stock_engine_retirement_unavailable$"):
            api.StockEngineRetirer().retire_predecessor(store)


@pytest.mark.parametrize("phase", ["inspect", "delete"])
def test_extra_bytes_in_a_later_response_read_never_acknowledge_retirement(
    scenario, monkeypatch, phase
):
    api = module()
    with admitted(scenario) as (store, predecessor, _):
        chunks = (
            [[missing(), b"x", b""]]
            if phase == "inspect"
            else [
                [response(200, encoded(stopped(predecessor))), b""],
                [response(204), b"x", b""],
            ]
        )
        requests = []

        class Peer:
            def __init__(self, rows):
                self.rows = rows

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def settimeout(self, seconds):
                assert 0 < seconds <= 5

            def sendall(self, raw):
                requests.append(raw)

            def recv(self, size):
                raw = self.rows.pop(0)
                assert len(raw) <= size
                return raw

        monkeypatch.setattr(api, "_connection", lambda deadline: Peer(chunks.pop(0)))
        with pytest.raises(ValueError, match=r"^stock_engine_retirement_unavailable$"):
            api.StockEngineRetirer().retire_predecessor(store)
        assert store.snapshot().removed_sha256 is None
        assert len(requests) == (1 if phase == "inspect" else 2)


@pytest.mark.parametrize("phase", ["inspect", "delete"])
def test_each_retirement_exchange_has_one_nonrenewing_five_second_budget(
    scenario, monkeypatch, phase
):
    api = module()
    with admitted(scenario) as (store, predecessor, _):
        tick = {"now": time.monotonic()}
        requests = []
        rows = [response(200, encoded(stopped(predecessor))), response(204)]

        class SlowPeer:
            def __init__(self, index):
                self.index, self.reads = index, 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def settimeout(self, seconds):
                assert 0 < seconds <= 5

            def sendall(self, raw):
                requests.append(raw)

            def recv(self, size):
                if self.index == (0 if phase == "inspect" else 1):
                    tick["now"] += 3
                self.reads += 1
                return rows[self.index] if self.reads == 1 else b""

        monkeypatch.setattr(time, "monotonic", lambda: tick["now"])
        monkeypatch.setattr(api, "_connection", lambda deadline: SlowPeer(len(requests)))
        with pytest.raises(ValueError, match=r"^stock_engine_retirement_unavailable$"):
            api.StockEngineRetirer().retire_predecessor(store)
        assert len(requests) == (1 if phase == "inspect" else 2)
        assert store.snapshot().removed_sha256 is None


def test_removal_intent_flush_failure_sends_no_inspection(scenario, monkeypatch):
    api = module()
    with admitted(scenario) as (store, _, _):
        monkeypatch.setattr(api, "_connection", lambda deadline: pytest.fail("Socket opened"))
        monkeypatch.setattr(
            stock_attempts.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fictional"))
        )
        with pytest.raises(ValueError, match=r"^stock_engine_retirement_unavailable$"):
            api.StockEngineRetirer().retire_predecessor(store)


def test_namespace_drift_after_inspection_prevents_delete_bytes(scenario, monkeypatch):
    api = module()
    with admitted(scenario) as (store, predecessor, successor):

        def change(index):
            if index == 1:
                (scenario[1] / "active.json").write_bytes(b"{}\n")

        engine = Engine([response(200, encoded(stopped(predecessor))), response(204)], change)
        engine.install(monkeypatch, api)
        with pytest.raises(ValueError, match=r"^stock_engine_retirement_unavailable$"):
            api.StockEngineRetirer().retire_predecessor(store)
        engine.join()
        assert len(engine.requests) == 1 and engine.requests[0].startswith(b"GET ")
        assert not (scenario[1] / successor.attempt_id / "removed.json").exists()
