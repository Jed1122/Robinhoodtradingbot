"""Publish only complete encrypted snapshots from a stopped, reduced-owner helper."""

import hashlib
import io
import os
import stat

import pytest
from nacl.public import PrivateKey

from trading_bot.runtime import stock_backup_files as module
from trading_bot.runtime.stock_backup_crypto import decrypt_stream


@pytest.fixture
def files(tmp_path):
    root = tmp_path.resolve()
    root.chmod(0o700)
    source = root / "snapshot.bundle"
    source.write_bytes(b"fictional snapshot content" * 100)
    source.chmod(0o600)
    backup = root / "backups"
    backup.mkdir(mode=0o700)
    key = PrivateKey.generate()
    return source, backup, key


def publish(files, **overrides):
    source, backup, key = files
    kwargs = dict(
        source=source,
        source_uid=os.geteuid(),
        destination_root=backup,
        recipient_public_key=bytes(key.public_key),
        expected_plaintext_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    return module.encrypt_snapshot_bundle(**(kwargs | overrides))


def test_ciphertext_is_private_complete_hashed_and_decryptable(files):
    source, backup, key = files
    path, receipt = publish(files)
    assert path.parent == backup and path.name == receipt.ciphertext_sha256 + ".stockbackup"
    assert path.stat().st_mode & 0o777 == 0o600
    body = path.read_bytes()
    assert hashlib.sha256(body).hexdigest() == receipt.ciphertext_sha256
    result = io.BytesIO()
    decrypt_stream(io.BytesIO(body), result, bytes(key))
    assert result.getvalue() == source.read_bytes()
    assert list(backup.iterdir()) == [path]


@pytest.mark.parametrize(
    "unsafe",
    [
        "source_link",
        "source_hardlink",
        "source_public",
        "source_owner",
        "backup_public",
        "unexpected",
        "digest",
    ],
)
def test_unsafe_input_or_store_never_publishes(files, unsafe):
    source, backup, _ = files
    overrides = {}
    if unsafe == "source_link":
        saved = source.with_name("saved")
        source.rename(saved)
        source.symlink_to(saved)
    elif unsafe == "source_hardlink":
        os.link(source, source.with_name("saved"))
    elif unsafe == "source_public":
        source.chmod(0o644)
    elif unsafe == "source_owner":
        overrides["source_uid"] = os.geteuid() + 1
    elif unsafe == "backup_public":
        backup.chmod(0o755)
    elif unsafe == "unexpected":
        other = backup / "unrelated"
        other.write_bytes(b"preserve")
        other.chmod(0o600)
    else:
        overrides["expected_plaintext_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="stock_backup_publication_unavailable"):
        publish(files, **overrides)
    assert not list(backup.glob("*.stockbackup"))


def test_retention_limit_denies_without_pruning_any_generation(files):
    _, backup, _ = files
    for number in range(16):
        path = backup / (f"{number:064x}" + ".stockbackup")
        path.write_bytes(b"preserve encrypted fixture")
        path.chmod(0o600)
    before = {p.name: p.read_bytes() for p in backup.iterdir()}
    with pytest.raises(ValueError):
        publish(files)
    assert {p.name: p.read_bytes() for p in backup.iterdir()} == before


def test_partial_encryption_failure_is_never_published(files, monkeypatch):
    def fail(source, destination, *args, **kwargs):
        destination.write(b"partial ciphertext")
        raise OSError("private fixture failure")

    monkeypatch.setattr(module, "encrypt_stream", fail)
    with pytest.raises(ValueError, match="stock_backup_publication_unavailable"):
        publish(files)
    assert list(files[1].glob(".pending-*"))
    assert not list(files[1].glob("*.stockbackup"))
    with pytest.raises(ValueError, match="stock_backup_publication_unavailable"):
        publish(files)


def test_changed_source_after_encryption_denies_publication(files, monkeypatch):
    original = module.encrypt_stream

    def changed(*args, **kwargs):
        receipt = original(*args, **kwargs)
        files[0].write_bytes(b"changed after encryption")
        return receipt

    monkeypatch.setattr(module, "encrypt_stream", changed)
    with pytest.raises(ValueError):
        publish(files)
    assert list(files[1].glob(".pending-*"))
    assert not list(files[1].glob("*.stockbackup"))


def test_published_orphan_is_preserved_if_directory_fsync_is_uncertain(files, monkeypatch):
    original = module.os.fsync
    calls = []

    def fail_directory(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode) and list(files[1].glob("*.stockbackup")):
            calls.append(descriptor)
            raise OSError("uncertain directory durability")
        original(descriptor)

    monkeypatch.setattr(module.os, "fsync", fail_directory)
    with pytest.raises(ValueError):
        publish(files)
    assert len(calls) == 2  # Publication and the best-effort fence durability retry.
    assert len(list(files[1].glob("*.stockbackup"))) == 1
    assert list(files[1].glob(".pending-*"))


@pytest.fixture
def namespaces(files):
    source, backup, key = files
    root = source.parent
    sources, outputs = root / "source-namespace", root / "output-namespace"
    sources.mkdir(mode=0o700)
    outputs.mkdir(mode=0o700)
    inputs, destination = sources / "inputs", outputs / "backups"
    inputs.mkdir(mode=0o700)
    source.rename(inputs / source.name)
    backup.rename(destination)
    return inputs / source.name, destination, key


@pytest.mark.parametrize("changed", ["source", "destination"])
def test_ancestor_symlink_rebinding_never_returns_a_publication(namespaces, monkeypatch, changed):
    source, destination, _ = namespaces
    ancestor = source.parent.parent if changed == "source" else destination.parent
    moved = ancestor.with_name(ancestor.name + "-retained")
    original = module.encrypt_stream

    def rebind(*args, **kwargs):
        result = original(*args, **kwargs)
        ancestor.rename(moved)
        ancestor.symlink_to(moved, target_is_directory=True)
        return result

    monkeypatch.setattr(module, "encrypt_stream", rebind)
    with pytest.raises(ValueError, match="stock_backup_publication_unavailable"):
        publish(namespaces)
    retained = destination.resolve(strict=True)
    assert len(list(retained.glob("*.stockbackup"))) == 1
    assert list(retained.glob(".pending-*"))


@pytest.mark.parametrize("failure", ["publication", "cleanup"])
def test_uncertain_fsync_retains_fence_and_blocks_actual_next_call(files, monkeypatch, failure):
    _, destination, _ = files
    original_sync, original_encrypt = os.fsync, module.encrypt_stream
    failed, encrypted = [], []

    def encrypt(*args, **kwargs):
        encrypted.append(True)
        return original_encrypt(*args, **kwargs)

    def fail_once(descriptor):
        if (
            not failed
            and stat.S_ISDIR(os.fstat(descriptor).st_mode)
            and list(destination.glob("*.stockbackup"))
            and (failure == "publication" or not list(destination.glob(".pending-*")))
        ):
            failed.append(True)
            raise OSError("uncertain private fixture durability")
        original_sync(descriptor)

    monkeypatch.setattr(module.os, "fsync", fail_once)
    monkeypatch.setattr(module, "encrypt_stream", encrypt)
    with pytest.raises(ValueError, match="stock_backup_publication_unavailable"):
        publish(files)
    retained = {path.name: path.read_bytes() for path in destination.glob("*.stockbackup")}
    assert len(retained) == 1 and failed == [True]
    with pytest.raises(ValueError, match="stock_backup_publication_unavailable"):
        publish(files)
    assert encrypted == [True]
    assert {path.name: path.read_bytes() for path in destination.glob("*.stockbackup")} == retained
    assert list(destination.glob(".pending-*"))


@pytest.mark.parametrize("changed", ["source", "destination"])
def test_late_namespace_denial_recreates_a_fence_before_next_admission(
    namespaces, monkeypatch, changed
):
    source, destination, _ = namespaces
    ancestor = source.parent.parent if changed == "source" else destination.parent
    moved = ancestor.with_name(ancestor.name + "-retained")
    original = os.fsync
    rebound = []

    def late(descriptor):
        original(descriptor)
        if (
            not rebound
            and stat.S_ISDIR(os.fstat(descriptor).st_mode)
            and list(destination.glob("*.stockbackup"))
            and not list(destination.glob(".pending-*"))
        ):
            ancestor.rename(moved)
            ancestor.symlink_to(moved, target_is_directory=True)
            rebound.append(True)

    monkeypatch.setattr(module.os, "fsync", late)
    with pytest.raises(ValueError, match="stock_backup_publication_unavailable"):
        publish(namespaces)
    ancestor.unlink()
    moved.rename(ancestor)
    assert rebound == [True] and len(list(destination.glob("*.stockbackup"))) == 1
    with pytest.raises(ValueError, match="stock_backup_publication_unavailable"):
        publish(namespaces)
    assert list(destination.glob(".pending-*"))


def test_pending_fence_is_private_and_durable_before_first_ciphertext_creation(files, monkeypatch):
    _, destination, _ = files
    original_open, original_sync = os.open, os.fsync
    synced, checked = [], []

    def sync(descriptor):
        original_sync(descriptor)
        synced.append("directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file")

    def opened(path, flags, *args, **kwargs):
        if isinstance(path, str) and path.endswith(".cipher") and flags & os.O_CREAT:
            markers = list(destination.glob(".pending-*"))
            assert len(markers) == 1 and synced == ["file", "directory"]
            info = markers[0].stat()
            assert info.st_uid == os.geteuid() and info.st_nlink == 1 and info.st_size == 0
            assert stat.S_IMODE(info.st_mode) == 0o600
            checked.append(True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", opened)
    monkeypatch.setattr(module.os, "fsync", sync)
    path, _ = publish(files)
    assert checked == [True] and list(destination.iterdir()) == [path]


def test_initial_fence_directory_fsync_failure_blocks_next_call_before_encryption(
    files, monkeypatch
):
    _, destination, _ = files
    original = os.fsync
    failed, encrypted = [], []

    def fail_once(descriptor):
        if not failed and stat.S_ISDIR(os.fstat(descriptor).st_mode):
            failed.append(True)
            raise OSError("uncertain initial fence durability")
        original(descriptor)

    def forbidden(*args, **kwargs):
        encrypted.append(True)
        raise AssertionError("ciphertext creation must not begin")

    monkeypatch.setattr(module.os, "fsync", fail_once)
    monkeypatch.setattr(module, "encrypt_stream", forbidden)
    for _ in range(2):
        with pytest.raises(ValueError, match="stock_backup_publication_unavailable"):
            publish(files)
    assert encrypted == [] and failed == [True]
    markers = list(destination.glob(".pending-*"))
    assert len(markers) == 1 and markers[0].read_bytes() == b""
    assert not list(destination.glob("*.stockbackup"))


@pytest.mark.parametrize("drift", ["size", "digest"])
def test_actual_published_cipher_readback_failure_keeps_forensics_and_blocks_next_call(
    files, monkeypatch, drift
):
    _, destination, _ = files
    original_check, original_encrypt = module._verify_cipher, module.encrypt_stream
    encrypted = []

    def encrypt(*args, **kwargs):
        encrypted.append(True)
        return original_encrypt(*args, **kwargs)

    def corrupt(directory, name, receipt):
        if name.endswith(".stockbackup"):
            path = destination / name
            body = path.read_bytes()
            path.write_bytes(b"truncated" if drift == "size" else bytes([body[0] ^ 1]) + body[1:])
        return original_check(directory, name, receipt)

    monkeypatch.setattr(module, "_verify_cipher", corrupt)
    monkeypatch.setattr(module, "encrypt_stream", encrypt)
    with pytest.raises(ValueError, match="stock_backup_publication_unavailable"):
        publish(files)
    retained = {path.name: path.read_bytes() for path in destination.glob("*.stockbackup")}
    assert len(retained) == 1 and list(destination.glob(".pending-*"))
    with pytest.raises(ValueError, match="stock_backup_publication_unavailable"):
        publish(files)
    assert encrypted == [True]
    assert {path.name: path.read_bytes() for path in destination.glob("*.stockbackup")} == retained
