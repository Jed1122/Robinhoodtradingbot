"""Shared sticky signals across the actual nested probe, never real signals/Docker."""

import signal
import threading
from contextlib import suppress

import pytest
from test_stock_prestart import IMAGE
from test_stock_probe_controller import Daemon, module
from test_stock_probe_controller import scenario as probe_scenario

from infra.hybrid import stock_supervisor


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGINT])
def test_nested_shutdown_preserves_the_outer_sticky_signal_and_handlers(number):
    previous = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}
    with stock_supervisor._shutdown() as outer:
        installed = signal.getsignal(number)
        with stock_supervisor._shutdown() as inner:
            assert inner is outer
            assert signal.getsignal(number) is installed
            installed(number, None)
            assert inner == outer == [True]
        assert outer == [True] and signal.getsignal(number) is installed
    assert {number: signal.getsignal(number) for number in previous} == previous
    with stock_supervisor._shutdown() as fresh:
        assert fresh == [False] and fresh is not outer


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGINT])
@pytest.mark.parametrize("at", ["create", "start", "poll", "logs", "delete"])
def test_signal_in_actual_nested_probe_reaches_outer_producer(tmp_path, monkeypatch, number, at):
    scenario = probe_scenario.__wrapped__(tmp_path, monkeypatch)
    controller = module()
    daemon = Daemon(scenario).install(monkeypatch, controller)
    delivered = False

    def interrupt(method, path):
        nonlocal delivered
        matches = {
            "create": "/create?" in path,
            "start": path.endswith("/start"),
            "poll": path.endswith("/json") and daemon.started,
            "logs": "/logs?" in path,
            "delete": method == "DELETE",
        }
        if matches[at] and not delivered:
            delivered = True
            handler = signal.getsignal(number)
            assert callable(handler)
            handler(number, None)

    daemon.on_request = interrupt
    with stock_supervisor._shutdown() as outer:
        with suppress(ValueError):
            result = controller.run_probe(IMAGE)
            assert result.configuration is None
        assert delivered and outer == [True]
    daemon.join()
    assert daemon.count("/create?") == 1 and daemon.count("/start") <= 1


def test_another_thread_cannot_borrow_the_main_thread_shutdown_context():
    errors = []

    def enter():
        try:
            with stock_supervisor._shutdown():
                errors.append("borrowed")
        except ValueError:
            errors.append("denied")

    with stock_supervisor._shutdown():
        worker = threading.Thread(target=enter)
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
    assert errors == ["denied"]


def test_external_handler_replacement_denies_success_but_restores_both():
    previous = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}
    with pytest.raises(ValueError), stock_supervisor._shutdown():
        signal.signal(signal.SIGINT, lambda *_: None)
    assert {number: signal.getsignal(number) for number in previous} == previous
    with stock_supervisor._shutdown() as fresh:
        assert fresh == [False]
