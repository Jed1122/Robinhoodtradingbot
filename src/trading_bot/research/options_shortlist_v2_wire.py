"""Closed v2 envelopes: explicit private input, path-free diagnostic output only."""

import json
from dataclasses import asdict

from trading_bot.config import LoadedConfig
from trading_bot.domain import ConfigHash
from trading_bot.market_data.bundle_codec import _array, _date, _digest, _json, _mapping
from trading_bot.market_data.databento_bar_wire import bounds
from trading_bot.market_data.options_data_codec import _session
from trading_bot.market_data.options_definition_inputs import ContractReferenceInput
from trading_bot.market_data.options_session_inputs import SessionReferenceInput
from trading_bot.market_data.options_source_models import (
    PrivateArtifactRef,
    SourceEvidenceError,
    check,
)
from trading_bot.market_data.options_source_wire import (
    _reference,
    decode_source_bundle,
    encode_source_bundle,
)
from trading_bot.market_data.recording import canonical_json
from trading_bot.research.options_shortlist_models import ShortlistCalendarDay
from trading_bot.research.options_shortlist_v2 import (
    VerifiedShortlistInput,
    VerifiedShortlistResult,
)
from trading_bot.research.options_shortlist_wire import _action


def _ref(value: PrivateArtifactRef) -> dict[str, object]:
    return {"path": str(value.path), "sha256": value.sha256, "byte_count": value.byte_count}


def encode_verified_shortlist_input(request: VerifiedShortlistInput) -> bytes:
    check(type(request) is VerifiedShortlistInput)
    return canonical_json(
        {
            "schema": "options-shortlist-input-v2",
            "bundle": json.loads(encode_source_bundle(request.bundle)),
            "bars": _ref(request.bars),
            "definitions": _ref(request.definitions),
            "session": asdict(request.session),
            "contracts": {
                "references": [_ref(ref) for ref in request.contracts.references],
                "claim_hashes": request.contracts.claim_hashes,
            },
            "config_hash": request.config_hash,
        }
    ).encode()


def decode_verified_shortlist_input(body: bytes, *, loaded: LoadedConfig) -> VerifiedShortlistInput:
    try:
        row = _mapping(
            _json(
                body,
                max_bytes=loaded.config.options.research_shortlist.max_input_bytes,
                limits=bounds(loaded),
            ),
            {"schema", "bundle", "bars", "definitions", "session", "contracts", "config_hash"},
        )
        check(row["schema"] == "options-shortlist-input-v2")
        session = _mapping(
            row["session"], {"current", "prior", "calendar_days", "actions", "claim_hashes"}
        )
        days = []
        for value in _array(session["calendar_days"]):
            day = _mapping(value, {"trading_date", "regular_session"})
            days.append(
                ShortlistCalendarDay(
                    _date(day["trading_date"]),
                    None if day["regular_session"] is None else _session(day["regular_session"]),
                )
            )
        contracts = _mapping(row["contracts"], {"references", "claim_hashes"})
        result = VerifiedShortlistInput(
            decode_source_bundle(canonical_json(row["bundle"]).encode(), loaded=loaded),
            _reference(row["bars"]),
            _reference(row["definitions"]),
            SessionReferenceInput(
                _session(session["current"]),
                None if session["prior"] is None else _session(session["prior"]),
                tuple(days),
                tuple(_action(action) for action in _array(session["actions"])),
                tuple(_digest(item) for item in _array(session["claim_hashes"])),
            ),
            ContractReferenceInput(
                tuple(_reference(item) for item in _array(contracts["references"])),
                tuple(_digest(item) for item in _array(contracts["claim_hashes"])),
            ),
            ConfigHash(_digest(row["config_hash"])),
        )
        check(result.record_count <= loaded.config.options.research_shortlist.max_input_records)
        check(
            len(body)
            + sum(item.byte_count for item in result.bundle.references + result.bundle.manifests)
            <= loaded.config.options.research_shortlist.max_input_bytes
        )
        return result
    except Exception:
        raise SourceEvidenceError() from None


def encode_verified_shortlist_result(result: VerifiedShortlistResult) -> bytes:
    check(type(result) is VerifiedShortlistResult)
    return canonical_json(asdict(result)).encode()
