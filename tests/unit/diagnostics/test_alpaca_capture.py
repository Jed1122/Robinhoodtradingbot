"""Credential-free capture tests; provider responses and secrets are invented."""

import gzip
import hashlib
import importlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from trading_bot.config import load_config
from trading_bot.market_data.alpaca_native import AlpacaStockRequest, parse_timestamp_ns

ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def api():
    try:
        return importlib.import_module("trading_bot.diagnostics.alpaca_capture")
    except ModuleNotFoundError:
        pytest.fail("bounded native Alpaca capture is not implemented")


@dataclass(frozen=True)
class FixedClock:
    value: datetime = NOW

    def now(self):
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
    return api().prepare_capture(
        loaded,
        clock=FixedClock(),
        code_revision="a" * 40,
        request=AlpacaStockRequest(
            "bars",
            parse_timestamp_ns("2016-01-01T00:00:00Z"),
            parse_timestamp_ns("2026-01-01T00:00:00Z"),
        ),
        credential_file=tmp_path.resolve() / "credentials/key.json",
        quarantine_root=tmp_path.resolve() / "capture",
        repository_root=ROOT,
        max_pages=3,
    )


@pytest.fixture
def ready(manifest):
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


def body(day="2016-01-04", token=None):
    return json.dumps(
        {
            "symbol": "SPY",
            "bars": [
                {
                    "t": day + "T05:00:00Z",
                    "o": 200,
                    "h": 202,
                    "l": 199,
                    "c": 201,
                    "v": 1000,
                    "n": 10,
                    "vw": 200.1234,
                }
            ],
            "next_page_token": token,
        },
        separators=(",", ":"),
    ).encode()


def response(raw, status=200, headers=None):
    return httpx.Response(
        status,
        content=raw,
        headers={
            "content-type": "application/json",
            **(headers or {}),
        },
    )


async def run(manifest, loaded, **changes):
    kwargs = dict(
        approved_manifest_sha256=api().capture_manifest_sha256(manifest),
        loaded=loaded,
        active_code_revision="a" * 40,
        clock=FixedClock(),
    )
    return await api().capture_native(manifest, **(kwargs | changes))


def receipts(manifest):
    return sorted(
        (
            json.loads(p.read_bytes())
            for p in manifest.quarantine_root.glob("*.capture-receipt.json")
        ),
        key=lambda value: value["page_index"],
    )


def test_scope_is_separate_from_old_probe_and_round_trips_without_io(manifest):
    raw = api().encode_capture_manifest(manifest)
    assert api().encode_capture_manifest(api().decode_capture_manifest(raw)) == raw
    assert json.loads(raw)["schema"] == "alpaca-native-capture-v1"
    assert not manifest.credential_file.parent.exists()
    assert manifest.expires_at == NOW + timedelta(minutes=30)
    assert api().capture_manifest_sha256(manifest) == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    "change",
    [
        {"max_pages": 0},
        {"max_pages": 129},
        {"max_pages": True},
        {"repository_root": Path("relative")},
        {"quarantine_root": ROOT / "data"},
        {"credential_file": ROOT / "key.json"},
        {"code_revision": "A" * 40},
        {"expires_at": NOW + timedelta(hours=1)},
    ],
)
def test_scope_rejects_unsafe_or_unbounded_values(manifest, change):
    with pytest.raises(ValueError):
        replace(manifest, **change)


@pytest.mark.parametrize(
    "field,value",
    [
        ("base_url", "https://invalid.test"),
        ("method", "POST"),
        ("schema", "alpaca-first-response-v1"),
        ("max_pages", 1.0),
    ],
)
def test_wire_scope_cannot_inject_transport_or_old_approval(manifest, field, value):
    wire = json.loads(api().encode_capture_manifest(manifest))
    wire[field] = value
    with pytest.raises(ValueError):
        api().decode_capture_manifest(json.dumps(wire).encode())


async def test_preflight_denies_before_secret_read_or_egress(
    manifest, loaded, monkeypatch, respx_mock
):
    def forbidden(*args, **kwargs):
        pytest.fail("preflight reached credentials or network")

    monkeypatch.setattr(api(), "read_probe_credential", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    with pytest.raises(ValueError, match="capture_scope_mismatch"):
        await run(manifest, loaded, approved_manifest_sha256="b" * 64)
    with pytest.raises(ValueError, match="capture_scope_mismatch"):
        await run(manifest, loaded, active_code_revision="b" * 40)
    with pytest.raises(ValueError, match="capture_expired"):
        await run(manifest, loaded, clock=FixedClock(NOW + timedelta(minutes=31)))
    assert not respx_mock.calls


async def test_native_pages_have_exact_bytes_receipt_chain_and_no_qualification(
    ready, loaded, respx_mock, caplog
):
    raw = (body(token="opaque+/="), body("2016-01-05"))
    respx_mock.get("https://data.alpaca.markets/v2/stocks/SPY/bars").mock(
        side_effect=[response(item) for item in raw]
    )
    result = await run(ready, loaded)
    assert result.pagination_complete and result.record_count == 2
    assert result.source_qualified is False and result.evidence_promotable is False
    assert len(respx_mock.calls) == 2
    assert all(c.request.method == "GET" for c in respx_mock.calls)
    assert "page_token" not in respx_mock.calls[0].request.url.params
    query = dict(respx_mock.calls[1].request.url.params)
    assert query["page_token"] == "opaque+/=" and query["feed"] == "sip"
    assert query["adjustment"] == "raw" and query["asof"] == "-"
    stored = receipts(ready)
    assert len(stored) == 2
    assert stored[0]["previous_receipt_sha256"] is None
    assert stored[1]["previous_receipt_sha256"] == result.receipt_sha256s[0]
    for index, payload in enumerate(raw):
        digest = hashlib.sha256(payload).hexdigest()
        assert stored[index]["body_sha256"] == digest
        assert stored[index]["body_bytes"] == len(payload)
        assert (ready.quarantine_root / (digest + ".raw")).read_bytes() == payload
        assert stored[index]["reason"] == "page_retained"
        assert stored[index]["request_sha256"] == ready.request.request_hash
    assert "synthetic-secret" not in caplog.text and "opaque" not in caplog.text


@pytest.mark.parametrize(
    "status,reason",
    [
        (301, "capture_http_failed"),
        (401, "capture_access_denied"),
        (403, "capture_access_denied"),
        (429, "capture_rate_limited"),
        (500, "capture_http_failed"),
    ],
)
async def test_failure_has_sanitized_receipt_no_error_body_no_retry(
    ready, loaded, respx_mock, caplog, status, reason
):
    respx_mock.get("https://data.alpaca.markets/v2/stocks/SPY/bars").mock(
        return_value=response(
            b"synthetic-secret-123456", status, {"location": "https://invalid.test/orders"}
        )
    )
    result = await run(ready, loaded)
    assert result.reason == reason and not result.pagination_complete
    assert len(respx_mock.calls) == 1
    assert not list(ready.quarantine_root.glob("*.raw"))
    assert receipts(ready)[0]["body_sha256"] is None
    assert receipts(ready)[0]["status_code"] == status
    assert "synthetic-secret" not in caplog.text


@pytest.mark.parametrize(
    "raw",
    [
        b'{"message":"synthetic-secret-123456"}',
        b'{"message":"synthetic-secret-12345\\u0036"}',
        b'{"APCA-API-KEY-ID":"echo"}',
    ],
)
async def test_secret_echo_is_never_archived(ready, loaded, respx_mock, raw):
    respx_mock.get("https://data.alpaca.markets/v2/stocks/SPY/bars").mock(
        return_value=response(raw)
    )
    result = await run(ready, loaded)
    assert result.reason == "capture_secret_echo"
    assert not list(ready.quarantine_root.glob("*.raw"))


async def test_native_schema_change_is_quarantined_but_stops_next_page(ready, loaded, respx_mock):
    raw = body(token="next").replace(b'"symbol":"SPY"', b'"symbol":"SPY","new":1')
    respx_mock.get("https://data.alpaca.markets/v2/stocks/SPY/bars").mock(
        return_value=response(raw)
    )
    result = await run(ready, loaded)
    assert result.reason == "capture_native_invalid" and not result.pagination_complete
    assert len(respx_mock.calls) == 1
    assert len(list(ready.quarantine_root.glob("*.raw"))) == 1


async def test_partial_limit_is_not_complete_and_cannot_replay_attempt(ready, loaded, respx_mock):
    ready = replace(ready, max_pages=1)
    respx_mock.get("https://data.alpaca.markets/v2/stocks/SPY/bars").mock(
        return_value=response(body(token="next"))
    )
    result = await run(ready, loaded)
    assert result.reason == "capture_page_limit" and not result.pagination_complete
    with pytest.raises(ValueError, match="capture_scope_mismatch"):
        await run(ready, loaded)
    assert len(respx_mock.calls) == 1


async def test_repeated_cursor_denies_and_preserves_partial_receipts(ready, loaded, respx_mock):
    respx_mock.get("https://data.alpaca.markets/v2/stocks/SPY/bars").mock(
        side_effect=[response(body(token="again")), response(body("2016-01-05", token="again"))]
    )
    result = await run(ready, loaded)
    assert result.reason == "capture_native_invalid" and not result.pagination_complete
    assert len(respx_mock.calls) == 2 and len(receipts(ready)) == 2


async def test_timeout_keeps_claim_and_never_leaks_exception(ready, loaded, respx_mock):
    respx_mock.get("https://data.alpaca.markets/v2/stocks/SPY/bars").mock(
        side_effect=httpx.ReadTimeout("synthetic-secret-123456")
    )
    result = await run(ready, loaded)
    assert result.reason == "capture_timeout"
    assert len(respx_mock.calls) == 1
    assert len(list(ready.quarantine_root.glob("*.attempt"))) == 1


async def test_byte_budget_rejects_even_without_content_length(ready, loaded, respx_mock):
    respx_mock.get("https://data.alpaca.markets/v2/stocks/SPY/bars").mock(
        return_value=httpx.Response(
            200,
            stream=httpx.ByteStream(b" " * 1048577),
            headers={"content-type": "application/json"},
        )
    )
    result = await run(ready, loaded)
    assert result.reason == "capture_response_too_large"
    assert not list(ready.quarantine_root.glob("*.raw"))


async def test_receipt_failure_stops_egress_and_attempt_remains(
    ready, loaded, respx_mock, monkeypatch
):
    def failed(*args, **kwargs):
        raise OSError("synthetic-secret-123456")

    monkeypatch.setattr(api(), "_publish_receipt", failed)
    respx_mock.get("https://data.alpaca.markets/v2/stocks/SPY/bars").mock(
        return_value=response(body(token="next"))
    )
    with pytest.raises(ValueError, match="capture_storage_failed") as caught:
        await run(ready, loaded)
    assert caught.value.__context__ is None
    assert len(respx_mock.calls) == 1
    assert len(list(ready.quarantine_root.glob("*.attempt"))) == 1


async def test_tls_proxy_redirect_and_retry_policy_is_not_environment_controlled(
    ready,
    loaded,
    respx_mock,
    monkeypatch,
):
    original_transport, original_client = httpx.AsyncHTTPTransport, httpx.AsyncClient
    transport_args, client_args = [], []

    def transport(**kwargs):
        transport_args.append(kwargs)
        return original_transport(**kwargs)

    def client(**kwargs):
        client_args.append(kwargs)
        return original_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", transport)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setenv("HTTPS_PROXY", "https://invalid.test")
    respx_mock.get("https://data.alpaca.markets/v2/stocks/SPY/bars").mock(
        return_value=response(body())
    )
    result = await run(ready, loaded)
    assert result.pagination_complete
    assert transport_args == [{"verify": True, "trust_env": False, "retries": 0}]
    assert client_args[0]["verify"] is True and client_args[0]["trust_env"] is False
    assert client_args[0]["follow_redirects"] is False and client_args[0]["timeout"] == 10


@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "text/html"},
        {"content-encoding": "gzip"},
        {"content-length": "-1"},
        {"content-length": "3"},
    ],
)
async def test_invalid_response_metadata_cannot_complete(ready, loaded, respx_mock, headers):
    respx_mock.get("https://data.alpaca.markets/v2/stocks/SPY/bars").mock(
        return_value=httpx.Response(
            200,
            stream=httpx.ByteStream(
                gzip.compress(body()) if "content-encoding" in headers else body()
            ),
            headers={"content-type": "application/json", **headers},
        )
    )
    result = await run(ready, loaded)
    assert result.reason == "capture_response_invalid"
    assert not result.pagination_complete and not list(ready.quarantine_root.glob("*.raw"))


async def test_quote_capture_preserves_url_like_cursor_as_opaque_query_only(
    ready, loaded, respx_mock
):
    ready = replace(
        ready,
        request=AlpacaStockRequest(
            "quotes",
            parse_timestamp_ns("2016-01-04T14:30:00Z"),
            parse_timestamp_ns("2016-01-04T14:30:01Z"),
        ),
    )
    cursor = "https://invalid.test/orders?account=none&method=POST"
    quote = {
        "t": "2016-01-04T14:30:00.000000001Z",
        "bp": 200.0001,
        "ap": 200.0002,
        "bs": 1,
        "as": 1,
        "bx": "P",
        "ax": "P",
        "c": ["R"],
        "z": "B",
    }
    raw = [
        json.dumps({"symbol": "SPY", "quotes": [quote], "next_page_token": token}).encode()
        for token in (cursor, None)
    ]
    respx_mock.get("https://data.alpaca.markets/v2/stocks/SPY/quotes").mock(
        side_effect=[response(item) for item in raw]
    )
    result = await run(ready, loaded)
    assert result.pagination_complete and result.record_count == 2
    assert respx_mock.calls[1].request.url.host == "data.alpaca.markets"
    assert respx_mock.calls[1].request.url.params["page_token"] == cursor
    assert all(cursor not in json.dumps(item) for item in receipts(ready))


async def test_clock_regression_discards_response_and_never_fetches_continuation(
    ready, loaded, respx_mock
):
    class RegressingClock:
        def __init__(self):
            self.times = iter((NOW, NOW, NOW - timedelta(seconds=1)))

        def now(self):
            return next(self.times)

    respx_mock.get("https://data.alpaca.markets/v2/stocks/SPY/bars").mock(
        return_value=response(body(token="next"))
    )
    result = await run(ready, loaded, clock=RegressingClock())
    assert result.reason == "capture_expired" and not result.pagination_complete
    assert len(respx_mock.calls) == 1 and not list(ready.quarantine_root.glob("*.raw"))


async def test_missing_credential_retains_claim_but_makes_no_network_call(
    manifest, loaded, respx_mock
):
    manifest.quarantine_root.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="capture_credential_invalid"):
        await run(manifest, loaded)
    assert not respx_mock.calls
    assert len(list(manifest.quarantine_root.glob("*.attempt"))) == 1


async def test_preflight_clock_observation_cannot_be_discarded_before_first_page(
    ready,
    loaded,
    respx_mock,
):
    class RegressingClock:
        def __init__(self):
            self.times = iter(
                (
                    NOW + timedelta(minutes=20),
                    NOW + timedelta(minutes=1),
                    NOW + timedelta(minutes=1),
                )
            )

        def now(self):
            return next(self.times)

    respx_mock.get("https://data.alpaca.markets/v2/stocks/SPY/bars").mock(
        return_value=response(body())
    )
    with pytest.raises(ValueError, match="capture_expired"):
        await run(ready, loaded, clock=RegressingClock())
    assert not respx_mock.calls
    assert not list(ready.quarantine_root.glob("*.raw"))
