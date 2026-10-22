"""Supplied archive/build bytes only; no daemon, extraction or native authority."""

import gzip
import hashlib
import importlib
import io
import json
import tarfile
from pathlib import Path

import pytest

COMMIT = "a" * 40
IMAGE = "sha256:" + "b" * 64
BASE = "python:3.12-slim-bookworm@sha256:" + "c" * 64
FILES = {
    "Dockerfile": b"ARG PYTHON_BASE_IMAGE\nFROM ${PYTHON_BASE_IMAGE}\n",
    ".docker-base-image": (BASE + "\n").encode(),
    "pyproject.toml": b"[project]\nname='fixture'\n",
    "uv.lock": b"version = 1\n",
    "alembic.ini": b"[alembic]\n",
    "compose.stock-research.yml": b"services: {}\n",
    "src/trading_bot/__init__.py": b"",
    "configs/base.yaml": b"mode: paper\n",
    "migrations/env.py": b"# fixture\n",
}


def api():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_build_inputs.py"
    assert path.is_file(), "Bounded stock build input module is missing"
    return importlib.import_module("infra.hybrid.stock_build_inputs")


def archive(*, change=None, omit=(), extra=(), comment=COMMIT):
    output = io.BytesIO()
    with tarfile.open(
        fileobj=output, mode="w", format=tarfile.PAX_FORMAT, pax_headers={"comment": comment}
    ) as result:
        rows = [(name, None) for name in ("src", "src/trading_bot", "configs", "migrations")]
        rows.extend(FILES.items())
        rows.extend(extra)
        for name, body in rows:
            if name in omit:
                continue
            info = tarfile.TarInfo(name)
            info.mode = 0o755 if body is None else 0o644
            info.type = tarfile.DIRTYPE if body is None else tarfile.REGTYPE
            info.size = 0 if body is None else len(body)
            if change is not None:
                body = change(info, body)
            result.addfile(info, None if body is None else io.BytesIO(body))
    return output.getvalue()


def inspect(raw):
    return api().inspect_source(raw, expected_sha256=hashlib.sha256(raw).hexdigest())


def test_complete_source_is_copied_data_with_original_identity(monkeypatch):
    def no_extraction(*args, **kwargs):
        raise AssertionError("Must not extract an archive onto the host")

    monkeypatch.setattr(tarfile.TarFile, "extract", no_extraction)
    monkeypatch.setattr(tarfile.TarFile, "extractall", no_extraction)
    raw = archive()
    result = inspect(raw)
    assert result.digest == hashlib.sha256(raw).hexdigest()
    assert result.commit == COMMIT and result.raw == raw and result.base_ref == BASE
    assert result.dockerfile == FILES["Dockerfile"]
    assert result.compose_template == FILES["compose.stock-research.yml"]
    assert BASE not in repr(result) and "fixture" not in repr(result)
    with pytest.raises(AttributeError):
        result.commit = "b" * 40


@pytest.mark.parametrize("commit", ["a" * 40, "b" * 64])
def test_both_supported_git_commit_hash_lengths(commit):
    assert inspect(archive(comment=commit)).commit == commit


@pytest.mark.parametrize("value", [None, True, b"0" * 64, "f" * 64, "A" * 64, "1" * 63])
def test_expected_archive_hash_is_exact(value):
    with pytest.raises(ValueError, match="stock_build_inputs_unavailable"):
        api().inspect_source(archive(), expected_sha256=value)


@pytest.mark.parametrize("kind", ["empty", "gzip", "cut", "tail", "one_zero", "oversize"])
def test_uncompressed_complete_bounded_tar_only(kind):
    raw = archive()
    if kind == "empty":
        raw = b""
    elif kind == "gzip":
        raw = gzip.compress(raw)
    elif kind == "cut":
        raw = raw[:-1]
    elif kind == "tail":
        raw += b"x" + bytes(511)
    elif kind == "one_zero":
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as value:
            value.getmembers()
            raw = raw[: value.offset + 512]
    else:
        raw = bytes(16 * 1024 * 1024 + 512)
    with pytest.raises(ValueError, match="stock_build_inputs_unavailable"):
        inspect(raw)


@pytest.mark.parametrize("raw", [None, True, bytearray(b"a"), memoryview(b"a")])
def test_archive_requires_exact_bytes(raw):
    with pytest.raises(ValueError):
        api().inspect_source(raw, expected_sha256="a" * 64)


@pytest.mark.parametrize("name", [*list(FILES)[:6], "src", "configs", "migrations"])
def test_required_build_files_and_explicit_tree_directories(name):
    with pytest.raises(ValueError):
        inspect(archive(omit=[name]))


@pytest.mark.parametrize("tree", ["src", "configs", "migrations"])
def test_each_required_tree_contains_a_regular_file(tree):
    omitted = [name for name in FILES if name.startswith(tree + "/")]
    with pytest.raises(ValueError):
        inspect(archive(omit=omitted, extra=[(tree + "/empty", None)]))


@pytest.mark.parametrize(
    "name",
    [".env", "/etc/passwd", "src/../oops", "src//oops", "src/./oops", "src/.env",
     "src/a\\b", "src/..", "untracked.txt", "src/é.py", "src/a.py/child"],
)
def test_unapproved_or_ambiguous_paths_reject(name):
    extra = [("src/a.py", b"file")] if name == "src/a.py/child" else []
    with pytest.raises(ValueError):
        inspect(archive(extra=[*extra, (name, b"untrusted")]))


@pytest.mark.parametrize("field,value", [("uid", 1), ("gid", 1), ("mode", 0o666)])
def test_owner_and_mode_policy(field, value):
    def change(info, body):
        if info.name == "Dockerfile":
            setattr(info, field, value)
        return body

    with pytest.raises(ValueError):
        inspect(archive(change=change))


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE,
             tarfile.BLKTYPE, tarfile.GNUTYPE_SPARSE],
)
def test_links_devices_and_sparse_members_reject(kind):
    def change(info, body):
        if info.name == "Dockerfile":
            info.type, info.linkname = kind, "src/trading_bot/__init__.py"
        return body

    with pytest.raises(ValueError):
        inspect(archive(change=change))


@pytest.mark.parametrize(
    "mode", ["comment", "pax", "different_commit", "duplicate", "member", "count"]
)
def test_archive_consistency_and_structural_bounds(mode):
    def change(info, body):
        if info.name == "migrations/env.py" and mode in ("pax", "different_commit"):
            info.pax_headers = {"extra": "unknown"} if mode == "pax" else {"comment": "b" * 40}
        return body

    extra = []
    if mode == "duplicate":
        extra = [("Dockerfile", b"different")]
    elif mode == "member":
        extra = [("src/large.py", bytes(1048577))]
    elif mode == "count":
        extra = [(f"src/f{i}.py", b"") for i in range(2048)]
    raw = archive(change=change, extra=extra, comment="invalid" if mode == "comment" else COMMIT)
    with pytest.raises(ValueError):
        inspect(raw)


@pytest.mark.parametrize("base", [b"python:latest\n", (BASE + "\n\n").encode(),
                                  BASE.encode(), (BASE.upper() + "\n").encode()])
def test_base_reference_is_explicit_pinned_python_recipe(base):
    def change(info, body):
        if info.name == ".docker-base-image":
            info.size = len(base)
            return base
        return body

    with pytest.raises(ValueError):
        inspect(archive(change=change))


def test_quiet_full_id_is_accepted_after_supplied_complete_record():
    raw = json.dumps({"stream": IMAGE + "\n"}).encode() + b"\r\n"
    assert api().build_image_id(raw) == IMAGE


@pytest.mark.parametrize(
    "raw",
    [b"", b'{}\r\n', b'[]\r\n', b'{"stream":"unfinished',
     json.dumps({"aux": {"ID": IMAGE}}).encode() + b"\r\n",
     json.dumps({"stream": "Successfully built " + "b" * 12 + "\n"}).encode() + b"\r\n",
     json.dumps({"stream": IMAGE}).encode() + b"\r\n",
     json.dumps({"stream": IMAGE + "\n", "error": None}).encode() + b"\r\n",
     json.dumps({"stream": IMAGE + "\n", "errorDetail": {}}).encode() + b"\r\n",
     json.dumps({"stream": IMAGE.upper() + "\n"}).encode() + b"\r\n",
     json.dumps({"stream": IMAGE + "\n"}).encode(),
     json.dumps({"stream": IMAGE + "\n"}).encode() + b"\n",
     b'{"stream":"bad","stream":"bad"}\r\n',
     (json.dumps({"stream": IMAGE + "\n"}).encode() + b"\r\n") * 2,
     b" " * 1048577],
    ids=lambda raw: hashlib.sha256(raw).hexdigest()[:12],
)
def test_intermediate_error_truncated_or_extra_build_output_is_not_success(raw):
    with pytest.raises(ValueError, match="stock_build_inputs_unavailable"):
        api().build_image_id(raw)
