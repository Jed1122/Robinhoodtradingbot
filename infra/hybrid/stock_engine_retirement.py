"""Closed predecessor retirement; never resolves uncertain worker creation.

Only an owned stopped predecessor from a durable successor handoff is eligible.
An acknowledgement is lifecycle evidence, not successful research or deployment.
"""

from typing import NoReturn

from infra.hybrid import stock_attempts, stock_engine_mutation
from infra.hybrid.stock_attempts import AttemptStore, RemovalFence, RetirementProof
from infra.hybrid.stock_container import API_VERSION, _object
from infra.hybrid.stock_engine import _connection, _deadline, _remaining
from infra.hybrid.stock_engine_mutation import _ERRORS, _response_status


def _deny() -> NoReturn:
    raise ValueError("stock_engine_retirement_unavailable") from None


def _require(condition: bool) -> None:
    if not condition:
        _deny()


def _exchange(store: AttemptStore, fence: RemovalFence, *, delete: bool) -> tuple[int, bytes]:
    deadline = _deadline(fence.deadline_ns)
    prefix = "/v" + API_VERSION + "/containers/" + fence.target_container_id
    if delete:
        request = (
            "DELETE " + prefix + "?force=false&v=false&link=false HTTP/1.0\r\n"
            "Host: localhost\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
        )
    else:
        request = "GET " + prefix + "/json HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n"
    with _connection(deadline) as peer:
        store.check_removal_fence(fence)
        peer.settimeout(_remaining(deadline))
        peer.sendall(request.encode("ascii"))
        result = _response_status(peer, deadline, {204} if delete else {200, 404})
        _remaining(deadline)
    store.check_removal_fence(fence)
    return result


class StockEngineRetirer:
    """One bounded inspect and optional non-force removal, with no ID override."""

    def retire_predecessor(self, store: AttemptStore) -> None:
        try:
            stock_engine_mutation._production_store(store)
            fence = store.prepare_removal()
            status, raw = _exchange(store, fence, delete=False)
            if status == 404:
                message = _object(raw)
                _require(
                    set(message) == {"message"}
                    and type(message["message"]) is str
                    and message["message"] == "No such container: " + fence.target_container_id
                )
                evidence = "inspect_404"
            else:
                store.check_removal_observation(fence, raw)
                status, raw = _exchange(store, fence, delete=True)
                _require(status == 204 and not raw)
                evidence = "delete_204"
            clock = stock_attempts._clock()
            proof = RetirementProof(fence, evidence, clock["boot_id"], clock["monotonic_ns"])
            store.record_removed(fence, proof)
        except _ERRORS:
            _deny()
