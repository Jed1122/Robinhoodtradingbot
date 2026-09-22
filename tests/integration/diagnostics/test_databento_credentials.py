"""Credential persistence tested using invented keys only."""

import os

import pytest

from trading_bot.diagnostics.databento_preflight import (
    DatabentoCredential,
    DatabentoPreflightError,
    load_credential,
    save_credential,
)

KEY = "db-" + "a" * 29


@pytest.fixture
def locations(tmp_path):
    repo = tmp_path.resolve() / "repo"
    private = tmp_path.resolve() / "private"
    repo.mkdir(mode=0o700)
    private.mkdir(mode=0o700)
    return repo, private


def test_round_trip_private_key_and_no_overwrite(locations):
    repo, private = locations
    save_credential(private, DatabentoCredential(KEY), repository_root=repo)
    path = private / "databento.key"
    assert path.read_text() == KEY
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_credential(private, repository_root=repo).api_key == KEY
    with pytest.raises(DatabentoPreflightError, match="credential_storage_failed"):
        save_credential(private, DatabentoCredential("db-" + "b" * 29), repository_root=repo)
    assert path.read_text() == KEY


@pytest.mark.parametrize("marker", ["directory", "file", "symlink"])
def test_other_git_checkout_is_not_a_credential_destination(locations, marker):
    repo, private = locations
    marker_path = private.parent / ".git"
    if marker == "directory":
        marker_path.mkdir()
    elif marker == "file":
        marker_path.write_text("gitdir: /invented/common/worktrees/other\n")
    else:
        marker_path.symlink_to(private.parent / "missing-git")
    with pytest.raises(DatabentoPreflightError, match="credential_storage_failed"):
        save_credential(private, DatabentoCredential(KEY), repository_root=repo)
    assert list(private.iterdir()) == []


@pytest.mark.parametrize("marker", ["directory", "file"])
def test_read_is_refused_if_directory_becomes_part_of_git(locations, marker):
    repo, private = locations
    save_credential(private, DatabentoCredential(KEY), repository_root=repo)
    if marker == "directory":
        (private / ".git").mkdir()
    else:
        (private.parent / ".git").write_text("gitdir: /invented/worktrees/other\n")
    with pytest.raises(DatabentoPreflightError, match="credential_invalid"):
        load_credential(private, repository_root=repo)


def test_identical_store_rejects_hardlink_and_accepts_single_link(locations):
    repo, private = locations
    credential = DatabentoCredential(KEY)
    save_credential(private, credential, repository_root=repo)
    save_credential(private, credential, repository_root=repo)
    os.link(private / "databento.key", private / "other")
    with pytest.raises(DatabentoPreflightError, match="credential_storage_failed"):
        save_credential(private, credential, repository_root=repo)


@pytest.mark.parametrize(
    "case",
    [
        "directory_mode",
        "key_mode",
        "key_symlink",
        "ancestor_symlink",
        "fifo",
        "inside_repo",
        "too_large",
        "missing",
        "hard_link",
    ],
)
def test_unsafe_credential_paths_are_denied(locations, case):
    repo, private = locations
    save_credential(private, DatabentoCredential(KEY), repository_root=repo)
    path = private / "databento.key"
    if case == "directory_mode":
        private.chmod(0o755)
    elif case == "key_mode":
        path.chmod(0o644)
    elif case == "ancestor_symlink":
        link = private.parent / "link"
        link.symlink_to(private, target_is_directory=True)
        private = link
    elif case == "inside_repo":
        repo = private.parent
    elif case == "too_large":
        path.write_text("x" * 513)
    elif case == "hard_link":
        os.link(path, private / "key-copy")
    else:
        path.unlink()
        if case == "key_symlink":
            path.symlink_to(repo)
        elif case == "fifo":
            os.mkfifo(path, 0o600)
    with pytest.raises(DatabentoPreflightError, match="credential_invalid") as error:
        load_credential(private, repository_root=repo)
    assert KEY not in repr(error.value)
    assert error.value.__context__ is None
