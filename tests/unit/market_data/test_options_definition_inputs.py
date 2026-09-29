"""Fabricated native chain histories; no licensed data or economic assertions."""

import hashlib
import importlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.integration.market_data.test_databento_definitions import REQUEST, dbn, fixture, zstd
from tests.unit.market_data._options_source_fixtures import ROOT, config, verified_facts
from tests.unit.market_data.test_databento_batch import make_batch, no_network  # noqa: F401
from tests.unit.research._options_shortlist_fixtures import fixture_session
from trading_bot.domain import DataHash
from trading_bot.domain.options import (
    ExerciseStyle,
    OptionContract,
    OptionKind,
    SettlementKind,
    SettlementTiming,
)
from trading_bot.market_data.databento_native_rows import (
    definition_projection_hash,
    read_definition_rows,
)
from trading_bot.market_data.databento_stage import stage_batch, verify_staged
from trading_bot.market_data.options_records import select_chain
from trading_bot.market_data.options_session_inputs import _ns
from trading_bot.market_data.options_source_models import PrivateArtifactRef
from trading_bot.market_data.recording import canonical_json

AS_OF = datetime(2023, 1, 3, 14, 30, tzinfo=UTC)
OPEN = _ns(AS_OF)
BASELINE = _ns(datetime(2023, 1, 3, 8, tzinfo=UTC))
EXPIRY = date(2023, 1, 20)
CALL = "SPY   230120C00400000"
PUT = "SPY   230120P00400000"


def api():
    try:
        return importlib.import_module("trading_bot.market_data.options_definition_inputs")
    except ModuleNotFoundError:
        pytest.fail("as-known native definition assembly is not implemented")


def native(*, ident=42, symbol=CALL, stamp=BASELINE, action=None, strike=400000000000):
    return dict(
        instrument_id=ident,
        raw_symbol=symbol,
        ts_recv=stamp,
        ts_event=stamp - 1,
        strike_price=strike,
        instrument_class=dbn.InstrumentClass.PUT
        if "P" in symbol[12:13]
        else dbn.InstrumentClass.CALL,
        security_update_action=action or dbn.SecurityUpdateAction.ADD,
    )


def term(row):
    last = fixture_session(EXPIRY).closes_at
    return OptionContract(
        row.raw_symbol,
        row.raw_symbol,
        "SPY",
        OptionKind.CALL if row.instrument_class == "C" else OptionKind.PUT,
        Decimal(row.strike_price) / 10**9,
        EXPIRY,
        last,
        last + timedelta(days=3),
        ExerciseStyle.AMERICAN,
        SettlementKind.SHARES,
        SettlementTiming.PM,
        Decimal(100),
        Decimal(100),
        "SPY",
        False,
        Decimal("0.01"),
        (fixture_session(AS_OF.date()), fixture_session(EXPIRY)),
        AS_OF - timedelta(days=1),
        "a" * 64,
        "USD",
    )


def case(
    tmp_path,
    *,
    rows=None,
    baseline=True,
    terms=True,
    partial=False,
    explained=True,
    state_change=None,
    term_change=None,
    calendar=True,
    publication_changes=None,
):
    api()
    tmp_path.mkdir(mode=0o700, exist_ok=True)
    changes = rows or [native(), native(ident=43, symbol=PUT)]
    payload = fixture(count=0, metadata_changes={"partial": ["SPY.OPT"]} if partial else {})
    payload += b"".join(fixture(count=1, record_changes=change)[-520:] for change in changes)
    source = make_batch(tmp_path, payload=zstd.ZstdCompressor().compress(payload))
    target = tmp_path / "staged"
    target.mkdir(mode=0o700)
    path = stage_batch(source, target, expected=REQUEST, repository_root=ROOT)
    all_rows = tuple(
        read_definition_rows(
            path,
            start_ns=REQUEST.start_ns,
            end_ns=REQUEST.end_ns,
            loaded=config(),
            repository_root=ROOT,
        )
    )
    visible = tuple(row for row in all_rows if row.ts_recv <= OPEN)
    profile = verify_staged(path, repository_root=ROOT)["validation"]
    state = {
        "kind": "definition_state",
        "as_of_ns": OPEN,
        "start_ns": OPEN - 1,
        "end_ns": OPEN,
        "query_start_ns": REQUEST.start_ns,
        "query_end_ns": REQUEST.end_ns,
        "baseline_at_ns": BASELINE if baseline else None,
        "baseline_hashes": sorted(
            {row.record_sha256 for row in visible if row.ts_recv == BASELINE}
        ),
        "publications": [
            {
                "native_hash": row.record_sha256,
                "projection_hash": definition_projection_hash(row),
                "published_at_ns": (publication_changes or {}).get(row.record_sha256, row.ts_recv),
            }
            for row in {r.record_sha256: r for r in visible}.values()
        ],
        "mappings": [
            {
                "publisher_id": row.publisher_id,
                "instrument_id": row.instrument_id,
                "raw_symbol": row.raw_symbol,
                "start_ns": REQUEST.start_ns,
                "end_ns": REQUEST.end_ns,
            }
            for row in {
                (r.publisher_id, r.instrument_id, r.raw_symbol): r for r in visible
            }.values()
        ],
        "partial_symbol_count": profile["metadata"]["partial_symbol_count"],
        "partial_coverage": [
            {"start_ns": REQUEST.start_ns, "end_ns": OPEN + 1, "symbol": "SPY.OPT"}
        ]
        if partial and explained
        else [],
    }
    if state_change:
        state_change(state)
    facts = {"definition_state": [state]}
    if terms:
        facts["contract_terms"] = []
        if calendar:
            facts["calendar"] = []
        for row in {r.record_sha256: r for r in visible}.values():
            if row.security_update_action == "D":
                continue
            value = json.loads(canonical_json(term(row)))
            if term_change:
                term_change(value)
            facts["contract_terms"].append(
                {"kind": "contract_terms", "native_hash": row.record_sha256, "contract": value}
            )
            if calendar:
                facts["calendar"].append(
                    {
                        "kind": "contract_sessions",
                        "standardized_id": row.raw_symbol,
                        "eligible_sessions": value["eligible_sessions"],
                        "last_trading_at": value["last_trading_at"],
                        "settlement_at": value["settlement_at"],
                    }
                )
    descriptor = PrivateArtifactRef(path, DataHash(path.stem), path.stat().st_size)
    bundle, verification = verified_facts(
        tmp_path / "proof",
        facts,
        start_ns=OPEN - 1,
        end_ns=OPEN,
        as_of_ns=OPEN,
        manifests=(descriptor,),
    )
    reference = api().ContractReferenceInput(
        tuple(r for r in bundle.manifests if r.path != path), verification.visible_claim_hashes
    )
    return SimpleNamespace(
        path=path,
        reference=reference,
        verification=verification,
        rows=all_rows,
        facts=facts,
        bundle=bundle,
    )


def assemble(value, **overrides):
    args = dict(verification=value.verification, as_of=AS_OF, loaded=config(), repository_root=ROOT)
    args.update(overrides)
    return api().assemble_definition_inputs(value.path, value.reference, **args)


def test_complete_baseline_chain_retains_exact_terms_and_flags(tmp_path):
    value = case(tmp_path)
    result = assemble(value)
    assert result.contract_ids == (CALL, PUT) and result.baseline_verified
    contracts = select_chain(result.records, source="OPRA.PILLAR", underlying="SPY", as_of=AS_OF)
    assert len(contracts) == 2 and all(c.premium_multiplier == 100 for c in contracts)
    assert all(c.last_trading_at.hour == 21 and c.tick_size == Decimal("0.01") for c in contracts)
    assert not result.reasons and len(result.records) == 3
    assert not result.production_eligible and not result.evidence_promotable
    assert not result.download_authorized and not result.live_authorized


def test_future_definition_does_not_enter_open_chain(tmp_path):
    before = assemble(case(tmp_path / "before"))
    rows = [native(), native(ident=43, symbol=PUT), native(ident=44, stamp=OPEN + 1)]
    after = assemble(case(tmp_path / "after", rows=rows))
    assert after.contract_ids == before.contract_ids
    assert after.visible_hash == before.visible_hash
    assert after.visible_native_hashes == before.visible_native_hashes


@pytest.mark.parametrize(
    "terms,baseline,reason",
    [(False, True, "contract_terms_unverified"), (True, False, "chain_baseline_unverified")],
)
def test_missing_terms_or_baseline_never_get_defaults(tmp_path, terms, baseline, reason):
    result = assemble(case(tmp_path, terms=terms, baseline=baseline))
    assert result.records == () and reason in result.reasons


def test_exact_duplicate_update_is_retained_once_and_conflict_denies(tmp_path):
    update = native(stamp=BASELINE + 1000, action=dbn.SecurityUpdateAction.MODIFY)
    good = assemble(
        case(tmp_path / "good", rows=[native(), native(ident=43, symbol=PUT), update, update])
    )
    assert good.update_count == 1 and good.contract_ids == (CALL, PUT)
    conflict = {**update, "min_price_increment": 50000000}
    bad = assemble(case(tmp_path / "bad", rows=[native(), update, conflict]))
    assert bad.records == () and "definition_state_conflict" in bad.reasons


def test_visible_deletion_removes_membership(tmp_path):
    rows = [
        native(),
        native(ident=43, symbol=PUT),
        native(stamp=BASELINE + 1000, action=dbn.SecurityUpdateAction.DELETE),
    ]
    result = assemble(case(tmp_path, rows=rows))
    assert result.contract_ids == (PUT,) and result.delete_count == 1


def test_rehashed_projection_cannot_reuse_unchanged_native_publication_evidence(tmp_path):
    """Outer file integrity must not authorize a changed meaning for a native record."""
    import hashlib

    from trading_bot.market_data.options_parquet import _connection

    value = case(
        tmp_path / "original",
        rows=[
            native(),
            native(ident=43, symbol=PUT),
            native(stamp=BASELINE + 1000, action=dbn.SecurityUpdateAction.MODIFY),
        ],
    )
    manifest = json.loads(value.path.read_bytes())
    root = value.path.parent.parent
    part = manifest["files"][0]
    old_path = root / part["path"]
    changed = old_path.with_name("changed.parquet")
    connection = _connection(old_path.parent)
    try:
        connection.execute(
            "COPY (SELECT * REPLACE (CASE WHEN security_update_action = 'M' THEN 'D' "
            "ELSE security_update_action END AS security_update_action) "
            "FROM read_parquet(?, hive_partitioning=false)) TO ? (FORMAT PARQUET)",
            [str(changed), str(old_path)],
        )
    finally:
        connection.close()
    changed.chmod(0o600)
    body = changed.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    renamed = changed.with_name(digest + ".parquet")
    changed.rename(renamed)
    part.update(path=str(renamed.relative_to(root)), sha256=digest, byte_count=len(body))
    encoded = canonical_json(manifest).encode()
    path = value.path.with_name(hashlib.sha256(encoded).hexdigest() + ".json")
    path.write_bytes(encoded)
    path.chmod(0o600)
    descriptor = PrivateArtifactRef(path, DataHash(path.stem), len(encoded))
    bundle, verification = verified_facts(
        tmp_path / "reverified",
        value.facts,
        start_ns=OPEN - 1,
        end_ns=OPEN,
        as_of_ns=OPEN,
        manifests=(descriptor,),
    )
    assert verification.status == "verified"
    reference = api().ContractReferenceInput(
        tuple(r for r in bundle.manifests if r.path != path), verification.visible_claim_hashes
    )
    attacked = SimpleNamespace(path=path, reference=reference, verification=verification)
    result = assemble(attacked)
    assert result.records == ()
    assert "source_integrity_invalid" in result.reasons


def test_projection_binding_precedes_native_hash_duplicate_collapse(tmp_path, monkeypatch):
    from dataclasses import replace

    value = case(tmp_path)
    module = api()
    original = module.read_definition_rows

    def altered(*args, **kwargs):
        rows = tuple(original(*args, **kwargs))
        yield replace(rows[0], security_update_action="D")
        yield from rows

    monkeypatch.setattr(module, "read_definition_rows", altered)
    result = assemble(value)
    assert result.records == () and "source_integrity_invalid" in result.reasons


def test_unexplained_delete_and_unknown_action_deny(tmp_path):
    for name, action in (
        ("deleted", dbn.SecurityUpdateAction.DELETE),
        ("unknown", dbn.SecurityUpdateAction.INVALID),
    ):
        rows = [native(), native(ident=44, stamp=BASELINE + 1000, action=action)]
        result = assemble(case(tmp_path / name, rows=rows))
        assert result.records == () and "definition_state_conflict" in result.reasons


@pytest.mark.parametrize("explained", [False, True])
def test_partial_symbol_requires_exact_interval_explanation(tmp_path, explained):
    result = assemble(case(tmp_path, partial=True, explained=explained))
    assert bool(result.records) is explained
    if not explained:
        assert "chain_coverage_unverified" in result.reasons


@pytest.mark.parametrize(
    "field,value",
    [
        ("premium_multiplier", "10"),
        ("deliverable_units", "10"),
        ("adjusted", True),
        ("tick_size", "0"),
        ("eligible_sessions", []),
        ("exercise_style", "european"),
        ("settlement_timing", "am"),
        ("currency", "EUR"),
        ("last_trading_at", "2023-01-20T00:00:00.000000Z"),
        ("underlying", "QQQ"),
    ],
)
def test_unsupported_or_missing_terms_deny_entire_chain(tmp_path, field, value):
    result = assemble(case(tmp_path, term_change=lambda term: term.update({field: value})))
    assert result.records == () and "contract_terms_unverified" in result.reasons


@pytest.mark.parametrize(
    "change",
    [
        {"strike_price": 401000000000},
        {"raw_symbol": "SPY   230120P00400000"},
        {"expiration": 1674259200000000000},
    ],
)
def test_occ_native_terms_must_agree(tmp_path, change):
    result = assemble(case(tmp_path, rows=[{**native(), **change}]))
    assert result.records == () and "contract_terms_unverified" in result.reasons


def test_raw_multiplier_sentinel_is_not_premium_evidence(tmp_path):
    value = case(tmp_path)
    assert all(row.contract_multiplier is None for row in value.rows)
    assert assemble(value).records  # explicit independent pinned terms, not a default
    assert assemble(case(tmp_path / "missing", terms=False)).records == ()


def test_mapping_window_is_half_open(tmp_path):
    value = case(tmp_path, state_change=lambda state: state["mappings"][0].update(end_ns=BASELINE))
    result = assemble(value)
    assert result.records == () and "definition_mapping_unverified" in result.reasons


@pytest.mark.parametrize("transition", ["expired", "remapped", "overlapping"])
def test_surviving_contract_requires_unique_mapping_at_decision(tmp_path, transition):
    def change(state):
        original = state["mappings"][0]
        if transition != "overlapping":
            original["end_ns"] = OPEN
        if transition != "expired":
            state["mappings"].append(
                {
                    **original,
                    "raw_symbol": PUT if transition == "remapped" else CALL,
                    "start_ns": OPEN,
                    "end_ns": REQUEST.end_ns,
                }
            )

    result = assemble(case(tmp_path, state_change=change))
    assert result.records == () and result.contract_ids == ()
    assert "definition_mapping_unverified" in result.reasons


def test_adjacent_matching_mapping_renewal_is_valid_at_decision(tmp_path):
    def change(state):
        original = state["mappings"][0]
        state["mappings"].append({**original, "start_ns": OPEN})
        original["end_ns"] = OPEN

    result = assemble(case(tmp_path, state_change=change))
    assert result.contract_ids == (CALL, PUT)
    assert result.reasons == ()


def test_deleted_contract_needs_no_active_mapping_at_decision(tmp_path):
    rows = [
        native(),
        native(ident=43, symbol=PUT),
        native(stamp=BASELINE + 1000, action=dbn.SecurityUpdateAction.DELETE),
    ]
    result = assemble(
        case(
            tmp_path,
            rows=rows,
            state_change=lambda state: state["mappings"][0].update(end_ns=OPEN),
        )
    )
    assert result.contract_ids == (PUT,) and result.delete_count == 1
    assert result.reasons == ()


def test_calendar_role_is_independently_required(tmp_path):
    result = assemble(case(tmp_path, calendar=False))
    assert result.records == () and "calendar_unverified" in result.reasons


def test_private_reference_tampering_and_scope_substitution_deny(tmp_path):
    value = case(tmp_path)
    stale = replace(
        value.verification,
        context=replace(value.verification.context, code_hash=DataHash("0" * 64)),
    )
    assert assemble(value, verification=stale).records == ()
    value.reference.references[0].path.write_bytes(b"changed")
    assert assemble(value).records == ()


def test_unknown_baseline_cannot_be_caller_promoted(tmp_path):
    value = case(tmp_path, baseline=False)
    with pytest.raises((TypeError, ValueError)):
        replace(value.reference, verified=True)
    assert not assemble(value).baseline_verified


def test_historical_id_reuse_requires_nonoverlapping_dated_mappings(tmp_path):
    rows = [
        native(),
        native(stamp=BASELINE + 1000, action=dbn.SecurityUpdateAction.DELETE),
        native(symbol=PUT, stamp=BASELINE + 2000),
    ]

    def dated(state):
        state["mappings"][0]["end_ns"] = BASELINE + 2000
        state["mappings"][1]["start_ns"] = BASELINE + 2000

    result = assemble(case(tmp_path / "dated", rows=rows, state_change=dated))
    assert result.contract_ids == (PUT,) and result.delete_count == result.update_count == 1
    overlap = assemble(case(tmp_path / "overlap", rows=rows))
    assert overlap.records == () and "definition_mapping_unverified" in overlap.reasons


def test_one_nanosecond_late_publication_cannot_change_visible_result(tmp_path):
    before = assemble(case(tmp_path / "before"))
    future = native(ident=44, stamp=BASELINE + 1000)
    digest = hashlib.sha256(fixture(count=1, record_changes=future)[-520:]).hexdigest()
    after = assemble(
        case(
            tmp_path / "after",
            rows=[native(), native(ident=43, symbol=PUT), future],
            publication_changes={digest: OPEN + 1},
        )
    )
    assert after.contract_ids == before.contract_ids
    assert after.visible_native_hashes == before.visible_native_hashes
    assert after.visible_hash == before.visible_hash


def test_whole_chain_above_ceiling_is_not_truncated(tmp_path):
    rows = [
        native(
            ident=index + 1, symbol=f"SPY   230120C{index + 1:08d}", strike=(index + 1) * 1000000
        )
        for index in range(10001)
    ]
    result = assemble(case(tmp_path, rows=rows, terms=False))
    assert result.records == () and result.contract_ids == ()
    assert result.reasons == ("source_limit_exceeded",)
