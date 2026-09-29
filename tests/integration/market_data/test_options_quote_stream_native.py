"""Fabricated DBN archives through real private storage and the causal consumer."""

import hashlib
import json

import pytest

from tests.unit.market_data._native_quotes_fixtures import compressed, record, request
from tests.unit.market_data._options_source_fixtures import ROOT, config
from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from tests.unit.market_data.test_options_quote_stream import events, setup
from trading_bot.market_data.databento_quote_store import stage_quotes, verify_quote_stage
from trading_bot.market_data.options_source_models import SourceEvidenceError

pytest.importorskip("duckdb")


def archives(tmp_path, *, condition_states=None):
    paths = {}
    for underlying in (True, False):
        label = "underlying" if underlying else "options"
        source = tmp_path / (label + "-download")
        source.mkdir(mode=0o700)
        name = "fixture." + ("mbp-1" if underlying else "cmbp-1") + ".dbn.zst"
        body = compressed(
            [
                record(
                    underlying=underlying,
                    bid=475000000000 if underlying else 1000000000,
                    ask=475010000000 if underlying else 1200000000,
                    flags=160,
                )
            ],
            underlying=underlying,
        )
        (source / name).write_bytes(body)
        (source / "metadata.json").write_text(
            json.dumps(
                {
                    "job_id": "SYNTHETIC-JOB",
                    "version": 1,
                    "query": request(underlying=underlying).query(),
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
            )
        )
        (source / "condition.json").write_text(
            json.dumps(
                [
                    {
                        "date": "2024-01-02",
                        "condition": (condition_states or {}).get(label, "available"),
                        "last_modified_date": None,
                    }
                ]
            )
        )
        receipts = []
        for path in sorted(source.iterdir()):
            body = path.read_bytes()
            receipts.append(
                {
                    "filename": path.name,
                    "size": len(body),
                    "hash": "sha256:" + hashlib.sha256(body).hexdigest(),
                    "urls": {"https": "https://example.invalid/fabricated"},
                }
            )
        (source / "manifest.json").write_text(
            json.dumps({"job_id": "SYNTHETIC-JOB", "files": receipts})
        )
        for path in source.iterdir():
            path.chmod(0o600)
        destination = tmp_path / (label + "-stage")
        destination.mkdir(mode=0o700)
        paths[label] = stage_quotes(
            source,
            destination,
            expected=request(underlying=underlying),
            loaded=config(),
            repository_root=ROOT,
        )
    return paths


def test_real_native_snapshots_produce_only_fixture_events(tmp_path, monkeypatch):
    paths = archives(tmp_path)
    request_value, loaded = setup(tmp_path, monkeypatch, native_stages=paths)
    result = events(request_value, loaded)
    assert len([v for v in result if v.record]) == 2
    assert all(v.record.source_kind == "synthetic" for v in result if v.record)
    assert all(not v.economic_evidence and not v.production_eligible for v in result)


@pytest.mark.parametrize("feed", ["options", "underlying"])
@pytest.mark.parametrize("condition", ["degraded", "missing"])
def test_provider_warning_blocks_native_rows_before_first_event(
    tmp_path, monkeypatch, feed, condition
):
    paths = archives(tmp_path, condition_states={feed: condition})
    request_value, loaded = setup(tmp_path, monkeypatch, native_stages=paths)
    from trading_bot.market_data.options_quote_stream import iter_quote_events

    stream = iter_quote_events(request_value, loaded=loaded, repository_root=ROOT)
    with pytest.raises(SourceEvidenceError):
        next(stream)


@pytest.mark.parametrize("target", ["part", "blob"])
def test_mutated_native_part_invalidates_resume_before_first_event(tmp_path, monkeypatch, target):
    paths = archives(tmp_path)
    request_value, loaded = setup(tmp_path, monkeypatch, native_stages=paths)
    assert events(request_value, loaded)
    dataset = verify_quote_stage(paths["options"], loaded=loaded, repository_root=ROOT)
    root = paths["options"].parent.parent
    path = (
        root / dataset.parts[0].path
        if target == "part"
        else root / "blobs" / (dataset.archives[0].chunks[0].sha256 + ".raw")
    )
    path.write_bytes(b"replaced")
    from trading_bot.market_data.options_quote_stream import iter_quote_events

    stream = iter_quote_events(request_value, loaded=loaded, repository_root=ROOT)
    with pytest.raises(SourceEvidenceError):
        next(stream)
