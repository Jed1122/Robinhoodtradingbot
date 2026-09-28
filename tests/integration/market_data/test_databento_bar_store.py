"""Fabricated private native batches; no provider data, credentials or network."""

import errno
import hashlib
import importlib
import json
import os
from pathlib import Path

import pytest

from tests.unit.market_data._native_bars_fixtures import (
    END,
    START,
    bar_fixture,
    models,
    native_bytes,
    native_record,
    zstd,
)
from tests.unit.market_data.test_databento_batch import no_network  # noqa: F401
from trading_bot.config import load_config
from trading_bot.market_data.databento_batch import DatabentoImportError

pytest.importorskip("duckdb")
ROOT = Path(__file__).resolve().parents[3]
DATA = "fixture.ohlcv-1m.dbn.zst"


def api():
    try:
        return importlib.import_module("trading_bot.market_data.databento_bar_store")
    except ModuleNotFoundError:
        pytest.fail("native bar store is not implemented")


def config(environ=None):
    return load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/options/native-data/simulation.yaml",
        ROOT / "configs/safety-envelope.yaml",
        environ or {},
    )


def rehash(root):
    entries = []
    for name in (DATA, "metadata.json", "condition.json"):
        body = (root / name).read_bytes()
        entries.append(
            {
                "filename": name,
                "size": len(body),
                "hash": "sha256:" + hashlib.sha256(body).hexdigest(),
                "urls": {"https": "https://example.invalid/private-location"},
            }
        )
    (root / "manifest.json").write_text(json.dumps({"job_id": "SYNTHETIC-JOB", "files": entries}))
    for path in root.iterdir():
        if path.is_file():
            path.chmod(0o600)


def batch(tmp_path, *, payload=None):
    source = tmp_path / "download"
    source.mkdir(mode=0o700)
    if payload is None:
        payload, _, _ = bar_fixture()
    metadata = {
        "job_id": "SYNTHETIC-JOB",
        "version": 1,
        "query": models().NativeBarRequest(START, END).query(),
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
    (source / DATA).write_bytes(payload)
    (source / "metadata.json").write_text(json.dumps(metadata))
    (source / "condition.json").write_text(
        json.dumps(
            [
                {
                    "date": "2024-01-02",
                    "condition": "available",
                    "last_modified_date": "2025-05-04",
                },
                {"date": "2024-01-03", "condition": "degraded", "last_modified_date": None},
            ]
        )
    )
    rehash(source)
    return source


def stage(tmp_path, *, payload=None, loaded=None):
    module = api()
    source = batch(tmp_path, payload=payload)
    target = tmp_path / "staged"
    target.mkdir(mode=0o700)
    loaded = loaded or config()
    path = module.stage_bars(
        source,
        target,
        expected=models().NativeBarRequest(START, END),
        loaded=loaded,
        repository_root=ROOT,
    )
    return path, module.verify_bar_stage(path, loaded=loaded, repository_root=ROOT)


def test_batch_exact_inventory_and_private_manifest_retains_conditions(tmp_path):
    module = api()
    source = batch(tmp_path)
    result = module.validate_bar_batch(
        source,
        expected=models().NativeBarRequest(START, END),
        loaded=config(),
        repository_root=ROOT,
    )
    assert len(result.files) == 4
    assert result.bar_file == DATA
    assert result.conditions[0].last_modified_date.isoformat() == "2025-05-04"
    assert "private-location" not in repr(result)
    assert "SYNTHETIC-JOB" not in repr(result)


def test_duplicate_stage_is_idempotent_and_private(tmp_path):
    path, dataset = stage(tmp_path)
    again = api().stage_bars(
        tmp_path / "download",
        tmp_path / "staged",
        expected=models().NativeBarRequest(START, END),
        loaded=config(),
        repository_root=ROOT,
    )
    assert path == again
    assert dataset.manifest_hash == hashlib.sha256(path.read_bytes()).hexdigest()
    assert dataset.profile.accepted_count == 1
    assert not dataset.production_eligible and not dataset.economic_evidence
    assert not dataset.download_authorized and not dataset.live_authorized
    assert (
        b"private-location" not in path.read_bytes() and b"SYNTHETIC-JOB" not in path.read_bytes()
    )
    for item in path.parent.parent.rglob("*"):
        assert item.stat().st_mode & 0o777 == (0o700 if item.is_dir() else 0o600)


def test_failed_footer_publishes_no_success_manifest(tmp_path):
    api()
    body, _, _ = bar_fixture(count=10001)
    with pytest.raises(DatabentoImportError, match="databento_dbn_invalid"):
        stage(tmp_path, payload=body[:-1])
    assert not list((tmp_path / "staged").rglob("*.json"))


def test_10001_identical_rows_split_without_losing_duplicate_observations(tmp_path):
    api()
    body = zstd.ZstdCompressor().compress(native_bytes(records=(native_record(),) * 10001))
    path, dataset = stage(tmp_path, payload=body)
    assert [part.record_count for part in dataset.parts] == [10000, 1]
    assert dataset.profile.duplicate_count == 10000
    assert json.loads(path.read_bytes())["schema"] == "databento-native-bars-parquet-v1"


@pytest.mark.parametrize(
    "mutation",
    [
        "query",
        "customization",
        "bool_size",
        "digest",
        "extra",
        "unknown_key",
        "duplicate",
        "data_tamper",
        "suffix",
    ],
)
def test_batch_mismatch_never_reaches_scanner(tmp_path, mutation):
    module = api()
    source = batch(tmp_path)
    if mutation in ("query", "customization"):
        meta = json.loads((source / "metadata.json").read_bytes())
        if mutation == "query":
            meta["query"]["start"] = START + 1
        else:
            meta["customizations"]["pretty_px"] = True
        (source / "metadata.json").write_text(json.dumps(meta))
        rehash(source)
    elif mutation == "extra":
        (source / "extra").write_bytes(b"extra")
    elif mutation == "data_tamper":
        (source / DATA).write_bytes(b"corrupt")
    else:
        manifest = json.loads((source / "manifest.json").read_bytes())
        item = manifest["files"][0]
        if mutation == "bool_size":
            item["size"] = True
        elif mutation == "digest":
            item["hash"] = "sha256:" + "0" * 64
        elif mutation == "unknown_key":
            item["trust"] = True
        elif mutation == "duplicate":
            manifest["files"].append(item)
        else:
            (source / DATA).rename(source / "fixture.definition.dbn.zst")
            item["filename"] = "fixture.definition.dbn.zst"
        (source / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(DatabentoImportError):
        module.validate_bar_batch(
            source,
            expected=models().NativeBarRequest(START, END),
            loaded=config(),
            repository_root=ROOT,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "symlink",
        "hardlink",
        "mode",
        "root_mode",
        "git_ancestor",
        "root_symlink",
        "wrong_owner",
        "url",
    ],
)
def test_unsafe_source_paths_denied(tmp_path, monkeypatch, mutation):
    module = api()
    source = batch(tmp_path)
    data = source / DATA
    if mutation == "symlink":
        original = tmp_path / "original"
        data.rename(original)
        data.symlink_to(original)
    elif mutation == "hardlink":
        os.link(data, tmp_path / "second-name")
    elif mutation == "mode":
        data.chmod(0o644)
    elif mutation == "root_mode":
        source.chmod(0o755)
    elif mutation == "git_ancestor":
        (tmp_path / ".git").mkdir()
    elif mutation == "root_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(source, target_is_directory=True)
        source = alias
    elif mutation == "wrong_owner":
        owner = os.geteuid()
        monkeypatch.setattr(os, "geteuid", lambda: owner + 1)
    else:
        source = Path("https://example.invalid/data")
    with pytest.raises(DatabentoImportError):
        module.validate_bar_batch(
            source,
            expected=models().NativeBarRequest(START, END),
            loaded=config(),
            repository_root=ROOT,
        )


def test_publication_failure_does_not_claim_success(tmp_path, monkeypatch):
    module = api()

    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, "synthetic disk full")

    monkeypatch.setattr(module, "_publish", fail)
    with pytest.raises(DatabentoImportError):
        stage(tmp_path)
    assert not list((tmp_path / "staged").rglob("*.json"))


def test_manifest_tamper_and_colliding_content_denied(tmp_path):
    path, _ = stage(tmp_path)
    path.write_bytes(b"different content")
    with pytest.raises(DatabentoImportError):
        api().verify_bar_stage(path, loaded=config(), repository_root=ROOT)
    with pytest.raises(DatabentoImportError):
        api().stage_bars(
            tmp_path / "download",
            tmp_path / "staged",
            expected=models().NativeBarRequest(START, END),
            loaded=config(),
            repository_root=ROOT,
        )


def test_reduced_limits_and_config_identity_checked_on_reverification(tmp_path):
    path, _ = stage(tmp_path)
    for loaded in (
        config({"TRADING_BOT__OPTIONS__NATIVE_DATA__MAX_PART_BYTES": "1"}),
        config({"TRADING_BOT__OPTIONS__NATIVE_DATA__ENABLED": "false"}),
    ):
        with pytest.raises(DatabentoImportError):
            api().verify_bar_stage(path, loaded=loaded, repository_root=ROOT)


def test_source_replacement_after_validation_is_rehashed(tmp_path, monkeypatch):
    module = api()
    original = module.validate_bar_batch

    def replacing(source, **kwargs):
        result = original(source, **kwargs)
        (source / DATA).write_bytes(b"changed")
        return result

    monkeypatch.setattr(module, "validate_bar_batch", replacing)
    with pytest.raises(DatabentoImportError):
        stage(tmp_path)
    assert not list((tmp_path / "staged").rglob("*.json"))


@pytest.mark.parametrize(
    "field",
    [
        "production_eligible",
        "economic_evidence",
        "download_authorized",
        "live_authorized",
        "evidence_promotable",
        "unknown",
        "conditions",
    ],
)
def test_forged_closed_manifest_contract_denied_even_with_fresh_hash(tmp_path, field):
    path, _ = stage(tmp_path)
    value = json.loads(path.read_bytes())
    if field == "conditions":
        value["conditions"][0]["trading_date"] = "2020-01-01"
    else:
        value[field] = True
    body = json.dumps(value).encode()
    changed = path.with_name(hashlib.sha256(body).hexdigest() + ".json")
    changed.write_bytes(body)
    changed.chmod(0o600)
    with pytest.raises(DatabentoImportError):
        api().verify_bar_stage(changed, loaded=config(), repository_root=ROOT)


@pytest.mark.parametrize("mode", ["hardlink", "symlink", "permissions", "tamper"])
def test_staged_part_access_and_tampering_denied(tmp_path, mode):
    path, dataset = stage(tmp_path)
    part = path.parent.parent / dataset.parts[0].path
    if mode == "hardlink":
        os.link(part, tmp_path / "link")
    elif mode == "symlink":
        original = tmp_path / "original"
        part.rename(original)
        part.symlink_to(original)
    elif mode == "permissions":
        part.chmod(0o644)
    else:
        part.write_bytes(b"changed")
    with pytest.raises(DatabentoImportError):
        api().verify_bar_stage(path, loaded=config(), repository_root=ROOT)


def test_storage_limits_tighten_chunking_and_deny_part_count_overflow(tmp_path):
    api()
    body, _, _ = bar_fixture(count=3)
    loaded = config(
        {
            "TRADING_BOT__OPTIONS__NATIVE_DATA__MAX_PART_ROWS": "1",
            "TRADING_BOT__OPTIONS__NATIVE_DATA__MAX_PARTS": "2",
        }
    )
    with pytest.raises(DatabentoImportError, match="databento_limit_exceeded"):
        stage(tmp_path, payload=body, loaded=loaded)
    assert not list((tmp_path / "staged").rglob("*.json"))


@pytest.mark.parametrize("target", ["part", "manifest"])
def test_idempotent_publication_does_not_accept_hardlinked_existing_artifacts(tmp_path, target):
    path, dataset = stage(tmp_path)
    artifact = path if target == "manifest" else path.parent.parent / dataset.parts[0].path
    os.link(artifact, tmp_path / "alias")
    before = path.read_bytes()
    with pytest.raises(DatabentoImportError):
        api().stage_bars(
            tmp_path / "download",
            tmp_path / "staged",
            expected=models().NativeBarRequest(START, END),
            loaded=config(),
            repository_root=ROOT,
        )
    assert path.read_bytes() == before
