"""Invented keys and offline HTTP fixtures; never contact Databento."""

import base64
import gzip
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from trading_bot.diagnostics.databento_preflight import (
    CostRequest,
    DatabentoCredential,
    DatabentoPreflightError,
    estimate_cost,
)

KEY = "db-" + "a" * 29
NOW = datetime(2026, 9, 18, tzinfo=UTC)


class Clock:
    def now(self):
        return NOW


@pytest.fixture
def request_scope():
    return CostRequest(("SPY",), "cbbo-1m", date(2025, 1, 2), date(2025, 1, 3))


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    import socket

    def denied(*args, **kwargs):
        raise AssertionError("network forbidden")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.mark.parametrize("value", ["", "db-short", "db-" + "a" * 30, KEY + "\n", None, 123])
def test_bad_key_never_appears_in_error(value):
    with pytest.raises(DatabentoPreflightError, match=r"^credential_invalid$") as error:
        DatabentoCredential(value)
    assert error.value.__context__ is None


def test_key_repr_does_not_expose_value():
    credential = DatabentoCredential(KEY)
    assert KEY not in repr(credential)


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbols", ()),
        ("symbols", ("SPY", "SPY")),
        ("symbols", ("ALL_SYMBOLS",)),
        ("symbols", ("SPY&schema=mbo",)),
        ("symbols", ["SPY"]),
        ("schema", "orders"),
        ("start", "2025-01-02"),
        ("start", datetime(2025, 1, 2, tzinfo=UTC)),
        ("end", date(2025, 1, 2)),
    ],
)
def test_cost_scope_cannot_expand_to_all_symbols_or_other_operations(request_scope, field, value):
    with pytest.raises(DatabentoPreflightError, match="scope_invalid"):
        replace(request_scope, **{field: value})


def wire_transport(monkeypatch, handler):
    from trading_bot.diagnostics import databento_preflight as module

    def make_transport(**kwargs):
        assert kwargs == {"verify": True, "trust_env": False, "retries": 0}
        return httpx.MockTransport(handler)

    monkeypatch.setattr(module.httpx, "AsyncHTTPTransport", make_transport)


async def test_only_exact_free_cost_endpoint_can_be_called(monkeypatch, request_scope):
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        assert str(request.url.copy_with(query=None)) == (
            "https://hist.databento.com/v0/metadata.get_cost"
        )
        assert dict(request.url.params) == {
            "dataset": "OPRA.PILLAR",
            "symbols": "SPY.OPT",
            "schema": "cbbo-1m",
            "stype_in": "parent",
            "start": "2025-01-02T00:00:00+00:00",
            "end": "2025-01-03T00:00:00+00:00",
        }
        assert request.headers["authorization"] == (
            "Basic " + base64.b64encode((KEY + ":").encode()).decode()
        )
        return httpx.Response(
            200, content=b"0.1234567890123456789", headers={"content-type": "application/json"}
        )

    wire_transport(monkeypatch, respond)
    result = await estimate_cost(
        request_scope, DatabentoCredential(KEY), clock=Clock(), allow_metadata_network=True
    )
    assert result.cost_usd == Decimal("0.1234567890123456789")
    assert result.quoted_at == NOW
    assert result.download_authorized is False
    assert result.economic_evidence is False
    assert len(requests) == 1


@pytest.mark.parametrize("approved", [False, 1, "yes", None])
async def test_network_requires_exact_explicit_opt_in(request_scope, approved):
    with pytest.raises(DatabentoPreflightError, match="metadata_network_not_authorized"):
        await estimate_cost(
            request_scope,
            DatabentoCredential(KEY),
            clock=Clock(),
            allow_metadata_network=approved,
        )


@pytest.mark.parametrize(
    "status,body,headers,reason",
    [
        (401, KEY.encode(), {}, "access_denied"),
        (403, b"denied", {}, "access_denied"),
        (429, b"rate limited", {}, "rate_limited"),
        (500, KEY.encode(), {}, "http_failed"),
        (302, b"", {"location": "https://example.invalid/leak"}, "http_failed"),
        (200, b"true", {}, "response_invalid"),
        (200, b"null", {}, "response_invalid"),
        (200, b"NaN", {}, "response_invalid"),
        (200, b"1e9999", {}, "response_invalid"),
        (200, b"-1", {}, "response_invalid"),
        (200, b'"0.1"', {}, "response_invalid"),
        (200, b'{"cost": 0.1}', {}, "response_invalid"),
        (200, KEY.encode(), {}, "response_invalid"),
        (200, b"0" * 513, {}, "response_invalid"),
        (200, b"0.1", {"content-type": "text/html"}, "response_invalid"),
        (200, b"0.1", {"content-encoding": "gzip"}, "response_invalid"),
    ],
)
async def test_failure_has_no_retry_redirect_or_secret_echo(
    monkeypatch, request_scope, status, body, headers, reason
):
    requests = []

    def respond(request):
        requests.append(request)
        wire = gzip.compress(body) if headers.get("content-encoding") == "gzip" else body
        return httpx.Response(
            status, content=wire, headers={"content-type": "application/json", **headers}
        )

    wire_transport(monkeypatch, respond)
    with pytest.raises(DatabentoPreflightError, match="^" + reason + "$") as error:
        await estimate_cost(
            request_scope, DatabentoCredential(KEY), clock=Clock(), allow_metadata_network=True
        )
    assert len(requests) == 1
    assert KEY not in str(error.value)
    assert error.value.__context__ is None


async def test_transport_exception_is_sanitized(monkeypatch, request_scope):
    def respond(request):
        raise httpx.ConnectError(KEY)

    wire_transport(monkeypatch, respond)
    with pytest.raises(DatabentoPreflightError, match=r"^http_failed$") as error:
        await estimate_cost(
            request_scope, DatabentoCredential(KEY), clock=Clock(), allow_metadata_network=True
        )
    assert error.value.__context__ is None


async def test_future_date_refused_before_network(request_scope):
    with pytest.raises(DatabentoPreflightError, match="scope_invalid"):
        await estimate_cost(
            replace(request_scope, end=date(2027, 1, 1)),
            DatabentoCredential(KEY),
            clock=Clock(),
            allow_metadata_network=True,
        )


def test_raw_symbol_is_preserved_and_parent_default_is_unchanged(request_scope):
    raw = replace(request_scope, symbols=("SPY   250117C00500000",), stype_in="raw_symbol")
    assert raw.query() == {
        "dataset": "OPRA.PILLAR",
        "symbols": "SPY   250117C00500000",
        "schema": "cbbo-1m",
        "stype_in": "raw_symbol",
        "start": "2025-01-02T00:00:00+00:00",
        "end": "2025-01-03T00:00:00+00:00",
    }
    assert request_scope.query()["symbols"] == "SPY.OPT"
    assert request_scope.query()["stype_in"] == "parent"


@pytest.mark.parametrize(
    "symbol",
    [
        "SPY",
        "SPY.OPT",
        "ALL_SYMBOLS",
        "SPY   250117C00500000,SPY",
        "SPY   250117C00500000\n",
        "SPY   250230C00500000",
        "SPY   250117C00000000",
        "SPY   \uff12\uff15\uff10\uff11\uff11\uff17C00500000",
        "SPY\u00a0  250117C00500000",
        "QQQ   250117C00500000",
        "SPY1  250117C00500000",
        "SPY   250117c00500000",
        None,
    ],
)
def test_invalid_raw_symbols_are_denied(request_scope, symbol):
    with pytest.raises(DatabentoPreflightError, match=r"^scope_invalid$"):
        replace(request_scope, symbols=(symbol,), stype_in="raw_symbol")


def test_raw_list_boundaries_and_other_modes_are_denied(request_scope):
    symbols = tuple(f"SPY   250117C{strike:08d}" for strike in range(1, 102))
    assert len(replace(request_scope, symbols=symbols[:100], stype_in="raw_symbol").symbols) == 100
    for values in ((), symbols, (symbols[0], symbols[0]), (symbols[0], "SPY")):
        with pytest.raises(DatabentoPreflightError, match=r"^scope_invalid$"):
            replace(request_scope, symbols=values, stype_in="raw_symbol")
    raw = replace(request_scope, symbols=symbols[:1], stype_in="raw_symbol")
    for change in ({"schema": "definition"}, {"stype_in": "instrument_id"}, {"stype_in": None}):
        with pytest.raises(DatabentoPreflightError, match=r"^scope_invalid$"):
            replace(raw, **change)


def test_calendar_validation_accepts_leap_day_and_keeps_parent_limit(request_scope):
    raw = replace(request_scope, symbols=("SPY   240229C00500000",), stype_in="raw_symbol")
    assert raw.query()["symbols"] == "SPY   240229C00500000"
    with pytest.raises(DatabentoPreflightError, match=r"^scope_invalid$"):
        replace(request_scope, symbols=("SPY", "QQQ", "IWM", "DIA", "XLF"))


@pytest.mark.parametrize("status", [200, 302])
async def test_raw_mode_keeps_fixed_cost_endpoint_and_no_redirect(
    monkeypatch, request_scope, status
):
    scope = replace(request_scope, symbols=("SPY   250117P00500000",), stype_in="raw_symbol")
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == "GET"
        assert str(request.url.copy_with(query=None)) == (
            "https://hist.databento.com/v0/metadata.get_cost"
        )
        assert dict(request.url.params) == {
            "dataset": "OPRA.PILLAR",
            "symbols": "SPY   250117P00500000",
            "schema": "cbbo-1m",
            "stype_in": "raw_symbol",
            "start": "2025-01-02T00:00:00+00:00",
            "end": "2025-01-03T00:00:00+00:00",
        }
        return httpx.Response(
            status,
            content=b"0.125",
            headers={
                "content-type": "application/json",
                "location": "https://example.invalid/denied",
            },
        )

    wire_transport(monkeypatch, respond)
    if status == 200:
        result = await estimate_cost(
            scope, DatabentoCredential(KEY), clock=Clock(), allow_metadata_network=True
        )
        assert result.cost_usd == Decimal("0.125")
        assert result.download_authorized is False
        assert result.economic_evidence is False
    else:
        with pytest.raises(DatabentoPreflightError, match=r"^http_failed$"):
            await estimate_cost(
                scope, DatabentoCredential(KEY), clock=Clock(), allow_metadata_network=True
            )
    assert len(calls) == 1
