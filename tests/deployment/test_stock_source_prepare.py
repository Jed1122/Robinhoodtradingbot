"""Actual disposable local Git repositories; no daemon/provider/credential access."""

import hashlib
import importlib
import subprocess
from pathlib import Path

import pytest
from test_stock_build_inputs import FILES

ROOT = Path(__file__).resolve().parents[2]
GIT = "/usr/bin/git"


def api():
    path = ROOT / "infra/hybrid/stock_source_prepare.py"
    assert path.is_file(), "Bounded clean Git source preparer is missing"
    return importlib.import_module("infra.hybrid.stock_source_prepare")


def git(repo, *arguments):
    return subprocess.run(
        [GIT, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
        timeout=10,
    ).stdout


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir(mode=0o700)
    git(repo, "init", "-q")
    for name, raw in FILES.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (repo / ".gitignore").write_text(".env\n")
    (repo / "outside.txt").write_bytes(b"unselected tracked fixture")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "fixture committed source")
    (repo / ".env").write_bytes(b"invented fixture secret outside build")
    output = tmp_path / "source.tar"
    return repo, output


def test_prepare_owns_clean_git_archive_hash_and_excludes_unselected_files(source):
    module = api()
    repo, output = source
    sha = module._prepare_source(output, repo=repo)
    raw = output.read_bytes()
    assert sha == hashlib.sha256(raw).hexdigest()
    from infra.hybrid.stock_build_inputs import inspect_source

    parsed = inspect_source(raw, expected_sha256=sha)
    assert parsed.commit.encode() + b"\n" == git(repo, "rev-parse", "HEAD")
    assert parsed.dockerfile == FILES["Dockerfile"]
    assert b"unselected tracked fixture" not in raw
    assert b"invented fixture secret" not in raw
    assert output.stat().st_mode & 0o777 == 0o600
    assert not git(repo, "status", "--porcelain")


@pytest.mark.parametrize("kind", ["tracked", "staged", "untracked"])
def test_dirty_repository_never_writes_archive(source, kind):
    repo, output = source
    if kind == "untracked":
        (repo / "untracked").write_text("x")
    else:
        (repo / "Dockerfile").write_bytes(b"changed")
        if kind == "staged":
            git(repo, "add", "Dockerfile")
    with pytest.raises(ValueError):
        api()._prepare_source(output, repo=repo)
    assert not output.exists()


@pytest.mark.parametrize(
    "kind", ["existing", "symlink", "parent_link", "parent_writable", "relative"]
)
def test_output_is_exclusive_under_a_trusted_nonsymlink_parent(source, kind):
    repo, output = source
    if kind == "existing":
        output.write_bytes(b"preserve")
    elif kind == "symlink":
        output.symlink_to(repo / "Dockerfile")
    elif kind == "parent_link":
        link = output.parent / "linked"
        link.symlink_to(output.parent, target_is_directory=True)
        output = link / "source.tar"
    elif kind == "parent_writable":
        output.parent.chmod(0o777)
    else:
        output = Path("relative.tar")
    with pytest.raises(ValueError):
        api()._prepare_source(output, repo=repo)
    assert (repo / "Dockerfile").read_bytes() == FILES["Dockerfile"]
    if kind == "existing":
        assert output.read_bytes() == b"preserve"


def test_ambient_git_environment_and_global_attributes_are_not_inputs(source, monkeypatch):
    repo, output = source
    for name in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_CONFIG_COUNT",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
    ):
        monkeypatch.setenv(name, "invalid ambient fixture")
    sha = api()._prepare_source(output, repo=repo)
    assert sha == hashlib.sha256(output.read_bytes()).hexdigest()


@pytest.mark.parametrize("kind", ["root_attributes", "nested_attributes", "info_attributes"])
def test_archive_attribute_overrides_cannot_rewrite_committed_build_inputs(source, kind):
    repo, output = source
    if kind == "info_attributes":
        (repo / ".git/info/attributes").write_text("src/* export-ignore\n")
    else:
        path = repo / (".gitattributes" if kind == "root_attributes" else "src/.gitattributes")
        path.write_text("* export-subst\n.gitattributes export-ignore\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "fixture archive attributes")
    with pytest.raises(ValueError):
        api()._prepare_source(output, repo=repo)
    assert not output.exists()


@pytest.mark.parametrize("kind", ["large_file", "large_archive"])
def test_original_tar_limits_apply_before_output_publication(source, kind):
    repo, output = source
    count = 1 if kind == "large_file" else 17
    raw = bytes(1048577 if kind == "large_file" else 1048576)
    for i in range(count):
        (repo / "src" / ("large" + str(i) + ".py")).write_bytes(raw)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "fixture oversized source")
    with pytest.raises(ValueError):
        api()._prepare_source(output, repo=repo)
    assert not output.exists()


@pytest.mark.parametrize("kind", ["head", "dirty", "parent", "source_link"])
def test_changes_after_archive_do_not_return_an_acknowledged_source(source, monkeypatch, kind):
    module = api()
    repo, output = source
    original = module._native
    changed = False

    def mutate(repository, arguments, *args, **kwargs):
        nonlocal changed
        raw = original(repository, arguments, *args, **kwargs)
        if arguments[0] == "archive" and not changed:
            changed = True
            if kind == "head":
                git(repo, "commit", "--allow-empty", "-qm", "fixture concurrent HEAD")
            elif kind == "dirty":
                (repo / "Dockerfile").write_text("concurrent edit")
            elif kind == "parent":
                output.parent.rename(output.parent.with_name(output.parent.name + "-old"))
                output.parent.mkdir(mode=0o700)
            else:
                output.symlink_to(repo / "Dockerfile")
        return raw

    monkeypatch.setattr(module, "_native", mutate)
    with pytest.raises(ValueError, match=r"^stock_source_prepare_unavailable$"):
        module._prepare_source(output, repo=repo)
    assert changed
    assert output.is_symlink() if kind == "source_link" else not output.exists()


@pytest.mark.parametrize("kind", ["disk", "replace", "late"])
def test_durable_file_does_not_imply_success_after_failed_or_late_boundary(
    source, monkeypatch, kind
):
    module = api()
    repo, output = source
    original = module.os.fsync
    clock = [module.time.monotonic()]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    changed = False

    def interrupted(fd):
        nonlocal changed
        original(fd)
        if output.exists() and not changed:
            info, expected = module.os.fstat(fd), output.stat()
            if (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino):
                changed = True
                if kind == "disk":
                    raise OSError("fixture fsync failure")
                if kind == "replace":
                    raw = output.read_bytes()
                    output.rename(output.with_name("old-source"))
                    output.write_bytes(raw)
                    output.chmod(0o600)
                else:
                    clock[0] += 30

    monkeypatch.setattr(module.os, "fsync", interrupted)
    with pytest.raises(ValueError, match=r"^stock_source_prepare_unavailable$"):
        module._prepare_source(output, repo=repo)
    assert changed and output.exists()


@pytest.mark.parametrize("kind", ["stdout", "stderr", "idle", "closed_then_idle", "ignore_term"])
def test_git_child_output_and_elapsed_time_are_bounded_and_child_is_reaped(
    source, monkeypatch, kind
):
    import sys
    import time

    module = api()
    repo, _ = source
    original = module.subprocess.Popen
    children = []
    programs = {
        "stdout": "import os; os.write(1, b'x' * 65)",
        "stderr": "import os; os.write(2, b'x' * 16385)",
        "idle": "import time; time.sleep(10)",
        "closed_then_idle": "import os,time; os.close(1); os.close(2); time.sleep(10)",
        "ignore_term": (
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(10)"
        ),
    }

    def child(arguments, **kwargs):
        process = original([sys.executable, "-c", programs[kind]], **kwargs)
        children.append(process)
        assert kwargs["env"]["GIT_CONFIG_GLOBAL"] == "/dev/null"
        assert "GIT_DIR" not in kwargs["env"] and "HOME" not in kwargs["env"]
        return process

    monkeypatch.setattr(module.subprocess, "Popen", child)
    with pytest.raises((ValueError, subprocess.TimeoutExpired)):
        module._git(repo, ("status",), limit=64, deadline=time.monotonic() + 0.2)
    assert len(children) == 1 and children[0].poll() is not None
    assert children[0].stdout.closed and children[0].stderr.closed
