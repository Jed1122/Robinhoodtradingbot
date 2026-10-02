"""Offline bounded capture tests with invented frames and mocked credentials only."""

import asyncio
import hashlib
import json
import ssl
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.diagnostics import alpaca_observe as observe
from trading_bot.diagnostics.alpaca_probe import ProbeCredential
from trading_bot.market_data.alpaca_native import MAX_PAGE_BYTES, parse_timestamp_ns
from trading_bot.market_data.recording import canonical_json

ROOT = Path(__file__).parents[3]
NOW = datetime(2026, 10, 1, 14, tzinfo=UTC)
KEY = "invented-key-123456"
SECRET = "invented-secret-123456"
CONNECTED = b'[{"T":"success","msg":"connected"}]'
AUTHENTICATED = b'[{"T":"success","msg":"authenticated"}]'
SUBSCRIBED = b'[{"T":"subscription","quotes":["SPY"],"statuses":["SPY"],"lulds":["SPY"]}]'
ORIGINAL_CONNECT = observe._FixedConnect


@dataclass(frozen=True)
class FixedClock:
    value: datetime = NOW

    def now(self) -> datetime:
        return self.value


class SequenceClock:
    def __init__(self, *values):
        self.values = iter(values)
        self.last = values[-1]

    def now(self):
        return next(self.values, self.last)


class MockConnection:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []
        self.received = 0

    async def recv(self):
        self.received += 1
        if not self.frames:
            raise RuntimeError("invented stream ended")
        value = self.frames.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    async def send(self, message):
        self.sent.append(message)


class MockConnect:
    def __init__(self, frames):
        self.connection = MockConnection(frames)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *args):
        return False


@pytest.fixture
def loaded():
    return load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/backtest.yaml",
        ROOT / "configs/safety-envelope.yaml",
        environ={},
    )


@pytest.fixture
def plan(tmp_path, loaded):
    root = tmp_path.resolve() / "observations"
    root.mkdir(mode=0o700)
    return observe.prepare_observation_capture(
        loaded,
        clock=FixedClock(),
        code_revision="a" * 40,
        credential_file=tmp_path.resolve() / "absent/credentials.json",
        output_root=root,
        repository_root=observe._REPOSITORY,
        max_frames=1,
    )


@pytest.fixture
def credential_reads(monkeypatch):
    calls = []

    def read(path, *, repository_root):
        calls.append((path, repository_root))
        return ProbeCredential(KEY, SECRET)

    monkeypatch.setattr(observe, "read_probe_credential", read)
    return calls


def quote(**changes):
    return {
        "T": "q",
        "S": "SPY",
        "t": "2026-10-01T13:59:59.123456789Z",
        "bp": 500,
        "ap": 501,
        "bs": 40,
        "as": 80,
        "bx": "P",
        "ax": "N",
        "c": ["R"],
        "z": "B",
    } | changes


def status(**changes):
    return {
        "T": "s",
        "S": "SPY",
        "t": "2026-10-01T13:59:59.123456789Z",
        "sc": "H",
        "sm": "Invented halt",
        "rc": "T1",
        "rm": "Invented reason",
        "z": "B",
    } | changes


def luld(**changes):
    return {
        "T": "l",
        "S": "SPY",
        "t": "2026-10-01T13:59:59.123456789Z",
        "u": 510,
        "d": 490,
        "i": "B",
        "z": "B",
    } | changes


def encoded(*rows):
    return json.dumps(rows, separators=(",", ":")).encode()


@pytest.mark.parametrize("extra_bytes", [-10, -9, 0, 1])
def test_raw_frame_limit_excludes_the_screening_envelope(
    plan, loaded, credential_reads, monkeypatch, extra_bytes
):
    row = encoded(quote())
    body = row + b" " * (MAX_PAGE_BYTES + extra_bytes - len(row))
    transport(monkeypatch, body)
    summary = capture(plan, loaded)
    result = read_result(plan, summary)
    if extra_bytes <= 0:
        assert summary["termination"] == "frame_limit"
        assert result["total_raw_bytes"] == len(body)
        assert summary["counts"] == {"quote": 1, "status": 0, "luld": 0}
        assert audit(plan, summary)["reference_bytes_reverified"] is True
    else:
        assert summary["termination"] == "capture_failed"
        assert result["total_raw_bytes"] == 0
        assert not list(plan.output_root.glob("*.raw"))


@pytest.mark.parametrize("invalid", ["secret", "duplicate"])
def test_full_size_frame_still_screens_secrets_and_duplicate_keys(
    plan, loaded, credential_reads, monkeypatch, invalid
):
    if invalid == "secret":
        row = encoded(status(sm=SECRET)).replace(SECRET.encode(), b"\\u0069" + SECRET[1:].encode())
    else:
        row = encoded(quote()).replace(b'"T":"q"', b'"T":"q","T":"q"')
    body = row + b" " * (MAX_PAGE_BYTES - len(row))
    transport(monkeypatch, body)
    summary = capture(plan, loaded)
    assert summary["termination"] == "capture_failed"
    assert read_result(plan, summary)["total_raw_bytes"] == 0
    assert not list(plan.output_root.glob("*.raw"))


def transport(monkeypatch, *frames):
    fake = MockConnect([CONNECTED, AUTHENTICATED, SUBSCRIBED, *frames])
    monkeypatch.setattr(observe, "_FixedConnect", fake)
    return fake


def capture(plan, loaded, *, clock=None, active_code_revision=None, approved_plan_hash=None):
    return asyncio.run(
        observe.capture_observations(
            plan,
            loaded=loaded,
            clock=clock or FixedClock(),
            active_code_revision=active_code_revision or plan.code_revision,
            approved_plan_hash=approved_plan_hash or plan.plan_hash,
        )
    )


def read_result(plan, summary):
    return json.loads(
        (plan.output_root / (summary["result_hash"] + ".observation-result.json")).read_bytes()
    )


def audit(plan, summary):
    return observe.audit_observation_capture(
        plan.output_root, summary["result_hash"], plan.repository_root
    )


def publish(root, row, suffix):
    body = canonical_json(row).encode()
    digest = hashlib.sha256(body).hexdigest()
    path = root / (digest + suffix)
    path.write_bytes(body)
    path.chmod(0o600)
    return digest


def test_plan_round_trip_is_exact_and_preparation_does_not_open_credentials(plan):
    body = observe.encode_observation_plan(plan)
    assert observe.encode_observation_plan(observe.decode_observation_plan(body)) == body
    assert plan.plan_hash == hashlib.sha256(body).hexdigest()
    assert plan.expires_at_ns - plan.prepared_at_ns == 1800 * 10**9
    assert not plan.credential_file.parent.exists()
    assert list(plan.output_root.iterdir()) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("code_revision", "A" * 40),
        ("code_revision", "a" * 39),
        ("config_hash", "b" * 63),
        ("config_hash", True),
        ("prepared_at_ns", -1),
        ("prepared_at_ns", True),
        ("expires_at_ns", 1),
        ("duration_seconds", 0),
        ("duration_seconds", 901),
        ("duration_seconds", True),
        ("max_frames", 0),
        ("max_frames", 10001),
        ("max_frames", True),
        ("credential_file", "relative.json"),
        ("credential_file", "/tmp/../credentials.json"),
        ("output_root", "/"),
        ("repository_root", "relative"),
        ("predecessor_result_hash", "b" * 63),
        ("predecessor_result_hash", True),
    ],
)
def test_plan_decode_refuses_scope_type_and_path_injection(plan, field, value):
    wire = json.loads(observe.encode_observation_plan(plan))
    wire["plan"][field] = value
    with pytest.raises(
        observe.AlpacaObservationError, match=r"^alpaca_observation_capture_invalid$"
    ):
        observe.decode_observation_plan(json.dumps(wire).encode())


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b"null",
        b"{",
        b"\xff",
        b'{"schema":NaN}',
        b'{"schema":1,"schema":2}',
        b" " * 16385,
    ],
)
def test_plan_decode_errors_do_not_render_untrusted_input(body):
    with pytest.raises(observe.AlpacaObservationError) as caught:
        observe.decode_observation_plan(body)
    assert caught.value.args == ("alpaca_observation_capture_invalid",)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("case", ["hash", "revision", "config", "before", "expired"])
def test_review_and_identity_gates_run_before_claim_keys_or_transport(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    case,
):
    fake = transport(monkeypatch, encoded(quote()))
    kwargs = {}
    if case == "hash":
        kwargs["approved_plan_hash"] = "b" * 64
    elif case == "revision":
        kwargs["active_code_revision"] = "b" * 40
    elif case == "config":
        plan = replace(plan, config_hash="b" * 64)
    elif case == "before":
        kwargs["clock"] = FixedClock(NOW - timedelta(seconds=1))
    else:
        kwargs["clock"] = FixedClock(NOW + timedelta(minutes=30))
    with pytest.raises(observe.AlpacaObservationError):
        capture(plan, loaded, **kwargs)
    assert not credential_reads and not fake.calls
    assert not list(plan.output_root.iterdir())


def test_tampered_canonical_config_is_denied_before_credentials(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
):
    fake = transport(monkeypatch, encoded(quote()))
    with pytest.raises(ValueError):
        capture(plan, replace(loaded, canonical_json=b"{}"))
    assert not credential_reads and not fake.calls


def test_forged_repository_root_is_denied_before_claim_keys_or_egress(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    tmp_path,
):
    plan = replace(plan, repository_root=tmp_path / "invented-repository")
    fake = transport(monkeypatch, encoded(quote()))
    with pytest.raises(observe.AlpacaObservationError):
        capture(plan, loaded)
    assert not credential_reads and not fake.calls
    assert not list(plan.output_root.iterdir())


@pytest.mark.parametrize("config", ["paper.yaml", "shadow.yaml", "simulation.yaml"])
def test_non_backtest_configuration_cannot_prepare_capture(plan, config):
    loaded = load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs" / config,
        ROOT / "configs/safety-envelope.yaml",
        environ={},
    )
    with pytest.raises(observe.AlpacaObservationError):
        observe.prepare_observation_capture(
            loaded,
            clock=FixedClock(),
            code_revision=plan.code_revision,
            credential_file=plan.credential_file,
            output_root=plan.output_root,
            repository_root=plan.repository_root,
        )
    assert not list(plan.output_root.iterdir())


@pytest.mark.parametrize(
    "case", ["credential_in_repository", "output_in_repository", "credential_in_output"]
)
def test_plan_refuses_repository_or_output_credential_overlap(plan, case):
    kwargs = {
        "credential_in_repository": {"credential_file": plan.repository_root / "invented.json"},
        "output_in_repository": {"output_root": plan.repository_root / "invented-output"},
        "credential_in_output": {"credential_file": plan.output_root / "invented.json"},
    }
    with pytest.raises(observe.AlpacaObservationError):
        replace(plan, **kwargs[case])


def test_transport_pins_sip_spy_channels_and_private_unqualified_archive(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
):
    body = encoded(quote(), status(), luld())
    fake = transport(monkeypatch, body.decode())
    summary = capture(plan, loaded)
    assert credential_reads == [(plan.credential_file, plan.repository_root)]
    assert len(fake.calls) == 1
    url, options = fake.calls[0]
    assert url == "wss://stream.data.alpaca.markets/v2/sip"
    assert options["proxy"] is None and options["compression"] is None
    assert options["max_size"] == MAX_PAGE_BYTES and options["max_queue"] == 1
    assert options["open_timeout"] == 10 and options["close_timeout"] == 5
    assert options["ssl"].verify_mode == ssl.CERT_REQUIRED
    assert options["ssl"].check_hostname and options["logger"].disabled
    assert [json.loads(value) for value in fake.connection.sent] == [
        {"action": "auth", "key": KEY, "secret": SECRET},
        {"action": "subscribe", "quotes": ["SPY"], "statuses": ["SPY"], "lulds": ["SPY"]},
    ]
    assert summary["termination"] == "frame_limit"
    assert summary["counts"] == {"quote": 1, "status": 1, "luld": 1}
    assert all(
        summary[name] is False
        for name in (
            "source_qualified",
            "execution_enabled",
            "evidence_promotable",
        )
    )
    assert (plan.output_root / (hashlib.sha256(body).hexdigest() + ".raw")).read_bytes() == body
    for path in plan.output_root.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
        assert KEY.encode() not in path.read_bytes() and SECRET.encode() not in path.read_bytes()
    report = audit(plan, summary)
    assert report["status"] == "OBSERVED_UNQUALIFIED"
    assert report["reference_bytes_reverified"] is True
    assert report["quote_quality"]["two_sided_uncrossed"] == 1
    assert "customer_costs_not_measured_by_market_data" in report["reasons"]


def test_fixed_connector_never_follows_redirect_exception():
    error = RuntimeError("invented redirect")
    assert ORIGINAL_CONNECT.process_redirect(None, error) is error


def test_subscription_accepts_only_empty_unrequested_documented_channels(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
):
    row = json.loads(SUBSCRIBED)[0]
    for name in ("trades", "bars", "updatedBars", "dailyBars", "corrections", "cancelErrors"):
        row[name] = []
    fake = MockConnect([CONNECTED, AUTHENTICATED, encoded(row), encoded(quote())])
    monkeypatch.setattr(observe, "_FixedConnect", fake)
    summary = capture(plan, loaded)
    assert summary["termination"] == "frame_limit"
    assert fake.connection.received == 4


def test_scope_claim_prevents_replay_after_success(plan, loaded, credential_reads, monkeypatch):
    fake = transport(monkeypatch, encoded(quote()))
    capture(plan, loaded)
    with pytest.raises(observe.AlpacaObservationError):
        capture(plan, loaded)
    assert len(credential_reads) == 1 and len(fake.calls) == 1


def test_scope_is_consumed_before_credential_failure(plan, loaded, monkeypatch):
    calls = []

    def fail(*args, **kwargs):
        calls.append(True)
        raise ValueError(SECRET)

    monkeypatch.setattr(observe, "read_probe_credential", fail)
    fake = transport(monkeypatch, encoded(quote()))
    for _ in range(2):
        with pytest.raises(observe.AlpacaObservationError) as caught:
            capture(plan, loaded)
        assert SECRET not in str(caught.value)
    assert calls == [True] and not fake.calls
    assert (plan.output_root / (plan.plan_hash + ".observation.attempt")).exists()


@pytest.mark.parametrize(
    "index,body",
    [
        (0, AUTHENTICATED),
        (0, b'[{"T":"success","msg":"connected","extra":true}]'),
        (1, CONNECTED),
        (1, b'[{"T":"error","code":402,"msg":"invented denied"}]'),
        (2, b'[{"T":"subscription","quotes":["QQQ"],"statuses":["SPY"],"lulds":["SPY"]}]'),
        (2, b'[{"T":"subscription","quotes":["SPY"],"statuses":["SPY"]}]'),
        (
            2,
            b'[{"T":"subscription","quotes":["SPY"],"statuses":["SPY"],'
            b'"lulds":["SPY"],"trades":["SPY"]}]',
        ),
        (
            2,
            b'[{"T":"subscription","quotes":["SPY"],"statuses":["SPY"],"lulds":["SPY"],"future":[]}]',
        ),
    ],
)
def test_auth_and_subscription_failures_are_terminal_and_never_reconnect(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    index,
    body,
):
    frames = [CONNECTED, AUTHENTICATED, SUBSCRIBED, encoded(quote())]
    frames[index] = body
    fake = MockConnect(frames)
    monkeypatch.setattr(observe, "_FixedConnect", fake)
    summary = capture(plan, loaded)
    assert summary["termination"] == "capture_failed"
    assert summary["counts"] == {"quote": 0, "status": 0, "luld": 0}
    assert len(fake.calls) == 1 and len(credential_reads) == 1
    assert not list(plan.output_root.glob("*.raw"))
    assert audit(plan, summary)["status"] == "BLOCKED_INPUTS"
    with pytest.raises(observe.AlpacaObservationError):
        capture(plan, loaded)
    assert len(fake.calls) == 1


@pytest.mark.parametrize(
    "message",
    [
        SECRET,
        KEY.upper(),
        "APCA-API-SECRET-KEY",
        "apca-api-key-id",
    ],
)
def test_secret_echo_screening_drops_frame_without_raw_publication(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    message,
):
    body = encoded(status(sm=message))
    if message == SECRET:
        body = body.replace(SECRET.encode(), b"\\u0069" + SECRET[1:].encode())
    transport(monkeypatch, body)
    summary = capture(plan, loaded)
    assert summary["termination"] == "capture_failed"
    assert not list(plan.output_root.glob("*.raw"))
    assert message not in canonical_json(summary)


@pytest.mark.parametrize(
    "body",
    [
        b'[{"T":"q","T":"q"}]',
        b'[{"T":"error","msg":"invented error"}]',
        encoded(quote(S="QQQ")),
        encoded(quote(T="t")),
        b"null",
        b"\xff",
        b"[NaN]",
        b" " * (MAX_PAGE_BYTES + 1),
    ],
    ids=["duplicate", "error", "wrong-symbol", "wrong-channel", "null", "utf8", "nan", "oversized"],
)
def test_invalid_or_oversized_frames_produce_sanitized_failure_result(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    body,
):
    fake = transport(monkeypatch, body)
    summary = capture(plan, loaded)
    assert summary["termination"] == "capture_failed"
    assert len(fake.calls) == 1
    assert not list(plan.output_root.glob("*.raw"))
    assert read_result(plan, summary)["total_raw_bytes"] == 0


def test_frame_limit_stops_without_consuming_extra_frame(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
):
    fake = transport(monkeypatch, encoded(quote()), encoded(status()))
    summary = capture(plan, loaded)
    assert fake.connection.received == 4
    assert len(fake.connection.frames) == 1
    assert summary["termination"] == "frame_limit"
    assert summary["counts"] == {"quote": 1, "status": 0, "luld": 0}


def test_total_byte_limit_keeps_complete_prefix_and_marks_unretained_frame(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
):
    first, second = encoded(quote()), encoded(status())
    monkeypatch.setattr(observe, "_MAX_TOTAL_BYTES", len(first) + len(second) - 1)
    plan = replace(plan, max_frames=3)
    fake = transport(monkeypatch, first, second, encoded(luld()))
    summary = capture(plan, loaded)
    result = read_result(plan, summary)
    assert summary["termination"] == "byte_limit_unretained_frame"
    assert result["total_raw_bytes"] == len(first) and len(result["receipt_hashes"]) == 1
    assert fake.connection.received == 5
    assert not (plan.output_root / (hashlib.sha256(second).hexdigest() + ".raw")).exists()
    assert audit(plan, summary)["counts"] == {"quote": 1, "status": 0, "luld": 0}


@pytest.mark.parametrize("retained_frames", [1, 2])
def test_audit_rejects_byte_limit_at_or_below_possible_overflow_threshold(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    retained_frames,
):
    page_bytes, total_bytes = 1024, 3072
    monkeypatch.setattr(observe, "MAX_PAGE_BYTES", page_bytes)
    monkeypatch.setattr(observe, "_MAX_TOTAL_BYTES", total_bytes)
    frame = b"[]" + b" " * (page_bytes - 2)
    plan = replace(plan, max_frames=3)
    transport(monkeypatch, *([frame] * retained_frames))
    summary = capture(plan, loaded)
    result = read_result(plan, summary)
    assert result["total_raw_bytes"] == page_bytes * retained_frames
    assert result["total_raw_bytes"] <= total_bytes - page_bytes
    assert audit(plan, summary)["termination"] == "capture_failed"
    result["termination"] = "byte_limit_unretained_frame"
    summary["result_hash"] = publish(plan.output_root, result, ".observation-result.json")
    with pytest.raises(observe.AlpacaObservationError):
        audit(plan, summary)


@pytest.mark.parametrize("retained_frames", [1, 2])
def test_restart_rejects_forged_predecessor_byte_limit_before_new_capture(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    retained_frames,
):
    page_bytes, total_bytes = 1024, 3072
    monkeypatch.setattr(observe, "MAX_PAGE_BYTES", page_bytes)
    monkeypatch.setattr(observe, "_MAX_TOTAL_BYTES", total_bytes)
    frame = b"[]" + b" " * (page_bytes - 2)
    plan = replace(plan, max_frames=3)
    transport(monkeypatch, *([frame] * retained_frames))
    first = capture(plan, loaded)
    result = read_result(plan, first)
    assert result["total_raw_bytes"] <= total_bytes - page_bytes
    result["termination"] = "byte_limit_unretained_frame"
    predecessor_hash = publish(plan.output_root, result, ".observation-result.json")
    next_plan = replace(plan, predecessor_result_hash=predecessor_hash)
    fake = transport(monkeypatch, encoded(quote()))
    with pytest.raises(observe.AlpacaObservationError):
        capture(next_plan, loaded)
    assert len(credential_reads) == 1 and not fake.calls
    assert not (plan.output_root / (next_plan.plan_hash + ".observation.attempt")).exists()


def test_byte_limit_preserves_real_overflow_prefix_above_required_threshold(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
):
    page_bytes, total_bytes = 1024, 3072
    monkeypatch.setattr(observe, "MAX_PAGE_BYTES", page_bytes)
    monkeypatch.setattr(observe, "_MAX_TOTAL_BYTES", total_bytes)
    full_frame = b"[]" + b" " * (page_bytes - 2)
    unretained_frame = b"[\n]" + b" " * (page_bytes - 3)
    plan = replace(plan, max_frames=4)
    fake = transport(monkeypatch, full_frame, full_frame[:-1], b"[]", unretained_frame)
    summary = capture(plan, loaded)
    result = read_result(plan, summary)
    assert summary["termination"] == "byte_limit_unretained_frame"
    assert len(result["receipt_hashes"]) == 3
    assert result["total_raw_bytes"] == 2 * page_bytes + 1
    assert total_bytes - page_bytes < result["total_raw_bytes"] <= total_bytes
    assert result["total_raw_bytes"] + len(unretained_frame) > total_bytes
    assert fake.connection.received == 7
    digest = hashlib.sha256(unretained_frame).hexdigest()
    assert not (plan.output_root / (digest + ".raw")).exists()
    report = audit(plan, summary)
    assert report["termination"] == "byte_limit_unretained_frame"
    assert report["reference_bytes_reverified"] is True


@pytest.mark.parametrize("termination", ["duration_limit", "byte_limit_unretained_frame"])
def test_audit_rejects_elapsed_or_byte_stop_with_full_retained_frame_count(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    termination,
):
    frames = [encoded(quote())]
    if termination == "byte_limit_unretained_frame":
        page_bytes, total_bytes = 1024, 3072
        monkeypatch.setattr(observe, "MAX_PAGE_BYTES", page_bytes)
        monkeypatch.setattr(observe, "_MAX_TOTAL_BYTES", total_bytes)
        full_frame = b"[]" + b" " * (page_bytes - 2)
        frames = [full_frame, full_frame[:-1], b"[]"]
    plan = replace(plan, max_frames=len(frames))
    transport(monkeypatch, *frames)
    summary = capture(plan, loaded)
    result = read_result(plan, summary)
    assert len(result["receipt_hashes"]) == plan.max_frames
    assert audit(plan, summary)["termination"] == "frame_limit"
    if termination == "byte_limit_unretained_frame":
        assert result["total_raw_bytes"] > total_bytes - page_bytes
    result["termination"] = termination
    summary["result_hash"] = publish(plan.output_root, result, ".observation-result.json")
    with pytest.raises(observe.AlpacaObservationError):
        audit(plan, summary)


@pytest.mark.parametrize("operation", ["recv", "publication"])
def test_operational_timeout_before_collection_deadline_reports_capture_failure(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    operation,
):
    plan = replace(plan, max_frames=3)
    next_frame = encoded(status())
    failure = TimeoutError("invented operational timeout")
    fake = transport(monkeypatch, encoded(quote()), failure if operation == "recv" else next_frame)
    if operation == "publication":
        original_publish = observe._publish
        failing_name = hashlib.sha256(next_frame).hexdigest() + ".raw"

        def fail_raw_publication(descriptor, name, body):
            if name == failing_name:
                raise failure
            original_publish(descriptor, name, body)

        monkeypatch.setattr(observe, "_publish", fail_raw_publication)
    summary = capture(plan, loaded)
    assert summary["termination"] == "capture_failed"
    assert summary["counts"] == {"quote": 1, "status": 0, "luld": 0}
    assert len(read_result(plan, summary)["receipt_hashes"]) == 1
    assert len(list(plan.output_root.glob("*.raw"))) == 1
    assert audit(plan, summary)["termination"] == "capture_failed"
    assert len(fake.calls) == 1 and len(credential_reads) == 1


def test_duration_timeout_retains_prefix_as_unqualified(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
):
    class BlockingConnection(MockConnection):
        async def recv(self):
            if self.frames:
                return await super().recv()
            await asyncio.Event().wait()

    plan = replace(plan, max_frames=3, duration_seconds=1)
    fake = MockConnect([])
    fake.connection = BlockingConnection([CONNECTED, AUTHENTICATED, SUBSCRIBED, encoded(quote())])
    monkeypatch.setattr(observe, "_FixedConnect", fake)
    summary = capture(plan, loaded)
    assert summary["termination"] == "duration_limit"
    assert audit(plan, summary)["status"] == "OBSERVED_UNQUALIFIED"
    assert len(fake.calls) == 1


def test_failure_after_good_frame_publishes_only_reverifiable_prefix(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
):
    plan = replace(plan, max_frames=3)
    fake = transport(monkeypatch, encoded(quote()), RuntimeError(SECRET))
    summary = capture(plan, loaded)
    assert summary["termination"] == "capture_failed" and len(fake.calls) == 1
    assert audit(plan, summary)["counts"] == {"quote": 1, "status": 0, "luld": 0}
    assert SECRET not in canonical_json(read_result(plan, summary))


@pytest.mark.parametrize("case", ["utc", "monotonic"])
def test_receipt_clock_regression_is_terminal_without_retaining_bad_frame(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    case,
):
    transport(monkeypatch, encoded(quote()))
    clock = FixedClock()
    if case == "utc":
        clock = SequenceClock(NOW, NOW - timedelta(seconds=1), NOW)
    else:
        values = iter([200, 100])
        monkeypatch.setattr(observe.time, "monotonic_ns", lambda: next(values))
    summary = capture(plan, loaded, clock=clock)
    assert summary["termination"] == "capture_failed"
    assert not list(plan.output_root.glob("*.raw"))


def test_final_clock_regression_consumes_scope_without_fabricated_result(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
):
    fake = transport(monkeypatch, encoded(quote()))
    with pytest.raises(observe.AlpacaObservationError):
        capture(plan, loaded, clock=SequenceClock(NOW, NOW, NOW - timedelta(seconds=1)))
    assert not list(plan.output_root.glob("*.observation-result.json"))
    with pytest.raises(observe.AlpacaObservationError):
        capture(plan, loaded)
    assert len(fake.calls) == 1


@pytest.mark.parametrize("case", ["receipt", "finished"])
def test_clock_jump_beyond_expiry_consumes_scope_without_invalid_result(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    case,
):
    fake = transport(monkeypatch, encoded(quote()))
    expired = NOW + timedelta(minutes=30, seconds=1)
    clock = SequenceClock(NOW, expired if case == "receipt" else NOW, expired)
    with pytest.raises(observe.AlpacaObservationError) as caught:
        capture(plan, loaded, clock=clock)
    assert caught.value.args == ("alpaca_observation_capture_invalid",)
    assert not list(plan.output_root.glob("*.observation-result.json"))
    assert (plan.output_root / (plan.plan_hash + ".observation.attempt")).exists()
    assert len(list(plan.output_root.glob("*.raw"))) == (case == "finished")
    with pytest.raises(observe.AlpacaObservationError):
        capture(plan, loaded)
    assert len(fake.calls) == 1 and len(credential_reads) == 1


@pytest.mark.parametrize("case", ["root_mode", "root_symlink", "ancestor_symlink", "claim_symlink"])
def test_private_capture_storage_is_checked_before_credentials(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    tmp_path,
    case,
):
    fake = transport(monkeypatch, encoded(quote()))
    if case == "root_mode":
        plan.output_root.chmod(0o755)
    elif case == "root_symlink":
        link = tmp_path / "link"
        link.symlink_to(plan.output_root, target_is_directory=True)
        plan = replace(plan, output_root=link)
    elif case == "ancestor_symlink":
        link = tmp_path.parent / (tmp_path.name + "-link")
        link.symlink_to(tmp_path, target_is_directory=True)
        plan = replace(plan, output_root=link / "observations")
    else:
        (plan.output_root / (plan.plan_hash + ".observation.attempt")).symlink_to(
            tmp_path / "absent"
        )
    with pytest.raises(observe.AlpacaObservationError):
        capture(plan, loaded)
    assert not credential_reads and not fake.calls


@pytest.mark.parametrize(
    "suffix",
    [
        ".raw",
        ".observation-plan.json",
        ".observation-receipt.json",
        ".observation-result.json",
    ],
)
def test_audit_rejects_exact_byte_tampering(plan, loaded, credential_reads, monkeypatch, suffix):
    transport(monkeypatch, encoded(quote()))
    summary = capture(plan, loaded)
    path = next(plan.output_root.glob("*" + suffix))
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(observe.AlpacaObservationError):
        audit(plan, summary)


@pytest.mark.parametrize(
    "field,value",
    [
        ("counts", {"quote": 2, "status": 0, "luld": 0}),
        ("total_raw_bytes", 0),
        ("termination", "complete"),
        ("source_qualified", True),
        ("execution_enabled", True),
        ("evidence_promotable", True),
        ("initial_control_state_verified", True),
        ("transport_continuity_verified", True),
        ("segment_gap_before_start", False),
        ("started_at_ns", True),
        ("finished_at_ns", 0),
        ("predecessor_result_hash", "c" * 64),
    ],
)
def test_audit_revalidates_readdressed_result_semantics(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    field,
    value,
):
    transport(monkeypatch, encoded(quote()))
    summary = capture(plan, loaded)
    result = read_result(plan, summary)
    result[field] = value
    summary["result_hash"] = publish(plan.output_root, result, ".observation-result.json")
    with pytest.raises(observe.AlpacaObservationError):
        audit(plan, summary)


@pytest.mark.parametrize("retained_frames", [0, 1, 2])
def test_frame_limit_requires_full_receipt_count_after_result_readdressing(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    retained_frames,
):
    plan = replace(plan, max_frames=3)
    transport(monkeypatch, *([encoded(quote())] * retained_frames))
    summary = capture(plan, loaded)
    result = read_result(plan, summary)
    assert len(result["receipt_hashes"]) == retained_frames
    assert audit(plan, summary)["termination"] == "capture_failed"
    original_hash = summary["result_hash"]
    result["termination"] = "frame_limit"
    summary["result_hash"] = publish(plan.output_root, result, ".observation-result.json")
    assert summary["result_hash"] != original_hash
    with pytest.raises(observe.AlpacaObservationError):
        audit(plan, summary)


def test_transport_exit_failure_can_report_failed_capture_at_full_frame_count(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
):
    class ExitFailureConnect(MockConnect):
        async def __aexit__(self, *args):
            raise RuntimeError("invented close failure")

    plan = replace(plan, max_frames=2)
    fake = ExitFailureConnect(
        [CONNECTED, AUTHENTICATED, SUBSCRIBED, encoded(quote()), encoded(status())]
    )
    monkeypatch.setattr(observe, "_FixedConnect", fake)
    summary = capture(plan, loaded)
    assert len(read_result(plan, summary)["receipt_hashes"]) == plan.max_frames
    assert summary["termination"] == "capture_failed"
    report = audit(plan, summary)
    assert report["termination"] == "capture_failed"
    assert report["counts"] == {"quote": 1, "status": 1, "luld": 0}
    assert report["status"] == "OBSERVED_UNQUALIFIED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("plan_hash", "c" * 64),
        ("frame_index", True),
        ("frame_index", 1),
        ("previous_receipt_hash", "c" * 64),
        ("received_at_ns", 0),
        ("received_monotonic_ns", -1),
        ("received_monotonic_ns", 2**63),
        ("observation_hashes", []),
        ("body_sha256", "c" * 64),
    ],
)
def test_audit_revalidates_readdressed_receipt_chain(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    field,
    value,
):
    transport(monkeypatch, encoded(quote()))
    summary = capture(plan, loaded)
    result = read_result(plan, summary)
    path = plan.output_root / (result["receipt_hashes"][0] + ".observation-receipt.json")
    receipt = json.loads(path.read_bytes())
    receipt[field] = value
    digest = publish(plan.output_root, receipt, ".observation-receipt.json")
    result["receipt_hashes"] = [digest]
    summary["result_hash"] = publish(plan.output_root, result, ".observation-result.json")
    with pytest.raises(observe.AlpacaObservationError):
        audit(plan, summary)


@pytest.mark.parametrize("frame_count", [1, 3])
def test_empty_frames_remain_blocked_without_observations(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    frame_count,
):
    plan = replace(plan, max_frames=frame_count)
    transport(monkeypatch, *([b"[]"] * frame_count))
    summary = capture(plan, loaded)
    result = read_result(plan, summary)
    assert len(result["receipt_hashes"]) == frame_count
    assert result["total_raw_bytes"] == 2 * frame_count
    report = audit(plan, summary)
    assert report["counts"] == {"quote": 0, "status": 0, "luld": 0}
    assert report["status"] == "BLOCKED_INPUTS"
    assert report["reference_bytes_reverified"] is True
    assert all(
        report[name] is False
        for name in (
            "source_qualified",
            "execution_enabled",
            "evidence_promotable",
        )
    )


@pytest.mark.parametrize("frame_count", [0, 1])
def test_missing_interframe_measurement_is_none_with_fewer_than_two_frames(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    frame_count,
):
    frames = [encoded(quote(), status(), luld())] if frame_count else []
    transport(monkeypatch, *frames)
    summary = capture(plan, loaded)
    assert len(read_result(plan, summary)["receipt_hashes"]) == frame_count
    report = audit(plan, summary)
    assert report["counts"] == dict.fromkeys(("quote", "status", "luld"), frame_count)
    assert report["maximum_interframe_receipt_gap_ns"] is None


@pytest.mark.parametrize("frame_count", [2, 3])
def test_equal_monotonic_receipts_measure_an_integer_zero_gap(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    frame_count,
):
    plan = replace(plan, max_frames=frame_count)
    transport(monkeypatch, *([encoded(quote())] * frame_count))
    ticks = iter([10, *([20] * frame_count)])
    monkeypatch.setattr(observe.time, "monotonic_ns", lambda: next(ticks))
    summary = capture(plan, loaded)
    assert len(read_result(plan, summary)["receipt_hashes"]) == frame_count
    report = audit(plan, summary)
    assert report["status"] == "OBSERVED_UNQUALIFIED"
    gap = report["maximum_interframe_receipt_gap_ns"]
    assert type(gap) is int and gap == 0


def test_mixed_empty_and_observed_frames_measure_gap_and_report_observations(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
):
    plan = replace(plan, max_frames=2)
    transport(monkeypatch, b"[]", encoded(quote()))
    ticks = iter([10, 20, 30])
    monkeypatch.setattr(observe.time, "monotonic_ns", lambda: next(ticks))
    summary = capture(plan, loaded)
    report = audit(plan, summary)
    assert report["counts"] == {"quote": 1, "status": 0, "luld": 0}
    assert report["status"] == "OBSERVED_UNQUALIFIED"
    assert report["maximum_interframe_receipt_gap_ns"] == 10


def test_receipts_bind_raw_frames_in_order_and_measure_only_receipt_gap(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
):
    plan = replace(plan, max_frames=3)
    transport(monkeypatch, encoded(quote(bp=0)), encoded(quote(bp=501)), encoded(quote(bp=502)))
    ticks = iter([10, 20, 50, 100])
    monkeypatch.setattr(observe.time, "monotonic_ns", lambda: next(ticks))
    summary = capture(plan, loaded)
    result = read_result(plan, summary)
    previous = None
    for index, digest in enumerate(result["receipt_hashes"]):
        receipt = json.loads(
            (plan.output_root / (digest + ".observation-receipt.json")).read_bytes()
        )
        assert receipt["frame_index"] == index
        assert receipt["previous_receipt_hash"] == previous
        previous = digest
    report = audit(plan, summary)
    assert report["maximum_interframe_receipt_gap_ns"] == 50
    assert report["quote_quality"] == {
        "inactive": 1,
        "locked": 1,
        "crossed": 1,
        "two_sided_uncrossed": 0,
    }
    assert "latency_ns" not in report


def test_restart_requires_existing_predecessor_before_claim_keys_or_egress(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
):
    plan = replace(plan, predecessor_result_hash="c" * 64)
    fake = transport(monkeypatch, encoded(quote()))
    with pytest.raises(observe.AlpacaObservationError):
        capture(plan, loaded)
    assert not credential_reads and not fake.calls
    assert not list(plan.output_root.iterdir())


@pytest.mark.parametrize(
    "case",
    [
        "missing_field",
        "extra_field",
        "negative_count",
        "invalid_receipt",
        "unknown_termination",
        "reversed_time",
        "invalid_bytes",
        "verified_controls",
    ],
)
def test_readdressed_predecessor_requires_bounded_terminal_metadata(
    plan, loaded, credential_reads, monkeypatch, case
):
    transport(monkeypatch, encoded(quote()))
    first = capture(plan, loaded)
    row = read_result(plan, first)
    if case == "missing_field":
        row.pop("receipt_hashes")
    elif case == "extra_field":
        row["invented_extra"] = True
    elif case == "negative_count":
        row["counts"]["quote"] = -1
    elif case == "invalid_receipt":
        row["receipt_hashes"] = ["not-a-hash"]
    elif case == "unknown_termination":
        row["termination"] = "invented_success"
    elif case == "reversed_time":
        row["started_at_ns"] = row["finished_at_ns"] + 1
    elif case == "invalid_bytes":
        row["total_raw_bytes"] = 0
    else:
        row["initial_control_state_verified"] = True
    digest = publish(plan.output_root, row, ".observation-result.json")
    next_plan = replace(plan, predecessor_result_hash=digest)
    fake = transport(monkeypatch, encoded(status()))
    with pytest.raises(observe.AlpacaObservationError):
        capture(next_plan, loaded)
    assert len(credential_reads) == 1 and not fake.calls
    assert not (plan.output_root / (next_plan.plan_hash + ".observation.attempt")).exists()


@pytest.mark.parametrize("case", ["missing", "tampered"])
def test_restart_is_explicit_gap_and_audit_reverifies_direct_predecessor(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    case,
):
    transport(monkeypatch, encoded(quote()))
    first = capture(plan, loaded)
    next_plan = replace(plan, predecessor_result_hash=first["result_hash"])
    transport(monkeypatch, encoded(status()))
    second = capture(next_plan, loaded)
    result = read_result(next_plan, second)
    assert result["predecessor_result_hash"] == first["result_hash"]
    assert result["segment_gap_before_start"] is True
    assert result["transport_continuity_verified"] is False
    report = audit(next_plan, second)
    assert report["status"] == "OBSERVED_UNQUALIFIED"
    assert report["predecessor_result_bytes_reverified"] is True
    path = plan.output_root / (first["result_hash"] + ".observation-result.json")
    if case == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(observe.AlpacaObservationError):
        audit(next_plan, second)


@pytest.mark.parametrize("case", ["mode", "symlink", "missing"])
def test_audit_requires_private_regular_raw_archive_files(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
    tmp_path,
    case,
):
    transport(monkeypatch, encoded(quote()))
    summary = capture(plan, loaded)
    raw = next(plan.output_root.glob("*.raw"))
    if case == "mode":
        raw.chmod(0o644)
    elif case == "missing":
        raw.unlink()
    else:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.write_bytes(raw.read_bytes())
        elsewhere.chmod(0o600)
        raw.unlink()
        raw.symlink_to(elsewhere)
    with pytest.raises(observe.AlpacaObservationError):
        audit(plan, summary)


def test_audit_reports_provider_clock_skew_without_inventing_latency(
    plan,
    loaded,
    credential_reads,
    monkeypatch,
):
    stamp = (NOW + timedelta(seconds=1)).isoformat()
    transport(monkeypatch, encoded(quote(t=stamp)))
    summary = capture(plan, loaded)
    report = audit(plan, summary)
    assert report["clock_skew_observation_count"] == 1
    assert parse_timestamp_ns(stamp) > plan.prepared_at_ns
    assert report["source_qualified"] is False and report["evidence_promotable"] is False
