"""Bounded, non-executable checkpoints for the internal modeled lifecycle clock.

Restore replays the exact command/observation prefix instead of trusting serialized
balances or reconstructing an active order from incomplete journal projections.
The caller must retain the expected digest in its run manifest and reverify source
inputs separately. Hash consistency is not market-data or broker evidence.
"""

import hashlib
import os
from dataclasses import fields
from pathlib import Path
from typing import cast

from trading_bot.config import LoadedConfig
from trading_bot.domain import AccountId, DataHash
from trading_bot.domain.options_serialization import options_intent_from_payload
from trading_bot.lifecycle.options_expiry import OptionExpiryCalendar
from trading_bot.market_data.bundle_codec import (
    _array,
    _boolean,
    _date,
    _decimal,
    _digest,
    _integer,
    _json,
    _mapping,
    _string,
    _strings,
    _time,
)
from trading_bot.market_data.databento_bar_store import _private_root, _publish_checked, _read
from trading_bot.market_data.options_data_codec import (
    _contract,
    _session,
    decode_record,
    encode_record,
)
from trading_bot.market_data.options_quote_stream_models import (
    EventState,
    OptionsMarketEvent,
    QuoteScope,
)
from trading_bot.market_data.options_source_models import (
    PrivateArtifactRef,
    SourceEvidenceError,
    check,
)
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.options_account_journal_models import AccountJournalEntry
from trading_bot.research.options_study_models import StudyScenario
from trading_bot.research.options_study_registration import study_code_hash
from trading_bot.risk.options_loss_history import OptionsLossObservation, OptionsLossPoint
from trading_bot.simulation.options_historical_clock import _EpisodeClock
from trading_bot.simulation.options_historical_models import OptionsAccountPathState
from trading_bot.simulation.options_replay_wire import replay_file_limits


def _cursor_hash(clock: _EpisodeClock) -> DataHash:
    pending = () if clock._pending_quote is None else (clock._pending_quote,)
    return content_hash(
        (
            clock.now_ns,
            tuple(sorted(clock._seen)),
            clock._event_count,
            tuple(sorted(clock._consumed.items())),
            tuple(sorted(clock._calendars.items())),
            *pending,
        )
    )


def clock_state_hash(clock: _EpisodeClock) -> DataHash:
    """Bind continuation state without imposing optional checkpoint-file size limits.

    A bounded market-event run may produce more internal actions than events. Its
    result does not require publishing those actions as a standalone checkpoint.
    The public owner retains and replays verified inputs to recover longer runs.
    """
    check(type(clock) is _EpisodeClock)
    return content_hash(
        (
            "historical-clock-state-v1",
            study_code_hash(),
            clock.initial,
            clock._prefix,
            clock.scenario,
            clock.seed,
            clock.result(),
            _cursor_hash(clock),
        )
    )


def encode_clock_checkpoint(clock: _EpisodeClock) -> bytes:
    """Return private research bytes; no I/O, credentials, pickle or broker client."""
    check(type(clock) is _EpisodeClock)
    limits = replay_file_limits(clock.loaded)
    check(len(clock._actions) <= limits.max_records)
    actions: list[tuple[str, object]] = []
    for name, value in clock._actions:
        if name == "quote":
            event = cast(OptionsMarketEvent, value)
            value = {
                **{f.name: getattr(event, f.name) for f in fields(event) if f.init},
                "record": None if event.record is None else encode_record(event.record).decode(),
            }
        actions.append((name, value))
    body = canonical_json(
        {
            "schema": "options-clock-checkpoint-v1",
            "code_hash": study_code_hash(),
            "genesis_hash": content_hash(clock.initial),
            "prefix_hash": content_hash(clock._prefix),
            "scenario_hash": clock.scenario.scenario_hash,
            "seed": clock.seed,
            "actions": actions,
            "result_hash": content_hash(clock.result()),
            "clock_hash": _cursor_hash(clock),
        }
    ).encode()
    check(len(body) <= limits.max_envelope_bytes)
    return body


def _market(value: object, loaded: LoadedConfig) -> OptionsMarketEvent:
    row = _mapping(value, {f.name for f in fields(OptionsMarketEvent) if f.init})
    return OptionsMarketEvent(
        _integer(row["event_ns"]),
        _integer(row["available_ns"]),
        _string(row["source"]),
        _digest(row["source_hash"]),
        None if row["record_ordinal"] is None else _integer(row["record_ordinal"]),
        _string(row["symbol"]),
        cast(QuoteScope, _string(row["quote_scope"])),
        cast(EventState, _string(row["state"])),
        None
        if row["record"] is None
        else decode_record(_string(row["record"]).encode(), limits=replay_file_limits(loaded)),
        _strings(row["quality_reasons"]),
    )


def _apply(clock: _EpisodeClock, action: object) -> None:
    pair = _array(action)
    check(len(pair) == 2)
    name, value = _string(pair[0]), pair[1]
    if name == "time":
        clock.advance_time(_integer(value))
    elif name == "quote":
        clock.advance(_market(value, clock.loaded))
    elif name == "submit":
        items = _array(value)
        check(len(items) == 4)
        check(type(items[2]) is dict)
        clock.submit(
            _string(items[0]),
            _string(items[1]),
            options_intent_from_payload(
                {"schema": "options-order-intent-v1", **cast(dict[str, object], items[2])}
            ),
            available_ns=_integer(items[3]),
        )
    elif name == "cancel":
        items = _array(value)
        check(len(items) == 2)
        clock.cancel(_string(items[0]), available_ns=_integer(items[1]))
    elif name == "mark":
        items = _array(value)
        check(len(items) == 3)
        clock.mark(
            _string(items[0]),
            None if items[1] is None else _decimal(items[1]),
            available_ns=_integer(items[2]),
        )
    elif name == "flow":
        items = _array(value)
        check(len(items) == 2)
        clock.external_flow(_decimal(items[0]), available_ns=_integer(items[1]))
    elif name == "loss":
        observation = _mapping(value, {"point", "available_ns", "ordinal"})
        row = _mapping(observation["point"], {f.name for f in fields(OptionsLossPoint)})
        clock.observe_loss(
            OptionsLossObservation(
                OptionsLossPoint(
                    _string(row["event_id"]),
                    AccountId(_string(row["account_id"])),
                    _digest(row["config_hash"]),
                    _time(row["observed_at"]),
                    _string(row["session_id"]),
                    _time(row["session_open"]),
                    _time(row["session_close"]),
                    None
                    if row["previous_session_close"] is None
                    else _time(row["previous_session_close"]),
                    _decimal(row["liquidation_equity"]),
                    _decimal(row["cumulative_external_flows"]),
                    _digest(row["source_hash"]),
                    _boolean(row["complete"]),
                ),
                _integer(observation["available_ns"]),
                _integer(observation["ordinal"]),
            )
        )
    elif name == "watch":
        items = _array(value)
        check(len(items) == 2)
        row = _mapping(items[1], {f.name for f in fields(OptionExpiryCalendar)})
        calendar = OptionExpiryCalendar(
            _string(row["contract_id"]),
            _date(row["coverage_start"]),
            _date(row["coverage_end"]),
            tuple(_session(s) for s in _array(row["sessions"])),
            _boolean(row["complete"]),
            _time(row["known_at"]),
            _digest(row["evidence_hash"]),
        )
        clock.watch_expiry(_contract(items[0]), calendar)
    else:
        raise SourceEvidenceError()


def restore_clock_checkpoint(
    body: bytes,
    *,
    initial: OptionsAccountPathState,
    prefix: tuple[AccountJournalEntry, ...],
    loaded: LoadedConfig,
    scenario: StudyScenario,
    seed: int,
    expected_sha256: str,
) -> _EpisodeClock:
    """Recompute every order cursor, reservation, timer and consumed-liquidity fact."""
    try:
        limits = replay_file_limits(loaded)
        check(type(body) is bytes and len(body) <= limits.max_envelope_bytes)
        check(hashlib.sha256(body).hexdigest() == _digest(expected_sha256))
        row = _mapping(
            _json(body, max_bytes=limits.max_envelope_bytes, limits=limits),
            {
                "schema",
                "code_hash",
                "genesis_hash",
                "prefix_hash",
                "scenario_hash",
                "seed",
                "actions",
                "result_hash",
                "clock_hash",
            },
        )
        check(row["schema"] == "options-clock-checkpoint-v1")
        check(row["code_hash"] == study_code_hash())
        check(row["genesis_hash"] == content_hash(initial))
        check(row["prefix_hash"] == content_hash(prefix))
        check(row["scenario_hash"] == scenario.scenario_hash and _integer(row["seed"]) == seed)
        actions = _array(row["actions"])
        check(len(actions) <= limits.max_records)
        clock = _EpisodeClock(initial, prefix, loaded=loaded, scenario=scenario, seed=seed)
        for action in actions:
            _apply(clock, action)
        check(_digest(row["result_hash"]) == content_hash(clock.result()))
        check(_digest(row["clock_hash"]) == _cursor_hash(clock))
        return clock
    except Exception:
        raise SourceEvidenceError() from None


def save_clock_checkpoint(
    clock: _EpisodeClock, *, root: Path, repository_root: Path
) -> PrivateArtifactRef:
    """Atomic content-addressed publication outside Git; never overwrite a checkpoint."""
    try:
        body = encode_clock_checkpoint(clock)
        digest = DataHash(hashlib.sha256(body).hexdigest())
        parent = _private_root(root, repository_root)
        try:
            _publish_checked(parent, digest + ".json", body)
        finally:
            os.close(parent)
        return PrivateArtifactRef(root / (digest + ".json"), digest, len(body))
    except Exception:
        raise SourceEvidenceError() from None


def load_clock_checkpoint(
    reference: PrivateArtifactRef,
    *,
    initial: OptionsAccountPathState,
    prefix: tuple[AccountJournalEntry, ...],
    loaded: LoadedConfig,
    scenario: StudyScenario,
    seed: int,
    repository_root: Path,
) -> _EpisodeClock:
    try:
        check(type(reference) is PrivateArtifactRef)
        limits = replay_file_limits(loaded)
        check(reference.byte_count <= limits.max_envelope_bytes)
        parent = _private_root(reference.path.parent, repository_root)
        try:
            body = _read(parent, reference.path.name, limits.max_envelope_bytes)
        finally:
            os.close(parent)
        check(len(body) == reference.byte_count)
        return restore_clock_checkpoint(
            body,
            initial=initial,
            prefix=prefix,
            loaded=loaded,
            scenario=scenario,
            seed=seed,
            expected_sha256=reference.sha256,
        )
    except Exception:
        raise SourceEvidenceError() from None
