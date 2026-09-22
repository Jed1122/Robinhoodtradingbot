"""Real descriptor-relative IO, privacy, collision and durability fault checks."""

import hashlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.research._options_shortlist_fixtures import (
    load_shortlist,
    make_case,
    selected_result,
)


@pytest.fixture
def paths(tmp_path):
    root = tmp_path.resolve() / "private"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    repository = tmp_path.resolve() / "repo"
    repository.mkdir()
    return root, repository


def input_file(root):
    from trading_bot.research.options_shortlist_wire import encode_shortlist_input

    path = root / "input.json"
    path.write_bytes(encode_shortlist_input(make_case()))
    path.chmod(0o600)
    return path


def read(path, repository, settings=None):
    from trading_bot.research.options_shortlist_io import read_shortlist_input

    return read_shortlist_input(
        path,
        settings=settings or load_shortlist().config.options.research_shortlist,
        repository_root=repository,
    )


def write(root, repository, settings=None):
    from trading_bot.research.options_shortlist_io import write_shortlist_manifest

    return write_shortlist_manifest(
        root,
        selected_result(),
        repository_root=repository,
        settings=settings or load_shortlist().config.options.research_shortlist,
    )


def test_private_input_hash_and_manifest_are_reproducible(paths):
    root, repository = paths
    path = input_file(root)
    case, digest = read(path, repository)
    assert case == make_case()
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    result_hash = write(root, repository)
    assert result_hash == write(root, repository)
    artifact = root / "options-shortlists" / (result_hash + ".json")
    assert artifact.stat().st_mode & 0o777 == 0o600
    assert artifact.parent.stat().st_mode & 0o777 == 0o700
    document = json.loads(artifact.read_bytes())
    assert document["schema"] == "options-shortlist-manifest-v1"
    assert document["result"]["candidate_count"] == 2
    assert document["result"]["live_authorized"] is False
    assert str(root) not in artifact.read_text()


@pytest.mark.parametrize(
    "change", ["file_mode", "root_mode", "relative", "traversal", "missing", "fifo", "repository"]
)
def test_unsafe_inputs_deny_with_sanitized_errors(paths, change):
    root, repository = paths
    path = input_file(root)
    if change == "file_mode":
        path.chmod(0o644)
    elif change == "root_mode":
        root.chmod(0o755)
    elif change == "relative":
        path = Path("input.json")
    elif change == "traversal":
        path = root / ".." / root.name / path.name
    elif change == "missing":
        path = root / "absent.json"
    elif change == "fifo":
        path = root / "fifo"
        os.mkfifo(path, mode=0o600)
    else:
        repository = root
    with pytest.raises(ValueError) as caught:
        read(path, repository)
    assert str(root) not in str(caught.value)
    assert caught.value.__context__ is None


@pytest.mark.parametrize("where", ["input", "root", "ancestor", "output_directory", "output_file"])
def test_symlinks_rejected_at_each_boundary(paths, where):
    root, repository = paths
    path = input_file(root)
    if where == "input":
        link = root / "link.json"
        link.symlink_to(path)
        with pytest.raises(ValueError):
            read(link, repository)
    elif where in {"root", "ancestor"}:
        link = root.parent / "link"
        link.symlink_to(root if where == "root" else root.parent, target_is_directory=True)
        target = link / path.name if where == "root" else link / root.name / path.name
        with pytest.raises(ValueError):
            read(target, repository)
    elif where == "output_directory":
        (root / "options-shortlists").symlink_to(repository, target_is_directory=True)
        with pytest.raises(ValueError):
            write(root, repository)
    else:
        digest = write(root, repository)
        artifact = root / "options-shortlists" / (digest + ".json")
        artifact.unlink()
        artifact.symlink_to(path)
        with pytest.raises(ValueError):
            write(root, repository)
    assert path.exists()


def test_conflicting_artifact_preserved(paths):
    root, repository = paths
    digest = write(root, repository)
    artifact = root / "options-shortlists" / (digest + ".json")
    artifact.write_bytes(b"existing different bytes")
    with pytest.raises(ValueError, match="shortlist_storage_conflict"):
        write(root, repository)
    assert artifact.read_bytes() == b"existing different bytes"


def test_input_stat_and_read_growth_bounds(paths, monkeypatch):
    root, repository = paths
    path = input_file(root)
    settings = load_shortlist().config.options.research_shortlist.model_copy(
        update={"max_input_bytes": 100}
    )
    with pytest.raises(ValueError):
        read(path, repository, settings)
    original = os.fstat

    def small_stat(fd):
        info = original(fd)
        if stat.S_ISREG(info.st_mode):
            return SimpleNamespace(st_mode=info.st_mode, st_uid=info.st_uid, st_size=0)
        return info

    monkeypatch.setattr(os, "fstat", small_stat)
    with pytest.raises(ValueError):
        read(path, repository, settings)


def test_oversized_manifest_has_no_publication(paths):
    root, repository = paths
    settings = load_shortlist().config.options.research_shortlist.model_copy(
        update={"max_input_bytes": 100}
    )
    with pytest.raises(ValueError):
        write(root, repository, settings)
    assert not (root / "options-shortlists").exists()


def test_short_writes_finish_and_zero_write_denies(paths, monkeypatch):
    root, repository = paths
    original = os.write
    monkeypatch.setattr(os, "write", lambda fd, body: original(fd, body[: max(1, len(body) // 2)]))
    assert len(write(root, repository)) == 64
    other = root / "other"
    other.mkdir(mode=0o700)
    monkeypatch.setattr(os, "write", lambda fd, body: 0)
    with pytest.raises(ValueError, match="shortlist_storage_unavailable"):
        write(other, repository)
    assert not list((other / "options-shortlists").iterdir())


@pytest.mark.parametrize("operation", ["link", "fsync"])
def test_publication_faults_report_failure_without_false_success(paths, monkeypatch, operation):
    root, repository = paths

    def broken(*args, **kwargs):
        raise OSError("fabricated storage failure")

    monkeypatch.setattr(os, operation, broken)
    with pytest.raises(ValueError, match="shortlist_storage_unavailable"):
        write(root, repository)


def test_post_link_sync_failure_preserves_complete_artifact_and_retry(paths, monkeypatch):
    root, repository = paths
    original = os.fsync
    count = 0

    def uncertain(fd):
        nonlocal count
        count += 1
        if count == 3:
            raise OSError("fabricated uncertain directory durability")
        original(fd)

    monkeypatch.setattr(os, "fsync", uncertain)
    with pytest.raises(ValueError, match="shortlist_storage_unavailable"):
        write(root, repository)
    artifacts = list((root / "options-shortlists").glob("*.json"))
    assert len(artifacts) == 1
    before = artifacts[0].read_bytes()
    monkeypatch.setattr(os, "fsync", original)
    assert write(root, repository) == artifacts[0].stem
    assert artifacts[0].read_bytes() == before


def test_scoped_code_hash_is_stable_and_missing_source_denies(monkeypatch):
    from trading_bot.research.options_shortlist_io import shortlist_code_hash

    assert shortlist_code_hash() == shortlist_code_hash()

    def missing(path):
        raise OSError("fabricated source missing")

    monkeypatch.setattr(Path, "read_bytes", missing)
    with pytest.raises(ValueError):
        shortlist_code_hash()
