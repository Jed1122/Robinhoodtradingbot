"""Hostile local checkpoint inputs; no production recovery or broker assertions."""

import json
import os
from dataclasses import replace
from decimal import Decimal

import pytest

from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from tests.unit.simulation.test_options_historical_clock import (
    attach_calendar,
    closing,
    setup,
    submit,
)
from tests.unit.simulation.test_options_historical_execution import scenario
from tests.unit.simulation.test_options_historical_restart import api, resume
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain.enums import OrderState
from trading_bot.market_data.options_source_models import SourceEvidenceError


def _load(clock, reference, repository_root):
    return api().load_clock_checkpoint(
        reference,
        initial=clock.initial,
        prefix=clock._prefix,
        loaded=clock.loaded,
        scenario=clock.scenario,
        seed=clock.seed,
        repository_root=repository_root,
    )


def _saved(tmp_path, clock):
    root, repository = tmp_path / "checkpoints", tmp_path / "repository"
    root.mkdir(mode=0o700)
    repository.mkdir(mode=0o700)
    reference = api().save_clock_checkpoint(clock, root=root, repository_root=repository)
    return reference, repository


@pytest.mark.parametrize(
    "action",
    [
        [],
        ["time"],
        ["time", 1, None],
        [True, 1],
        {"name": "time", "value": 1},
        ["unrecognized-operation", 1],
        ["time", True],
        ["time", "1704205800000000000"],
        ["time", None],
        ["quote", []],
        ["submit", []],
        ["submit", ["episode", "session", {}, 1, "extra"]],
        ["submit", ["episode", "session", [], 1]],
        ["cancel", []],
        ["cancel", ["order"]],
        ["cancel", ["order", 1, "extra"]],
        ["watch", []],
        ["watch", [{}, {}, "extra"]],
        ["watch", [{}, {"unexpected": True}]],
    ],
)
def test_malformed_commands_deny_even_with_fresh_outer_digest(tmp_path, monkeypatch, action):
    clock, _, _ = setup(tmp_path, monkeypatch)
    payload = json.loads(api().encode_clock_checkpoint(clock))
    payload["actions"] = [action]
    before = clock.result()
    with pytest.raises(SourceEvidenceError):
        resume(clock, body=json.dumps(payload).encode())
    assert clock.result() == before


@pytest.mark.parametrize("schema", ["options-clock-checkpoint-v2", "pickle", None, 1, True])
def test_unknown_or_nontext_schema_has_no_fallback(tmp_path, monkeypatch, schema):
    clock, _, _ = setup(tmp_path, monkeypatch)
    payload = json.loads(api().encode_clock_checkpoint(clock))
    payload["schema"] = schema
    with pytest.raises(SourceEvidenceError):
        resume(clock, body=json.dumps(payload).encode())


@pytest.mark.parametrize("payload", [b"\x80\x04N.", b"{", b"null", b"[]", b"\xff"])
def test_non_json_and_non_object_inputs_never_load_as_checkpoints(tmp_path, monkeypatch, payload):
    clock, _, _ = setup(tmp_path, monkeypatch)
    with pytest.raises(SourceEvidenceError):
        resume(clock, body=payload)


@pytest.mark.parametrize("field", ["event_ns", "available_ns", "record_ordinal"])
@pytest.mark.parametrize("value", [True, "1", 1.0])
def test_quote_integer_fields_cannot_coerce_types(tmp_path, monkeypatch, field, value):
    clock, _, events = setup(tmp_path, monkeypatch)
    clock.advance(events[0])
    payload = json.loads(api().encode_clock_checkpoint(clock))
    payload["actions"][0][1][field] = value
    with pytest.raises(SourceEvidenceError):
        resume(clock, body=json.dumps(payload).encode())


def test_duplicate_root_keys_cannot_override_schema(tmp_path, monkeypatch):
    clock, _, _ = setup(tmp_path, monkeypatch)
    body = api().encode_clock_checkpoint(clock)
    body = b'{"schema":"unknown",' + body[1:]
    with pytest.raises(SourceEvidenceError):
        resume(clock, body=body)


def test_restore_rejects_oversized_input_before_json_parsing(tmp_path, monkeypatch):
    clock, _, _ = setup(tmp_path, monkeypatch)
    body = b" " * (clock.loaded.config.options.replay_max_bytes + 1)
    with pytest.raises(SourceEvidenceError):
        resume(clock, body=body)


def test_restore_rejects_excess_commands_even_when_they_are_noops(tmp_path, monkeypatch):
    clock, _, _ = setup(tmp_path, monkeypatch)
    payload = json.loads(api().encode_clock_checkpoint(clock))
    payload["actions"] = [
        ["time", clock.now_ns] for _ in range(clock.loaded.config.options.replay_max_records + 1)
    ]
    with pytest.raises(SourceEvidenceError):
        resume(clock, body=json.dumps(payload).encode())


def test_encode_rejects_excess_recorded_commands(tmp_path, monkeypatch):
    clock, _, _ = setup(tmp_path, monkeypatch)
    for _ in range(clock.loaded.config.options.replay_max_records + 1):
        clock.advance_time(clock.now_ns)
    with pytest.raises(SourceEvidenceError):
        api().encode_clock_checkpoint(clock)


def test_restore_rejects_deeply_nested_actions(tmp_path, monkeypatch):
    clock, _, _ = setup(tmp_path, monkeypatch)
    payload = json.loads(api().encode_clock_checkpoint(clock))
    value = []
    for _ in range(clock.loaded.config.options.replay_max_json_depth + 1):
        value = [value]
    payload["actions"] = value
    with pytest.raises(SourceEvidenceError):
        resume(clock, body=json.dumps(payload).encode())


@pytest.mark.parametrize("kind", ["file-symlink", "file-hardlink", "world-readable"])
def test_load_and_save_deny_unsafe_existing_checkpoint_file(tmp_path, monkeypatch, kind):
    clock, _, _ = setup(tmp_path, monkeypatch)
    reference, repository = _saved(tmp_path, clock)
    original = reference.path.read_bytes()
    if kind == "file-symlink":
        target = reference.path.with_name("retained-original.json")
        reference.path.rename(target)
        reference.path.symlink_to(target)
    elif kind == "file-hardlink":
        target = reference.path.with_name("hardlink-alias.json")
        os.link(reference.path, target)
    else:
        reference.path.chmod(0o644)
    with pytest.raises(SourceEvidenceError):
        _load(clock, reference, repository)
    with pytest.raises(SourceEvidenceError):
        api().save_clock_checkpoint(clock, root=reference.path.parent, repository_root=repository)
    assert reference.path.read_bytes() == original


def test_parent_directory_symlink_is_not_a_private_storage_escape(tmp_path, monkeypatch):
    clock, _, _ = setup(tmp_path, monkeypatch)
    reference, repository = _saved(tmp_path, clock)
    alias = tmp_path / "checkpoint-alias"
    alias.symlink_to(reference.path.parent, target_is_directory=True)
    with pytest.raises(SourceEvidenceError):
        _load(clock, replace(reference, path=alias / reference.path.name), repository)
    with pytest.raises(SourceEvidenceError):
        api().save_clock_checkpoint(clock, root=alias, repository_root=repository)


@pytest.mark.parametrize("change", ["byte-count", "public-parent", "non-reference"])
def test_load_validates_the_reference_and_directory(tmp_path, monkeypatch, change):
    clock, _, _ = setup(tmp_path, monkeypatch)
    reference, repository = _saved(tmp_path, clock)
    if change == "byte-count":
        reference = replace(reference, byte_count=reference.byte_count + 1)
    elif change == "public-parent":
        reference.path.parent.chmod(0o755)
    else:
        reference = {"path": reference.path, "sha256": reference.sha256}
    with pytest.raises(SourceEvidenceError):
        _load(clock, reference, repository)


@pytest.mark.parametrize("change", ["canonical", "digest", "valid-different-config"])
def test_restart_does_not_accept_unbound_configuration(tmp_path, monkeypatch, change):
    clock, order, _ = setup(tmp_path, monkeypatch)
    submit(clock, order)
    loaded = clock.loaded
    if change == "canonical":
        loaded = replace(loaded, canonical_json=b"{}")
    elif change == "digest":
        loaded = replace(loaded, config_hash="a" * 64)
    else:
        config = loaded.config.model_copy(
            update={
                "options": loaded.config.options.model_copy(
                    update={"replay_max_records": loaded.config.options.replay_max_records - 1}
                )
            }
        )
        canonical, digest = hash_loaded_config(config, loaded.safety_envelope)
        loaded = replace(loaded, config=config, canonical_json=canonical, config_hash=digest)
    with pytest.raises(SourceEvidenceError):
        resume(clock, loaded=loaded)


@pytest.mark.parametrize("field", ["code_hash", "genesis_hash", "prefix_hash", "scenario_hash"])
def test_inner_binding_substitution_fails_despite_rehashed_envelope(tmp_path, monkeypatch, field):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock.advance(events[0])
    payload = json.loads(api().encode_clock_checkpoint(clock))
    payload[field] = "a" * 64
    with pytest.raises(SourceEvidenceError):
        resume(clock, body=json.dumps(payload).encode())


@pytest.mark.parametrize("state", ["gap", "reset", "halt", "session_boundary"])
def test_recordless_controls_round_trip_without_becoming_fillable_quotes(
    tmp_path, monkeypatch, state
):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    control = replace(
        events[0], record=None, state=state, record_ordinal=None, quality_reasons=("uninitialized",)
    )
    clock.advance(control)
    restored = resume(clock)
    assert restored.result() == clock.result()
    assert restored.result().net_cash_flow == 0
    assert not restored.state.positions
    assert api().encode_clock_checkpoint(restored) == api().encode_clock_checkpoint(clock)


@pytest.mark.parametrize(
    "assumptions,expected_state,reservation",
    [
        (scenario(reject_ppm=1000000), OrderState.REJECTED, Decimal(0)),
        (
            scenario(ambiguous_ppm=1000000),
            OrderState.UNKNOWN_REQUIRES_RECONCILIATION,
            Decimal("26"),
        ),
    ],
)
def test_terminal_or_unknown_order_prefix_preserves_denial_and_reservations(
    tmp_path, monkeypatch, assumptions, expected_state, reservation
):
    original, order, events = setup(tmp_path, monkeypatch, assumptions=assumptions)
    submit(original, order)
    original.advance(events[0])
    assert original.result().orders[0].state is expected_state
    continued = type(original)(
        original.initial,
        original.journal,
        loaded=original.loaded,
        scenario=original.scenario,
        seed=original.seed,
    )
    continued.advance(events[1])
    restored = resume(continued)
    assert restored.result() == continued.result()
    restored.advance(events[2])
    continued.advance(events[2])
    assert restored.result() == continued.result()
    assert restored.result().orders[0].state is expected_state
    assert restored.state.cash == Decimal("10000") and restored.state.fees == 0
    assert restored.state.trial.reserved_risk == reservation
    assert not restored.state.positions


def test_completed_cash_prefix_is_not_replayed_as_new_fills(tmp_path, monkeypatch):
    original, order, events = setup(tmp_path, monkeypatch)
    attach_calendar(original, order)
    submit(original, order)
    original.advance(events[0])
    original.advance(events[1])
    submit(original, closing(order, events[1].available_ns))
    original.advance(events[2])
    original.advance(events[3])
    original.advance_time(events[3].available_ns + 10)
    assert original.result().status == "completed"
    continued = type(original)(
        original.initial,
        original.journal,
        loaded=original.loaded,
        scenario=original.scenario,
        seed=original.seed,
    )
    restored = resume(continued)
    assert restored.result() == continued.result()
    assert restored.state.cash == Decimal("9994") and restored.state.fees == Decimal("1")
    assert restored.result().net_cash_flow == restored.result().fees == 0
    assert restored.state.trial.consumed_loss == Decimal("6")
    assert restored.state.trial.reserved_risk == 0
    restored.advance_time(restored.now_ns + 1)
    assert restored.state.cash == Decimal("9994") and restored.state.fees == Decimal("1")
