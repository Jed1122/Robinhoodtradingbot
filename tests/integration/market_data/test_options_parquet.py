"""Offline options Parquet storage with synthetic and imported provenance fixtures."""

from __future__ import annotations

import importlib
import json
import os
import socket
import stat
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from tests.unit.domain.test_options import NOW, quote
from trading_bot.market_data.bundle_models import BundleLimits
from trading_bot.market_data.options_data_codec import encode_record
from trading_bot.market_data.options_records import ChainSnapshot, OptionsDataRecord

duckdb = pytest.importorskip("duckdb", reason="optional options research dependency")


ROOT = Path(__file__).parents[3].resolve()
LIMITS = BundleLimits(262144, 131072, 1048576, 100, 16)


@pytest.fixture(autouse=True)
def deny_python_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("network forbidden in options Parquet tests")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def _storage() -> ModuleType:
    try:
        return importlib.import_module("trading_bot.market_data.options_parquet")
    except ModuleNotFoundError:
        pytest.fail("options Parquet storage is not implemented")


def _root(tmp_path: Path, name: str = "options-data") -> Path:
    root = tmp_path / name
    root.mkdir(mode=0o700)
    return root


def _record(
    *,
    source_kind: str = "synthetic",
    source: str = "fixture",
    seconds: int = 0,
    bid: str = "0.123456789012345678901234567",
    ask: str = "0.223456789012345678901234567",
    raw: str = "f",
) -> OptionsDataRecord:
    event_at = NOW + timedelta(seconds=seconds)
    value = quote(
        bid=Decimal(bid),
        ask=Decimal(ask),
        event_at=event_at,
        received_at=event_at,
        underlying_event_at=event_at,
        source=source,
        data_hash=raw * 64,
    )
    return OptionsDataRecord(
        source,
        source_kind,  # type: ignore[arg-type]
        raw * 64,
        event_at,
        event_at,
        value,
    )


def _manifest(path: Path) -> dict[str, object]:
    loaded = json.loads(path.read_bytes())
    assert isinstance(loaded, dict)
    return loaded


def test_round_trip_preserves_exact_values_order_and_queryable_columns(tmp_path: Path) -> None:
    storage = _storage()
    root = _root(tmp_path)
    records = (
        _record(source="provider'); DROP TABLE records; --", source_kind="imported", raw="a"),
        _record(seconds=1, raw="b", bid="0.000000000000000000000000001", ask="0.01"),
        _record(seconds=86400, raw="c", bid="1.2300", ask="1.2400"),
    )

    path = storage.publish_dataset(root, records, repository_root=ROOT, limits=LIMITS)

    assert path.parent == root / "manifests"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert storage.read_dataset(path, repository_root=ROOT, limits=LIMITS) == records
    manifest = _manifest(path)
    assert manifest["record_hashes"] == [item.record_hash for item in records]
    assert manifest["record_count"] == 3
    files = manifest["files"]
    assert isinstance(files, list) and len(files) == 3

    first = files[0]
    assert isinstance(first, dict)
    parquet = root / str(first["path"])
    with duckdb.connect(":memory:") as connection:
        row = connection.execute(
            """
            SELECT kind, CAST(event_at AS VARCHAR), CAST(available_at AS VARCHAR), record_json
            FROM read_parquet(?)
            """,
            [str(parquet)],
        ).fetchone()
    assert row is not None
    assert row[0] == "option_quote"
    assert datetime.fromisoformat(row[1]).tzinfo is not None
    assert datetime.fromisoformat(row[2]).tzinfo is not None
    assert '"bid":"0.123456789012345678901234567"' in row[3] or (
        '"bid":"0.000000000000000000000000001"' in row[3]
    )
    assert not (tmp_path / "records").exists()


def test_manifest_partitions_source_kinds_without_granting_authority(tmp_path: Path) -> None:
    storage = _storage()
    root = _root(tmp_path)
    records = (
        _record(source_kind="synthetic", source="same-provider", raw="d"),
        _record(source_kind="imported", source="same-provider", raw="e"),
    )

    path = storage.publish_dataset(root, records, repository_root=ROOT, limits=LIMITS)
    manifest = _manifest(path)

    assert manifest["source_kinds"] == ["imported", "synthetic"]
    assert manifest["evidence_promotable"] is False
    assert manifest["production_eligible"] is False
    files = manifest["files"]
    assert isinstance(files, list)
    assert {item["source_kind"] for item in files} == {"synthetic", "imported"}
    assert len({item["path"] for item in files}) == 2
    assert all(
        "kind=option_quote/event_date=2026-09-18/source_kind=" in item["path"] for item in files
    )


def test_publication_is_deterministic_private_and_no_overwrite(tmp_path: Path) -> None:
    storage = _storage()
    root = _root(tmp_path)
    records = (_record(),)

    first = storage.publish_dataset(root, records, repository_root=ROOT, limits=LIMITS)
    first_body = first.read_bytes()
    first_files = _manifest(first)["files"]
    assert isinstance(first_files, list)
    parquet = root / first_files[0]["path"]
    parquet_body = parquet.read_bytes()

    second = storage.publish_dataset(root, records, repository_root=ROOT, limits=LIMITS)

    assert second == first
    assert second.read_bytes() == first_body
    assert parquet.read_bytes() == parquet_body
    assert all(
        stat.S_IMODE(item.stat().st_mode) == (0o700 if item.is_dir() else 0o600)
        for item in root.rglob("*")
    )

    parquet.write_bytes(b"x" * len(parquet_body))
    with pytest.raises(storage.OptionsParquetError, match="options_dataset_invalid"):
        storage.publish_dataset(root, records, repository_root=ROOT, limits=LIMITS)


@pytest.mark.parametrize("target", ["manifest", "parquet"])
def test_tampered_manifest_or_parquet_is_rejected_before_decoding(
    tmp_path: Path, target: str
) -> None:
    storage = _storage()
    root = _root(tmp_path)
    path = storage.publish_dataset(root, (_record(),), repository_root=ROOT, limits=LIMITS)
    manifest = _manifest(path)

    if target == "manifest":
        manifest["record_count"] = 99
        path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
    else:
        files = manifest["files"]
        assert isinstance(files, list)
        parquet = root / files[0]["path"]
        body = parquet.read_bytes()
        parquet.write_bytes(body[:-1] + bytes([body[-1] ^ 1]))

    with pytest.raises(storage.OptionsParquetError, match="options_dataset_invalid"):
        storage.read_dataset(path, repository_root=ROOT, limits=LIMITS)


def test_symlink_and_fifo_paths_are_rejected_with_sanitized_errors(tmp_path: Path) -> None:
    storage = _storage()
    real = _root(tmp_path, "real")
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(storage.OptionsParquetError, match="options_dataset_invalid"):
        storage.publish_dataset(linked, (_record(),), repository_root=ROOT, limits=LIMITS)

    manifest = storage.publish_dataset(real, (_record(),), repository_root=ROOT, limits=LIMITS)
    manifest.unlink()
    os.mkfifo(manifest, mode=0o600)
    with pytest.raises(storage.OptionsParquetError, match="options_dataset_invalid"):
        storage.read_dataset(manifest, repository_root=ROOT, limits=LIMITS)


def test_record_and_artifact_bounds_fail_before_manifest_publication(tmp_path: Path) -> None:
    storage = _storage()
    too_many_root = _root(tmp_path, "too-many")
    one_record = BundleLimits(262144, 131072, 1048576, 1, 16)
    records = (_record(raw="1"), _record(seconds=1, raw="2"))

    with pytest.raises(storage.OptionsParquetError, match="options_dataset_invalid"):
        storage.publish_dataset(too_many_root, records, repository_root=ROOT, limits=one_record)
    assert not (too_many_root / "manifests").exists()

    tiny_root = _root(tmp_path, "tiny")
    tiny_blob = BundleLimits(4096, 64, 8192, 10, 16)
    with pytest.raises(storage.OptionsParquetError, match="options_dataset_invalid"):
        storage.publish_dataset(tiny_root, (_record(),), repository_root=ROOT, limits=tiny_blob)
    assert not (tiny_root / "manifests").exists()


def test_read_applies_cumulative_decoded_byte_limit_across_partitions(tmp_path: Path) -> None:
    storage = _storage()
    source = "synthetic-" + ("x" * 20000)
    records = (
        _record(source=source, raw="3"),
        _record(source=source, seconds=86400, raw="4"),
    )
    strict = BundleLimits(65536, 65536, 65536, 100, 16)
    assert all(len(encode_record(record)) < strict.max_blob_bytes for record in records)
    assert sum(len(encode_record(record)) for record in records) > strict.max_total_bytes

    liberal_root = _root(tmp_path, "liberal")
    manifest = storage.publish_dataset(liberal_root, records, repository_root=ROOT, limits=LIMITS)
    with pytest.raises(storage.OptionsParquetError, match="options_dataset_invalid"):
        storage.read_dataset(manifest, repository_root=ROOT, limits=strict)

    strict_root = _root(tmp_path, "strict")
    with pytest.raises(storage.OptionsParquetError, match="options_dataset_invalid"):
        storage.publish_dataset(strict_root, records, repository_root=ROOT, limits=strict)


def test_publish_rejects_records_that_same_limits_cannot_decode(tmp_path: Path) -> None:
    storage = _storage()
    chain = OptionsDataRecord(
        "fixture",
        "synthetic",
        "5" * 64,
        NOW,
        NOW,
        ChainSnapshot("SYN", ("one", "two")),
    )
    cases = (
        (
            _record(source="synthetic-" + ("x" * 1000), raw="6"),
            BundleLimits(2048, 8192, 65536, 100, 16),
        ),
        (chain, BundleLimits(8192, 8192, 65536, 1, 16)),
        (_record(raw="7"), BundleLimits(8192, 8192, 65536, 100, 3)),
    )

    for index, (record, limits) in enumerate(cases):
        root = _root(tmp_path, f"decode-limit-{index}")
        with pytest.raises(storage.OptionsParquetError, match="options_dataset_invalid"):
            storage.publish_dataset(root, (record,), repository_root=ROOT, limits=limits)
        assert not list(root.iterdir())


def test_empty_or_nonexact_records_are_rejected_without_artifacts(tmp_path: Path) -> None:
    storage = _storage()
    root = _root(tmp_path)

    for records in ((), [_record()], (object(),)):
        with pytest.raises(storage.OptionsParquetError, match="options_dataset_invalid"):
            storage.publish_dataset(  # type: ignore[arg-type]
                root, records, repository_root=ROOT, limits=LIMITS
            )
    assert not list(root.iterdir())
