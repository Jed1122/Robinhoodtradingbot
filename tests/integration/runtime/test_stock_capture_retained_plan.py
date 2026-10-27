"""Bounded fictional retained plans preserve partial intent without fabricating calls."""

import hashlib
import json

import pytest

from tests.integration.runtime.test_stock_capture import Transport, run
from trading_bot.runtime import stock_capture as capture
from trading_bot.runtime.stock_archive import read_stock_observations


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "private"
    path.mkdir(mode=0o700)
    return path


def requests():
    return [
        capture.StockCaptureRequest("get_equity_fundamentals", {"symbols": [s]})
        for s in ("ALFA", "BETA")
    ]


def publish(root, manifest):
    body = capture._json(manifest)
    name = hashlib.sha256(body).hexdigest() + ".stock-capture.json"
    path = root / name
    path.write_bytes(body)
    path.chmod(0o600)
    return name


def test_default_manifest_bytes_remain_literal_v1(root):
    req = capture.StockCaptureRequest("get_equity_fundamentals", {"symbols": ["ACME"]})
    result, _, _ = run(capture, root, [req])
    assert (
        result["manifest_sha256"]
        == "988dc5d5742603602281c835866bb83ba4ec9206edb354576b1f2bff9dcca1ff"
    )
    body = json.loads((root / result["manifest_file"]).read_bytes())
    assert body["schema_version"] == 1 and "request_plan" not in body


@pytest.mark.parametrize("fail_at", [None, 1, 2])
def test_retained_plan_is_complete_even_when_no_successful_call_exists(root, fail_at):
    reqs = requests()
    result, transport, _ = run(
        capture, root, reqs, Transport(fail_at=fail_at), retain_request_plan=True
    )
    body = json.loads((root / result["manifest_file"]).read_bytes())
    expected = [{"tool": r.tool, "arguments": r.arguments} for r in reqs]
    assert body["schema_version"] == 2 and body["request_plan"] == expected
    assert body["request_plan_sha256"] == hashlib.sha256(capture._json(expected)).hexdigest()
    rows = read_stock_observations(root, result["manifest_file"])
    assert len(rows) == body["successful_calls"] == (2 if fail_at is None else fail_at - 1)
    assert len(transport.calls) == (2 if fail_at is None else fail_at)
    assert body["qualified"] is body["live_enabled"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "wrong_hash",
        "count",
        "reordered",
        "rebound",
        "extra_field",
        "empty",
        "too_many",
        "financial_write",
        "version_float",
    ],
)
def test_rehashed_invalid_retained_plan_cannot_rebind_observation_prefix(root, mutation):
    result, _, _ = run(capture, root, requests(), retain_request_plan=True)
    body = json.loads((root / result["manifest_file"]).read_bytes())
    if mutation == "missing":
        body.pop("request_plan")
    elif mutation == "wrong_hash":
        body["request_plan_sha256"] = "a" * 64
    elif mutation == "count":
        body["request_plan"].pop()
    elif mutation == "reordered":
        body["request_plan"].reverse()
    elif mutation == "rebound":
        body["request_plan"][0]["arguments"]["symbols"] = ["OTHER"]
    elif mutation == "extra_field":
        body["request_plan"][0]["secret"] = "private"
    elif mutation == "empty":
        body["request_plan"] = []
    elif mutation == "too_many":
        body["request_plan"] *= 17
    elif mutation == "financial_write":
        body["request_plan"][0] = {"tool": "place_equity_order", "arguments": {}}
    elif mutation == "version_float":
        body["schema_version"] = 2.0
    if mutation != "wrong_hash" and "request_plan" in body:
        body["request_plan_sha256"] = hashlib.sha256(
            capture._json(body["request_plan"])
        ).hexdigest()
    with pytest.raises(ValueError, match="stock_archive_invalid"):
        read_stock_observations(root, publish(root, body))


@pytest.mark.parametrize("retain", [None, 1, "true"])
def test_retention_opt_in_is_strict_bool_before_any_call(root, retain):
    transport = Transport()
    with pytest.raises(capture.StockCaptureError):
        run(capture, root, requests(), transport, retain_request_plan=retain)
    assert transport.calls == [] and list(root.iterdir()) == []
