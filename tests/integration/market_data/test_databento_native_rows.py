"""Readers must consume verified private snapshots, never a replaced source pathname."""

import hashlib
import importlib
import json
from dataclasses import replace

import pytest

from tests.integration.market_data.test_databento_bar_store import ROOT, config, stage
from tests.integration.market_data.test_databento_definitions import REQUEST, fixture
from tests.unit.market_data._native_bars_fixtures import (
    END,
    START,
    native_bytes,
    native_record,
    zstd,
)
from tests.unit.market_data.test_databento_batch import make_batch, no_network  # noqa: F401
from trading_bot.market_data.databento_batch import DatabentoImportError
from trading_bot.market_data.databento_stage import stage_batch


def api():
    try:
        return importlib.import_module("trading_bot.market_data.databento_native_rows")
    except ModuleNotFoundError:
        pytest.fail("verified native row readers are not implemented")


def test_native_bars_round_trip_nullable_prices_and_duplicates(tmp_path):
    module = api()
    bad = native_record(prices=(2**63 - 1,) * 4)
    body = zstd.ZstdCompressor().compress(native_bytes(records=(bad, bad)))
    _, dataset = stage(tmp_path, payload=body)
    rows = tuple(
        module.read_bar_rows(
            dataset, start_ns=START, end_ns=END, loaded=config(), repository_root=ROOT
        )
    )
    assert [row.record_ordinal for row in rows] == [0, 1]
    assert [row.disposition for row in rows] == ["rejected", "duplicate"]
    assert all(row.close_nanos is None for row in rows)
    assert rows[0].record_hash == hashlib.sha256(bad).hexdigest()


def test_reader_uses_bytes_it_verified(tmp_path, monkeypatch):
    module = api()
    path, dataset = stage(tmp_path)
    part = path.parent.parent / dataset.parts[0].path
    original = module._read

    def replacing_read(directory, name, max_bytes):
        body = original(directory, name, max_bytes)
        if name == part.name:
            part.write_bytes(b"replaced after verification")
        return body

    monkeypatch.setattr(module, "_read", replacing_read)
    rows = tuple(
        module.read_bar_rows(
            dataset, start_ns=START, end_ns=END, loaded=config(), repository_root=ROOT
        )
    )
    assert len(rows) == 1 and rows[0].close_nanos == 101000000000
    with pytest.raises(DatabentoImportError):
        tuple(
            module.read_bar_rows(
                dataset, start_ns=START, end_ns=END, loaded=config(), repository_root=ROOT
            )
        )


@pytest.mark.parametrize("bounds", [(True, END), (START - 1, END), (START, END + 1), (END, START)])
def test_invalid_query_windows_deny(tmp_path, bounds):
    module = api()
    _, dataset = stage(tmp_path)
    with pytest.raises(DatabentoImportError):
        tuple(
            module.read_bar_rows(
                dataset, start_ns=bounds[0], end_ns=bounds[1], loaded=config(), repository_root=ROOT
            )
        )


def test_forged_dataset_descriptor_cannot_substitute_manifest_identity(tmp_path):
    module = api()
    _, dataset = stage(tmp_path)
    with pytest.raises(DatabentoImportError):
        forged = replace(dataset, manifest_hash="0" * 64)
        tuple(
            module.read_bar_rows(
                forged, start_ns=START, end_ns=END, loaded=config(), repository_root=ROOT
            )
        )


def test_definition_projection_preserves_all_native_fields_and_null_multiplier(tmp_path):
    module = api()
    source = make_batch(tmp_path, payload=zstd.ZstdCompressor().compress(fixture()))
    target = tmp_path / "staged"
    target.mkdir(mode=0o700)
    path = stage_batch(source, target, expected=REQUEST, repository_root=ROOT)
    rows = tuple(
        module.read_definition_rows(
            path,
            start_ns=REQUEST.start_ns,
            end_ns=REQUEST.end_ns,
            loaded=config(),
            repository_root=ROOT,
        )
    )
    assert len(rows) == 2
    assert rows[0].ts_recv == 1672704000000000002
    assert rows[0].contract_multiplier is None
    assert rows[0].strike_price == 400123456789
    assert rows[0].record_ordinal == 0 and rows[1].record_ordinal == 1


def test_definition_reader_rehashes_parts_before_emitting_rows(tmp_path):
    module = api()
    source = make_batch(tmp_path, payload=zstd.ZstdCompressor().compress(fixture()))
    target = tmp_path / "staged"
    target.mkdir(mode=0o700)
    path = stage_batch(source, target, expected=REQUEST, repository_root=ROOT)
    next(target.rglob("*.parquet")).write_bytes(b"changed")
    with pytest.raises(DatabentoImportError):
        tuple(
            module.read_definition_rows(
                path,
                start_ns=REQUEST.start_ns,
                end_ns=REQUEST.end_ns,
                loaded=config(),
                repository_root=ROOT,
            )
        )


def test_definition_reader_remains_spy_only(tmp_path):
    module = api()
    source = make_batch(tmp_path, payload=zstd.ZstdCompressor().compress(fixture()))
    target = tmp_path / "staged"
    target.mkdir(mode=0o700)
    path = stage_batch(source, target, expected=REQUEST, repository_root=ROOT)
    payload = json.loads(path.read_bytes())
    payload["validation"]["request"]["symbols"] = ["QQQ.OPT"]
    body = json.dumps(payload).encode()
    changed = path.with_name(hashlib.sha256(body).hexdigest() + ".json")
    changed.write_bytes(body)
    changed.chmod(0o600)
    with pytest.raises(DatabentoImportError):
        tuple(
            module.read_definition_rows(
                changed,
                start_ns=REQUEST.start_ns,
                end_ns=REQUEST.end_ns,
                loaded=config(),
                repository_root=ROOT,
            )
        )


def test_definition_scan_stops_at_declared_part_count(tmp_path, monkeypatch):
    module = api()
    source = make_batch(tmp_path, payload=zstd.ZstdCompressor().compress(fixture()))
    target = tmp_path / "staged"
    target.mkdir(mode=0o700)
    path = stage_batch(source, target, expected=REQUEST, repository_root=ROOT)
    original = module._rows
    observed = []

    def extra_rows(connection, snapshot, columns):
        values = list(original(connection, snapshot, columns))
        for index in range(5):
            observed.append(index)
            yield values[0]

    monkeypatch.setattr(module, "_rows", extra_rows)
    with pytest.raises(DatabentoImportError):
        tuple(
            module.read_definition_rows(
                path,
                start_ns=REQUEST.start_ns,
                end_ns=REQUEST.end_ns,
                loaded=config(),
                repository_root=ROOT,
            )
        )
    assert observed == [0, 1, 2]
