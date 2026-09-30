"""Private manufactured native inputs for the offline historical episode consumer.

The deliberately sparse three-session option calendar is fabricated, not a claim
about exchange dates. All source rules remain synthetic and non-promotable. Native
bars, definitions and quotes use the real DBN and private Parquet boundaries.
"""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from tests.unit.market_data import _options_source_fixtures as source_fixtures
from tests.unit.market_data import test_options_definition_inputs as definition_fixtures
from tests.unit.market_data import test_options_session_inputs as session_fixtures
from tests.unit.market_data._native_quotes_fixtures import compressed, record
from tests.unit.research import test_options_shortlist_v2 as shortlist_fixtures
from tests.unit.research._options_shortlist_fixtures import fixture_session
from tests.unit.research.test_options_study_registration import config
from tests.unit.simulation.test_options_historical_execution import scenario as make_scenario
from trading_bot.domain import Bar
from trading_bot.domain.enums import BarInterval
from trading_bot.lifecycle.options_expiry import OptionExpiryCalendar
from trading_bot.market_data import options_source_rules, options_source_verify
from trading_bot.market_data.databento_bar_store import verify_bar_stage
from trading_bot.market_data.databento_quote_models import NativeQuoteRequest
from trading_bot.market_data.databento_quote_store import stage_quotes
from trading_bot.market_data.options_definition_inputs import (
    ContractReferenceInput,
    assemble_definition_inputs,
)
from trading_bot.market_data.options_quote_stream import QuoteFeedBinding, QuoteStreamRequest
from trading_bot.market_data.options_records import select_chain
from trading_bot.market_data.options_session_inputs import _ns, assemble_session_inputs
from trading_bot.market_data.options_source_models import PrivateArtifactRef, SourceRule
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.options_shortlist_v2 import select_verified_shortlist
from trading_bot.research.options_study_models import (
    CAPITAL_TIERS,
    REJECTION_CRITERIA,
    HistoryObservation,
    OptionsStudySpec,
    StudyFold,
    VerifiedHistoryCoverage,
)
from trading_bot.research.options_study_registration import study_code_hash, study_consumer_hash

ROOT = source_fixtures.ROOT
DAY_NS = 86400 * 10**9


def _reverify(bundle, context, loaded):
    context = replace(context, rulebook_hash=options_source_rules.reviewed_rulebook_hash())
    result = options_source_verify.verify_source_bundle(
        bundle, context=context, loaded=loaded, repository_root=ROOT
    )
    assert result.status == "verified", result.reasons
    return result


def _shortlist(tmp_path, monkeypatch, loaded):
    # Only fixture configuration and the private fixture rulebook are injected;
    # the actual parsers, verification, aggregation and shortlist remain real.
    for module in (
        source_fixtures,
        definition_fixtures,
        session_fixtures,
        shortlist_fixtures,
    ):
        monkeypatch.setattr(module, "config", lambda: loaded)
    original = shortlist_fixtures.arrangement(tmp_path / "selection", strikes=(100,))
    request = original.request
    entry = request.session.current
    expiry_day = entry.trading_date + timedelta(days=30)
    sessions = (entry, fixture_session(expiry_day - timedelta(days=1)), fixture_session(expiry_day))
    facts = {}
    for reference in request.contracts.references:
        document = json.loads(reference.path.read_bytes())
        payloads = [row["record"] for row in document["records"]]
        for payload in payloads:
            if payload["kind"] == "contract_terms":
                payload["contract"]["eligible_sessions"] = json.loads(canonical_json(sessions))
            elif payload["kind"] == "contract_sessions":
                payload["eligible_sessions"] = json.loads(canonical_json(sessions))
        facts[document["role"]] = payloads
    bundle, verified = source_fixtures.verified_facts(
        tmp_path / "shortlist-sources",
        facts,
        start_ns=_ns(request.session.prior.opens_at),
        end_ns=_ns(entry.opens_at),
        as_of_ns=_ns(entry.opens_at),
        manifests=(request.bars, request.definitions),
    )
    roles = sorted({claim.role for claim in bundle.claims} | {"quote_semantics"})
    rules = tuple(
        SourceRule(
            "fixture." + role,
            role,
            "synthetic.source",
            "synthetic-source-records-v1",
            1,
            2**63 - 1,
            (bundle.references[0].sha256,),
            "synthetic-records-v1",
        )
        for role in roles
    )
    monkeypatch.setattr(options_source_rules, "load_reviewed_rules", lambda: rules)
    monkeypatch.setattr(options_source_verify, "load_reviewed_rules", lambda: rules)
    verified = _reverify(bundle, verified.context, loaded)
    source_refs = tuple(
        ref for ref in bundle.manifests if ref not in (request.bars, request.definitions)
    )
    request = replace(
        request,
        bundle=bundle,
        session=replace(request.session, claim_hashes=verified.visible_claim_hashes),
        contracts=ContractReferenceInput(source_refs, verified.visible_claim_hashes),
    )
    selected = select_verified_shortlist(request, loaded=loaded, repository_root=ROOT)
    assert selected.status == "selected", selected.reasons
    definitions = assemble_definition_inputs(
        request.definitions.path,
        request.contracts,
        verification=selected.verification,
        as_of=entry.opens_at,
        loaded=loaded,
        repository_root=ROOT,
    )
    contracts = select_chain(
        definitions.records, source="OPRA.PILLAR", underlying="SPY", as_of=entry.opens_at
    )
    assert tuple(c.standardized_id for c in contracts) == tuple(
        c.standardized_id for c in selected.candidates
    )
    prior = assemble_session_inputs(
        verify_bar_stage(request.bars.path, loaded=loaded, repository_root=ROOT),
        request.session,
        verification=selected.verification,
        loaded=loaded,
        repository_root=ROOT,
    )
    assert not prior.reasons and prior.bar is not None
    assert all(c.reference_close_hash == content_hash(prior.bar) for c in selected.candidates)
    return request, contracts, sessions, prior


def _quote_feeds(tmp_path, loaded, contracts, sessions):
    start, end = _ns(sessions[0].opens_at), _ns(sessions[-1].closes_at) + 1000
    feeds = []
    for underlying in (True, False):
        label = "underlying" if underlying else "options"
        symbols = ("SPY",) if underlying else tuple(sorted(c.standardized_id for c in contracts))
        query = NativeQuoteRequest(
            "XNAS.ITCH" if underlying else "OPRA.PILLAR",
            "mbp-1" if underlying else "cmbp-1",
            "raw_symbol",
            symbols,
            start,
            end,
        )
        rows = []
        # Different observation times, not repeated same-time books. The first
        # quote supports a decision; later quotes support acknowledgement/fill.
        for session in sessions:
            for tick in range(1, 7):
                stamp = _ns(session.opens_at) + tick * 1000
                for index, _symbol in enumerate(symbols):
                    rows.append(
                        record(
                            underlying=underlying,
                            stamp=stamp,
                            recv=stamp + index,
                            instrument_id=42 + index,
                            flags=160,
                            sequence=tick,
                            bid=100000000000 if underlying else 90000000,
                            ask=100010000000 if underlying else 100000000,
                        )
                    )
        mappings = [
            SimpleNamespace(
                raw_symbol=symbol,
                intervals=[
                    SimpleNamespace(
                        start_date=sessions[0].trading_date,
                        end_date=sessions[-1].trading_date + timedelta(days=1),
                        symbol=str(42 + index),
                    )
                ],
            )
            for index, symbol in enumerate(symbols)
        ]
        body = compressed(
            rows,
            underlying=underlying,
            metadata_changes={
                "start": start,
                "end": end,
                "symbols": list(symbols),
                "mappings": mappings,
            },
        )
        source, target = tmp_path / (label + "-download"), tmp_path / (label + "-stage")
        source.mkdir(mode=0o700)
        target.mkdir(mode=0o700)
        payloads = {
            "fixture." + query.schema + ".dbn.zst": body,
            "metadata.json": canonical_json(
                {
                    "job_id": "SYNTHETIC-JOB",
                    "version": 1,
                    "query": query.query(),
                    "customizations": {
                        "pretty_px": False,
                        "pretty_ts": False,
                        "map_symbols": False,
                        "split_symbols": False,
                        "split_duration": None,
                        "split_size": None,
                        "packaging": None,
                        "delivery": "download",
                    },
                }
            ).encode(),
            "condition.json": canonical_json(
                [
                    {"date": s.trading_date, "condition": "available", "last_modified_date": None}
                    for s in sessions
                ]
            ).encode(),
        }
        receipts = []
        for name, payload in payloads.items():
            source_fixtures.private_file(source, name, payload)
            receipts.append(
                {
                    "filename": name,
                    "size": len(payload),
                    "hash": "sha256:" + hashlib.sha256(payload).hexdigest(),
                    "urls": {"https": "https://example.invalid/manufactured"},
                }
            )
        source_fixtures.private_file(
            source,
            "manifest.json",
            canonical_json({"job_id": "SYNTHETIC-JOB", "files": receipts}).encode(),
        )
        path = stage_quotes(source, target, expected=query, loaded=loaded, repository_root=ROOT)
        manifest = PrivateArtifactRef(path, path.stem, path.stat().st_size)
        feeds.append(
            QuoteFeedBinding(
                manifest,
                "synthetic.episode." + label,
                "synthetic",
                "exchange_specific" if underlying else "consolidated",
                "snapshot_last_v1",
            )
        )
    return tuple(feeds), start, end


def _observation(session, close=Decimal("100")):
    return HistoryObservation(
        Bar(
            "SPY",
            BarInterval.ONE_DAY,
            session.opens_at,
            session.closes_at,
            close,
            close + 1,
            close - 1,
            close,
            Decimal("1000"),
            "synthetic.episode.history",
            content_hash(("manufactured-daily-bar", session.session_id)),
        ),
        session.closes_at + timedelta(microseconds=1),
        session,
        (content_hash(("manufactured-native", session.session_id)),),
    )


def _history(tmp_path, loaded, observations, end_ns, decisions, bindings):
    sessions = tuple(o.session for o in observations)
    start_ns = _ns(sessions[0].opens_at)
    actions = {
        "kind": "history-actions-v1",
        "underlying": "SPY",
        "start_ns": start_ns,
        "end_ns": end_ns,
        "adjustment": "unadjusted",
        "actions": (),
    }
    availability = {"kind": "study-availability-v1", "sessions": decisions}
    bundle, verified = source_fixtures.verified_facts(
        tmp_path,
        {
            "bar_publication": [
                {"kind": "study-daily-bar-v1", "observation": o} for o in observations
            ],
            "calendar": [
                {
                    "kind": "history-calendar-v1",
                    "start_ns": start_ns,
                    "end_ns": end_ns,
                    "sessions": sessions,
                },
                {"kind": "study-decision-calendar-v1", "sessions": decisions},
            ],
            "actions": [actions],
            "quote_semantics": [availability],
        },
        start_ns=start_ns,
        end_ns=end_ns,
        as_of_ns=end_ns,
        manifests=bindings,
    )
    verified = _reverify(bundle, verified.context, loaded)
    history = VerifiedHistoryCoverage(
        observations,
        sessions,
        start_ns,
        end_ns,
        content_hash(actions),
        bundle,
        verified.context,
        visible_claim_hashes=verified.visible_claim_hashes,
    )
    return history, verified, content_hash(availability)


def episode_inputs(tmp_path, monkeypatch, *, trend="call", scenario_changes=None, outcome_days=31):
    """Create fresh, mutually bound offline inputs without replacing consumer logic."""
    tmp_path.mkdir(mode=0o700, exist_ok=True)
    loaded = config()
    shortlist, contracts, sessions, prior = _shortlist(tmp_path, monkeypatch, loaded)
    feeds, start, end = _quote_feeds(tmp_path, loaded, contracts, sessions)
    calendars = tuple(
        OptionExpiryCalendar(
            c.contract_id,
            sessions[0].trading_date,
            c.expiration,
            c.eligible_sessions,
            True,
            sessions[0].opens_at,
            content_hash(("fixture-expiry", c.contract_id)),
        )
        for c in contracts
    )
    bundle, verified = source_fixtures.verified_facts(
        tmp_path / "stream-sources",
        {
            "quote_semantics": [feed.fact for feed in feeds],
            "contract_terms": [
                {"kind": "quote-stream-contract-v1", "contract": c} for c in contracts
            ],
            "calendar": [
                *({"kind": "quote-stream-session-v1", "session": s} for s in sessions),
                *({"kind": "historical-expiry-calendar-v1", "calendar": c} for c in calendars),
            ],
        },
        start_ns=start,
        end_ns=end,
        as_of_ns=start,
        manifests=tuple(feed.manifest for feed in feeds),
    )
    verified = _reverify(bundle, verified.context, loaded)
    stream = QuoteStreamRequest(feeds, bundle, verified.context, contracts, sessions, start, end)
    # Only these three sessions are open in the fabricated episode calendar. The
    # larger synthetic decision calendar exists solely to exercise policy splits.
    decisions = (
        *sessions,
        *(
            fixture_session(sessions[-1].trading_date + timedelta(days=2 * i))
            for i in range(1, 618)
        ),
    )
    observations = (
        *(
            _observation(
                fixture_session(date(2010, 1, 1) + timedelta(days=5 * i)),
                Decimal("200")
                if trend == "put" or (trend == "mixed" and i > 649)
                else Decimal("100"),
            )
            for i in range(749)
        ),
        HistoryObservation(
            prior.bar, prior.available_at, shortlist.session.prior, prior.selected_native_hashes
        ),
    )
    bindings = tuple(
        {ref.sha256: ref for ref in shortlist.bundle.manifests + bundle.manifests}.values()
    )
    subsequent = []
    for index, session in enumerate(sessions[1:], start=1):
        later = observations + tuple(_observation(s, Decimal("101")) for s in sessions[:index])
        history, _, _ = _history(
            tmp_path / f"later-history-{index}",
            loaded,
            later,
            _ns(session.opens_at),
            decisions,
            bindings,
        )
        subsequent.append(history)
    # Bind retained later-history preimages too; callers cannot substitute an
    # unregistered signal history merely because it independently verifies.
    bindings = tuple(
        {
            ref.sha256: ref
            for ref in (*bindings, *(ref for h in subsequent for ref in h.source_bundle.manifests))
        }.values()
    )
    history, verified_history, availability_hash = _history(
        tmp_path / "history", loaded, observations, start, decisions, bindings
    )
    scenario = make_scenario(**(scenario_changes or {}))
    spec = OptionsStudySpec(
        purpose="engineering_pilot",
        registered_at=datetime(2026, 9, 29, 15, tzinfo=UTC),
        selection_frozen_at=datetime(2026, 9, 29, 16, tzinfo=UTC),
        outcome_access_started_at=None,
        decision_sessions=decisions,
        declared_history_start_ns=history.start_ns,
        history_hash=history.history_hash,
        source_hashes=verified_history.source_hashes,
        availability_hash=availability_hash,
        config_hash=loaded.config_hash,
        code_hash=study_code_hash(),
        consumer_hash=study_consumer_hash(),
        hypothesis="unvalidated-momentum-20-100-v1",
        shortlist_version="spy-prior-close-atm-30d-v1",
        exit_policy="signal_invalidation_or_prior_session_expiry",
        scenario_hashes=tuple(
            (name, replace(scenario, name=name).scenario_hash)
            for name in ("base", "conservative", "optimistic")
        ),
        cost_hash=content_hash(("manufactured-fees", Decimal("0.50"), Decimal("0.50"))),
        capital_tiers=CAPITAL_TIERS,
        folds=tuple(
            StudyFold(
                "fold-" + str(i),
                tuple(s.session_id for s in decisions[: 50 + i * 100]),
                tuple(s.session_id for s in decisions[82 + i * 100 : 132 + i * 100]),
            )
            for i in range(5)
        ),
        final_session_ids=tuple(s.session_id for s in decisions[570:620]),
        embargo_ns=31 * DAY_NS,
        max_outcome_ns=outcome_days * DAY_NS,
        block_lengths_ns=(31 * DAY_NS, 62 * DAY_NS),
        bootstrap_seed=17,
        execution_seed=23,
        rejection_criteria=REJECTION_CRITERIA,
        contracts=contracts,
        coverage_semantics=(),
        initialization_sessions=(),
    )
    return SimpleNamespace(
        loaded=loaded,
        spec=spec,
        history=history,
        shortlist=shortlist,
        stream=stream,
        scenario=scenario,
        repository_root=ROOT,
        subsequent_history=tuple(subsequent),
        calendars=calendars,
    )
