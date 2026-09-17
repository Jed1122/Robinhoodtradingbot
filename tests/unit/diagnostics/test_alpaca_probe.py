"""Offline diagnostic scope tests; all values are invented, never provider evidence."""

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

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
