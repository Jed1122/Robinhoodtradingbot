"""Evidence-bound whole-chain reconstruction, with no implicit contract economics."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

from trading_bot.clock import require_utc
from trading_bot.config import LoadedConfig
from trading_bot.config.hashing import hash_loaded_config
from trading_bot.domain import DataHash
from trading_bot.domain.options import (
    ExerciseStyle,
    OptionContract,
    OptionKind,
    SettlementKind,
    SettlementTiming,
)
from trading_bot.market_data.bundle_codec import _array, _digest, _integer, _json, _mapping, _string
from trading_bot.market_data.databento_bar_models import native_limits
from trading_bot.market_data.databento_bar_wire import bounds
from trading_bot.market_data.databento_native_rows import NativeDefinitionRow, read_definition_rows
from trading_bot.market_data.databento_stage import verify_staged
from trading_bot.market_data.options_data_codec import _contract
from trading_bot.market_data.options_records import ChainSnapshot, OptionsDataRecord, select_chain
from trading_bot.market_data.options_session_inputs import _fact, _ns
from trading_bot.market_data.options_source_models import (
    PrivateArtifactRef,
    SourceEvidenceBundle,
    SourceVerification,
    check,
    hashes,
)
from trading_bot.market_data.options_source_rules import source_code_hash
from trading_bot.market_data.options_source_verify import _snapshots
from trading_bot.market_data.recording import content_hash

REASONS = frozenset(
    {
        "source_scope_mismatch",
        "source_integrity_invalid",
        "source_limit_exceeded",
        "chain_baseline_unverified",
        "chain_coverage_unverified",
        "definition_state_conflict",
        "definition_mapping_unverified",
        "contract_terms_unverified",
        "calendar_unverified",
        "chain_empty",
    }
)


class _Denied(ValueError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise _Denied(reason)


@dataclass(frozen=True, slots=True)
class ContractReferenceInput:
    references: tuple[PrivateArtifactRef, ...]
    claim_hashes: tuple[DataHash, ...]

    def __post_init__(self) -> None:
        check(type(self.references) is tuple and len(self.references) <= 25000)
        check(all(type(item) is PrivateArtifactRef for item in self.references))
        check(len({item.sha256 for item in self.references}) == len(self.references))
        hashes(self.claim_hashes)


@dataclass(frozen=True, slots=True)
class DefinitionInputs:
    records: tuple[OptionsDataRecord, ...]
    contract_ids: tuple[str, ...]
    visible_hash: DataHash
    visible_native_hashes: tuple[DataHash, ...]
    baseline_verified: bool
    update_count: int
    delete_count: int
    reasons: tuple[str, ...]
    production_eligible: Literal[False] = field(default=False, init=False)
    evidence_promotable: Literal[False] = field(default=False, init=False)
    download_authorized: Literal[False] = field(default=False, init=False)
    live_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        check(type(self.records) is tuple and len(self.records) <= 10001)
        check(all(type(record) is OptionsDataRecord for record in self.records))
        check(type(self.contract_ids) is tuple and len(self.contract_ids) <= 10000)
        check(all(type(item) is str and 0 < len(item) <= 1024 for item in self.contract_ids))
        check(self.contract_ids == tuple(sorted(set(self.contract_ids))))
        hashes((self.visible_hash,))
        hashes(self.visible_native_hashes)
        check(type(self.baseline_verified) is bool)
        for count in (self.update_count, self.delete_count):
            check(type(count) is int and 0 <= count <= 25000)
        check(type(self.reasons) is tuple and all(reason in REASONS for reason in self.reasons))
        check(self.reasons == tuple(sorted(set(self.reasons))))
        check(bool(self.records) == bool(self.contract_ids) == (not self.reasons))


def _facts(
    reference: ContractReferenceInput,
    verification: SourceVerification,
    loaded: LoadedConfig,
    repository_root: Path,
) -> dict[str, list[dict[str, object]]]:
    _require(
        all(item.sha256 in verification.source_hashes for item in reference.references),
        "source_scope_mismatch",
    )
    bodies = _snapshots(SourceEvidenceBundle((), reference.references, ()), loaded, repository_root)
    facts: dict[str, list[dict[str, object]]] = {}
    count = 0
    for body in bodies.values():
        decoded = _json(
            body,
            max_bytes=loaded.config.options.research_shortlist.max_input_bytes,
            limits=bounds(loaded),
        )
        check(type(decoded) is dict)
        keys = {"schema", "source_id", "role", "era_start_ns", "era_end_ns", "records"}
        if "invalidations" in cast(dict[str, object], decoded):
            keys.add("invalidations")
        document = _mapping(decoded, keys)
        # No installed provider rules use this fixed protocol; provider prose cannot qualify.
        check(document["schema"] == "synthetic-source-records-v1")
        check(_string(document["source_id"]).startswith("synthetic."))
        role = _string(document["role"])
        for value in _array(document["records"]):
            count += 1
            _require(
                count <= loaded.config.options.research_shortlist.max_input_records,
                "source_limit_exceeded",
            )
            envelope = _mapping(
                value, {"published_at_ns", "effective_start_ns", "effective_end_ns", "record"}
            )
            fact = envelope["record"]
            check(type(fact) is dict)
            if _fact(verification, role, fact):
                facts.setdefault(role, []).append(cast(dict[str, object], fact))
    return facts


def _state(
    facts: dict[str, list[dict[str, object]]],
    verification: SourceVerification,
    profile: dict[str, object],
) -> dict[str, object]:
    items = [
        item for item in facts.get("definition_state", ()) if item.get("kind") == "definition_state"
    ]
    _require(len(items) == 1, "chain_baseline_unverified")
    state = _mapping(
        items[0],
        {
            "kind",
            "as_of_ns",
            "start_ns",
            "end_ns",
            "query_start_ns",
            "query_end_ns",
            "baseline_at_ns",
            "baseline_hashes",
            "publications",
            "mappings",
            "partial_symbol_count",
            "partial_coverage",
        },
    )
    context = verification.context
    request = cast(dict[str, object], profile["request"])
    _require(
        (state["as_of_ns"], state["start_ns"], state["end_ns"])
        == (context.as_of_ns, context.start_ns, context.end_ns)
        and state["query_start_ns"] == request["start"]
        and state["query_end_ns"] == request["end"],
        "source_scope_mismatch",
    )
    baseline = state["baseline_at_ns"]
    _require(
        type(baseline) is int and cast(int, request["start"]) <= baseline <= context.as_of_ns,
        "chain_baseline_unverified",
    )
    partial = cast(dict[str, object], profile["metadata"])["partial_symbol_count"]
    _require(
        type(state["partial_symbol_count"]) is int and state["partial_symbol_count"] == partial,
        "chain_coverage_unverified",
    )
    coverage = _array(state["partial_coverage"])
    _require(len(coverage) == partial, "chain_coverage_unverified")
    for entry in coverage:
        row = _mapping(entry, {"symbol", "start_ns", "end_ns"})
        _require(
            partial == 1
            and row["symbol"] == "SPY.OPT"
            and _integer(row["start_ns"]) == request["start"]
            and context.as_of_ns < _integer(row["end_ns"]) <= cast(int, request["end"]),
            "chain_coverage_unverified",
        )
    _require(profile["outside_requested_receive_window_rows"] == 0, "chain_coverage_unverified")
    return state


def _mapping_index(mappings: list[object]) -> dict[tuple[int, int], list[dict[str, object]]]:
    result: dict[tuple[int, int], list[dict[str, object]]] = {}
    for value in mappings:
        item = _mapping(
            value, {"publisher_id", "instrument_id", "raw_symbol", "start_ns", "end_ns"}
        )
        key = (_integer(item["publisher_id"]), _integer(item["instrument_id"]))
        check(0 <= key[0] <= 65535 and 0 <= key[1] < 2**32)
        check(_integer(item["start_ns"]) < _integer(item["end_ns"]))
        _string(item["raw_symbol"])
        result.setdefault(key, []).append(item)
    return result


def _mapping_matches(
    row: NativeDefinitionRow, mappings: dict[tuple[int, int], list[dict[str, object]]]
) -> bool:
    matches = []
    for item in mappings.get((row.publisher_id, row.instrument_id), ()):
        if cast(int, item["start_ns"]) <= cast(int, row.ts_recv) < cast(int, item["end_ns"]):
            matches.append(item)
    return len(matches) == 1 and matches[0]["raw_symbol"] == row.raw_symbol


def _members(
    rows: tuple[NativeDefinitionRow, ...], state: dict[str, object], as_of_ns: int
) -> tuple[dict[tuple[int, int], NativeDefinitionRow], tuple[DataHash, ...], int, int]:
    observed = {row.record_sha256: row for row in rows}
    publications: dict[str, int] = {}
    for value in _array(state["publications"]):
        item = _mapping(value, {"native_hash", "published_at_ns"})
        publication_hash, stamp = _digest(item["native_hash"]), _integer(item["published_at_ns"])
        _require(publication_hash not in publications, "chain_coverage_unverified")
        publications[publication_hash] = stamp
    _require(set(publications) == set(observed), "chain_coverage_unverified")
    visible = {digest: row for digest, row in observed.items() if publications[digest] <= as_of_ns}
    revisions: dict[tuple[object, ...], str] = {}
    mappings = _mapping_index(_array(state["mappings"]))
    for digest, row in visible.items():
        _require(
            row.ts_recv is not None
            and row.ts_event is not None
            and 0 < row.ts_event <= row.ts_recv <= publications[digest],
            "chain_coverage_unverified",
        )
        revision_key = (row.publisher_id, row.instrument_id, row.ts_event, row.ts_recv)
        _require(
            revision_key not in revisions or revisions[revision_key] == digest,
            "definition_state_conflict",
        )
        revisions[revision_key] = digest
        _require(_mapping_matches(row, mappings), "definition_mapping_unverified")
        _require(row.security_update_action in {"A", "M", "D"}, "definition_state_conflict")
    baseline = cast(int, state["baseline_at_ns"])
    baseline_hashes = tuple(_digest(item) for item in _array(state["baseline_hashes"]))
    _require(len(set(baseline_hashes)) == len(baseline_hashes), "chain_baseline_unverified")
    members: dict[tuple[int, int], NativeDefinitionRow] = {}
    for digest in baseline_hashes:
        _require(
            digest in visible and publications[digest] <= baseline, "chain_baseline_unverified"
        )
        row = visible[digest]
        key = (row.publisher_id, row.instrument_id)
        _require(
            key not in members and row.security_update_action != "D", "definition_state_conflict"
        )
        members[key] = row
    updates = deletes = 0
    events = sorted(
        (row for digest, row in visible.items() if publications[digest] > baseline),
        key=lambda row: (
            publications[row.record_sha256],
            row.ts_event,
            row.ts_recv,
            row.publisher_id,
            row.instrument_id,
        ),
    )
    for row in events:
        key = (row.publisher_id, row.instrument_id)
        previous = members.get(key)
        if row.security_update_action == "A":
            _require(previous is None, "definition_state_conflict")
            members[key] = row
            updates += 1
        else:
            _require(
                previous is not None and previous.raw_symbol == row.raw_symbol,
                "definition_state_conflict",
            )
            if row.security_update_action == "D":
                del members[key]
                deletes += 1
            else:
                members[key] = row
                updates += 1
    return members, tuple(sorted(DataHash(digest) for digest in visible)), updates, deletes


def _enrich(
    row: NativeDefinitionRow, facts: dict[str, list[dict[str, object]]], as_of: datetime
) -> OptionContract:
    items = [
        item
        for item in facts.get("contract_terms", ())
        if item.get("native_hash") == row.record_sha256
    ]
    _require(len(items) == 1, "contract_terms_unverified")
    item = _mapping(items[0], {"kind", "native_hash", "contract"})
    _require(item["kind"] == "contract_terms", "contract_terms_unverified")
    try:
        contract = _contract(item["contract"])
        strike_code = contract.strike * 1000
        symbol = (
            f"SPY   {contract.expiration:%y%m%d}{contract.kind.value[0].upper()}"
            f"{int(strike_code):08d}"
        )
        _require(
            strike_code == strike_code.to_integral_value()
            and 0 < strike_code <= 99999999
            and row.raw_symbol == contract.standardized_id == symbol
            and contract.contract_id == symbol
            and contract.underlying == "SPY"
            and row.strike_price == contract.strike * 10**9
            and row.instrument_class == ("C" if contract.kind is OptionKind.CALL else "P")
            and row.expiration == _ns(datetime.combine(contract.expiration, time(), UTC))
            and contract.premium_multiplier == contract.deliverable_units == Decimal(100)
            and contract.deliverable_symbol == "SPY"
            and contract.currency == "USD"
            and contract.exercise_style is ExerciseStyle.AMERICAN
            and contract.settlement_kind is SettlementKind.SHARES
            and contract.settlement_timing is SettlementTiming.PM
            and not contract.adjusted
            and contract.available_at <= as_of < contract.last_trading_at
            and any(
                session.opens_at <= as_of < session.closes_at
                for session in contract.eligible_sessions
            )
            and contract.eligible_sessions[-1].closes_at == contract.last_trading_at,
            "contract_terms_unverified",
        )
    except Exception:
        raise _Denied("contract_terms_unverified") from None
    calendar = {
        "kind": "contract_sessions",
        "standardized_id": row.raw_symbol,
        "eligible_sessions": contract.eligible_sessions,
        "last_trading_at": contract.last_trading_at,
        "settlement_at": contract.settlement_at,
    }
    _require(
        any(content_hash(calendar) == content_hash(value) for value in facts.get("calendar", ())),
        "calendar_unverified",
    )
    return replace(
        contract,
        available_at=as_of,
        data_hash=str(content_hash({"native_hash": row.record_sha256, "terms": item})),
    )


def assemble_definition_inputs(
    manifest_path: Path,
    reference: ContractReferenceInput,
    *,
    verification: SourceVerification,
    as_of: datetime,
    loaded: LoadedConfig,
    repository_root: Path,
) -> DefinitionInputs:
    check(type(reference) is ContractReferenceInput and type(verification) is SourceVerification)
    require_utc(as_of)
    native_limits(loaded)
    visible: tuple[DataHash, ...] = ()
    baseline = False
    updates = deletes = 0
    try:
        canonical, config_hash = hash_loaded_config(loaded.config, loaded.safety_envelope)
        _require(
            config_hash == loaded.config_hash == verification.context.config_hash
            and canonical == loaded.canonical_json
            and verification.context.code_hash == source_code_hash()
            and verification.context.as_of_ns == _ns(as_of)
            and manifest_path.stem in verification.source_hashes
            and bool(reference.claim_hashes)
            and set(reference.claim_hashes) <= set(verification.visible_claim_hashes),
            "source_scope_mismatch",
        )
        facts = _facts(reference, verification, loaded, repository_root)
        manifest = verify_staged(manifest_path, repository_root=repository_root)
        profile = cast(dict[str, object], manifest["validation"])
        state = _state(facts, verification, profile)
        rows = []
        for row in read_definition_rows(
            manifest_path,
            start_ns=cast(int, state["query_start_ns"]),
            end_ns=_ns(as_of) + 1,
            loaded=loaded,
            repository_root=repository_root,
        ):
            rows.append(row)
            _require(
                len(rows) <= loaded.config.options.research_shortlist.max_input_records,
                "source_limit_exceeded",
            )
        members, visible, updates, deletes = _members(tuple(rows), state, _ns(as_of))
        baseline = True
        _require(len(members) <= 10000, "source_limit_exceeded")
        _require(bool(members), "chain_empty")
        contracts = tuple(
            sorted(
                (_enrich(row, facts, as_of) for row in members.values()),
                key=lambda c: c.contract_id,
            )
        )
        identifiers = tuple(contract.contract_id for contract in contracts)
        _require(len(set(identifiers)) == len(identifiers), "definition_state_conflict")
        raw_hash = str(
            content_hash(
                {
                    "visible_native_hashes": visible,
                    "contracts": contracts,
                    "config_hash": verification.context.config_hash,
                    "code_hash": verification.context.code_hash,
                    "rulebook_hash": verification.context.rulebook_hash,
                }
            )
        )
        records = tuple(
            OptionsDataRecord("OPRA.PILLAR", "imported", raw_hash, as_of, as_of, contract)
            for contract in contracts
        )
        records += (
            OptionsDataRecord(
                "OPRA.PILLAR", "imported", raw_hash, as_of, as_of, ChainSnapshot("SPY", identifiers)
            ),
        )
        check(
            select_chain(records, source="OPRA.PILLAR", underlying="SPY", as_of=as_of) == contracts
        )
        return DefinitionInputs(
            records, identifiers, content_hash(records), visible, baseline, updates, deletes, ()
        )
    except _Denied as exc:
        reason = str(exc)
    except Exception:
        reason = "source_integrity_invalid"
    return DefinitionInputs(
        (),
        (),
        content_hash({"as_of": as_of, "visible": visible, "reason": reason}),
        visible,
        baseline,
        updates,
        deletes,
        (reason,),
    )
