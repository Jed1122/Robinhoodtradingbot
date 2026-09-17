"""Offline diagnostic scope tests; all values are invented, never provider evidence."""

import asyncio
import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from trading_bot.config import load_config
from trading_bot.diagnostics.alpaca_probe import (
    ProbeCredential,
    ProbeError,
    ProbeReceipt,
    decode_manifest,
    encode_manifest,
    manifest_sha256,
    prepare_probe,
)

ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 9, 17, 12, tzinfo=UTC)
END = datetime(2026, 9, 15, tzinfo=UTC)


@dataclass(frozen=True)
class FixedClock:
    value: datetime = NOW

    def now(self) -> datetime:
        return self.value


@pytest.fixture
def loaded():
    return load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/backtest.yaml",
        ROOT / "configs/safety-envelope.yaml",
        environ={},
    )


@pytest.fixture
def manifest(tmp_path, loaded):
    return prepare_probe(
        loaded,
        clock=FixedClock(),
        code_revision="a" * 40,
        requested_end=END,
        credential_file=tmp_path.resolve() / "absent/credentials.json",
        quarantine_root=tmp_path.resolve() / "absent/quarantine",
        repository_root=ROOT,
    )


def test_prepare_preserves_canonical_scope_without_opening_paths(manifest):
    bars, actions = manifest.requests
    assert bars.path == "/v2/stocks/bars"
    assert dict(bars.query) == {
        "symbols": "SPY,QQQ,IWM,DIA",
        "timeframe": "1Day",
        "start": "2016-09-17T00:00:00+00:00",
        "end": "2026-09-15T00:00:00+00:00",
        "adjustment": "raw",
        "asof": "-",
        "feed": "sip",
        "currency": "USD",
        "sort": "asc",
        "limit": "1",
    }
    assert actions.path == "/v1/corporate-actions"
    assert dict(actions.query) == {
        "symbols": "SPY,QQQ,IWM,DIA",
        "start": "2016-09-17",
        "end": "2026-09-15",
        "region": "us",
        "data_quality": "all",
        "sort": "asc",
        "limit": "1",
    }
    assert manifest.expires_at == datetime(2026, 9, 17, 12, 30, tzinfo=UTC)
    assert not manifest.credential_file.parent.exists()


def test_round_trip_binds_exact_manifest_bytes(manifest):
    encoded = encode_manifest(manifest)
    assert encode_manifest(decode_manifest(encoded)) == encoded
    assert manifest_sha256(manifest) == hashlib.sha256(encoded).hexdigest()
    assert json.loads(encoded)["schema_version"] == "alpaca-first-response-v1"
    assert manifest_sha256(replace(manifest, code_revision="b" * 40)) != manifest_sha256(manifest)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "future"),
        ("base_url", "https://invalid.test"),
        ("method", "POST"),
        ("code_revision", "A" * 40),
        ("code_revision", "a" * 39),
        ("config_hash", "b" * 63),
        ("config_hash", True),
        ("prepared_at", "2026-09-17T12:00:00"),
        ("expires_at", "2026-09-17T12:31:00+00:00"),
        ("prepared_at", "2026-09-17T12:00:00+01:00"),
        ("max_response_bytes", True),
        ("max_response_bytes", 1048577),
        ("max_response_bytes", -1),
        ("total_timeout_seconds", 61),
        ("total_timeout_seconds", 60.0),
        ("credential_file", "relative.json"),
        ("credential_file", "/tmp/../escape.json"),
        ("quarantine_root", "/"),
        ("repository_root", "relative"),
        ("requests", []),
    ],
)
def test_decode_rejects_scope_or_type_injection(manifest, field, value):
    wire = json.loads(encode_manifest(manifest))
    wire[field] = value
    with pytest.raises(ProbeError, match=r"^probe_manifest_invalid$"):
        decode_manifest(json.dumps(wire).encode())


@pytest.mark.parametrize(
    "key,value",
    [
        ("feed", "iex"),
        ("limit", "2"),
        ("adjustment", "all"),
        ("asof", "2020-01-01"),
        ("timeframe", "1Min"),
        ("currency", "EUR"),
        ("sort", "desc"),
        ("page_token", "synthetic-token"),
        ("symbols", "SPY,SPY"),
        ("symbols", "spy"),
        ("start", "2030-01-01T00:00:00+00:00"),
        ("end", "2026-09-17T12:00:00+00:00"),
    ],
)
def test_decode_rejects_changed_request_policy(manifest, key, value):
    wire = json.loads(encode_manifest(manifest))
    query = dict(wire["requests"][0]["query"])
    query[key] = value
    wire["requests"][0]["query"] = list(query.items())
    with pytest.raises(ProbeError):
        decode_manifest(json.dumps(wire).encode())


@pytest.mark.parametrize(
    "case",
    [
        "duplicate_path",
        "extra_request",
        "url_path",
        "duplicate_query",
        "action_date",
        "action_filter",
        "request_unknown_key",
    ],
)
def test_decode_rejects_request_array_inconsistency(manifest, case):
    wire = json.loads(encode_manifest(manifest))
    requests = wire["requests"]
    if case == "duplicate_path":
        requests[1] = requests[0]
    elif case == "extra_request":
        requests.append(requests[0])
    elif case == "url_path":
        requests[0]["path"] = "https://invalid.test/orders"
    elif case == "duplicate_query":
        requests[0]["query"].append(requests[0]["query"][0])
    elif case == "request_unknown_key":
        requests[0]["method"] = "POST"
    else:
        key, value = (
            ("start", "2017-01-01") if case == "action_date" else ("data_quality", "complete")
        )
        query = dict(requests[1]["query"])
        query[key] = value
        requests[1]["query"] = list(query.items())
    with pytest.raises(ProbeError):
        decode_manifest(json.dumps(wire).encode())


@pytest.mark.parametrize(
    "body",
    [
        b'{"a":1,"a":2}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b"[]",
        b"null",
        b"\xff",
        b"{",
        b" " * 16385,
        b'{"a":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}",
    ],
)
def test_untrusted_manifest_json_has_only_safe_errors(body):
    with pytest.raises(ProbeError) as caught:
        decode_manifest(body)
    assert caught.value.args == ("probe_manifest_invalid",)
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "end",
    [
        NOW,
        NOW - timedelta(hours=23),
        datetime(2026, 9, 15),
        END.replace(tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_prepare_rejects_recent_or_noncanonical_cutoff(loaded, tmp_path, end):
    with pytest.raises(ProbeError):
        prepare_probe(
            loaded,
            clock=FixedClock(),
            code_revision="a" * 40,
            requested_end=end,
            credential_file=tmp_path / "key.json",
            quarantine_root=tmp_path / "raw",
            repository_root=ROOT,
        )


def test_prepare_rejects_tampered_loaded_identity(loaded, tmp_path):
    with pytest.raises(ProbeError, match="probe_scope_mismatch"):
        prepare_probe(
            replace(loaded, canonical_json=b"{}"),
            clock=FixedClock(),
            code_revision="a" * 40,
            requested_end=END,
            credential_file=tmp_path / "key.json",
            quarantine_root=tmp_path / "raw",
            repository_root=ROOT,
        )


def test_error_and_credential_representations_do_not_echo_inputs():
    credential = ProbeCredential("synthetic-key-123456", "synthetic-secret-123456")
    assert "synthetic" not in repr(credential)
    assert str(ProbeError("unexpected synthetic-secret-123456")) == "probe_manifest_invalid"


@pytest.mark.parametrize(
    "changes",
    [
        {"body_sha256": "a" * 64},
        {"body_bytes": -1},
        {"request_index": True},
        {"status_code": 900},
        {"reason_code": "provider-secret"},
        {"completed_at": NOW - timedelta(seconds=1)},
    ],
)
def test_receipt_cannot_claim_data_or_carry_arbitrary_values(changes):
    values = dict(
        manifest_sha256="a" * 64,
        request_index=0,
        started_at=NOW,
        completed_at=NOW,
        status_code=403,
        body_sha256=None,
        body_bytes=0,
        reason_code="probe_access_denied",
    )
    values.update(changes)
    with pytest.raises(ProbeError):
        ProbeReceipt(**values)


@pytest.fixture
def capture_ready(manifest):
    manifest.credential_file.parent.mkdir(mode=0o700)
    manifest.quarantine_root.mkdir(mode=0o700)
    manifest.credential_file.write_text(
        json.dumps(
            {
                "key_id": "synthetic-key-123456",
                "secret_key": "synthetic-secret-123456",
            }
        )
    )
    manifest.credential_file.chmod(0o600)
    return manifest


async def run_capture(manifest, loaded, *, clock=None, approval=None, revision="a" * 40):
    from trading_bot.diagnostics.alpaca_probe import capture_probe

    return await capture_probe(
        manifest,
        approved_manifest_sha256=(manifest_sha256(manifest) if approval is None else approval),
        loaded=loaded,
        active_code_revision=revision,
        clock=clock or FixedClock(),
    )


async def test_capture_denies_wrong_scope_before_credentials_or_network(
    manifest, loaded, monkeypatch
):
    from trading_bot.diagnostics import alpaca_probe_io

    def forbidden(*args, **kwargs):
        raise AssertionError("credential/network side effect before approval")

    monkeypatch.setattr(alpaca_probe_io, "read_probe_credential", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    with pytest.raises(ProbeError, match="probe_scope_mismatch"):
        await run_capture(manifest, loaded, approval="0" * 64)


@pytest.mark.parametrize("case", ["revision", "config", "expired", "future", "root_missing"])
async def test_capture_preflight_has_no_egress(manifest, loaded, respx_mock, case):
    clock = FixedClock()
    revision = "a" * 40
    if case == "revision":
        revision = "b" * 40
    elif case == "config":
        loaded = replace(loaded, config_hash="0" * 64)
    elif case == "expired":
        clock = FixedClock(NOW + timedelta(minutes=30))
    elif case == "future":
        clock = FixedClock(NOW - timedelta(seconds=1))
    with pytest.raises(ProbeError):
        await run_capture(manifest, loaded, clock=clock, revision=revision)
    assert not respx_mock.calls


def mock_response(respx_mock, path, *, status=200, body=b'{"synthetic":true}', headers=None):
    return respx_mock.get("https://data.alpaca.markets" + path).mock(
        return_value=httpx.Response(
            status,
            content=body,
            headers=({"content-type": "application/json"} if headers is None else headers),
        )
    )


async def test_capture_is_two_gets_with_exact_scope_and_only_quarantined_bytes(
    capture_ready,
    loaded,
    respx_mock,
    caplog,
):
    bodies = [
        b'{"synthetic":{"value":1.2300},"next_page_token":"do-not-follow"}',
        b'{"synthetic":[],"next_page_token":"do-not-follow"}',
    ]
    for request, body in zip(capture_ready.requests, bodies, strict=True):
        mock_response(respx_mock, request.path, body=body)
    receipts = await run_capture(capture_ready, loaded)
    assert len(respx_mock.calls) == len(receipts) == 2
    for index, (call, receipt, body) in enumerate(
        zip(respx_mock.calls, receipts, bodies, strict=True)
    ):
        assert call.request.method == "GET"
        assert dict(call.request.url.params) == dict(capture_ready.requests[index].query)
        assert call.request.headers["Accept-Encoding"] == "identity"
        assert receipt.body_sha256 == hashlib.sha256(body).hexdigest()
        assert (capture_ready.quarantine_root / (receipt.body_sha256 + ".raw")).read_bytes() == body
        assert receipt.reason_code == "probe_sample_retained"
    assert "synthetic-secret" not in caplog.text
    assert "do-not-follow" not in caplog.text
    assert len(list(capture_ready.quarantine_root.glob("*.receipt.json"))) == 2


@pytest.mark.parametrize(
    "status,code",
    [
        (301, "probe_http_failed"),
        (400, "probe_http_failed"),
        (401, "probe_access_denied"),
        (403, "probe_access_denied"),
        (429, "probe_rate_limited"),
        (500, "probe_http_failed"),
    ],
)
async def test_http_denial_never_retries_follows_or_retains_error_body(
    capture_ready,
    loaded,
    respx_mock,
    status,
    code,
    caplog,
):
    mock_response(
        respx_mock,
        capture_ready.requests[0].path,
        status=status,
        body=b"synthetic-secret-123456",
        headers={"location": "https://invalid.test/orders"},
    )
    with pytest.raises(ProbeError, match=code) as caught:
        await run_capture(capture_ready, loaded)
    assert caught.value.__context__ is None
    assert len(respx_mock.calls) == 1
    assert not list(capture_ready.quarantine_root.glob("*.raw"))
    assert "synthetic-secret" not in caplog.text
    receipt = json.loads(next(capture_ready.quarantine_root.glob("*.receipt.json")).read_bytes())
    assert receipt["status_code"] == status
    assert receipt["reason_code"] == code


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b"null",
        b"{",
        b'{"v":NaN}',
        b'{"v":1,"v":2}',
        b"\xff",
        b'{"v":"synthetic-secret-123456"}',
        b'{"v":"synthetic-key-123456"}',
        b'{"APCA-API-KEY-ID":"something"}',
        b'{"v":"synthetic-secret-12345\\u0036"}',
        b'{"x":' + b"[" * 70 + b"1" + b"]" * 70 + b"}",
    ],
)
async def test_unsafe_success_body_is_not_retained(capture_ready, loaded, respx_mock, body):
    mock_response(respx_mock, capture_ready.requests[0].path, body=body)
    with pytest.raises(ProbeError):
        await run_capture(capture_ready, loaded)
    assert len(respx_mock.calls) == 1
    assert not list(capture_ready.quarantine_root.glob("*.raw"))


@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "text/html"},
        {"content-type": "application/json", "content-encoding": "gzip"},
        {"content-type": "application/json", "content-length": "1048577"},
    ],
)
async def test_response_headers_cannot_bypass_body_contract(
    capture_ready,
    loaded,
    respx_mock,
    headers,
):
    # Stream avoids HTTPX eagerly decompressing the deliberately invalid synthetic encoding.
    respx_mock.get("https://data.alpaca.markets/v2/stocks/bars").mock(
        return_value=httpx.Response(200, stream=httpx.ByteStream(b"{}"), headers=headers)
    )
    with pytest.raises(ProbeError):
        await run_capture(capture_ready, loaded)
    assert not list(capture_ready.quarantine_root.glob("*.raw"))


async def test_stream_byte_count_enforces_limit_without_content_length(
    capture_ready,
    loaded,
    respx_mock,
):
    respx_mock.get("https://data.alpaca.markets/v2/stocks/bars").mock(
        return_value=httpx.Response(
            200,
            stream=httpx.ByteStream(b" " * 1048577),
            headers={"content-type": "application/json"},
        )
    )
    with pytest.raises(ProbeError, match="probe_response_too_large"):
        await run_capture(capture_ready, loaded)
    assert len(respx_mock.calls) == 1
    assert not list(capture_ready.quarantine_root.glob("*.raw"))


async def test_transport_timeout_is_sanitized_without_retry(capture_ready, loaded, respx_mock):
    respx_mock.get("https://data.alpaca.markets/v2/stocks/bars").mock(
        side_effect=httpx.ReadTimeout("synthetic-secret-123456")
    )
    with pytest.raises(ProbeError, match="probe_timeout") as caught:
        await run_capture(capture_ready, loaded)
    assert caught.value.__context__ is None
    assert len(respx_mock.calls) == 1


async def test_second_failure_preserves_first_sample_as_incomplete(
    capture_ready, loaded, respx_mock
):
    mock_response(respx_mock, capture_ready.requests[0].path)
    mock_response(respx_mock, capture_ready.requests[1].path, status=403)
    with pytest.raises(ProbeError, match="probe_access_denied"):
        await run_capture(capture_ready, loaded)
    assert len(respx_mock.calls) == 2
    assert len(list(capture_ready.quarantine_root.glob("*.raw"))) == 1
    assert len(list(capture_ready.quarantine_root.glob("*.receipt.json"))) == 2


@pytest.mark.parametrize("after", [NOW - timedelta(seconds=1), NOW + timedelta(minutes=30)])
async def test_bad_collection_clock_never_publishes_sample(
    capture_ready,
    loaded,
    respx_mock,
    after,
):
    class MovingClock:
        value = NOW

        def now(self):
            return self.value

    clock = MovingClock()

    def response(request):
        clock.value = after
        return httpx.Response(200, content=b"{}", headers={"content-type": "application/json"})

    respx_mock.get("https://data.alpaca.markets/v2/stocks/bars").mock(side_effect=response)
    with pytest.raises(ProbeError, match="probe_expired"):
        await run_capture(capture_ready, loaded, clock=clock)
    assert len(respx_mock.calls) == 1
    assert not list(capture_ready.quarantine_root.glob("*.raw"))


async def test_total_deadline_stops_even_a_nonresponsive_body(
    capture_ready,
    loaded,
    respx_mock,
    monkeypatch,
):
    from trading_bot.diagnostics import alpaca_probe

    original_timeout = asyncio.timeout
    requested_deadlines = []

    def fast_timeout(seconds):
        requested_deadlines.append(seconds)
        return original_timeout(0.1)

    class StalledStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.Event().wait()
            yield b"{}"

    monkeypatch.setattr(alpaca_probe.asyncio, "timeout", fast_timeout)
    respx_mock.get("https://data.alpaca.markets/v2/stocks/bars").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "application/json"}, stream=StalledStream()
        )
    )
    with pytest.raises(ProbeError, match="probe_timeout"):
        await run_capture(capture_ready, loaded)
    assert requested_deadlines == [60]
    assert len(respx_mock.calls) <= 1
    assert not list(capture_ready.quarantine_root.glob("*.raw"))


async def test_receipt_write_failure_does_not_continue_or_claim_success(
    capture_ready,
    loaded,
    respx_mock,
    monkeypatch,
):
    from trading_bot.diagnostics import alpaca_probe_io

    def failed_receipt(*args, **kwargs):
        raise ProbeError("probe_storage_failed")

    monkeypatch.setattr(alpaca_probe_io, "publish_probe_receipt", failed_receipt)
    mock_response(respx_mock, capture_ready.requests[0].path)
    with pytest.raises(ProbeError, match="probe_storage_failed"):
        await run_capture(capture_ready, loaded)
    assert len(respx_mock.calls) == 1
    assert len(list(capture_ready.quarantine_root.glob("*.raw"))) == 1
    assert not list(capture_ready.quarantine_root.glob("*.receipt.json"))


@pytest.mark.parametrize(
    "body", [b'{"value":1e9999999999999999999}', b'{"value":-1e9999999999999999999}']
)
def test_unrepresentable_numeric_json_is_sanitized(body):
    with pytest.raises(ProbeError, match="probe_manifest_invalid") as caught:
        decode_manifest(body)
    assert caught.value.__context__ is None


async def test_approved_manifest_cannot_be_replayed(capture_ready, loaded, respx_mock):
    for request in capture_ready.requests:
        mock_response(respx_mock, request.path)
    await run_capture(capture_ready, loaded)
    with pytest.raises(ProbeError, match="probe_scope_mismatch"):
        await run_capture(capture_ready, loaded)
    assert len(respx_mock.calls) == 2


async def test_denied_attempt_cannot_be_retried_with_same_manifest(
    capture_ready, loaded, respx_mock
):
    mock_response(respx_mock, capture_ready.requests[0].path, status=403)
    for _ in range(2):
        with pytest.raises(ProbeError):
            await run_capture(capture_ready, loaded)
    assert len(respx_mock.calls) == 1
