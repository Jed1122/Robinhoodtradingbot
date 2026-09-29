"""Credential-free, network-denied archive publication and tamper tests."""

import errno
import hashlib
import json
import os
from dataclasses import replace

import pytest

from tests.integration.market_data.test_databento_bar_store import ROOT, config
from tests.unit.market_data._native_quotes_fixtures import (
    STAMP,
    compressed,
    module,
    record,
    request,
)
from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from trading_bot.market_data.databento_batch import DatabentoImportError
from trading_bot.market_data.recording import canonical_json

duckdb = pytest.importorskip("duckdb")
DATA = "fixture.cmbp-1.dbn.zst"


def rehash(source):
    entries = []
    for name in (DATA, "metadata.json", "condition.json"):
        body = (source / name).read_bytes()
        entries.append(
            dict(
                filename=name,
                size=len(body),
                hash="sha256:" + hashlib.sha256(body).hexdigest(),
                urls={"https": "https://example.invalid/private-location"},
            )
        )
    (source / "manifest.json").write_text(json.dumps(dict(job_id="SYNTHETIC-JOB", files=entries)))
    for path in source.iterdir():
        if path.is_file():
            path.chmod(0o600)


def batch(tmp_path, payload=None):
    source = tmp_path / "download"
    source.mkdir(mode=0o700)
    (source / DATA).write_bytes(compressed() if payload is None else payload)
    (source / "metadata.json").write_text(
        json.dumps(
            dict(
                job_id="SYNTHETIC-JOB",
                version=1,
                query=request().query(),
                customizations=dict(
                    pretty_px=False,
                    pretty_ts=False,
                    map_symbols=False,
                    split_symbols=False,
                    split_duration=None,
                    split_size=None,
                    packaging=None,
                    delivery="download",
                ),
            )
        )
    )
    (source / "condition.json").write_text(
        json.dumps([dict(date="2024-01-02", condition="available", last_modified_date=None)])
    )
    rehash(source)
    return source


def setup(tmp_path, payload=None):
    source = batch(tmp_path, payload)
    root = tmp_path / "staged"
    root.mkdir(mode=0o700)
    return source, root, config()


def stage(source, root, loaded):
    return module("quote_store").stage_quotes(
        source, root, expected=request(), loaded=loaded, repository_root=ROOT
    )


def verify(path, loaded):
    return module("quote_store").verify_quote_stage(path, loaded=loaded, repository_root=ROOT)


def test_private_idempotent_archive_preserves_raw_inputs_and_denies_authority(tmp_path):
    source, root, loaded = setup(tmp_path)
    manifest = stage(source, root, loaded)
    result = verify(manifest, loaded)
    assert stage(source, root, loaded) == manifest
    assert result.request == request()
    assert result.profile.accepted_count == 1
    assert result.profile.rejected_count == 0
    assert len(result.archives) == 4
    for name in (
        "production_eligible",
        "economic_evidence",
        "live_authorized",
        "evidence_promotable",
        "download_authorized",
    ):
        assert getattr(result, name) is False
    encoded = manifest.read_text()
    assert "SYNTHETIC-JOB" not in encoded and "private-location" not in encoded
    for item in result.archives:
        restored = b"".join(
            (root / "blobs" / (chunk.sha256 + ".raw")).read_bytes() for chunk in item.chunks
        )
        assert restored == (source / item.name).read_bytes()
    for path in root.rglob("*"):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)


def test_larger_than_one_part_and_nanosecond_values(tmp_path):
    source, root, loaded = setup(
        tmp_path, compressed([record(recv=STAMP + i + 1) for i in range(10001)])
    )
    result = verify(stage(source, root, loaded), loaded)
    assert [part.record_count for part in result.parts] == [10000, 1]
    assert result.profile.decoded_count == 10001


@pytest.mark.parametrize("kind", ["part", "blob", "manifest"])
def test_any_published_byte_replacement_denies(tmp_path, kind):
    source, root, loaded = setup(tmp_path)
    path = stage(source, root, loaded)
    result = verify(path, loaded)
    target = {
        "part": root / result.parts[0].path,
        "blob": root / "blobs" / (result.archives[0].chunks[0].sha256 + ".raw"),
        "manifest": path,
    }[kind]
    target.write_bytes(b"tampered")
    with pytest.raises(DatabentoImportError):
        verify(path, loaded)


@pytest.mark.parametrize(
    "kind",
    [
        "source_link",
        "source_hardlink",
        "root_alias",
        "source_alias",
        "public_source",
        "git_source",
        "part_link",
        "part_hardlink",
    ],
)
def test_aliases_and_unprivate_files_deny(tmp_path, kind):
    source, root, loaded = setup(tmp_path)
    path = None
    if kind.startswith("part_"):
        path = stage(source, root, loaded)
        target = root / verify(path, loaded).parts[0].path
    else:
        target = source / DATA
    if kind in ("source_link", "part_link"):
        moved = tmp_path / "moved"
        target.rename(moved)
        target.symlink_to(moved)
    elif kind in ("source_hardlink", "part_hardlink"):
        os.link(target, tmp_path / "hardlink")
    elif kind in ("root_alias", "source_alias"):
        alias = tmp_path / "alias"
        alias.symlink_to(root if kind == "root_alias" else source, target_is_directory=True)
        if kind == "root_alias":
            root = alias
        else:
            source = alias
    elif kind == "public_source":
        target.chmod(0o644)
    else:
        (source / ".git").mkdir()
    with pytest.raises(DatabentoImportError):
        verify(path, loaded) if path else stage(source, root, loaded)


def test_late_truncated_input_publishes_no_manifest(tmp_path):
    source, root, loaded = setup(tmp_path, compressed([record()] * 10001)[:-1])
    with pytest.raises(DatabentoImportError):
        stage(source, root, loaded)
    assert not list(root.rglob("*.json"))


@pytest.mark.parametrize("exception", [OSError(errno.ENOSPC, "sensitive"), KeyboardInterrupt()])
def test_failed_publication_retry_cannot_publish_partial_manifest(tmp_path, monkeypatch, exception):
    source, root, loaded = setup(tmp_path)
    store = module("quote_store")
    original = store._publish_checked

    def fail(*args):
        raise exception

    monkeypatch.setattr(store, "_publish_checked", fail)
    with pytest.raises((DatabentoImportError, KeyboardInterrupt)) as failure:
        stage(source, root, loaded)
    assert "sensitive" not in str(failure.value)
    assert not list(root.rglob("*.json"))
    monkeypatch.setattr(store, "_publish_checked", original)
    assert verify(stage(source, root, loaded), loaded).profile.decoded_count == 1


@pytest.mark.parametrize("change", ["query", "customization", "receipt", "extra"])
def test_batch_scope_is_exact(tmp_path, change):
    source, root, loaded = setup(tmp_path)
    if change == "receipt":
        (source / DATA).write_bytes(b"changed")
    elif change == "extra":
        (source / "extra").write_bytes(b"extra")
    else:
        path = source / "metadata.json"
        value = json.loads(path.read_text())
        if change == "query":
            value["query"]["limit"] = 100
        else:
            value["customizations"]["pretty_px"] = True
        path.write_text(json.dumps(value))
        rehash(source)
    with pytest.raises(DatabentoImportError):
        stage(source, root, loaded)


def test_duckdb_cannot_load_extensions_or_access_external_files(tmp_path):
    connection = module("quote_store")._connection(tmp_path)
    try:
        for sql in (
            "INSTALL httpfs",
            "LOAD httpfs",
            "SELECT * FROM read_csv('/etc/passwd')",
            "SELECT * FROM read_parquet('https://example.invalid/private.parquet')",
        ):
            with pytest.raises(duckdb.Error):
                connection.execute(sql)
    finally:
        connection.close()


def rewritten_manifest(path, value):
    body = canonical_json(value).encode()
    replacement = path.parent / (hashlib.sha256(body).hexdigest() + ".json")
    replacement.write_bytes(body)
    replacement.chmod(0o600)
    return replacement


@pytest.mark.parametrize(
    "field,value",
    [
        ("economic_evidence", True),
        ("config_hash", "0" * 64),
        ("schema", "native-quotes-v2"),
        ("extra", None),
    ],
)
def test_self_consistent_manifest_hash_cannot_enable_trust(tmp_path, field, value):
    source, root, loaded = setup(tmp_path)
    path = stage(source, root, loaded)
    wire = json.loads(path.read_text())
    wire[field] = value
    with pytest.raises(DatabentoImportError):
        verify(rewritten_manifest(path, wire), loaded)


@pytest.mark.parametrize("change", [{"ask_px": 1200000004}, {"record_ordinal": 1}])
def test_rehashed_projection_conflict_denies_against_native_occurrence(tmp_path, change):
    from tests.unit.market_data._native_quotes_fixtures import scan

    source, root, loaded = setup(tmp_path)
    path = stage(source, root, loaded)
    wire = json.loads(path.read_text())
    _, rows = scan()
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    changed = module("quote_store")._part(scratch, [replace(rows[0], **change)], 0, 16777216)
    body = changed.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    old = root / wire["parts"][0]["path"]
    replacement = old.parent / (digest + ".parquet")
    replacement.write_bytes(body)
    replacement.chmod(0o600)
    wire["parts"][0].update(
        path=str(replacement.relative_to(root)), sha256=digest, byte_count=len(body)
    )
    with pytest.raises(DatabentoImportError):
        verify(rewritten_manifest(path, wire), loaded)


def test_failure_after_partial_blob_publication_is_recoverable(tmp_path, monkeypatch):
    source, root, loaded = setup(tmp_path)
    store = module("quote_store")
    original = store._publish_checked
    count = 0

    def fail_late(*args):
        nonlocal count
        count += 1
        if count == 3:
            raise OSError(errno.ENOSPC, "private details")
        return original(*args)

    monkeypatch.setattr(store, "_publish_checked", fail_late)
    with pytest.raises(DatabentoImportError):
        stage(source, root, loaded)
    retained = {p: p.read_bytes() for p in root.rglob("*.raw")}
    assert len(retained) == 2 and not list(root.rglob("*.json"))
    monkeypatch.setattr(store, "_publish_checked", original)
    assert verify(stage(source, root, loaded), loaded).profile.decoded_count == 1
    assert all(path.read_bytes() == value for path, value in retained.items())


def test_empty_archive_does_not_manufacture_coverage(tmp_path):
    source, root, loaded = setup(tmp_path, compressed([]))
    result = verify(stage(source, root, loaded), loaded)
    assert result.profile.decoded_count == 0 and result.parts == ()
    assert result.economic_evidence is False
