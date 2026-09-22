"""Private-file diagnostics using invented credentials and temporary directories only."""

import hashlib
import json
import os
from datetime import UTC, datetime

import pytest

from trading_bot.diagnostics.alpaca_probe import ProbeError, ProbeReceipt
from trading_bot.diagnostics.alpaca_probe_io import (
    publish_probe_blob,
    publish_probe_receipt,
    read_probe_credential,
)
from trading_bot.market_data import bundle_store

BODY = b'{"synthetic":true}\n'
KEY = "synthetic-key-123456"
SECRET = "synthetic-secret-123456"


@pytest.fixture
def locations(tmp_path):
    repo, private = tmp_path.resolve() / "repo", tmp_path.resolve() / "private"
    repo.mkdir(mode=0o700)
    private.mkdir(mode=0o700)
    key = private / "credentials.json"
    key.write_text(json.dumps({"key_id": KEY, "secret_key": SECRET}))
    key.chmod(0o600)
    return repo, private, key


def test_exact_bytes_private_permissions_and_no_overwrite(locations):
    repo, root, _ = locations
    digest = publish_probe_blob(root, BODY, repository_root=repo)
    target = root / (digest + ".raw")
    assert digest == hashlib.sha256(BODY).hexdigest()
    assert target.read_bytes() == BODY
    assert target.stat().st_mode & 0o777 == 0o600
    assert publish_probe_blob(root, BODY, repository_root=repo) == digest
    target.write_bytes(b"different")
    with pytest.raises(ProbeError, match="probe_storage_failed"):
        publish_probe_blob(root, BODY, repository_root=repo)
    assert target.read_bytes() == b"different"


def test_private_credential_returns_only_expected_fields(locations):
    repo, _, key = locations
    credential = read_probe_credential(key, repository_root=repo)
    assert credential.key_id == KEY
    assert credential.secret_key == SECRET
    assert KEY not in repr(credential) and SECRET not in str(credential)


@pytest.mark.parametrize(
    "case",
    [
        "root_link",
        "ancestor_link",
        "key_link",
        "key_mode",
        "root_mode",
        "fifo",
        "directory",
        "inside_repo",
        "relative",
        "traversal",
        "missing",
        "too_large",
        "invalid_json",
        "duplicate_key",
    ],
)
def test_credential_boundary_rejects_unsafe_files_without_echo(locations, case):
    repo, root, key = locations
    if case == "root_link":
        link = root.parent / "link"
        link.symlink_to(root, target_is_directory=True)
        key = link / key.name
    elif case == "ancestor_link":
        link = root.parent / "link"
        link.symlink_to(root.parent, target_is_directory=True)
        key = link / root.name / key.name
    elif case in ("key_link", "fifo", "directory"):
        key.unlink()
        if case == "key_link":
            key.symlink_to(repo)
        elif case == "fifo":
            os.mkfifo(key, 0o600)
        else:
            key.mkdir(mode=0o700)
    elif case == "key_mode":
        key.chmod(0o644)
    elif case == "root_mode":
        root.chmod(0o755)
    elif case == "inside_repo":
        repo = root.parent
    elif case == "relative":
        key = type(key)("credentials.json")
    elif case == "traversal":
        key = root / ".." / root.name / key.name
    elif case == "missing":
        key.unlink()
    elif case == "too_large":
        key.write_bytes(b"x" * 4097)
    elif case == "invalid_json":
        key.write_bytes(SECRET.encode())
    else:
        key.write_bytes(b'{"key_id":"synthetic-key-123456","key_id":"duplicate"}')
    with pytest.raises(ProbeError) as caught:
        read_probe_credential(key, repository_root=repo)
    assert KEY not in str(caught.value) and SECRET not in repr(caught.value)
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        "short",
        "x" * 257,
        "x" * 16 + "\n",
        "x" * 16 + " ",
        "x" * 16 + "\x00",
        "é" * 20,
        True,
        123,
        None,
        [],
    ],
)
def test_credential_value_validation_is_strict(locations, value):
    repo, _, key = locations
    key.write_text(json.dumps({"key_id": KEY, "secret_key": value}))
    with pytest.raises(ProbeError, match="probe_credential_invalid"):
        read_probe_credential(key, repository_root=repo)


def test_extra_credential_fields_are_rejected(locations):
    repo, _, key = locations
    key.write_text(json.dumps({"key_id": KEY, "secret_key": SECRET, "account": "invented"}))
    with pytest.raises(ProbeError):
        read_probe_credential(key, repository_root=repo)


@pytest.mark.parametrize("case", ["symlink", "mode", "repo", "oversized", "empty", "wrong_type"])
def test_quarantine_publication_refuses_unsafe_scope(locations, case):
    repo, root, _ = locations
    body = BODY
    if case == "symlink":
        link = root.parent / "link"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif case == "mode":
        root.chmod(0o755)
    elif case == "repo":
        repo = root.parent
    elif case == "oversized":
        body = b"x" * 1048577
    elif case == "empty":
        body = b""
    else:
        body = "not bytes"
    with pytest.raises(ProbeError):
        publish_probe_blob(root, body, repository_root=repo)


def test_receipt_is_content_addressed_and_contains_no_provider_fields(locations):
    repo, root, _ = locations
    now = datetime(2026, 9, 17, tzinfo=UTC)
    receipt = ProbeReceipt("a" * 64, 0, now, now, 403, None, 0, "probe_access_denied")
    digest = publish_probe_receipt(root, receipt, repository_root=repo)
    target = root / (digest + ".receipt.json")
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    assert json.loads(target.read_bytes())["status_code"] == 403
    assert KEY not in target.read_text() and SECRET not in target.read_text()
    assert target.stat().st_mode & 0o777 == 0o600


def test_short_writes_preserve_exact_blob(locations, monkeypatch):
    repo, root, _ = locations
    original = os.write
    monkeypatch.setattr(bundle_store.os, "write", lambda fd, body: original(fd, body[:2]))
    digest = publish_probe_blob(root, BODY, repository_root=repo)
    assert (root / (digest + ".raw")).read_bytes() == BODY


@pytest.mark.parametrize("operation", ["write", "fsync", "link"])
def test_storage_failures_are_sanitized_and_never_overwrite(locations, monkeypatch, operation):
    repo, root, _ = locations

    def fail(*args, **kwargs):
        raise OSError(SECRET)

    monkeypatch.setattr(bundle_store.os, operation, fail)
    with pytest.raises(ProbeError, match="probe_storage_failed") as caught:
        publish_probe_blob(root, BODY, repository_root=repo)
    assert caught.value.__context__ is None
    assert not (root / (hashlib.sha256(BODY).hexdigest() + ".raw")).exists()
