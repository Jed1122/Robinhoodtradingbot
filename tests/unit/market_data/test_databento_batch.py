"""Synthetic batches only; catch unauthorized scope and corrupted acquisition evidence."""

import hashlib
import importlib
import json
import os
import socket
from contextlib import contextmanager, suppress
from pathlib import Path

import pytest

START = 1672531200000000000
END = 1767225600000000000


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("offline batch validation must not use network")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def api():
    try:
        return importlib.import_module("trading_bot.market_data.databento_batch")
    except ModuleNotFoundError:
        pytest.fail("offline Databento batch validation is not implemented")


def make_batch(tmp_path, *, payload=b"synthetic compressed bytes"):
    root = tmp_path / "download"
    root.mkdir()
    metadata = {
        "version": 1,
        "job_id": "SYNTHETIC-JOB",
        "query": {
            "dataset": "OPRA.PILLAR",
            "schema": "definition",
            "symbols": ["SPY.OPT"],
            "stype_in": "parent",
            "stype_out": "instrument_id",
            "start": START,
            "end": END,
            "limit": None,
            "encoding": "dbn",
            "compression": "zstd",
        },
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
    (root / "metadata.json").write_text(json.dumps(metadata))
    (root / "condition.json").write_text(
        json.dumps(
            [
                {
                    "date": "2023-01-03",
                    "condition": "available",
                    "last_modified_date": "2025-05-04",
                },
                {"date": "2023-01-04", "condition": "degraded", "last_modified_date": None},
            ]
        )
    )
    (root / "fixture.definition.dbn.zst").write_bytes(payload)
    rehash(root)
    return root


def rehash(root):
    files = []
    for name in ["condition.json", "metadata.json", "fixture.definition.dbn.zst"]:
        body = (root / name).read_bytes()
        files.append(
            {
                "filename": name,
                "size": len(body),
                "hash": "sha256:" + hashlib.sha256(body).hexdigest(),
                "urls": {"https": "https://example.invalid/private-location"},
            }
        )
    (root / "manifest.json").write_text(json.dumps({"job_id": "SYNTHETIC-JOB", "files": files}))


def verify(root, **kwargs):
    module = api()
    return module.validate_batch(
        root, expected=module.DefinitionRequest("SPY.OPT", START, END), **kwargs
    )


def test_full_inventory_binds_hashes_and_scope_without_granting_evidence(tmp_path):
    result = verify(make_batch(tmp_path))
    assert len(result.files) == 4
    assert result.definition_file == "fixture.definition.dbn.zst"
    assert result.conditions == (("2023-01-03", "available"), ("2023-01-04", "degraded"))
    assert result.production_eligible is False
    assert result.economic_evidence is False
    assert result.record_validation_complete is False
    assert "private-location" not in repr(result)
    assert "SYNTHETIC-JOB" not in repr(result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", "cbbo-1m"),
        ("symbols", ["QQQ.OPT"]),
        ("limit", 100),
        ("start", START + 1),
        ("end", END - 1),
        ("encoding", "csv"),
        ("compression", "none"),
        ("stype_in", "raw_symbol"),
        ("start", True),
    ],
)
def test_wrong_or_truncated_request_denied_even_with_valid_hashes(tmp_path, field, value):
    root = make_batch(tmp_path)
    body = json.loads((root / "metadata.json").read_text())
    body["query"][field] = value
    (root / "metadata.json").write_text(json.dumps(body))
    rehash(root)
    with pytest.raises(api().DatabentoImportError, match="databento_batch_invalid"):
        verify(root)


@pytest.mark.parametrize(
    "target", ["condition.json", "metadata.json", "fixture.definition.dbn.zst"]
)
def test_modified_file_or_size_cannot_validate(tmp_path, target):
    root = make_batch(tmp_path)
    (root / target).write_bytes((root / target).read_bytes() + b"x")
    with pytest.raises(api().DatabentoImportError):
        verify(root)


@pytest.mark.parametrize(
    "mutation",
    ["traversal", "duplicate", "unknown", "bool_size", "job", "extra", "symlink", "directory"],
)
def test_manifest_and_filesystem_abuse_denied(tmp_path, mutation):
    root = make_batch(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    if mutation == "traversal":
        manifest["files"][0]["filename"] = "../condition.json"
    elif mutation == "duplicate":
        manifest["files"].append(manifest["files"][0])
    elif mutation == "unknown":
        manifest["files"][0]["injected"] = "ignore rules"
    elif mutation == "bool_size":
        manifest["files"][0]["size"] = True
    elif mutation == "job":
        manifest["job_id"] = "OTHER"
    elif mutation == "extra":
        (root / "unapproved.dbn.zst").write_bytes(b"extra")
    else:
        target = root / "fixture.definition.dbn.zst"
        target.unlink()
        if mutation == "symlink":
            target.symlink_to(tmp_path / "outside")
        else:
            target.mkdir()
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(api().DatabentoImportError):
        verify(root)


def test_limits_and_duplicate_json_keys_fail_closed(tmp_path):
    root = make_batch(tmp_path)
    with pytest.raises(api().DatabentoImportError):
        verify(root, max_file_bytes=1)
    (root / "manifest.json").write_text('{"job_id":"a","job_id":"b","files":[]}')
    with pytest.raises(api().DatabentoImportError):
        verify(root)


def test_private_copy_is_verified_idempotent_and_never_overwrites(tmp_path):
    root = make_batch(tmp_path)
    result = verify(root)
    destination = tmp_path / "private"
    destination.mkdir(mode=0o700)
    module = api()
    repository = Path(__file__).resolve().parents[3]
    module.preserve_batch(root, destination, result, repository_root=repository)
    module.preserve_batch(root, destination, result, repository_root=repository)
    assert {p.name for p in destination.iterdir()} == {p.name for p in root.iterdir()}
    for path in destination.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.read_bytes() == (root / path.name).read_bytes()
    (destination / "metadata.json").write_bytes(b"conflict")
    with pytest.raises(module.DatabentoImportError):
        module.preserve_batch(root, destination, result, repository_root=repository)
    assert (destination / "metadata.json").read_bytes() == b"conflict"


def test_source_changed_after_validation_is_not_published(tmp_path):
    root = make_batch(tmp_path)
    result = verify(root)
    (root / "fixture.definition.dbn.zst").write_bytes(b"changed")
    destination = tmp_path / "private"
    destination.mkdir(mode=0o700)
    with pytest.raises(api().DatabentoImportError):
        api().preserve_batch(root, destination, result, repository_root=Path(__file__).parents[3])
    assert not (destination / "fixture.definition.dbn.zst").exists()


def test_failed_destination_open_closes_the_source_descriptor(tmp_path, monkeypatch):
    module = api()
    source = make_batch(tmp_path)
    batch = verify(source)
    descriptor = module._source_root(source)
    monkeypatch.setattr(module, "_source_root", lambda path: descriptor)
    with pytest.raises(module.DatabentoImportError):
        module.preserve_batch(
            source, tmp_path / "absent", batch, repository_root=Path(__file__).parents[3]
        )
    try:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    finally:
        with suppress(OSError):
            os.close(descriptor)


@pytest.mark.parametrize("target", ["manifest.json", "condition.json"])
def test_json_parsing_is_bound_to_the_exact_hashed_snapshot(tmp_path, monkeypatch, target):
    module = api()
    source = make_batch(tmp_path)
    original = (source / target).read_bytes()
    original_open = module._file
    switched = False

    @contextmanager
    def replacing(parent, name, max_bytes):
        nonlocal switched
        with original_open(parent, name, max_bytes) as stream:
            yield stream
        if name == target and not switched:
            switched = True
            if target == "condition.json":
                body = json.loads(original)
                body[0]["condition"] = "missing"
            else:
                body = json.loads(original)
                body["job_id"] = "REPLACED"
            (source / target).write_text(json.dumps(body))

    monkeypatch.setattr(module, "_file", replacing)
    result = verify(source)
    assert switched
    assert result.conditions[0] == ("2023-01-03", "available")
    assert (
        next(item.sha256 for item in result.files if item.name == target)
        == hashlib.sha256(original).hexdigest()
    )
