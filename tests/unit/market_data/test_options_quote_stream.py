"""Causal stream tests with fabricated observations and explicitly private fixture rules."""

import hashlib
import importlib
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.unit.domain.test_options import contract
from tests.unit.market_data._options_source_fixtures import (
    ROOT,
    config,
    private_file,
    verified_facts,
)
from trading_bot.market_data.databento_quote_models import NativeQuoteRequest, NativeQuoteRow
from trading_bot.market_data.options_source_models import SourceEvidenceError, SourceRule
from trading_bot.market_data.recording import canonical_json

NS = 10**9
STAMP = 1704205800 * NS
SYMBOL = "SPY   240119C00475000"


def api():
    try:
        return importlib.import_module("trading_bot.market_data.options_quote_stream")
    except ModuleNotFoundError:
        pytest.fail("causal options quote stream is not implemented")


def row(*, underlying=False, offset=1, event_offset=None, snapshot=True, **changes):
    from trading_bot.market_data.databento_quote_models import quality_reasons

    value = dict(
        record_ordinal=offset,
        dbn_version=3,
        schema="mbp-1" if underlying else "cmbp-1",
        raw_symbol="SPY" if underlying else SYMBOL,
        publisher_id=2 if underlying else 30,
        instrument_id=42,
        ts_event=STAMP + (offset if event_offset is None else event_offset),
        ts_recv=STAMP + offset,
        price=1000000000,
        size=2,
        action="A",
        side="B",
        flags=128 + (32 if snapshot else 0),
        ts_in_delta=0,
        bid_px=475000000000 if underlying else 1000000000,
        ask_px=475010000000 if underlying else 1200000000,
        bid_sz=2,
        ask_sz=3,
        bid_pb=None if underlying else 20,
        ask_pb=None if underlying else 22,
        bid_ct=1 if underlying else None,
        ask_ct=1 if underlying else None,
        depth=0 if underlying else None,
        sequence=1 if underlying else None,
        raw_record_hex="00" * 80,
        record_hash="a" * 64,
        raw_hash=("b" if underlying else "c") * 64,
    )
    value.update(changes)
    reasons = quality_reasons(
        **{
            k: value[k]
            for k in (
                "schema",
                "publisher_id",
                "side",
                "ts_in_delta",
                "flags",
                "ts_event",
                "ts_recv",
                "action",
                "bid_px",
                "ask_px",
                "bid_sz",
                "ask_sz",
            )
        }
    )
    return NativeQuoteRow(
        **value,
        reasons=reasons,
        disposition="control" if value["action"] == "R" else "rejected" if reasons else "accepted",
    )


def setup(
    tmp_path,
    monkeypatch,
    *,
    options=None,
    underlying=None,
    end_offset=60 * NS,
    native_stages=None,
):
    stream = api()
    loaded = config()
    start = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    from trading_bot.domain.options import OptionSession

    session = OptionSession(
        "SPY-2024-01-02",
        start,
        start + timedelta(hours=6, minutes=30),
        date(2024, 1, 2),
        "America/New_York",
    )
    c = contract(
        contract_id="fixture-call",
        standardized_id=SYMBOL,
        underlying="SPY",
        deliverable_symbol="SPY",
        strike=Decimal("475"),
        expiration=date(2024, 1, 19),
        last_trading_at=datetime(2024, 1, 19, 21, tzinfo=UTC),
        settlement_at=datetime(2024, 1, 22, 21, tzinfo=UTC),
        available_at=start - timedelta(days=1),
        eligible_sessions=(session,),
    )
    feeds, datasets, observations = [], {}, {}
    for is_underlying, rows in ((True, underlying), (False, options)):
        label = "underlying" if is_underlying else "options"
        rows = [row(underlying=is_underlying)] if rows is None else rows
        if native_stages is None:
            manifest = private_file(tmp_path / label, "manifest.json", label.encode())
        else:
            from trading_bot.market_data.options_source_models import PrivateArtifactRef

            path = native_stages[label]
            body = path.read_bytes()
            manifest = PrivateArtifactRef(path, hashlib.sha256(body).hexdigest(), len(body))
        feed = stream.QuoteFeedBinding(
            manifest,
            "synthetic." + label,
            "synthetic",
            "exchange_specific" if is_underlying else "consolidated",
            "snapshot_last_v1",
        )
        feeds.append(feed)
        datasets[manifest.path] = SimpleNamespace(
            manifest_hash=manifest.sha256,
            request=NativeQuoteRequest(
                "XNAS.ITCH" if is_underlying else "OPRA.PILLAR",
                "mbp-1" if is_underlying else "cmbp-1",
                "raw_symbol",
                ("SPY",) if is_underlying else (SYMBOL,),
                STAMP,
                STAMP + end_offset,
            ),
            profile=SimpleNamespace(raw_hash=("b" if is_underlying else "c") * 64),
            config_hash=loaded.config_hash,
        )
        observations[manifest.sha256] = tuple(rows)
    bundle, verified = verified_facts(
        tmp_path / "sources",
        {
            "quote_semantics": [f.fact for f in feeds],
            "contract_terms": [{"kind": "quote-stream-contract-v1", "contract": c}],
            "calendar": [{"kind": "quote-stream-session-v1", "session": session}],
        },
        start_ns=STAMP,
        end_ns=STAMP + end_offset,
        as_of_ns=STAMP,
        manifests=tuple(f.manifest for f in feeds),
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
    import trading_bot.market_data.options_source_verify as verifier

    monkeypatch.setattr(verifier, "load_reviewed_rules", lambda: rules)

    @contextmanager
    def snapshots(path, **_):
        # This is only the storage boundary. Separate integration tests exercise
        # real raw/Parquet revalidation. Source verification above stays real.
        if path.read_bytes() != (b"underlying" if path.parent.name == "underlying" else b"options"):
            raise SourceEvidenceError()
        yield datasets[path], (), None

    if native_stages is None:
        monkeypatch.setattr(stream, "quote_snapshots", snapshots)
        monkeypatch.setattr(
            stream, "_native_rows", lambda dataset, *_: iter(observations[dataset.manifest_hash])
        )
    request = stream.QuoteStreamRequest(
        tuple(feeds),
        bundle,
        verified.context,
        (c,),
        (session,),
        STAMP,
        STAMP + end_offset,
    )
    return request, loaded


def events(request, loaded):
    return tuple(api().iter_quote_events(request, loaded=loaded, repository_root=ROOT))


def option_events(values):
    return [v for v in values if v.symbol == SYMBOL]


def test_reset_does_not_carry_last_quote(tmp_path, monkeypatch):
    request, loaded = setup(
        tmp_path,
        monkeypatch,
        options=[
            row(),
            row(offset=2, action="R", side="N"),
            row(offset=3, snapshot=False),
            row(offset=4),
        ],
    )
    values = option_events(events(request, loaded))
    assert values[1].record is not None
    reset = next(v for v in values if v.state == "reset")
    assert reset.record is None
    after_reset = next(v for v in values if v.available_ns == STAMP + 3)
    assert after_reset.record is None and "uninitialized" in after_reset.quality_reasons
    assert next(v for v in values if v.available_ns == STAMP + 4).record is not None


def test_missing_feed_is_not_unchanged_quote(tmp_path, monkeypatch):
    request, loaded = setup(tmp_path, monkeypatch, underlying=[])
    values = option_events(events(request, loaded))
    assert all(v.record is None for v in values)
    assert (
        "underlying_unavailable"
        in next(v for v in values if v.available_ns == STAMP + 1).quality_reasons
    )


def test_same_timestamp_cannot_fill_earlier(tmp_path, monkeypatch):
    request, loaded = setup(tmp_path, monkeypatch, options=[row(), row(record_ordinal=2)])
    values = [v for v in option_events(events(request, loaded)) if v.record]
    assert len(values) == 2
    assert all(not v.can_follow(STAMP + 1) for v in values)
    assert all(v.can_follow(STAMP) for v in values)
    assert values[0].identity != values[1].identity
    assert values[0].record.available_at.microsecond == 1  # ceiling, not truncation


def test_mutated_part_invalidates_resume(tmp_path, monkeypatch):
    request, loaded = setup(tmp_path, monkeypatch)
    assert events(request, loaded)
    request.feeds[0].manifest.path.write_bytes(b"replaced")
    with pytest.raises(SourceEvidenceError):
        events(request, loaded)


def test_stale_feed_emits_gap_and_does_not_refresh_observation(tmp_path, monkeypatch):
    request, loaded = setup(tmp_path, monkeypatch)
    values = events(request, loaded)
    delay = int(loaded.config.freshness.max_executable_quote_age_seconds * NS)
    gaps = [v for v in option_events(values) if "stale_feed" in v.quality_reasons]
    assert len(gaps) == 1 and gaps[0].available_ns == STAMP + 1 + delay + 1
    assert gaps[0].record is None
    assert len([v for v in option_events(values) if v.record]) == 1


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"bid_px": 0}, "zero_bid"),
        ({"bid_px": 1200000000}, "locked_quote"),
        ({"bid_px": 1000000001}, "off_tick"),
        ({"flags": 164}, "native_bad_book"),
        ({"snapshot": False}, "uninitialized"),
    ],
)
def test_quality_is_not_silently_promoted(tmp_path, monkeypatch, change, reason):
    request, loaded = setup(tmp_path, monkeypatch, options=[row(**change)])
    value = next(v for v in option_events(events(request, loaded)) if v.available_ns == STAMP + 1)
    assert reason in value.quality_reasons and not value.can_follow(STAMP)
    assert value.production_eligible is False and value.economic_evidence is False


def test_underlying_scope_is_preserved(tmp_path, monkeypatch):
    request, loaded = setup(tmp_path, monkeypatch)
    value = next(v for v in events(request, loaded) if v.symbol == "SPY" and v.record)
    assert value.quote_scope == "exchange_specific"
    assert value.record.source == "synthetic.underlying:exchange_specific"
    assert "NBBO" not in canonical_json(asdict(value))


def test_actual_rulebook_denies_even_matching_fixture_projection(tmp_path, monkeypatch):
    request, loaded = setup(tmp_path, monkeypatch)
    import trading_bot.market_data.options_source_verify as verifier

    monkeypatch.setattr(verifier, "load_reviewed_rules", lambda: ())
    with pytest.raises(SourceEvidenceError):
        events(request, loaded)


def test_contract_projection_substitution_denies(tmp_path, monkeypatch):
    request, loaded = setup(tmp_path, monkeypatch)
    request = replace(request, contracts=(replace(request.contracts[0], strike=Decimal("476")),))
    with pytest.raises(SourceEvidenceError):
        events(request, loaded)


def test_future_correction_does_not_change_earlier_decision(tmp_path, monkeypatch):
    request, loaded = setup(tmp_path, monkeypatch)
    earlier = events(request, loaded)
    reference = next(
        r for r in request.source_bundle.manifests if r.path.name == "contract_terms.json"
    )
    import json

    payload = json.loads(reference.path.read_text())
    payload["records"].append(
        {**payload["records"][0], "published_at_ns": STAMP + 20, "record": {"future": "correction"}}
    )
    body = canonical_json(payload).encode()
    reference.path.write_bytes(body)
    updated = replace(reference, sha256=hashlib.sha256(body).hexdigest(), byte_count=len(body))
    bundle = replace(
        request.source_bundle,
        manifests=tuple(updated if r == reference else r for r in request.source_bundle.manifests),
        claims=tuple(
            replace(c, raw_hashes=(updated.sha256,)) if c.role == "contract_terms" else c
            for c in request.source_bundle.claims
        ),
    )
    assert events(replace(request, source_bundle=bundle), loaded) == earlier


def test_option_feed_still_ages_while_underlying_is_missing(tmp_path, monkeypatch):
    delay = int(config().config.freshness.max_executable_quote_age_seconds * NS) + 2
    request, loaded = setup(
        tmp_path,
        monkeypatch,
        options=[row(), row(offset=delay, record_ordinal=2, snapshot=False)],
        underlying=[row(underlying=True, offset=delay, record_ordinal=1)],
    )
    value = next(
        v
        for v in option_events(events(request, loaded))
        if v.available_ns == STAMP + delay and v.record_ordinal is not None
    )
    assert value.record is None and "uninitialized" in value.quality_reasons


def test_underlying_reset_blocks_options_until_new_baseline(tmp_path, monkeypatch):
    request, loaded = setup(
        tmp_path,
        monkeypatch,
        options=[row(), row(offset=2), row(offset=3), row(offset=4)],
        underlying=[
            row(underlying=True),
            row(underlying=True, offset=2, action="R", side="N"),
            row(underlying=True, offset=3, snapshot=False),
            row(underlying=True, offset=4),
        ],
    )
    values = {v.available_ns: v for v in option_events(events(request, loaded))}
    assert values[STAMP + 2].record is None
    assert values[STAMP + 3].record is None
    assert values[STAMP + 4].record is not None


def test_ns_age_check_cannot_be_hidden_by_datetime_rounding(tmp_path, monkeypatch):
    delay = int(config().config.freshness.max_executable_quote_age_seconds * NS)
    request, loaded = setup(
        tmp_path,
        monkeypatch,
        options=[row(offset=delay + 2, event_offset=1, record_ordinal=1)],
        underlying=[row(underlying=True, offset=delay + 2, record_ordinal=1)],
    )
    value = next(
        v for v in option_events(events(request, loaded)) if v.available_ns == STAMP + delay + 2
    )
    assert value.record is None and "stale_quote" in value.quality_reasons


@pytest.mark.parametrize(
    "changes",
    [
        {"start_ns": True},
        {"feeds": ()},
        {"contracts": []},
        {"sessions": ()},
        {"contracts": ("untyped",)},
        {"sessions": ("untyped",)},
        {"end_ns": STAMP - 1},
    ],
)
def test_invalid_request_denies(tmp_path, monkeypatch, changes):
    request, _ = setup(tmp_path, monkeypatch)
    with pytest.raises(SourceEvidenceError):
        replace(request, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"initialization": "trust-first-row"},
        {"source_kind": "verified"},
        {"source_kind": "imported"},
        {"quote_scope": "NBBO"},
        {"source_id": "bad source"},
    ],
)
def test_invalid_feed_binding_denies(tmp_path, monkeypatch, changes):
    request, _ = setup(tmp_path, monkeypatch)
    with pytest.raises(SourceEvidenceError):
        replace(request.feeds[0], **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"available_ns": STAMP},
        {"event_ns": STAMP + 2},
        {"source": "other.source"},
        {"quote_scope": "exchange_specific"},
        {"state": "gap"},
        {"record": None},
    ],
)
def test_event_projection_identity_cannot_diverge(tmp_path, monkeypatch, changes):
    request, loaded = setup(tmp_path, monkeypatch)
    value = next(v for v in option_events(events(request, loaded)) if v.record)
    with pytest.raises(SourceEvidenceError):
        replace(value, **changes)


@pytest.mark.parametrize("native_event", [0, STAMP + 2, 2**64 - 1])
def test_invalid_native_timestamp_is_retained_as_a_denied_observation(
    tmp_path,
    monkeypatch,
    native_event,
):
    request, loaded = setup(tmp_path, monkeypatch, options=[row(ts_event=native_event)])
    value = next(v for v in option_events(events(request, loaded)) if v.record_ordinal is not None)
    assert value.event_ns == native_event
    assert value.record is None and "native_bad_timestamp" in value.quality_reasons
