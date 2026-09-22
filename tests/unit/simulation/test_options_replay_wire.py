"""Untrusted saved inputs cannot change config, origin, precision or record bounds."""

import hashlib
import json
from dataclasses import replace
from decimal import Decimal

import pytest

from tests.unit.config.test_options_config import load_options
from trading_bot.simulation.options_fixtures import synthetic_options_request


def document():
    from trading_bot.simulation.options_replay_wire import encode_options_replay

    r = synthetic_options_request(load_options(), Decimal("2500"))
    return r, json.loads(encode_options_replay(r))


def encode_row(row: dict) -> bytes:
    values = {key: value for key, value in row.items() if key != "document_hash"}
    body = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    row["document_hash"] = hashlib.sha256(body.encode()).hexdigest()
    return json.dumps(row).encode()


def test_roundtrip_retains_exact_values_and_prior_trial_episodes() -> None:
    from trading_bot.risk.options_economics import TrialEpisode, TrialLossState
    from trading_bot.simulation.options_replay_wire import (
        decode_options_replay,
        encode_options_replay,
    )

    r = synthetic_options_request(load_options(), Decimal("2500"))
    prior = TrialEpisode("completed-loss", Decimal("11"), Decimal("-6"), True, True, True)
    r = replace(r, trial=TrialLossState((prior,)))
    decoded = decode_options_replay(encode_options_replay(r), r.loaded)
    assert decoded == r
    assert decoded.initial_quote.ask == Decimal("0.10")
    assert decoded.trial.consumed_loss == Decimal("6")
    assert decoded.trial.remaining(Decimal("50")) == Decimal("44")
    assert "loaded" not in json.loads(encode_options_replay(r))["payload"]


@pytest.mark.parametrize(
    ("location", "key", "value"),
    [
        ("root", "schema", "historical-options-v1"),
        ("root", "extra", "https://must-not-be-fetched.invalid/"),
        ("payload", "source_kind", "historical"),
        ("payload", "research_capital", 2500),
        ("payload", "loaded", {}),
        ("payload", "entry_fee", "NaN"),
        ("contract", "strike", "1e2"),
        ("contract", "adjusted", True),
        ("contract", "available_at", "2026-09-17T15:00:00+00:00"),
        ("initial_quote", "bid_size", True),
        ("initial_quote", "ask", 0.10),
        ("initial_quote", "source", "broker-live"),
    ],
)
def test_rehashed_invalid_inputs_still_fail_closed(location: str, key: str, value: object) -> None:
    from trading_bot.simulation.options_replay_wire import (
        OptionsReplayFileError,
        decode_options_replay,
    )

    r, row = document()
    target = row if location == "root" else row["payload"]
    if location not in ("root", "payload"):
        target = target[location]
    target[key] = value
    with pytest.raises(OptionsReplayFileError) as caught:
        decode_options_replay(encode_row(row), r.loaded)
    assert str(caught.value) == "options_replay_input_invalid"
    assert caught.value.__context__ is None


def test_digest_mismatch_and_changed_config_are_rejected() -> None:
    from trading_bot.simulation.options_replay_wire import (
        OptionsReplayFileError,
        decode_options_replay,
    )

    r, row = document()
    row["payload"]["close_limit"] = "0.16"
    with pytest.raises(OptionsReplayFileError):
        decode_options_replay(json.dumps(row).encode(), r.loaded)
    r, row = document()
    tightened = load_options({"TRADING_BOT__OPTIONS__MAX_PER_TRADE_LOSS_USD": "25"})
    with pytest.raises(OptionsReplayFileError):
        decode_options_replay(json.dumps(row).encode(), tightened)


@pytest.mark.parametrize("body", [b'{"schema":1,"schema":2}', b'{"x":NaN}', b"\xff", b"[]"])
def test_invalid_json_forms_have_sanitized_failures(body: bytes) -> None:
    from trading_bot.simulation.options_replay_wire import (
        OptionsReplayFileError,
        decode_options_replay,
    )

    with pytest.raises(OptionsReplayFileError):
        decode_options_replay(body, load_options())


@pytest.mark.parametrize(
    "bound", ["REPLAY_MAX_BYTES", "REPLAY_MAX_RECORDS", "REPLAY_MAX_JSON_DEPTH"]
)
def test_tightened_resource_ceiling_denies_export_before_publication(bound: str) -> None:
    from trading_bot.simulation.options_replay_wire import (
        OptionsReplayFileError,
        encode_options_replay,
    )

    r = synthetic_options_request(
        load_options({"TRADING_BOT__OPTIONS__" + bound: "1"}), Decimal("2500")
    )
    with pytest.raises(OptionsReplayFileError):
        encode_options_replay(r)
