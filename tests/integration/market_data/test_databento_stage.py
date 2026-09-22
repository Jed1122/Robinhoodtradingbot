"""Private staging with synthetic DBN input; incomplete imports never publish a manifest."""

import hashlib
import importlib
import json
from pathlib import Path

import pytest

from tests.integration.market_data.test_databento_definitions import REQUEST, fixture, zstd
from tests.unit.market_data.test_databento_batch import make_batch, no_network  # noqa: F401
from trading_bot.market_data.databento_batch import DatabentoImportError

duckdb = pytest.importorskip("duckdb")
ROOT = Path(__file__).resolve().parents[3]


def api():
    try:
        return importlib.import_module("trading_bot.market_data.databento_stage")
    except ModuleNotFoundError:
        pytest.fail("Databento private staging is not implemented")


def test_staging_preserves_native_fields_and_publishes_private_bound_manifest(tmp_path):
    source = make_batch(tmp_path, payload=zstd.ZstdCompressor().compress(fixture()))
    target = tmp_path / "staged"
    target.mkdir(mode=0o700)
    path = api().stage_batch(source, target, expected=REQUEST, repository_root=ROOT)
    manifest = json.loads(path.read_bytes())
    assert manifest["validation"]["record_count"] == 2
    assert manifest["production_eligible"] is False
    assert manifest["economic_evidence"] is False
    assert manifest["files"][0]["record_count"] == 2
    assert manifest["conditions"] == [["2023-01-03", "available"], ["2023-01-04", "degraded"]]
    assert b"private-location" not in path.read_bytes()
    assert b"SYNTHETIC-JOB" not in path.read_bytes()
    part = target / manifest["files"][0]["path"]
    with duckdb.connect(":memory:") as con:
        rows = con.execute(
            "SELECT record_ordinal,ts_recv,strike_price,contract_multiplier "
            "FROM read_parquet(?) ORDER BY record_ordinal",
            [str(part)],
        ).fetchall()
    assert rows == [
        (0, 1672704000000000002, 400123456789, None),
        (1, 1672704000000000002, 400123456789, None),
    ]
    assert all(
        p.stat().st_mode & 0o777 == (0o700 if p.is_dir() else 0o600) for p in target.rglob("*")
    )
    assert api().stage_batch(source, target, expected=REQUEST, repository_root=ROOT) == path
    assert api().verify_staged(path, repository_root=ROOT)["validation"]["record_count"] == 2
    part.write_bytes(b"tampered")
    with pytest.raises(DatabentoImportError):
        api().verify_staged(path, repository_root=ROOT)


def test_incomplete_compression_cannot_publish_any_manifest(tmp_path):
    compressed = zstd.ZstdCompressor(write_checksum=True).compress(fixture(count=12000))
    source = make_batch(tmp_path, payload=compressed[:-1])
    target = tmp_path / "staged"
    target.mkdir(mode=0o700)
    with pytest.raises(DatabentoImportError):
        api().stage_batch(source, target, expected=REQUEST, repository_root=ROOT)
    assert not list(target.rglob("*.json"))
    assert not list(target.rglob("*.parquet"))


def test_partitioned_chunks_retain_duplicates_and_sequence(tmp_path):
    source = make_batch(tmp_path, payload=zstd.ZstdCompressor().compress(fixture(count=10001)))
    target = tmp_path / "staged"
    target.mkdir(mode=0o700)
    path = api().stage_batch(source, target, expected=REQUEST, repository_root=ROOT)
    manifest = api().verify_staged(path, repository_root=ROOT)
    assert len(manifest["files"]) == 2
    assert [item["record_count"] for item in manifest["files"]] == [10000, 1]
    assert manifest["validation"]["record_count"] == 10001


def test_publication_denies_in_repo_or_nonprivate_target(tmp_path):
    source = make_batch(tmp_path, payload=zstd.ZstdCompressor().compress(fixture()))
    with pytest.raises(DatabentoImportError):
        api().stage_batch(source, ROOT, expected=REQUEST, repository_root=ROOT)
    target = tmp_path / "staged"
    target.mkdir(mode=0o755)
    with pytest.raises(DatabentoImportError):
        api().stage_batch(source, target, expected=REQUEST, repository_root=ROOT)


def test_parquet_queries_use_the_hashed_snapshot_not_reopened_mutable_source(tmp_path, monkeypatch):
    module = api()
    source = make_batch(tmp_path, payload=zstd.ZstdCompressor().compress(fixture()))
    target = tmp_path / "staged"
    target.mkdir(mode=0o700)
    manifest_path = module.stage_batch(source, target, expected=REQUEST, repository_root=ROOT)
    manifest = json.loads(manifest_path.read_bytes())
    part = target / manifest["files"][0]["path"]
    expected_digest = hashlib.sha256(part.read_bytes()).hexdigest()
    replacement = tmp_path / "replacement.parquet"
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "COPY (SELECT * REPLACE(999::BIGINT AS strike_price) "
            "FROM read_parquet(?, hive_partitioning=false)) TO ? (FORMAT PARQUET)",
            [str(replacement), str(part)],
        )
    replacement_body = replacement.read_bytes()
    original_read = module._read
    original_connection = module._connection
    inspected = []

    def replacing_read(directory, name, max_bytes):
        body = original_read(directory, name, max_bytes)
        if name == part.name:
            part.write_bytes(replacement_body)
        return body

    class Connection:
        def __init__(self, directory):
            self.wrapped = original_connection(directory)

        def execute(self, sql, params):
            inspected.append(hashlib.sha256(Path(params[0]).read_bytes()).hexdigest())
            return self.wrapped.execute(sql, params)

        def close(self):
            self.wrapped.close()

    monkeypatch.setattr(module, "_read", replacing_read)
    monkeypatch.setattr(module, "_connection", Connection)
    module.verify_staged(manifest_path, repository_root=ROOT)
    assert inspected == [expected_digest, expected_digest]


@pytest.mark.parametrize("mutation", ["profile_schema", "input_files", "conditions", "eligibility"])
def test_unknown_or_malformed_nested_manifest_never_gets_verified(tmp_path, mutation):
    module = api()
    source = make_batch(tmp_path, payload=zstd.ZstdCompressor().compress(fixture()))
    target = tmp_path / "staged"
    target.mkdir(mode=0o700)
    path = module.stage_batch(source, target, expected=REQUEST, repository_root=ROOT)
    manifest = json.loads(path.read_bytes())
    if mutation == "profile_schema":
        manifest["validation"]["schema"] = "unreviewed-v999"
    elif mutation == "eligibility":
        manifest["validation"]["historical_availability_verified"] = True
    else:
        manifest[mutation] = "malformed"
    body = json.dumps(manifest).encode()
    altered = path.parent / (hashlib.sha256(body).hexdigest() + ".json")
    altered.write_bytes(body)
    altered.chmod(0o600)
    with pytest.raises(DatabentoImportError):
        module.verify_staged(altered, repository_root=ROOT)
