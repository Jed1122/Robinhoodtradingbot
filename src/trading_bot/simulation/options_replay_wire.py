"""Closed, bounded saved-input format for fabricated options engineering replays.

Hashes bind content and canonical configuration, not authenticity or market provenance.
No credentials, embedded configuration, file references or transport dispatch are accepted.
"""

from dataclasses import fields
from decimal import Decimal
from typing import cast

from trading_bot.config import LoadedConfig, enforce_safety_envelope
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import Bar, InstrumentId
from trading_bot.domain.options import OptionContract, OptionQuote
from trading_bot.domain.options_serialization import _decode
from trading_bot.market_data.bundle_codec import (
    _array,
    _boolean,
    _decimal,
    _digest,
    _integer,
    _json,
    _mapping,
    _string,
    _strings,
    _time,
    _value,
)
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.risk.options_economics import TrialEpisode, TrialLossState
from trading_bot.simulation.options_replay_models import (
    SOURCE,
    OptionsReplayEvent,
    OptionsReplayRequest,
)
from trading_bot.strategies.protocol import HistoricalSlice

SCHEMA = "synthetic-options-replay-input-v1"


class OptionsReplayFileError(ValueError):
    """Sanitized failure without raw input values or underlying exception context."""

    def __init__(self) -> None:
        super().__init__("options_replay_input_invalid")


def _require(valid: bool) -> None:
    if not valid:
        raise OptionsReplayFileError()


def replay_file_limits(loaded: LoadedConfig) -> BundleLimits:
    """Reuse the release envelope and bounded bundle codec, not a second config graph."""
    _require(type(loaded) is LoadedConfig)
    enforce_safety_envelope(loaded.config, loaded.safety_envelope)
    canonical, digest = hash_loaded_config(loaded.config, loaded.safety_envelope)
    _require(canonical == loaded.canonical_json and digest == loaded.config_hash)
    _require(loaded.config.options.enabled and not loaded.config.live_trading_enabled)
    options = loaded.config.options
    return BundleLimits(
        options.replay_max_bytes,
        options.replay_max_bytes,
        options.replay_max_bytes,
        options.replay_max_records,
        options.replay_max_json_depth,
    )


def _payload(request: OptionsReplayRequest) -> dict[str, object]:
    return {f.name: getattr(request, f.name) for f in fields(request) if f.name != "loaded"}


def _document(request: OptionsReplayRequest) -> dict[str, object]:
    row = {
        "schema": SCHEMA,
        "config_hash": request.loaded.config_hash,
        "payload": _payload(request),
    }
    return {**row, "document_hash": content_hash(row)}


def _count_records(value: object, limit: int) -> None:
    # Count every array item (including sessions, flags and trial history) before decoding.
    pending = [value]
    count = 0
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            count += len(item)
            _require(count <= limit)
            pending.extend(item)


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else _decimal(value)


def _quote(value: object) -> OptionQuote:
    row = _mapping(value, {f.name for f in fields(OptionQuote)})
    return OptionQuote(
        contract_id=_string(row["contract_id"]),
        bid=_decimal(row["bid"]),
        ask=_decimal(row["ask"]),
        bid_size=None if row["bid_size"] is None else _integer(row["bid_size"]),
        ask_size=None if row["ask_size"] is None else _integer(row["ask_size"]),
        event_at=_time(row["event_at"]),
        received_at=_time(row["received_at"]),
        underlying_event_at=_time(row["underlying_event_at"]),
        source=_string(row["source"]),
        data_hash=_digest(row["data_hash"]),
        quality_flags=_strings(row["quality_flags"]),
        underlying=_string(row["underlying"]),
    )


def _event(value: object) -> OptionsReplayEvent:
    row = _mapping(value, {f.name for f in fields(OptionsReplayEvent)})
    return OptionsReplayEvent(
        _string(row["event_id"]),
        _time(row["at"]),
        _string(row["action"]),
        None if row["quote"] is None else _quote(row["quote"]),
    )


def _episode(value: object) -> TrialEpisode:
    row = _mapping(value, {f.name for f in fields(TrialEpisode)})
    return TrialEpisode(
        _string(row["episode_id"]),
        _decimal(row["reserved_risk"]),
        _optional_decimal(row["net_cash_flow"]),
        _boolean(row["flat"]),
        _boolean(row["orders_terminal"]),
        _boolean(row["settlement_and_fees_final"]),
    )


def _request(value: object, loaded: LoadedConfig) -> OptionsReplayRequest:
    row = _mapping(value, {f.name for f in fields(OptionsReplayRequest)} - {"loaded"})
    history = _mapping(row["history"], {f.name for f in fields(HistoricalSlice)})
    trial = _mapping(row["trial"], {"episodes"})
    _require(row["source_kind"] == SOURCE)
    result = OptionsReplayRequest(
        loaded=loaded,
        research_capital=_decimal(row["research_capital"]),
        as_of=_time(row["as_of"]),
        history=HistoricalSlice(
            InstrumentId(_string(history["instrument_id"])),
            tuple(cast(Bar, _value("bar", bar)) for bar in _array(history["bars"])),
            _optional_decimal(history["spread_percentage"]),
            _digest(history["data_hash"]),
        ),
        contract=_decode(row["contract"], OptionContract),
        initial_quote=_quote(row["initial_quote"]),
        entry_fee=_decimal(row["entry_fee"]),
        exit_fee=_decimal(row["exit_fee"]),
        close_limit=_decimal(row["close_limit"]),
        events=tuple(_event(event) for event in _array(row["events"])),
        trial=TrialLossState(tuple(_episode(item) for item in _array(trial["episodes"]))),
    )
    # The shared options decoder accepts alternate Decimal/date spellings. The file
    # format does not: require an exact canonical round trip without rewriting hashes.
    _require(canonical_json(_payload(result)) == canonical_json(row))
    return result


def decode_options_replay(body: bytes, loaded: LoadedConfig) -> OptionsReplayRequest:
    try:
        limits = replay_file_limits(loaded)
        row = _mapping(
            _json(body, max_bytes=limits.max_blob_bytes, limits=limits),
            {"schema", "config_hash", "payload", "document_hash"},
        )
        _count_records(row, limits.max_records)
        _require(row["schema"] == SCHEMA and str(_digest(row["config_hash"])) == loaded.config_hash)
        _require(
            _digest(row["document_hash"])
            == content_hash({key: item for key, item in row.items() if key != "document_hash"})
        )
        return _request(row["payload"], loaded)
    except (ValueError, TypeError, KeyError, ArithmeticError, RecursionError):
        pass
    raise OptionsReplayFileError()


def encode_options_replay(request: OptionsReplayRequest) -> bytes:
    try:
        _require(type(request) is OptionsReplayRequest)
        body = canonical_json(_document(request)).encode()
        decode_options_replay(body, request.loaded)
        return body
    except (ValueError, TypeError, KeyError, ArithmeticError, RecursionError):
        pass
    raise OptionsReplayFileError()
