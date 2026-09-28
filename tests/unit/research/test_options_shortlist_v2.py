"""End-to-end fabricated native inputs. Fixture rules are installed only by test patches."""

import hashlib
import importlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.unit.market_data import test_options_definition_inputs as definitions
from tests.unit.market_data._options_source_fixtures import ROOT, config, verified_facts
from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from tests.unit.market_data.test_options_session_inputs import case as bar_case
from tests.unit.research._options_shortlist_fixtures import (
    fixture_session,
    load_shortlist,
    make_case,
)
from trading_bot.domain import ConfigHash, DataHash
from trading_bot.market_data.options_source_models import PrivateArtifactRef, SourceRule
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.options_shortlist import select_options_shortlist
from trading_bot.research.options_shortlist_wire import encode_shortlist_input


def api(suffix=""):
    try:
        return importlib.import_module("trading_bot.research.options_shortlist_v2" + suffix)
    except ModuleNotFoundError:
        pytest.fail("independently verified v2 shortlist is not implemented")


def arrangement(
    tmp_path, *, dtes=(30,), strikes=(100, 102), missing_put=False, future=False, reverse=False
):
    module = api()
    tmp_path.mkdir(mode=0o700, exist_ok=True)
    (tmp_path / "bars").mkdir(mode=0o700)
    bars = bar_case(tmp_path / "bars", prior_day=date(2023, 1, 2), current_day=date(2023, 1, 3))
    rows = []
    for dte in dtes:
        expiry = definitions.AS_OF.date() + timedelta(days=dte)
        for kind in ("C",) if missing_put else ("C", "P"):
            for strike in strikes:
                symbol = f"SPY   {expiry:%y%m%d}{kind}{strike * 1000:08d}"
                rows.append(
                    {
                        **definitions.native(
                            ident=42 + len(rows), symbol=symbol, strike=strike * 10**9
                        ),
                        "expiration": definitions._ns(datetime.combine(expiry, time(), UTC)),
                    }
                )
    if future:
        rows.append(
            {
                **rows[0],
                "instrument_id": 999,
                "ts_event": definitions.OPEN,
                "ts_recv": definitions.OPEN + 1,
            }
        )

    def term_dates(value):
        expiry = datetime.strptime(value["standardized_id"][6:12], "%y%m%d").date()
        session = fixture_session(expiry)
        value["expiration"] = expiry.isoformat()
        value["last_trading_at"] = json.loads(canonical_json(session.closes_at))
        value["settlement_at"] = json.loads(canonical_json(session.closes_at + timedelta(days=3)))
        value["eligible_sessions"] = json.loads(
            canonical_json((fixture_session(definitions.AS_OF.date()), session))
        )

    defs = definitions.case(
        tmp_path / "definitions",
        rows=list(reversed(rows)) if reverse else rows,
        term_change=term_dates,
    )
    facts = defs.facts
    for path in (tmp_path / "bars" / "proof").glob("*.json"):
        doc = json.loads(path.read_bytes())
        facts.setdefault(doc["role"], []).extend(row["record"] for row in doc["records"])
    start = definitions._ns(bars.prior.opens_at)
    facts["definition_state"][0]["start_ns"] = start
    bar_ref = PrivateArtifactRef(
        bars.dataset.manifest_path,
        bars.dataset.manifest_hash,
        bars.dataset.manifest_path.stat().st_size,
    )
    def_ref = PrivateArtifactRef(defs.path, DataHash(defs.path.stem), defs.path.stat().st_size)
    bundle, verification = verified_facts(
        tmp_path / "combined",
        facts,
        start_ns=start,
        end_ns=definitions.OPEN,
        as_of_ns=definitions.OPEN,
        manifests=(bar_ref, def_ref),
    )
    source_refs = tuple(item for item in bundle.manifests if item not in (bar_ref, def_ref))
    request = module.VerifiedShortlistInput(
        bundle,
        bar_ref,
        def_ref,
        replace(bars.reference, claim_hashes=verification.visible_claim_hashes),
        definitions.api().ContractReferenceInput(source_refs, verification.visible_claim_hashes),
        config().config_hash,
    )
    rules = tuple(
        SourceRule(
            claim.rule_id,
            claim.role,
            claim.source_id,
            claim.schema,
            claim.era_start_ns,
            claim.era_end_ns,
            (bundle.references[0].sha256,),
            "synthetic-records-v1",
        )
        for claim in bundle.claims
    )
    return SimpleNamespace(request=request, rules=rules, verification=verification)


def install_fixture_rules(monkeypatch, value):
    from trading_bot.market_data import options_source_rules, options_source_verify

    monkeypatch.setattr(options_source_rules, "load_reviewed_rules", lambda: value.rules)
    monkeypatch.setattr(options_source_verify, "load_reviewed_rules", lambda: value.rules)


def run(value):
    return api().select_verified_shortlist(value.request, loaded=config(), repository_root=ROOT)


def test_v1_wire_and_decision_goldens_are_unchanged():
    case = make_case()
    result = select_options_shortlist(
        case,
        settings=load_shortlist().config.options.research_shortlist,
        config_hash=ConfigHash("a" * 64),
        code_hash=DataHash("b" * 64),
        input_hash=content_hash(case),
    )
    assert (
        result.decision_hash == "c8940c5243e0c7218742f9b9869d81eca0baf19d0eff7500c1e867d34906bdca"
    )
    assert (
        hashlib.sha256(encode_shortlist_input(case)).hexdigest()
        == "e76698187c69c272ec150e01090c0b2f3a2bb71ad3ee37ae81f5610360a4ed64"
    )


def test_native_simulation_profile_enables_only_offline_shortlist_composition():
    loaded = config()
    assert loaded.config.options.native_data.enabled
    assert loaded.config.options.research_shortlist.enabled
    assert not loaded.config.live_trading_enabled


def test_installed_rulebook_cannot_qualify_fixture_or_real_import(tmp_path):
    result = run(arrangement(tmp_path))
    assert result.status == "no_candidate" and not result.candidates
    assert "source_evidence_unverified" in result.reasons


@pytest.mark.parametrize(
    "dtes,chosen", [((21,), 21), ((30,), 30), ((45,), 45), ((29, 31), 29), ((21, 30, 45), 30)]
)
def test_verified_private_fixture_reuses_expiry_and_lower_strike_policy(
    tmp_path, monkeypatch, dtes, chosen
):
    value = arrangement(tmp_path, dtes=dtes)
    install_fixture_rules(monkeypatch, value)
    result = run(value)
    assert result.status == "selected", result.reasons
    assert [c.kind.value for c in result.candidates] == ["call", "put"]
    assert all(
        c.strike == Decimal(100)
        and c.expiration == definitions.AS_OF.date() + timedelta(days=chosen)
        for c in result.candidates
    )
    assert not any(
        (
            result.production_eligible,
            result.evidence_promotable,
            result.download_authorized,
            result.live_authorized,
        )
    )


def test_missing_side_denies_without_choosing_a_single_candidate(tmp_path, monkeypatch):
    value = arrangement(tmp_path, missing_put=True)
    install_fixture_rules(monkeypatch, value)
    result = run(value)
    assert result.candidates == () and result.reasons == ("no_common_eligible_expiry",)


@pytest.mark.parametrize("change", ["future", "reverse"])
def test_future_append_or_input_permutation_preserves_causal_hash(tmp_path, monkeypatch, change):
    before = arrangement(tmp_path / "before")
    after = arrangement(tmp_path / "after", **{change: True})
    install_fixture_rules(monkeypatch, before)
    a, b = run(before), run(after)
    assert a.status == b.status == "selected", (a.reasons, b.reasons)
    assert a.candidates == b.candidates and a.decision_hash == b.decision_hash
    assert a.input_hash != b.input_hash


def test_diagnostics_do_not_become_a_reusable_verification_token(tmp_path, monkeypatch):
    value = arrangement(tmp_path)
    install_fixture_rules(monkeypatch, value)
    assert run(value).status == "selected"
    with pytest.raises((TypeError, ValueError)):
        replace(value.request, verification=value.verification)
    value.request.contracts.references[0].path.write_bytes(b"changed after prior run")
    result = run(value)
    assert not result.candidates and result.verification.status == "denied"


def test_changed_rulebook_recomputes_denial(tmp_path, monkeypatch):
    value = arrangement(tmp_path)
    install_fixture_rules(monkeypatch, value)
    assert run(value).status == "selected"
    from trading_bot.market_data import options_source_rules, options_source_verify

    monkeypatch.setattr(options_source_rules, "load_reviewed_rules", lambda: ())
    monkeypatch.setattr(options_source_verify, "load_reviewed_rules", lambda: ())
    assert run(value).status == "no_candidate"


def test_returned_canonical_record_hash_substitution_is_rejected(tmp_path, monkeypatch):
    value = arrangement(tmp_path)
    install_fixture_rules(monkeypatch, value)
    original = api().assemble_definition_inputs

    def altered(*args, **kwargs):
        result = original(*args, **kwargs)
        return replace(
            result, records=(replace(result.records[0], raw_hash="f" * 64), *result.records[1:])
        )

    monkeypatch.setattr(api(), "assemble_definition_inputs", altered)
    assert run(value).reasons == ("source_integrity_invalid",)


def test_later_audit_invalidation_does_not_rewrite_as_known_candidates(tmp_path, monkeypatch):
    value = arrangement(tmp_path)
    install_fixture_rules(monkeypatch, value)
    before = run(value)
    old = next(
        ref for ref in value.request.contracts.references if ref.path.name == "contract_terms.json"
    )
    document = json.loads(old.path.read_bytes())
    document["invalidations"] = [
        {
            "affected_hash": content_hash(document["records"][0]["record"]),
            "discovered_at": "2026-09-27T00:00:00.000000Z",
            "reason": "source_invalidated",
        }
    ]
    body = canonical_json(document).encode()
    old.path.write_bytes(body)
    new = PrivateArtifactRef(old.path, DataHash(hashlib.sha256(body).hexdigest()), len(body))
    bundle = value.request.bundle
    value.request = replace(
        value.request,
        bundle=replace(
            bundle,
            manifests=tuple(new if ref == old else ref for ref in bundle.manifests),
            claims=tuple(
                replace(claim, raw_hashes=(new.sha256,))
                if claim.role == "contract_terms"
                else claim
                for claim in bundle.claims
            ),
        ),
        contracts=replace(
            value.request.contracts,
            references=tuple(
                new if ref == old else ref for ref in value.request.contracts.references
            ),
        ),
    )
    after = run(value)
    assert before.status == after.status == "selected", after.reasons
    assert before.candidates == after.candidates and before.decision_hash == after.decision_hash
    assert before.input_hash != after.input_hash and len(after.verification.invalidations) == 1


def test_complete_request_record_count_cannot_exceed_limit(tmp_path):
    value = arrangement(tmp_path)
    session = replace(
        value.request.session, calendar_days=(value.request.session.calendar_days[0],) * 25000
    )
    value.request = replace(value.request, session=session)
    with pytest.raises(ValueError):
        run(value)


def test_unrelated_quote_semantics_denial_does_not_block_shortlisting(tmp_path, monkeypatch):
    value = arrangement(tmp_path)
    install_fixture_rules(monkeypatch, value)
    bundle = value.request.bundle
    unrelated = replace(bundle.claims[0], role="quote_semantics", rule_id="unreviewed.quotes")
    value.request = replace(
        value.request, bundle=replace(bundle, claims=(*bundle.claims, unrelated))
    )
    result = run(value)
    assert result.status == "selected" and result.verification.status == "denied"
    assert any(
        f.role == "quote_semantics" and f.status == "denied" for f in result.verification.findings
    )
