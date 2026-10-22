"""Canonical snapshot-container fixtures; packaging does not qualify application state."""

import hashlib
import importlib
import io
import os
import stat
import tarfile
from pathlib import Path

import pytest

DENIAL = r"^stock_snapshot_bundle_unavailable$"
DIRECTORIES = ("archive", "exports", "state")
FIXTURE_FILES = {
    "canonical-config.json": b"{}",
    "saved-control.json": b"{}",
    "manifest.json": b"{}",
    "state/ledger.sqlite3": b"fictional ledger bytes",
    "archive/"
    + hashlib.sha256(b"fictional observation").hexdigest()
    + ".stock-observation.json": b"fictional observation",
    "archive/.stock-research.lock": b"",
    "exports/.stock-research.lock": b"",
    "exports/stock-research.json": b"{}",
}


def module():
    path = Path(__file__).resolve().parents[3] / "src/trading_bot/runtime/stock_snapshot_bundle.py"
    assert path.is_file(), "The strict streaming snapshot bundle is missing"
    return importlib.import_module("trading_bot.runtime.stock_snapshot_bundle")


def header(name, size=0, kind=tarfile.REGTYPE, **updates):
    value = tarfile.TarInfo(name)
    value.type, value.size = kind, size
    value.mode = 0o700 if kind == tarfile.DIRTYPE else 0o600
    value.uid = value.gid = value.mtime = 0
    for key, changed in updates.items():
        setattr(value, key, changed)
    return value.tobuf(format=tarfile.USTAR_FORMAT, encoding="ascii", errors="strict")


def member(name, body=b"", kind=tarfile.REGTYPE, **updates):
    return header(name, len(body), kind, **updates) + body + b"\0" * (-len(body) % 512)


def bundle(files=None, *, extra=b""):
    files = FIXTURE_FILES if files is None else files
    return (
        b"".join(header(name, kind=tarfile.DIRTYPE) for name in DIRECTORIES)
        + b"".join(member(name, body) for name, body in sorted(files.items()))
        + extra
        + b"\0" * 1024
    )


def checksum(raw):
    value = bytearray(raw)
    value[148:156] = b" " * 8
    value[148:156] = f"{sum(value):06o}\0 ".encode()
    return bytes(value)


@pytest.fixture
def source_root(tmp_path):
    root = tmp_path.resolve() / "snapshot"
    root.mkdir(mode=0o700)
    for name in DIRECTORIES:
        (root / name).mkdir(mode=0o700)
    for name, body in FIXTURE_FILES.items():
        (root / name).write_bytes(body)
        (root / name).chmod(0o600)
    return root


def test_pack_is_deterministic_canonical_ustar_and_unpack_reproduces_private_files(source_root):
    api = module()
    stream = io.BytesIO()
    receipt = api.pack_snapshot(source_root, stream)
    raw = stream.getvalue()
    assert raw == bundle()
    assert receipt.bundle_sha256 == hashlib.sha256(raw).hexdigest()
    assert receipt.file_count == len(FIXTURE_FILES)
    assert receipt.total_bytes == sum(map(len, FIXTURE_FILES.values()))
    assert receipt.stream_bytes == len(raw)
    destination = source_root.parent / "unpacked"
    assert api.unpack_snapshot(io.BytesIO(raw), destination=destination) == receipt
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    for path in destination.rglob("*"):
        info = path.lstat()
        assert info.st_uid == os.geteuid()
        if path.is_dir():
            assert stat.S_IMODE(info.st_mode) == 0o700
        else:
            assert info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600
            assert path.read_bytes() == FIXTURE_FILES[path.relative_to(destination).as_posix()]
    second = io.BytesIO()
    assert api.pack_snapshot(destination, second) == receipt
    assert second.getvalue() == raw
    assert not stream.closed


class ShortReader(io.BytesIO):
    def read(self, amount=-1):
        assert 0 < amount <= 1024 * 1024
        return super().read(min(amount, 7))


class ShortWriter(io.BytesIO):
    def write(self, raw):
        assert len(raw) <= 1024 * 1024
        return super().write(raw[:5])


def test_streaming_short_reads_and_writes_do_not_drop_bytes(source_root):
    target = ShortWriter()
    receipt = module().pack_snapshot(source_root, target)
    source = ShortReader(target.getvalue())
    restored = module().unpack_snapshot(source, destination=source_root.parent / "restored")
    assert restored == receipt
    assert not target.closed and not source.closed


@pytest.mark.parametrize(
    "maximum_bytes,maximum_files",
    [
        (True, 20000),
        (0, 20000),
        (2**31 + 1, 20000),
        (2**31, True),
        (2**31, 0),
        (2**31, 20001),
    ],
)
def test_caps_are_strict_bounded_integers(source_root, maximum_bytes, maximum_files):
    target = io.BytesIO()
    with pytest.raises(ValueError, match=DENIAL):
        module().pack_snapshot(
            source_root, target, maximum_bytes=maximum_bytes, maximum_files=maximum_files
        )
    assert target.getvalue() == b""
    destination = source_root.parent / "restored"
    with pytest.raises(ValueError, match=DENIAL):
        module().unpack_snapshot(
            io.BytesIO(bundle()),
            destination=destination,
            maximum_bytes=maximum_bytes,
            maximum_files=maximum_files,
        )
    assert not destination.exists()


def test_exact_stream_and_count_caps_include_headers_padding_and_terminator(source_root):
    api = module()
    raw = bundle()
    receipt = api.pack_snapshot(
        source_root, io.BytesIO(), maximum_bytes=len(raw), maximum_files=len(FIXTURE_FILES)
    )
    assert receipt.stream_bytes == len(raw)
    assert (
        api.unpack_snapshot(
            io.BytesIO(raw),
            destination=source_root.parent / "exact",
            maximum_bytes=len(raw),
            maximum_files=len(FIXTURE_FILES),
        )
        == receipt
    )
    for index, changed in enumerate(
        ({"maximum_bytes": len(raw) - 1}, {"maximum_files": len(FIXTURE_FILES) - 1})
    ):
        target = io.BytesIO()
        with pytest.raises(ValueError, match=DENIAL):
            api.pack_snapshot(source_root, target, **changed)
        assert target.getvalue() == b""
        destination = source_root.parent / ("too-small-" + str(index))
        with pytest.raises(ValueError, match=DENIAL):
            api.unpack_snapshot(io.BytesIO(raw), destination=destination, **changed)
        if destination.exists():
            assert stat.S_IMODE(destination.stat().st_mode) == 0o700


@pytest.mark.parametrize("name", ["oauth", ".git", "identity.json", "configuration.json"])
def test_unknown_source_root_paths_are_not_packaged(source_root, name):
    (source_root / name).write_bytes(b"not snapshot material")
    (source_root / name).chmod(0o600)
    target = io.BytesIO()
    with pytest.raises(ValueError, match=DENIAL):
        module().pack_snapshot(source_root, target)
    assert target.getvalue() == b""


@pytest.mark.parametrize("change", ["symlink", "hardlink", "public", "fifo", "nested", "unknown"])
def test_unsafe_source_files_and_nested_entries_are_rejected(source_root, change):
    file = source_root / "state/ledger.sqlite3"
    if change == "symlink":
        file.unlink()
        file.symlink_to(source_root / "manifest.json")
    elif change == "hardlink":
        file.unlink()
        os.link(source_root / "manifest.json", file)
    elif change == "public":
        file.chmod(0o644)
    elif change == "fifo":
        file.unlink()
        os.mkfifo(file, 0o600)
    elif change == "nested":
        (source_root / "archive/nested").mkdir(mode=0o700)
    else:
        (source_root / "exports/oauth-store.key").write_bytes(b"unrelated")
    with pytest.raises(ValueError, match=DENIAL):
        module().pack_snapshot(source_root, io.BytesIO())


def test_directory_modes_and_required_inventory_are_checked(source_root):
    (source_root / "archive").chmod(0o755)
    with pytest.raises(ValueError, match=DENIAL):
        module().pack_snapshot(source_root, io.BytesIO())
    (source_root / "archive").chmod(0o700)
    (source_root / "manifest.json").unlink()
    with pytest.raises(ValueError, match=DENIAL):
        module().pack_snapshot(source_root, io.BytesIO())


@pytest.mark.parametrize(
    "name",
    [
        "/state/ledger.sqlite3",
        "../ledger.sqlite3",
        "state/../ledger.sqlite3",
        "state//ledger.sqlite3",
        "./manifest.json",
        "archive/nested/other.json",
        "oauth-store.key",
        ".git/config",
        "archive/" + "a" * 64 + ".other.json",
    ],
)
def test_untrusted_names_are_rejected_before_their_payload_is_written(source_root, name):
    raw = bundle(extra=member(name, b"untrusted"))
    destination = source_root.parent / "restored"
    with pytest.raises(ValueError, match=DENIAL):
        module().unpack_snapshot(io.BytesIO(raw), destination=destination)
    assert not (source_root.parent / "ledger.sqlite3").exists()
    assert not (destination / "oauth-store.key").exists()


@pytest.mark.parametrize(
    "kind",
    [
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
        tarfile.CHRTYPE,
        tarfile.BLKTYPE,
        tarfile.FIFOTYPE,
        tarfile.XHDTYPE,
        tarfile.XGLTYPE,
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_LONGLINK,
        tarfile.GNUTYPE_SPARSE,
        b"Z",
    ],
)
def test_links_devices_pax_gnu_and_unknown_types_are_never_interpreted(source_root, kind):
    raw = bundle(extra=member("manifest.json", b"", kind))
    with pytest.raises(ValueError, match=DENIAL):
        module().unpack_snapshot(io.BytesIO(raw), destination=source_root.parent / "restored")


@pytest.mark.parametrize(
    "field,value",
    [
        ("uid", 1),
        ("gid", 1),
        ("mtime", 1),
        ("uname", "other"),
        ("gname", "other"),
        ("mode", 0o777),
        ("linkname", "/other"),
    ],
)
def test_original_headers_must_match_canonical_metadata(source_root, field, value):
    raw = bundle()
    changed = header("archive", kind=tarfile.DIRTYPE, **{field: value})
    with pytest.raises(ValueError, match=DENIAL):
        module().unpack_snapshot(
            io.BytesIO(changed + raw[512:]), destination=source_root.parent / "restored"
        )


@pytest.mark.parametrize(
    "field,replacement",
    [
        ((124, 136), b"0000000000x\0"),
        ((124, 136), b"\x80" + b"\0" * 10 + b"\x01"),
        ((257, 263), b"ustar "),
        ((0, 1), b"\xff"),
    ],
)
def test_invalid_numeric_encoding_magic_or_nonascii_header_is_rejected(
    source_root, field, replacement
):
    raw = bundle()
    changed = bytearray(raw[:512])
    changed[field[0] : field[1]] = replacement
    changed = checksum(changed)
    with pytest.raises(ValueError, match=DENIAL):
        module().unpack_snapshot(
            io.BytesIO(changed + raw[512:]), destination=source_root.parent / "restored"
        )


def test_bad_checksum_is_rejected(source_root):
    raw = bytearray(bundle())
    raw[0] ^= 1
    with pytest.raises(ValueError, match=DENIAL):
        module().unpack_snapshot(io.BytesIO(raw), destination=source_root.parent / "restored")


@pytest.mark.parametrize("change", ["duplicate", "missing", "reordered", "padding", "too-large"])
def test_duplicate_missing_unordered_oversize_or_nonzero_padding_denies(source_root, change):
    if change == "duplicate":
        raw = bundle(extra=member("manifest.json", b"{}"))
    elif change == "missing":
        raw = bundle(
            {name: body for name, body in FIXTURE_FILES.items() if name != "manifest.json"}
        )
    elif change == "reordered":
        raw = header("state", kind=tarfile.DIRTYPE) + bundle()[512:]
    elif change == "padding":
        raw = bundle()
        offset = 3 * 512 + 512 + len(FIXTURE_FILES[sorted(FIXTURE_FILES)[0]])
        raw = raw[:offset] + b"x" + raw[offset + 1 :]
    else:
        raw = b"".join(header(name, kind=tarfile.DIRTYPE) for name in DIRECTORIES)
        raw += header("canonical-config.json", size=2**31) + b"\0" * 1024
    with pytest.raises(ValueError, match=DENIAL):
        module().unpack_snapshot(io.BytesIO(raw), destination=source_root.parent / "restored")


@pytest.mark.parametrize("length", [0, 1, 511, 513, 1600, 1800, -1, -512, -1024])
def test_truncated_stream_cannot_return_a_receipt(source_root, length):
    raw = bundle()[:length]
    with pytest.raises(ValueError, match=DENIAL):
        module().unpack_snapshot(io.BytesIO(raw), destination=source_root.parent / "restored")


@pytest.mark.parametrize("extra", [b"x", b"\0", b"\0" * 512])
def test_exact_two_end_blocks_require_eof_without_extra_padding(source_root, extra):
    with pytest.raises(ValueError, match=DENIAL):
        module().unpack_snapshot(
            io.BytesIO(bundle() + extra), destination=source_root.parent / "restored"
        )


@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
def test_existing_restore_destination_is_never_overwritten(source_root, kind):
    destination = source_root.parent / "restored"
    if kind == "directory":
        destination.mkdir(mode=0o700)
    elif kind == "file":
        destination.write_bytes(b"preserve")
    else:
        destination.symlink_to(source_root)
    with pytest.raises(ValueError, match=DENIAL):
        module().unpack_snapshot(io.BytesIO(bundle()), destination=destination)
    assert destination.exists()
    if kind == "file":
        assert destination.read_bytes() == b"preserve"


def test_restore_parent_must_already_be_private_and_owned(source_root):
    parent = source_root.parent / "public"
    parent.mkdir(mode=0o755)
    with pytest.raises(ValueError, match=DENIAL):
        module().unpack_snapshot(io.BytesIO(bundle()), destination=parent / "restored")
    assert list(parent.iterdir()) == []


def test_pack_checks_source_identity_after_streaming(source_root):
    class MutatingWriter(io.BytesIO):
        changed = False

        def write(self, raw):
            if raw == b"\0" * 1024 and not self.changed:
                self.changed = True
                (source_root / "manifest.json").write_bytes(b"xx")
            return super().write(raw)

    with pytest.raises(ValueError, match=DENIAL):
        module().pack_snapshot(source_root, MutatingWriter())


def test_stream_failure_is_sanitized_and_partial_restore_remains_private(source_root):
    class BrokenReader(io.BytesIO):
        def read(self, amount=-1):
            if self.tell() >= 1800:
                raise OSError("secret-provider-error")
            return super().read(amount)

    destination = source_root.parent / "restored"
    with pytest.raises(ValueError, match=DENIAL) as failure:
        module().unpack_snapshot(BrokenReader(bundle()), destination=destination)
    assert "secret-provider-error" not in str(failure.value)
    assert str(destination) not in str(failure.value)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    for entry in destination.rglob("*"):
        assert stat.S_IMODE(entry.stat().st_mode) == (0o700 if entry.is_dir() else 0o600)


@pytest.mark.parametrize("bad", [0, None, True])
def test_nonprogress_or_invalid_binary_write_is_rejected(source_root, bad):
    class BrokenWriter:
        def write(self, raw):
            return bad

    with pytest.raises(ValueError, match=DENIAL):
        module().pack_snapshot(source_root, BrokenWriter())


def test_eof_must_be_a_binary_empty_read_not_an_equal_mistyped_value(source_root):
    class MistypedEOF(io.BytesIO):
        def read(self, amount=-1):
            part = super().read(amount)
            return part if part else bytearray()

    with pytest.raises(ValueError, match=DENIAL):
        module().unpack_snapshot(MistypedEOF(bundle()), destination=source_root.parent / "restored")


def test_ustar_prefix_alias_is_rejected_even_when_it_resolves_to_an_allowed_name(source_root):
    raw = bundle()
    changed = bytearray(raw[1536:2048])
    changed[:100] = b".stock-research.lock".ljust(100, b"\0")
    changed[345:500] = b"archive".ljust(155, b"\0")
    with pytest.raises(ValueError, match=DENIAL):
        module().unpack_snapshot(
            io.BytesIO(raw[:1536] + checksum(changed) + raw[2048:]),
            destination=source_root.parent / "restored",
        )


def test_extraction_handles_short_local_file_writes(source_root, monkeypatch):
    original = os.write

    def short(fd, raw):
        return original(fd, raw[:3])

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", short)
        receipt = module().unpack_snapshot(
            io.BytesIO(bundle()), destination=source_root.parent / "restored"
        )
    assert receipt.total_bytes == sum(map(len, FIXTURE_FILES.values()))
    for name, raw in FIXTURE_FILES.items():
        assert (source_root.parent / "restored" / name).read_bytes() == raw


def test_large_payload_keeps_every_stream_operation_bounded(source_root):
    payload = b"x" * (3 * 1024 * 1024 + 17)
    (source_root / "manifest.json").write_bytes(payload)

    class BoundedWriter(io.BytesIO):
        def write(self, raw):
            assert len(raw) <= 1024 * 1024
            return super().write(raw)

    class BoundedReader(io.BytesIO):
        def read(self, amount=-1):
            assert 0 < amount <= 1024 * 1024
            return super().read(amount)

    stream = BoundedWriter()
    expected = module().pack_snapshot(source_root, stream)
    destination = source_root.parent / "restored"
    assert (
        module().unpack_snapshot(BoundedReader(stream.getvalue()), destination=destination)
        == expected
    )
    assert (destination / "manifest.json").read_bytes() == payload


def test_per_path_payload_limit_is_checked_before_pack_output(source_root):
    with (source_root / "saved-control.json").open("r+b") as target:
        target.truncate(8193)
    output = io.BytesIO()
    with pytest.raises(ValueError, match=DENIAL):
        module().pack_snapshot(source_root, output)
    assert output.getvalue() == b""


def test_ambiguous_directory_close_does_not_skip_or_retry_other_owned_descriptors(
    source_root, monkeypatch
):
    real_open, real_close = os.open, os.close
    active = {}
    closed = []
    failed = False

    def opening(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        active[fd] = str(path)
        return fd

    def closing(fd):
        nonlocal failed
        name = active.pop(fd, None)
        closed.append(name)
        real_close(fd)
        if name == "state" and not failed:
            failed = True
            raise OSError("ambiguous close")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "open", opening)
            patch.setattr(os, "close", closing)
            with pytest.raises(ValueError, match=DENIAL):
                module().pack_snapshot(source_root, io.BytesIO())
        assert failed and not active and None not in closed
    finally:
        for fd in active:
            real_close(fd)
