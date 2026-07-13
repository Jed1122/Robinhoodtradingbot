import re
import subprocess
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

import trading_bot.code_identity as code_identity
from trading_bot.code_identity import (
    CodeIdentity,
    CodeIdentityError,
    InvalidImageDigest,
    UnsafeCodeIdentity,
    require_clean_live_identity,
    resolve_code_identity,
)
from trading_bot.domain import CodeHash


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _initialize_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Test User")


def _commit_all(repo: Path, message: str = "fixture") -> str:
    _git(repo, "add", "--all")
    _git(repo, "commit", "--quiet", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_git_runner_uses_fixed_argv_without_a_shell(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        command: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout=b"ok")

    monkeypatch.setattr(code_identity.subprocess, "run", fake_run)

    assert code_identity._run_git(tmp_path, "status", "--porcelain=v1") == b"ok"
    assert captured == {
        "command": ("git", "status", "--porcelain=v1"),
        "cwd": tmp_path,
        "check": False,
        "capture_output": True,
        "shell": False,
    }


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    _initialize_repo(repo)
    (repo / "README.md").write_text("tracked\n", encoding="utf-8")
    _commit_all(repo)
    return repo


def test_clean_identity_records_commit_and_is_live_safe(tmp_git_repo: Path) -> None:
    expected_commit = _git(tmp_git_repo, "rev-parse", "HEAD")

    identity = resolve_code_identity(tmp_git_repo, image_digest=None)

    assert tuple(field.name for field in fields(identity)) == (
        "code_hash",
        "git_commit",
        "dirty",
        "image_digest",
        "non_promotable",
    )
    assert re.fullmatch(r"[0-9a-f]{64}", identity.code_hash)
    assert identity.git_commit == expected_commit
    assert not identity.dirty
    assert identity.image_digest is None
    assert not identity.non_promotable
    require_clean_live_identity(identity)


def test_code_identity_is_frozen(tmp_git_repo: Path) -> None:
    identity = resolve_code_identity(tmp_git_repo, image_digest=None)

    with pytest.raises(FrozenInstanceError):
        identity.dirty = True  # type: ignore[misc]


def test_modified_tracked_content_is_hashed_and_cannot_supply_live_identity(
    tmp_git_repo: Path,
) -> None:
    clean = resolve_code_identity(tmp_git_repo, image_digest=None)
    (tmp_git_repo / "README.md").write_text("modified\n", encoding="utf-8")

    dirty = resolve_code_identity(tmp_git_repo, image_digest=None)

    assert dirty.code_hash != clean.code_hash
    assert dirty.git_commit is None
    assert dirty.dirty
    assert dirty.non_promotable
    with pytest.raises(UnsafeCodeIdentity):
        require_clean_live_identity(dirty)


def test_staged_tracked_change_is_dirty(tmp_git_repo: Path) -> None:
    (tmp_git_repo / "README.md").write_text("staged\n", encoding="utf-8")
    _git(tmp_git_repo, "add", "README.md")

    identity = resolve_code_identity(tmp_git_repo, image_digest=None)

    assert identity.dirty
    assert identity.non_promotable


def test_deleted_tracked_path_changes_hash_and_is_dirty(tmp_git_repo: Path) -> None:
    clean = resolve_code_identity(tmp_git_repo, image_digest=None)
    (tmp_git_repo / "README.md").unlink()

    identity = resolve_code_identity(tmp_git_repo, image_digest=None)

    assert identity.code_hash != clean.code_hash
    assert identity.dirty


@pytest.mark.parametrize(
    "relative_path",
    ["src/new.py", "configs/new.yaml", "migrations/001.sql", "scripts/run.py"],
)
def test_relevant_untracked_content_is_hashed_and_marks_identity_dirty(
    tmp_git_repo: Path, relative_path: str
) -> None:
    clean = resolve_code_identity(tmp_git_repo, image_digest=None)
    path = tmp_git_repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("runtime content\n", encoding="utf-8")

    dirty = resolve_code_identity(tmp_git_repo, image_digest=None)

    assert dirty.code_hash != clean.code_hash
    assert dirty.dirty
    assert dirty.non_promotable


def test_irrelevant_untracked_content_does_not_change_identity(tmp_git_repo: Path) -> None:
    clean = resolve_code_identity(tmp_git_repo, image_digest=None)
    (tmp_git_repo / "notes.txt").write_text("local note\n", encoding="utf-8")

    after_note = resolve_code_identity(tmp_git_repo, image_digest=None)

    assert after_note == clean


def test_ignored_relevant_untracked_source_is_still_hashed(tmp_git_repo: Path) -> None:
    clean = resolve_code_identity(tmp_git_repo, image_digest=None)
    (tmp_git_repo / ".gitignore").write_text("src/ignored.py\n", encoding="utf-8")
    ignored_source = tmp_git_repo / "src/ignored.py"
    ignored_source.parent.mkdir()
    ignored_source.write_text("runtime content\n", encoding="utf-8")

    dirty = resolve_code_identity(tmp_git_repo, image_digest=None)

    assert dirty.code_hash != clean.code_hash
    assert dirty.dirty
    assert dirty.non_promotable


def test_code_hash_is_deterministic_regardless_of_file_creation_order(tmp_path: Path) -> None:
    repos: list[Path] = []
    for repo_name, paths in (
        ("first", ("src/a.py", "configs/a.yaml")),
        ("second", ("configs/a.yaml", "src/a.py")),
    ):
        repo = tmp_path / repo_name
        _initialize_repo(repo)
        for relative_path in paths:
            path = repo / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative_path, encoding="utf-8")
        _commit_all(repo)
        repos.append(repo)

    first = resolve_code_identity(repos[0], image_digest=None)
    second = resolve_code_identity(repos[1], image_digest=None)

    assert first.code_hash == second.code_hash


def test_length_prefixes_prevent_path_content_boundary_collisions(tmp_path: Path) -> None:
    first_repo = tmp_path / "first"
    _initialize_repo(first_repo)
    (first_repo / "src").mkdir()
    (first_repo / "src/a").write_bytes(b"bc")
    _commit_all(first_repo)

    second_repo = tmp_path / "second"
    _initialize_repo(second_repo)
    (second_repo / "src").mkdir()
    (second_repo / "src/ab").write_bytes(b"c")
    _commit_all(second_repo)

    first = resolve_code_identity(first_repo, image_digest=None)
    second = resolve_code_identity(second_repo, image_digest=None)

    assert first.code_hash != second.code_hash


def test_relevant_untracked_marker_distinguishes_untracked_from_tracked(tmp_path: Path) -> None:
    tracked_repo = tmp_path / "tracked"
    _initialize_repo(tracked_repo)
    (tracked_repo / "src").mkdir()
    (tracked_repo / "src/value.py").write_text("same", encoding="utf-8")
    _commit_all(tracked_repo)

    untracked_repo = tmp_path / "untracked"
    _initialize_repo(untracked_repo)
    _git(untracked_repo, "commit", "--quiet", "--allow-empty", "-m", "empty")
    (untracked_repo / "src").mkdir()
    (untracked_repo / "src/value.py").write_text("same", encoding="utf-8")

    tracked = resolve_code_identity(tracked_repo, image_digest=None)
    untracked = resolve_code_identity(untracked_repo, image_digest=None)

    assert tracked.code_hash != untracked.code_hash


def test_valid_immutable_image_digest_is_recorded(tmp_git_repo: Path) -> None:
    digest = f"sha256:{'d' * 64}"

    identity = resolve_code_identity(tmp_git_repo, image_digest=digest)

    assert identity.image_digest == digest
    require_clean_live_identity(identity)


@pytest.mark.parametrize(
    "digest",
    ["", "d" * 64, "sha256:short", f"sha256:{'G' * 64}", "sha512:" + "d" * 128],
)
def test_invalid_image_digest_is_rejected(tmp_git_repo: Path, digest: str) -> None:
    with pytest.raises(InvalidImageDigest):
        resolve_code_identity(tmp_git_repo, image_digest=digest)


def test_non_git_directory_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(CodeIdentityError):
        resolve_code_identity(tmp_path, image_digest=None)


def test_resolve_requires_repo_root_not_a_subdirectory(tmp_git_repo: Path) -> None:
    subdirectory = tmp_git_repo / "src"
    subdirectory.mkdir()

    with pytest.raises(CodeIdentityError):
        resolve_code_identity(subdirectory, image_digest=None)


def test_resolve_requires_an_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(CodeIdentityError):
        resolve_code_identity(tmp_path / "missing", image_digest=None)


def test_unsafe_identity_checks_all_invariants() -> None:
    safe_hash = "f" * 64
    unsafe_identities = (
        CodeIdentity(
            code_hash=CodeHash(safe_hash),
            git_commit=None,
            dirty=False,
            image_digest=None,
            non_promotable=False,
        ),
        CodeIdentity(
            code_hash=CodeHash(safe_hash),
            git_commit="e" * 40,
            dirty=False,
            image_digest=None,
            non_promotable=True,
        ),
    )

    for identity in unsafe_identities:
        with pytest.raises(UnsafeCodeIdentity):
            require_clean_live_identity(identity)
