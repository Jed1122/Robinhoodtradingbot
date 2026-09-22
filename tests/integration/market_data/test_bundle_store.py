import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from tests.unit.market_data._bundle_fixtures import LIMITS, fixture_package
from trading_bot.market_data.bundle_models import BundleError
from trading_bot.market_data.bundle_store import read_bundle, write_bundle


@pytest.fixture
def root(tmp_path):
    directory = tmp_path.resolve() / "private"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    return directory


def write(root, package=None, *, repository=None, limits=LIMITS):
    return write_bundle(
        root,
        fixture_package() if package is None else package,
        repository_root=Path.cwd().resolve() if repository is None else repository,
        limits=limits,
    )


def read(root, digest, *, limits=LIMITS):
    return read_bundle(root, digest, repository_root=Path.cwd().resolve(), limits=limits)


def test_private_bundle_round_trip_and_idempotency(root):
    digest = write(root)
    assert digest == write(root)
    result = read(root, digest)
    assert result.envelope.bundle_hash == digest
    assert result.envelope.classification == "synthetic"
    assert not hasattr(result, "blobs")
    for subdir in ("blobs", "bundles"):
        assert (root / subdir).stat().st_mode & 0o777 == 0o700
        for path in (root / subdir).iterdir():
            assert path.stat().st_mode & 0o777 == 0o600
            assert not path.name.startswith(".")


@pytest.mark.parametrize("case", ["missing", "inside_repo", "wrong_mode", "relative", "traversal"])
def test_root_contract_is_fail_closed(root, case):
    repository = Path.cwd().resolve()
    if case == "missing":
        root = root / "missing"
    elif case == "inside_repo":
        repository = root.parent
    elif case == "wrong_mode":
        root.chmod(0o755)
    elif case == "relative":
        root = Path("private")
    else:
        root = root / ".." / "private"
    with pytest.raises(BundleError, match=r"^bundle_path_invalid$") as caught:
        write(root, repository=repository)
    assert caught.value.__context__ is None
    assert caught.value.args == ("bundle_path_invalid",)


@pytest.mark.parametrize("location", ["root", "ancestor", "subdir", "file"])
def test_symlinks_are_rejected_at_every_path_boundary(root, location):
    if location == "root":
        link = root.parent / "root-link"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif location == "ancestor":
        link = root.parent / "ancestor-link"
        link.symlink_to(root.parent, target_is_directory=True)
        root = link / root.name
    elif location == "subdir":
        outside = root.parent / "outside"
        outside.mkdir(mode=0o700)
        (root / "blobs").symlink_to(outside, target_is_directory=True)
    else:
        digest = write(root)
        target = root / "bundles" / f"{digest}.json"
        saved = root.parent / "saved.json"
        target.rename(saved)
        target.symlink_to(saved)
        with pytest.raises(BundleError, match=r"^bundle_path_invalid$"):
            read(root, digest)
        return
    with pytest.raises(BundleError, match=r"^bundle_path_invalid$"):
        write(root)


@pytest.mark.parametrize("digest", ["../escape", "F" * 64, "a" * 63, True, "a" * 64 + ".json"])
def test_digest_cannot_control_paths(root, digest):
    with pytest.raises(BundleError, match=r"^bundle_path_invalid$"):
        read(root, digest)


@pytest.mark.parametrize("kind", ["fifo", "directory", "wide_mode"])
def test_nonregular_or_nonprivate_file_is_rejected_without_blocking(root, kind):
    digest = write(root)
    path = root / "bundles" / f"{digest}.json"
    path.unlink()
    if kind == "fifo":
        os.mkfifo(path, mode=0o600)
    elif kind == "directory":
        path.mkdir(mode=0o600)
    else:
        path.write_bytes(b"{}")
        path.chmod(0o644)
    with pytest.raises(BundleError, match=r"^bundle_path_invalid$"):
        read(root, digest)


def test_wrong_owner_metadata_fails_closed(root, monkeypatch):
    real = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: real + 1)
    with pytest.raises(BundleError, match=r"^bundle_path_invalid$"):
        write(root)


def test_existing_content_is_never_overwritten(root):
    digest = write(root)
    path = root / "bundles" / f"{digest}.json"
    path.write_bytes(b"changed-private-payload-marker")
    with pytest.raises(BundleError, match=r"^bundle_storage_conflict$") as caught:
        write(root)
    assert path.read_bytes() == b"changed-private-payload-marker"
    assert caught.value.__context__ is None


def test_short_writes_are_completed(root, monkeypatch):
    real_write = os.write

    def short_write(descriptor, value):
        view = memoryview(value)
        return real_write(descriptor, view[: max(1, len(view) // 2)])

    monkeypatch.setattr(os, "write", short_write)
    digest = write(root)
    assert read(root, digest).envelope.bundle_hash == digest


@pytest.mark.parametrize("operation", ["zero_write", "write", "file_fsync", "link"])
def test_prepublication_failures_never_publish_envelope(root, monkeypatch, operation):
    def fail(*args, **kwargs):
        raise OSError("private-path-marker")

    if operation == "zero_write":
        monkeypatch.setattr(os, "write", lambda *args: 0)
    else:
        monkeypatch.setattr(os, {"file_fsync": "fsync"}.get(operation, operation), fail)
    with pytest.raises(BundleError, match=r"^bundle_storage_unavailable$") as caught:
        write(root)
    assert caught.value.__context__ is None
    assert not tuple((root / "bundles").glob("*.json"))
    assert not tuple(root.rglob(".tmp-*"))


def test_postpublication_directory_fsync_failure_is_durability_uncertain(root, monkeypatch):
    real = os.fsync

    def fail_bundle_directory(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode) and tuple((root / "bundles").glob("*.json")):
            raise OSError("private-path-marker")
        real(descriptor)

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "fsync", fail_bundle_directory)
        with pytest.raises(BundleError, match=r"^bundle_storage_unavailable$"):
            write(root)
    (path,) = (root / "bundles").glob("*.json")
    assert read(root, path.stem).envelope.bundle_hash == path.stem
    assert write(root) == path.stem


def test_read_bounds_envelope_blob_and_combined_bytes(root):
    package = fixture_package()
    digest = write(root, package)
    for limits in (replace(LIMITS, max_envelope_bytes=100), replace(LIMITS, max_blob_bytes=100)):
        with pytest.raises(BundleError, match=r"^bundle_input_too_large$"):
            read(root, digest, limits=limits)
    largest = max(len(package.envelope_bytes), *(len(body) for _, body in package.blobs))
    limits = replace(
        LIMITS, max_envelope_bytes=largest, max_blob_bytes=largest, max_total_bytes=largest
    )
    with pytest.raises(BundleError, match=r"^bundle_input_too_large$"):
        read(root, digest, limits=limits)


def test_retained_verified_value_is_independent_of_later_disk_replacement(root):
    digest = write(root)
    verified = read(root, digest)
    old = verified.envelope
    path = root / "bundles" / f"{digest}.json"
    replacement = root / "replacement"
    replacement.write_bytes(b"{}")
    replacement.chmod(0o600)
    replacement.replace(path)
    assert verified.envelope == old
    with pytest.raises(BundleError):
        read(root, digest)


def test_invalid_package_cannot_create_artifact_subdirectories(root):
    package = replace(fixture_package(), envelope_bytes=b"{}")
    with pytest.raises(BundleError):
        write(root, package)
    assert list(root.iterdir()) == []


def test_combined_record_limit_precedes_domain_reconstruction_on_read(root, monkeypatch):
    from trading_bot.market_data import bundle_codec

    digest = write(root)

    def forbidden(*args, **kwargs):
        raise AssertionError("domain reconstruction preceded combined record limit")

    monkeypatch.setattr(bundle_codec, "_value", forbidden)
    with pytest.raises(BundleError, match=r"^bundle_input_too_large$"):
        read(root, digest, limits=replace(LIMITS, max_records=11))


def test_file_fsync_failure_after_writes_does_not_publish(root, monkeypatch):
    real = os.fsync
    observed = []

    def fail_regular(descriptor):
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            observed.append(os.fstat(descriptor).st_size)
            raise OSError("private-path-marker")
        real(descriptor)

    monkeypatch.setattr(os, "fsync", fail_regular)
    with pytest.raises(BundleError, match=r"^bundle_storage_unavailable$"):
        write(root)
    assert observed and observed[0] > 0
    assert not tuple((root / "bundles").glob("*.json"))
    assert not tuple(root.rglob(".tmp-*"))


def test_envelope_link_failure_keeps_completed_blob_but_no_bundle(root, monkeypatch):
    real = os.link

    def fail_envelope(source, destination, **kwargs):
        if destination.endswith(".json"):
            raise OSError("private-path-marker")
        real(source, destination, **kwargs)

    monkeypatch.setattr(os, "link", fail_envelope)
    with pytest.raises(BundleError, match=r"^bundle_storage_unavailable$"):
        write(root)
    assert tuple((root / "blobs").glob("*.raw"))
    assert not tuple((root / "bundles").glob("*.json"))
    assert not tuple(root.rglob(".tmp-*"))


def test_retry_reestablishes_parent_directory_durability(root, monkeypatch):
    real = os.fsync
    root_info = root.stat()
    calls = []

    def root_fsync(descriptor):
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) == (root_info.st_dev, root_info.st_ino):
            calls.append(descriptor)
            if len(calls) == 2:
                raise OSError("private-path-marker")
        real(descriptor)

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "fsync", root_fsync)
        with pytest.raises(BundleError, match=r"^bundle_storage_unavailable$"):
            write(root)
    assert (root / "bundles").is_dir()
    retried = []

    def record_root_fsync(descriptor):
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) == (root_info.st_dev, root_info.st_ino):
            retried.append(descriptor)
        real(descriptor)

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "fsync", record_root_fsync)
        digest = write(root)
    assert retried, "retry must fsync existing subdirectory entries in their parent"
    assert read(root, digest).envelope.bundle_hash == digest
