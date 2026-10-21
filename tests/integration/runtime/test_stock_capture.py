import asyncio
import hashlib
import importlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.brokers.robinhood_mcp_transport import McpToolResult

NOW = datetime(2026, 10, 21, 14, tzinfo=UTC)


class Transport:
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if len(self.calls) == self.fail_at:
            raise RuntimeError("secret-provider-message")
        return McpToolResult(
            (), False, {"data": {"results": []}, "guide": "untrusted instructions"}
        )


@pytest.fixture
def capture(tmp_path):
    module = importlib.import_module("trading_bot.runtime.stock_capture")
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    return module, root


def run(module, root, requests, transport=None, **kwargs):
    transport = transport or Transport()
    ticks = iter(NOW + timedelta(seconds=i) for i in range(100))
    pauses = []

    async def pause(seconds):
        pauses.append(seconds)

    result = asyncio.run(
        module.capture_stock_observations(
            transport=transport,
            requests=requests,
            output_dir=root,
            clock=lambda: next(ticks),
            sleep=pause,
            transport_authenticated=False,
            **kwargs,
        )
    )
    return result, transport, pauses


def test_complete_receipts_preserve_native_payload_and_availability(capture):
    module, root = capture
    requests = [module.StockCaptureRequest("get_equity_fundamentals", {"symbols": ["ACME"]})]
    report, transport, _ = run(module, root, requests)
    assert report["status"] == "complete"
    assert report["successful_calls"] == 1
    assert report["qualified"] is report["live_enabled"] is False
    assert "untrusted instructions" not in str(report)
    receipt = json.loads((root / report["manifest_file"]).read_bytes())
    item = receipt["observations"][0]
    raw = (root / item["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == item["sha256"]
    observation = json.loads(raw)
    assert observation["payload"]["guide"] == "untrusted instructions"
    assert observation["available_at"] == observation["received_at"]
    assert observation["request_started_at"] < observation["received_at"]
    assert observation["provider"] == "robinhood_official_mcp"
    assert observation["transport_authenticated"] is False
    assert observation["native_http_wire_receipt"] is False
    assert observation["qualified"] is False
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in root.iterdir())
    assert len(transport.calls) == 1


def test_failure_stops_without_blind_retry_and_records_partial_manifest(capture):
    module, root = capture
    request = module.StockCaptureRequest("get_equity_fundamentals", {"symbols": ["ACME"]})
    report, transport, pauses = run(module, root, [request] * 3, Transport(fail_at=2))
    assert report["status"] == "partial"
    assert report["attempted_calls"] == 2
    assert report["successful_calls"] == 1
    assert len(transport.calls) == 2
    assert pauses == [1.0]
    manifest = json.loads((root / report["manifest_file"]).read_bytes())
    assert manifest["failure_code"] == "research_call_failed"
    assert "secret-provider-message" not in str(manifest)
    assert "secret-provider-message" not in str(report)


@pytest.mark.parametrize(
    "requests",
    [
        [],
        [{"tool": "place_equity_order", "arguments": {}}],
        [{"tool": "get_equity_fundamentals", "arguments": {"symbols": ["ACME"] * 11}}],
        [{"tool": "get_financials", "arguments": {"symbols": ["ACME"], "limit": 41}}],
    ],
)
def test_plan_rejected_before_any_tool_or_file(capture, requests):
    module, root = capture
    transport = Transport()
    with pytest.raises(module.StockCaptureError):
        parsed = module.parse_stock_capture_plan(requests)
        run(module, root, parsed, transport)
    assert transport.calls == []
    assert list(root.iterdir()) == []


def test_request_snapshot_cannot_be_changed_after_construction(capture):
    module, root = capture
    arguments = {"symbols": ["ACME"]}
    request = module.StockCaptureRequest("get_equity_fundamentals", arguments)
    arguments["symbols"].append("OTHER")
    _, transport, _ = run(module, root, [request])
    assert transport.calls[0][1] == {"symbols": ["ACME"]}


def test_private_root_required_before_call(capture):
    module, root = capture
    root.chmod(0o755)
    transport = Transport()
    request = module.StockCaptureRequest("get_equity_fundamentals", {"symbols": ["ACME"]})
    with pytest.raises(module.StockCaptureError):
        run(module, root, [request], transport)
    assert transport.calls == []


def test_overwrite_and_clock_reversal_fail_closed(capture):
    module, root = capture
    request = module.StockCaptureRequest("get_equity_fundamentals", {"symbols": ["ACME"]})
    report, _, _ = run(module, root, [request])
    prior = {p.name: p.read_bytes() for p in root.iterdir()}
    with pytest.raises(module.StockCaptureError):
        run(module, root, [request])
    assert {p.name: p.read_bytes() for p in root.iterdir()} == prior
    assert report["manifest_file"] in prior


def test_plan_bounds_and_secret_extra_fields_rejected(capture):
    module, root = capture
    with pytest.raises(module.StockCaptureError):
        module.parse_stock_capture_plan(
            [{"tool": "get_scanner_filter_specs", "arguments": {}, "token": "secret"}]
        )
    request = module.StockCaptureRequest("get_scanner_filter_specs", {})
    with pytest.raises(module.StockCaptureError):
        run(module, root, [request] * 33)
    assert not list(root.iterdir())


def test_invalid_root_rejected_before_connection_construction(capture, monkeypatch):
    module, root = capture
    root.chmod(0o755)
    calls = []
    monkeypatch.setattr(module, "RobinhoodMcpSdkConnection", lambda **kw: calls.append(kw))
    with pytest.raises(module.StockCaptureError):
        module.run_stock_capture(
            oauth_store=root,
            plan=[{"tool": "get_scanner_filter_specs", "arguments": {}}],
            output_dir=root,
        )
    assert calls == []


def test_cancellation_keeps_explicit_partial_manifest(capture):
    module, root = capture

    class Cancel(Transport):
        async def call_tool(self, name, arguments):
            if self.calls:
                raise asyncio.CancelledError()
            return await super().call_tool(name, arguments)

    request = module.StockCaptureRequest("get_equity_fundamentals", {"symbols": ["ACME"]})
    with pytest.raises(asyncio.CancelledError):
        run(module, root, [request] * 2, Cancel())
    manifests = list(root.glob("*.stock-capture.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_bytes())
    assert manifest["status"] == "partial"
    assert manifest["failure_code"] == "research_capture_cancelled"
    assert manifest["successful_calls"] == 1
    assert manifest["attempted_calls"] == 2


def test_publication_sync_failure_removes_only_new_artifact(capture, monkeypatch):
    module, root = capture
    kept = root / "keep"
    kept.write_text("preserved")
    kept.chmod(0o600)
    real_fsync = module.os.fsync

    def fail_directory(fd):
        import stat

        if stat.S_ISDIR(module.os.fstat(fd).st_mode):
            raise OSError("secret-fsync-error")
        return real_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", fail_directory)
    request = module.StockCaptureRequest("get_equity_fundamentals", {"symbols": ["ACME"]})
    with pytest.raises(module.StockCaptureError) as error:
        run(module, root, [request])
    assert "secret" not in str(error.value)
    assert list(root.iterdir()) == [kept]


def test_reversed_clock_does_not_publish_success(capture):
    module, root = capture
    times = iter([NOW, NOW - timedelta(seconds=1)])
    request = module.StockCaptureRequest("get_equity_fundamentals", {"symbols": ["ACME"]})
    with pytest.raises(module.StockCaptureError):
        asyncio.run(
            module.capture_stock_observations(
                transport=Transport(),
                requests=[request],
                output_dir=root,
                clock=lambda: next(times),
                transport_authenticated=False,
            )
        )
    assert not list(root.iterdir())


def test_oversize_plan_rejected_before_read_or_connection(capture, monkeypatch):
    module, root = capture
    plan = root / "plan.json"
    plan.write_bytes(b" " * 131073)
    reads = []
    monkeypatch.setattr(module.os, "read", lambda *args: reads.append(args))
    with pytest.raises(module.StockCaptureError):
        module.read_stock_capture_plan(plan)
    assert reads == []


def test_cancellation_during_pacing_retains_manifest_without_next_call(capture):
    module, root = capture
    request = module.StockCaptureRequest("get_equity_fundamentals", {"symbols": ["ACME"]})
    transport = Transport()
    ticks = iter(NOW + timedelta(seconds=i) for i in range(10))

    async def cancel(seconds):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            module.capture_stock_observations(
                transport=transport,
                requests=[request] * 2,
                output_dir=root,
                clock=lambda: next(ticks),
                sleep=cancel,
                transport_authenticated=False,
            )
        )
    manifest = json.loads(next(root.glob("*.stock-capture.json")).read_bytes())
    assert manifest["failure_code"] == "research_capture_cancelled"
    assert len(transport.calls) == manifest["attempted_calls"] == 1


def test_retained_reader_rehashes_manifest_and_payload(capture):
    module, root = capture
    request = module.StockCaptureRequest("get_equity_fundamentals", {"symbols": ["ACME"]})
    report, _, _ = run(module, root, [request])
    reader = importlib.import_module("trading_bot.research.stock_archive")
    loaded = reader.read_stock_observations(root, report["manifest_file"])
    assert loaded[0]["tool"] == request.tool
    assert len(loaded[0]["observation_sha256"]) == 64
    file = next(root.glob("*.stock-observation.json"))
    file.write_bytes(file.read_bytes() + b" ")
    with pytest.raises(ValueError):
        reader.read_stock_observations(root, report["manifest_file"])


@pytest.mark.parametrize(
    "mutation",
    [
        "bool_count",
        "impossible_counts",
        "reversed_times",
        "future_start",
        "auth_mismatch",
        "wire_flag",
        "complete_failure",
    ],
)
def test_retained_reader_rejects_rehashed_incoherent_manifest(capture, mutation):
    module, root = capture
    reader = importlib.import_module("trading_bot.research.stock_archive")
    request = module.StockCaptureRequest("get_equity_fundamentals", {"symbols": ["ACME"]})
    report, _, _ = run(module, root, [request])
    manifest = json.loads((root / report["manifest_file"]).read_bytes())
    if mutation == "bool_count":
        manifest["successful_calls"] = True
    if mutation == "impossible_counts":
        manifest["attempted_calls"] = 0
    if mutation == "reversed_times":
        manifest["completed_at"] = NOW.replace(year=2000).isoformat()
    if mutation == "future_start":
        manifest["started_at"] = NOW.replace(year=2099).isoformat()
    if mutation == "auth_mismatch":
        manifest["transport_authenticated"] = True
    if mutation == "wire_flag":
        manifest["native_http_wire_receipt"] = True
    if mutation == "complete_failure":
        manifest["failure_code"] = "research_call_failed"
    body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    name = hashlib.sha256(body).hexdigest() + ".stock-capture.json"
    path = root / name
    path.write_bytes(body)
    path.chmod(0o600)
    with pytest.raises(ValueError):
        reader.read_stock_observations(root, name)
