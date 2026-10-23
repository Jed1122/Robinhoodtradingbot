"""Failure diagnostics exercise real build/CLI paths with native Docker denied."""

import errno
import importlib
import io
import json
import socket
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_stock_build_engine import Wire, response
from test_stock_build_engine import scenario as build_scenario
from test_stock_engine import connector as engine_connector
from test_stock_producer_command import scenario as command_scenario
from test_stock_release_producer import opened

SECRET = "fixture-secret /private/credential access_token=do-not-emit"


def api():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_producer_diagnostics.py"
    assert path.is_file(), "Bounded producer failure diagnostics are missing"
    return importlib.import_module("infra.hybrid.stock_producer_diagnostics")


def decoded(module):
    raw = module.failure_diagnostic()
    assert type(raw) is str and 0 < len(raw.encode()) <= 1024
    value = json.loads(raw)
    assert raw == json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    assert SECRET not in raw
    return value


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    return build_scenario.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def command(tmp_path, monkeypatch):
    return command_scenario.__wrapped__(tmp_path, monkeypatch)


def test_cli_failure_has_safe_diagnostic_without_changing_denial(monkeypatch, capsys):
    from infra.hybrid import stock_producer as cli

    @contextmanager
    def failing(_):
        raise OSError(errno.ENOSPC, SECRET)
        yield  # pragma: no cover

    monkeypatch.setattr(cli, "_completed_release", failing)
    assert cli.main(["a" * 64]) == 1
    output = capsys.readouterr()
    assert output.out == '{"reason":"stock_producer_unavailable","status":"blocked"}\n'
    diagnostic = json.loads(output.err)
    assert diagnostic["first"] == {"phase": "producer", "family": "OSError", "errno": errno.ENOSPC}
    assert SECRET not in output.err and len(output.err.encode()) <= 1024


def test_capture_is_inert_outside_scope_and_success_is_silent():
    module = api()
    with pytest.raises(OSError), module.phase("receive"):
        raise OSError(errno.EIO, SECRET)
    assert module.failure_diagnostic() is None
    with module.capture():
        with module.phase("receive"):
            pass
        assert module.failure_diagnostic() is None
    assert module.failure_diagnostic() is None


@pytest.mark.parametrize(
    "error,family,number",
    [
        (OSError(errno.EIO, SECRET), "OSError", errno.EIO),
        (ValueError(SECRET), "ValueError", None),
        (TypeError(SECRET), "TypeError", None),
        (KeyError(SECRET), "KeyError", None),
        (OverflowError(SECRET), "OverflowError", None),
        (AttributeError(SECRET), "AttributeError", None),
        (RecursionError(SECRET), "RecursionError", None),
        (RuntimeError(SECRET), "Exception", None),
        (OSError(999999, SECRET), "OSError", None),
    ],
)
def test_only_allowlisted_error_metadata_survives(error, family, number):
    module = api()
    with module.capture():
        with pytest.raises(type(error)), module.phase("parse"):
            raise error
        assert decoded(module) == {
            "schema_version": 1,
            "kind": "stock_producer_failure_diagnostic",
            "first": {"phase": "parse", "family": family, "errno": number},
            "secondary": [],
        }


def test_unknown_phase_and_hostile_errno_cannot_emit_supplied_strings():
    module = api()

    class Hostile(OSError):
        @property
        def errno(self):
            raise ValueError(SECRET)

    with module.capture():
        with pytest.raises(Hostile), module.phase(SECRET):
            raise Hostile(SECRET)
        assert decoded(module)["first"] == {
            "phase": "unknown", "family": "OSError", "errno": None
        }


def test_nested_capture_does_not_contaminate_another_invocation():
    module = api()
    with module.capture():
        with pytest.raises(ValueError), module.phase("parse"):
            raise ValueError(SECRET)
        with module.capture():
            assert module.failure_diagnostic() is None
            with pytest.raises(OSError), module.phase("connect"):
                raise OSError(errno.EIO, SECRET)
            assert decoded(module)["first"]["phase"] == "connect"
        assert decoded(module)["first"]["phase"] == "parse"
    with module.capture():
        assert module.failure_diagnostic() is None


def test_propagation_is_not_misreported_as_cleanup_and_secondary_storage_is_bounded():
    module = api()
    with module.capture():
        with pytest.raises(OSError), module.phase("send"), module.phase("lease_check"):
            raise OSError(errno.EIO, SECRET)
        assert decoded(module)["secondary"] == []
        for _ in range(100):
            with pytest.raises(OSError), module.phase("close"):
                raise OSError(errno.ENOSPC, SECRET)
        value = decoded(module)
        assert value["first"]["phase"] == "lease_check"
        assert len(value["secondary"]) <= 4


def test_diagnostic_encoding_failure_preserves_original_exception(monkeypatch):
    module = api()
    with module.capture():
        failure = OSError(errno.EIO, SECRET)
        with pytest.raises(OSError) as error, module.phase("receive"):
            raise failure
        assert error.value is failure

        def broken(*args, **kwargs):
            raise RuntimeError(SECRET)

        monkeypatch.setattr(module.json, "dumps", broken)
        assert module.failure_diagnostic() is None


@pytest.mark.parametrize(
    "name,path",
    [("version_get", "/version"), ("image_get", "/v1.52/images/sha256:" + "b" * 64 + "/json")],
)
def test_get_records_raw_errno_before_existing_engine_sanitization(monkeypatch, name, path):
    from infra.hybrid import stock_engine

    diagnostics = api()

    def denied_connection(deadline):
        raise OSError(errno.ECONNREFUSED, SECRET)

    monkeypatch.setattr(stock_engine, "_connection", denied_connection)
    with diagnostics.capture():
        with pytest.raises(ValueError, match="stock_engine_unavailable"), diagnostics.phase(name):
            stock_engine.StockEngineReader._get(path)
        value = decoded(diagnostics)
        assert value["first"] == {
            "phase": name, "family": "OSError", "errno": errno.ECONNREFUSED
        }
        assert value["secondary"] == []


def test_get_paired_cleanup_failure_cannot_replace_receive_errno(monkeypatch):
    from infra.hybrid import stock_engine

    diagnostics = api()
    client, server = socket.socketpair()

    class Peer:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            client.close()
            raise OSError(errno.EIO, SECRET)

        def settimeout(self, value):
            client.settimeout(value)

        def sendall(self, raw):
            client.sendall(raw)

        def recv(self, size):
            raise OSError(errno.ECONNRESET, SECRET)

    monkeypatch.setattr(stock_engine, "_connection", lambda deadline: Peer())
    try:
        with diagnostics.capture():
            with pytest.raises(ValueError), diagnostics.phase("image_get"):
                stock_engine.StockEngineReader._get("/version")
            value = decoded(diagnostics)
            assert value["first"] == {
                "phase": "image_get", "family": "OSError", "errno": errno.ECONNRESET
            }
            assert value["secondary"] == [
                {"phase": "close", "family": "OSError", "errno": errno.EIO}
            ]
    finally:
        client.close()
        server.close()


@pytest.mark.parametrize("name", ["version_get", "image_get"])
def test_get_close_only_failure_is_classified_as_close_after_valid_body(monkeypatch, name):
    from infra.hybrid import stock_engine

    diagnostics = api()
    client, server = socket.socketpair()
    server.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 3\r\n\r\n{}\n")
    server.shutdown(socket.SHUT_WR)

    class Peer:
        def __enter__(self):
            return client

        def __exit__(self, *_):
            client.close()
            raise OSError(errno.EIO, SECRET)

    monkeypatch.setattr(stock_engine, "_connection", lambda deadline: Peer())
    try:
        with diagnostics.capture():
            with (
                pytest.raises(ValueError, match="stock_engine_unavailable"),
                diagnostics.phase(name),
            ):
                stock_engine.StockEngineReader._get("/version")
            value = decoded(diagnostics)
            assert value["first"] == {
                "phase": "close", "family": "OSError", "errno": errno.EIO
            }
            assert value["secondary"] == []
    finally:
        client.close()
        server.close()


def test_connection_paired_cleanup_failure_cannot_replace_connect_errno(monkeypatch):
    diagnostics = api()
    engine, peer, calls = engine_connector.__wrapped__(monkeypatch)

    def failed_connect(path):
        calls.append("connect")
        raise OSError(errno.ECONNREFUSED, SECRET)

    def failed_close():
        calls.append("close")
        raise OSError(errno.EIO, SECRET)

    monkeypatch.setattr(peer, "connect", failed_connect)
    monkeypatch.setattr(peer, "close", failed_close)
    with diagnostics.capture():
        with pytest.raises(OSError) as error, diagnostics.phase("connect"):
            engine._connection(time.monotonic() + 1)
        assert error.value.errno == errno.EIO  # Original propagation is preserved.
        value = decoded(diagnostics)
        assert value["first"] == {
            "phase": "connect", "family": "OSError", "errno": errno.ECONNREFUSED
        }
        assert value["secondary"] == [{"phase": "close", "family": "OSError", "errno": errno.EIO}]
    assert calls.count("connect") == calls.count("close") == 1


def test_receive_error_survives_close_and_retention_failures_without_replay(scenario, monkeypatch):
    diagnostics = api()
    state, engine, version, _ = scenario
    wire = Wire([response(version), b""]).install(monkeypatch, engine)
    retained = state[0]._Lease.retain

    class BrokenPeer:
        def __init__(self, peer):
            self.peer = peer

        def __getattr__(self, name):
            return getattr(self.peer, name)

        def recv(self, size):
            raise ConnectionResetError(errno.ECONNRESET, SECRET)

        def close(self):
            self.peer.close()
            raise OSError(errno.EIO, SECRET)

    monkeypatch.setattr(engine, "_connection", lambda deadline: BrokenPeer(wire.connect(deadline)))

    def fail_response(lease, name, raw):
        if name == "build-response.http":
            raise OSError(errno.ENOSPC, SECRET)
        return retained(lease, name, raw)

    monkeypatch.setattr(state[0]._Lease, "retain", fail_response)
    with diagnostics.capture(), opened(state) as lease:
        with pytest.raises(ValueError, match="stock_build_engine_unavailable"):
            engine._build(lease)
        value = decoded(diagnostics)
        assert value["first"] == {
            "phase": "receive", "family": "OSError", "errno": errno.ECONNRESET
        }
        assert {entry["phase"] for entry in value["secondary"]} == {"close", "response_retain"}
        assert lease.dispatched and lease.built_image is None
    wire.join()
    assert len(wire.requests) == 2
    directory = state[1] / "attempts" / state[3]
    assert not (directory / "image.bin").exists()
    assert not (directory / "probe-intent.json").exists()


def test_parse_denial_records_policy_failure_and_keeps_original_prefix(scenario, monkeypatch):
    diagnostics = api()
    state, engine, version, _ = scenario
    raw = response(b'{"error":"' + SECRET.encode() + b'"}\r\n')
    wire = Wire([response(version), raw]).install(monkeypatch, engine)
    with diagnostics.capture(), opened(state) as lease:
        with pytest.raises(ValueError):
            engine._build(lease)
        assert decoded(diagnostics)["first"] == {
            "phase": "parse", "family": "ValueError", "errno": None
        }
    wire.join()
    directory = state[1] / "attempts" / state[3]
    assert (directory / "build-response.http").read_bytes() == raw
    assert len(wire.requests) == 2 and not (directory / "image.bin").exists()


def test_successful_cli_keeps_exact_output_and_empty_stderr(command, capsys):
    from infra.hybrid import stock_producer as cli

    state, release_root, wire, daemon, *_ = command
    assert cli.main([state[3]]) == 0
    output = capsys.readouterr()
    assert output.out == (
        '{"manifest":"' + str(release_root / state[3] / "manifest.json")
        + '","status":"succeeded"}\n'
    )
    assert output.err == ""
    wire.join()
    daemon.join()


def test_failed_stderr_sink_cannot_change_denial_or_retry(monkeypatch):
    from infra.hybrid import stock_producer as cli

    class Broken(io.StringIO):
        def write(self, text):
            raise OSError(errno.EIO, SECRET)

    stream = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    monkeypatch.setattr(cli.sys, "stderr", Broken())
    assert cli.main(["invalid-source"]) == 1
    assert stream.getvalue() == '{"reason":"stock_producer_unavailable","status":"blocked"}\n'


def test_failed_diagnostic_encoding_keeps_cli_denial_and_no_partial_stderr(monkeypatch, capsys):
    from infra.hybrid import stock_producer as cli

    diagnostics = api()

    def broken(*args, **kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(diagnostics.json, "dumps", broken)
    assert cli.main(["invalid-source"]) == 1
    output = capsys.readouterr()
    assert output.out == '{"reason":"stock_producer_unavailable","status":"blocked"}\n'
    assert output.err == ""
