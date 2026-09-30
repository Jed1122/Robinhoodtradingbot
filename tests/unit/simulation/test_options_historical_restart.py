"""Exact-prefix restart of modeled execution, never broker recovery evidence."""

import hashlib
import importlib
import json
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
from trading_bot.market_data.options_source_verify import ceil_available_at
from trading_bot.market_data.recording import content_hash


def api():
    try:
        return importlib.import_module("trading_bot.simulation.options_historical_restart")
    except ModuleNotFoundError:
        pytest.fail("exact-prefix clock restart is not implemented")


def resume(clock, *, body=None, digest=None, **changes):
    module = api()
    body = module.encode_clock_checkpoint(clock) if body is None else body
    args = dict(
        initial=clock.initial,
        prefix=clock._prefix,
        loaded=clock.loaded,
        scenario=clock.scenario,
        seed=clock.seed,
        expected_sha256=digest or hashlib.sha256(body).hexdigest(),
    )
    args.update(changes)
    return module.restore_clock_checkpoint(body, **args)


def test_result_identity_does_not_require_a_serializable_action_checkpoint(tmp_path, monkeypatch):
    clock, _, _ = setup(tmp_path, monkeypatch)
    for _ in range(clock.loaded.config.options.replay_max_records + 1):
        clock.advance_time(clock.now_ns)
    with pytest.raises(ValueError):
        api().encode_clock_checkpoint(clock)
    identity = api().clock_state_hash(clock)
    assert len(identity) == 64 and api().clock_state_hash(clock) == identity
    clock.advance_time(clock.now_ns + 1)
    assert api().clock_state_hash(clock) != identity


@pytest.mark.parametrize("cut", [0, 1, 2, 3, 4])
def test_active_order_restart_matches_uninterrupted_cash_and_cursor(tmp_path, monkeypatch, cut):
    clock, order, events = setup(tmp_path, monkeypatch)
    attach_calendar(clock, order)
    submit(clock, order)
    for i, event in enumerate(events[:4]):
        if i == cut:
            restored = resume(clock)
        clock.advance(event)
        if i >= cut:
            restored.advance(event)
        if i == 1:
            submit(clock, closing(order, event.available_ns))
            if i >= cut:
                submit(restored, closing(order, event.available_ns))
    if cut == 4:
        restored = resume(clock)
    assert restored.result() == clock.result()
    clock.advance_time(events[3].available_ns + 10)
    restored.advance_time(events[3].available_ns + 10)
    assert restored.result() == clock.result()
    assert restored.state.trial.consumed_loss == Decimal("6")
    assert api().encode_clock_checkpoint(restored) == api().encode_clock_checkpoint(clock)


def test_pending_cancel_survives_restart_without_extra_fill(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch, units=5)
    submit(clock, order)
    clock.advance(events[0])
    clock.cancel(order.intent_id, available_ns=clock.now_ns)
    restored = resume(clock)
    clock.advance(events[2])
    restored.advance(events[2])
    assert restored.result() == clock.result()
    assert restored.state.positions[0].units == 3


def test_consumed_native_liquidity_survives_restart(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch, units=5)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    restored = resume(clock)
    duplicate = replace(events[1], record_ordinal=99)
    restored.advance(duplicate)
    clock.advance(duplicate)
    assert restored.result() == clock.result()
    assert restored.state.positions[0].units == 3


@pytest.mark.parametrize("change", ["seed", "scenario", "genesis", "prefix", "digest"])
def test_wrong_restart_bindings_fail_closed(tmp_path, monkeypatch, change):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock.advance(events[0])
    module = api()
    body = module.encode_clock_checkpoint(clock)
    changes = {
        "seed": {"seed": 8},
        "scenario": {"scenario": replace(clock.scenario, slippage_ticks=1)},
        "genesis": {"initial": replace(clock.initial, cash=Decimal("9999"))},
        "prefix": {"prefix": clock.journal},
        "digest": {"digest": "a" * 64},
    }
    with pytest.raises(ValueError):
        resume(clock, body=body, **changes[change])


@pytest.mark.parametrize("change", ["extra", "result", "clock", "code", "action"])
def test_recomputed_outer_digest_cannot_hide_invalid_cursor(tmp_path, monkeypatch, change):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock.advance(events[0])
    payload = json.loads(api().encode_clock_checkpoint(clock))
    if change == "extra":
        payload["unexpected"] = True
    elif change == "action":
        payload["actions"][0][0] = "broker_place_order"
    else:
        payload[{"result": "result_hash", "clock": "clock_hash", "code": "code_hash"}[change]] = (
            "a" * 64
        )
    with pytest.raises(ValueError):
        resume(clock, body=json.dumps(payload).encode())


def test_failed_event_not_persisted_as_successful_cursor(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock.advance(events[0])
    before = api().encode_clock_checkpoint(clock)
    with pytest.raises(ValueError):
        clock.advance_time(clock.now_ns - 1)
    assert api().encode_clock_checkpoint(clock) == before


def test_late_duplicate_projection_remains_consumed_after_restart(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch, units=5)
    submit(clock, order)
    clock.advance(events[0])
    clock.advance(events[1])
    restored = resume(clock)
    old = events[1]
    duplicate = replace(
        old,
        available_ns=old.available_ns + 1,
        record_ordinal=99,
        record=replace(
            old.record,
            available_at=ceil_available_at(old.available_ns + 1),
            value=replace(old.record.value, data_hash=content_hash("new-projection")),
        ),
    )
    restored.advance(duplicate)
    assert restored.state.positions[0].units == 3


def test_private_checkpoint_persists_without_overwrite_and_reloads(tmp_path, monkeypatch):
    clock, order, events = setup(tmp_path, monkeypatch)
    submit(clock, order)
    clock.advance(events[0])
    root = tmp_path / "checkpoints"
    root.mkdir(mode=0o700)
    repo = tmp_path / "repo"
    repo.mkdir()
    module = api()
    ref = module.save_clock_checkpoint(clock, root=root, repository_root=repo)
    assert ref.path.stat().st_mode & 0o777 == 0o600
    assert module.save_clock_checkpoint(clock, root=root, repository_root=repo) == ref
    restored = module.load_clock_checkpoint(
        ref,
        initial=clock.initial,
        prefix=(),
        loaded=clock.loaded,
        scenario=clock.scenario,
        seed=7,
        repository_root=repo,
    )
    assert restored.result() == clock.result()
    ref.path.write_bytes(b"corrupted")
    with pytest.raises(ValueError):
        module.save_clock_checkpoint(clock, root=root, repository_root=repo)
    with pytest.raises(ValueError):
        module.load_clock_checkpoint(
            ref,
            initial=clock.initial,
            prefix=(),
            loaded=clock.loaded,
            scenario=clock.scenario,
            seed=7,
            repository_root=repo,
        )


def test_checkpoint_rejects_repository_and_public_directories(tmp_path, monkeypatch):
    clock, _, _ = setup(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir(mode=0o700)
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    for root in (repo, public):
        with pytest.raises(ValueError):
            api().save_clock_checkpoint(clock, root=root, repository_root=repo)
