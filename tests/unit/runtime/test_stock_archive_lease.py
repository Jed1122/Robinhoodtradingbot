"""Fictional private archives; no credentials or provider connections."""

import importlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from trading_bot.config.stock_research import StockWorkerSettings


@pytest.fixture
def archive(tmp_path):
    root = tmp_path.resolve() / "archive"
    root.mkdir(mode=0o700)
    return importlib.import_module("trading_bot.runtime.stock_archive_lease"), root


def orphan(root, number=1, size=0):
    path = root / (f"{number:064x}.stock-observation.json")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.ftruncate(descriptor, size)
    os.close(descriptor)
    return path


def test_capacity_reserves_complete_publication_growth_and_counts_orphans(archive):
    module, root = archive
    orphan(root, size=123)
    pending = root / (".pending-" + "a" * 32)
    pending.touch(mode=0o600)
    with module.StockArchiveLease(root) as lease:
        result = lease.admit(remaining_calls=32, policy=StockWorkerSettings())
        assert result == {
            "existing_bytes": 123,
            "existing_files": 3,
            "reserved_bytes": 315_000_000,
            "reserved_files": 35,
        }
    assert pending.exists() and (root / module.LOCK_NAME).stat().st_size == 0


def test_byte_quota_exact_boundary_then_one_byte_over_stops_without_cleanup(archive):
    module, root = archive
    policy = StockWorkerSettings(max_archive_bytes=335_544_320)
    path = orphan(root, size=policy.max_archive_bytes - 315_000_000)
    with module.StockArchiveLease(root) as lease:
        lease.admit(remaining_calls=32, policy=policy)
        with path.open("ab") as handle:
            handle.write(b"x")
        with pytest.raises(module.StockArchiveError, match="stock_archive_capacity_denied"):
            lease.admit(remaining_calls=32, policy=policy)
    assert path.stat().st_size == policy.max_archive_bytes - 315_000_000 + 1


def test_file_quota_exact_boundary_then_one_entry_over_stops(archive):
    module, root = archive
    policy = StockWorkerSettings(max_archive_files=128)
    for index in range(92):
        orphan(root, index)
    with module.StockArchiveLease(root) as lease:
        lease.admit(remaining_calls=32, policy=policy)
        orphan(root, 100)
        with pytest.raises(module.StockArchiveError, match="stock_archive_capacity_denied"):
            lease.admit(remaining_calls=32, policy=policy)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "mode", "unknown"])
def test_unsafe_entries_are_rejected_without_normalizing_or_deleting(archive, kind):
    module, root = archive
    path = orphan(root)
    original_mode = path.stat().st_mode
    if kind == "symlink":
        (root / ("2" * 64 + ".stock-capture.json")).symlink_to(path)
    elif kind == "hardlink":
        os.link(path, root / ("2" * 64 + ".stock-capture.json"))
    elif kind == "directory":
        (root / "nested").mkdir(mode=0o700)
    elif kind == "mode":
        path.chmod(0o644)
    else:
        (root / "unrecognized.json").touch(mode=0o600)
    with module.StockArchiveLease(root) as lease, pytest.raises(module.StockArchiveError):
        lease.admit(remaining_calls=17, policy=StockWorkerSettings())
    assert path.exists()
    assert path.stat().st_mode == (original_mode if kind != "mode" else original_mode | 0o044)


@pytest.mark.parametrize("field,value", [("f_bavail", 0), ("f_favail", 0)])
def test_insufficient_filesystem_capacity_denies_before_publication(
    archive, monkeypatch, field, value
):
    module, root = archive
    available = dict(f_bavail=1_000_000, f_frsize=4096, f_favail=1_000_000)
    available[field] = value
    monkeypatch.setattr(module.os, "fstatvfs", lambda fd: SimpleNamespace(**available))
    with (
        module.StockArchiveLease(root) as lease,
        pytest.raises(module.StockArchiveError, match="stock_archive_capacity_denied"),
    ):
        lease.admit(remaining_calls=17, policy=StockWorkerSettings())
    assert [path.name for path in root.iterdir()] == [module.LOCK_NAME]


def test_shared_lease_blocks_another_process_then_allows_reacquisition(archive):
    module, root = archive
    script = """
import sys
from pathlib import Path
from trading_bot.runtime.stock_archive_lease import StockArchiveLease, StockArchiveError
try:
    with StockArchiveLease(Path(sys.argv[1])):
        print('owned')
except StockArchiveError:
    print('blocked')
"""
    source = str(Path(__file__).resolve().parents[3] / "src")
    environment = dict(os.environ, PYTHONPATH=source)

    def child():
        result = subprocess.run(
            [sys.executable, "-c", script, str(root)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        assert result.stderr == ""
        return result.stdout.strip()

    with module.StockArchiveLease(root):
        assert child() == "blocked"
    assert child() == "owned"


def test_replaced_lock_anchor_and_unsafe_policy_fail_closed(archive):
    module, root = archive
    policy = StockWorkerSettings()
    with module.StockArchiveLease(root) as lease:
        with pytest.raises(module.StockArchiveError):
            lease.admit(remaining_calls=True, policy=policy)
        with pytest.raises(module.StockArchiveError):
            lease.admit(remaining_calls=33, policy=policy)
        with pytest.raises(module.StockArchiveError):
            lease.admit(
                remaining_calls=17,
                policy=policy.model_copy(update={"max_archive_bytes": 10**20}),
            )
        (root / module.LOCK_NAME).rename(root / "displaced-lock")
        (root / module.LOCK_NAME).touch(mode=0o600)
        with pytest.raises(module.StockArchiveError):
            lease.admit(remaining_calls=17, policy=policy)
    with pytest.raises(module.StockArchiveError):
        lease.admit(remaining_calls=17, policy=policy)


def test_lease_is_nonreentrant_and_borrowed_descriptor_survives_close(archive):
    module, root = archive
    from trading_bot.runtime.stock_capture import _private_directory

    descriptor = _private_directory(root)
    try:
        with module.StockArchiveLease(root, _directory_fd=descriptor) as lease:
            with pytest.raises(module.StockArchiveError):
                lease.__enter__()
            lease.admit(remaining_calls=0, policy=StockWorkerSettings())
        assert os.fstat(descriptor)
    finally:
        os.close(descriptor)
