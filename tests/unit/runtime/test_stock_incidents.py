"""Private temporary incident spools; no provider, host service or credential access."""

import importlib
import json
import os
import stat
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)
NAME = "stock-incidents.json"
LOCK = ".stock-incidents.lock"
DENIAL = "stock_incident_spool_unavailable"


def module():
    path = Path(__file__).resolve().parents[3] / "src/trading_bot/runtime/stock_incidents.py"
    assert path.is_file(), "The persistent private incident spool is missing"
    return importlib.import_module("trading_bot.runtime.stock_incidents")


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.fixture
def root(tmp_path):
    path = tmp_path.resolve() / "incidents"
    path.mkdir(mode=0o700)
    return path


def initialized(root):
    spool = module().StockIncidentSpool(root)
    spool.initialize(now=NOW)
    return spool


def row(code, *, first=NOW, last=NOW, resolved=None):
    return {
        "code": code,
        "first_seen": first.isoformat(),
        "last_seen": last.isoformat(),
        "resolved_at": None if resolved is None else resolved.isoformat(),
    }


def test_explicit_initialization_is_private_versioned_and_survives_reopening(root):
    spool = module().StockIncidentSpool(root)
    expected = {
        "schema_version": 1,
        "kind": "stock_operations_incidents",
        "last_observed_at": NOW.isoformat(),
        "incidents": [],
    }
    assert spool.initialize(now=NOW) == expected
    assert module().StockIncidentSpool(root).read() == expected
    assert (root / NAME).read_bytes() == encoded(expected)
    assert {entry.name for entry in root.iterdir()} == {NAME, LOCK}
    for entry in root.iterdir():
        assert stat.S_IMODE(entry.stat().st_mode) == 0o600
        assert entry.stat().st_uid == os.geteuid() and entry.stat().st_nlink == 1


def test_missing_spool_requires_explicit_initialization_and_creates_nothing(root):
    spool = module().StockIncidentSpool(root)
    for action in (spool.read, lambda: spool.update((), now=NOW)):
        with pytest.raises(ValueError, match="^" + DENIAL + "$"):
            action()
    assert list(root.iterdir()) == []


def test_initialization_never_overwrites_existing_history(root):
    spool = initialized(root)
    spool.update(("timer_disabled",), now=NOW)
    before = (root / NAME).read_bytes()
    with pytest.raises(ValueError, match="^" + DENIAL + "$"):
        spool.initialize(now=NOW + timedelta(seconds=1))
    assert (root / NAME).read_bytes() == before


def test_active_incidents_dedupe_and_keep_the_first_observation(root):
    spool = initialized(root)
    lock_inode = (root / LOCK).stat().st_ino
    assert spool.update(("timer_disabled", "timer_disabled"), now=NOW)["incidents"] == [
        row("timer_disabled")
    ]
    later = NOW + timedelta(seconds=10)
    assert spool.update(("timer_disabled",), now=later)["incidents"] == [
        row("timer_disabled", last=later)
    ]
    assert module().StockIncidentSpool(root).read()["last_observed_at"] == later.isoformat()
    assert (root / LOCK).stat().st_ino == lock_inode


def test_valid_complete_observation_resolves_and_recurrence_retains_history(root):
    spool = initialized(root)
    spool.update(("timer_disabled",), now=NOW)
    resolved = NOW + timedelta(seconds=10)
    assert spool.update((), now=resolved)["incidents"] == [row("timer_disabled", resolved=resolved)]
    again = NOW + timedelta(seconds=20)
    assert spool.update(("timer_disabled",), now=again)["incidents"] == [
        row("timer_disabled", resolved=resolved),
        row("timer_disabled", first=again, last=again),
    ]


@pytest.mark.parametrize(
    "observed",
    [
        None,
        ("unknown_provider_text",),
        ["timer_disabled"],
        (True,),
        "timer_disabled",
        ("timer_disabled",) * 129,
        ("observation_invalid",),
    ],
)
def test_unknown_observation_preserves_incidents_and_records_uncertainty(root, observed):
    spool = initialized(root)
    spool.update(("source_stale",), now=NOW)
    later = NOW + timedelta(seconds=10)
    result = spool.update(observed, now=later)
    assert result["incidents"] == [
        row("source_stale"),
        row("observation_invalid", first=later, last=later),
    ]
    assert "unknown_provider_text" not in (root / NAME).read_text()


def test_complete_observations_can_resolve_the_uncertainty_marker(root):
    spool = initialized(root)
    spool.update(None, now=NOW)
    result = spool.update((), now=NOW + timedelta(seconds=10))
    assert result["incidents"] == [row("observation_invalid", resolved=NOW + timedelta(seconds=10))]


def test_unknown_observation_does_not_falsely_renew_last_seen_of_other_incidents(root):
    spool = initialized(root)
    spool.update(("source_stale",), now=NOW)
    spool.update(None, now=NOW + timedelta(seconds=10))
    result = spool.update(None, now=NOW + timedelta(seconds=20))
    assert result["incidents"][0] == row("source_stale")
    assert result["incidents"][1] == row(
        "observation_invalid", first=NOW + timedelta(seconds=10), last=NOW + timedelta(seconds=20)
    )


@pytest.mark.parametrize(
    "stamp",
    [
        NOW - timedelta(microseconds=1),
        NOW.replace(tzinfo=None),
        NOW.isoformat(),
        True,
        NOW.astimezone(timezone(timedelta(hours=1))),
    ],
)
def test_restart_clock_rollback_or_invalid_time_does_not_mutate_history(root, stamp):
    initialized(root)
    before = (root / NAME).read_bytes()
    with pytest.raises(ValueError, match="^" + DENIAL + "$"):
        module().StockIncidentSpool(root).update(("timer_disabled",), now=stamp)
    assert (root / NAME).read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("kind", "other"),
        ("last_observed_at", NOW.replace(tzinfo=None).isoformat()),
        ("last_observed_at", "2026-10-22T12:00:00Z"),
        ("incidents", {}),
        ("incidents", [row("untrusted_token_value")]),
        ("incidents", [row("timer_disabled", first=NOW + timedelta(seconds=1))]),
        ("incidents", [row("timer_disabled", last=NOW - timedelta(seconds=1))]),
        ("incidents", [row("timer_disabled", resolved=NOW - timedelta(seconds=1))]),
        ("incidents", [row("timer_disabled"), row("timer_disabled")]),
        ("incidents", [row("timer_disabled")] * 129),
        ("unexpected", "secret_provider_error"),
    ],
)
def test_malformed_state_is_never_reset_or_repaired(root, field, value):
    spool = initialized(root)
    record = spool.read()
    record[field] = value
    (root / NAME).write_bytes(encoded(record))
    before = (root / NAME).read_bytes()
    for action in (
        spool.read,
        lambda: spool.update((), now=NOW),
        lambda: spool.initialize(now=NOW),
    ):
        with pytest.raises(ValueError, match="^" + DENIAL + "$") as failure:
            action()
        assert "secret_provider_error" not in str(failure.value)
        assert str(root) not in str(failure.value)
    assert (root / NAME).read_bytes() == before


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{}",
        b"[]",
        b"{",
        b"\xff",
        b'{"schema_version":1,"schema_version":1}',
        b'{"x":NaN}',
        b" " * 65537,
    ],
)
def test_malformed_bounded_json_is_denied_without_replacement(root, raw):
    spool = initialized(root)
    (root / NAME).write_bytes(raw)
    with pytest.raises(ValueError, match="^" + DENIAL + "$"):
        spool.update((), now=NOW)
    assert (root / NAME).read_bytes() == raw


@pytest.mark.parametrize("which", [NAME, LOCK])
@pytest.mark.parametrize("change", ["symlink", "hardlink", "public", "fifo"])
def test_private_file_identity_and_nofollow_are_required(root, tmp_path, which, change):
    spool = initialized(root)
    path = root / which
    if change == "symlink":
        target = tmp_path / "other"
        path.rename(target)
        path.symlink_to(target)
    elif change == "hardlink":
        os.link(path, tmp_path / "other")
    elif change == "public":
        path.chmod(0o644)
    else:
        path.unlink()
        os.mkfifo(path, 0o600)
    with pytest.raises(ValueError, match="^" + DENIAL + "$"):
        spool.update((), now=NOW)


def test_missing_state_after_initialization_does_not_reinitialize(root):
    spool = initialized(root)
    (root / NAME).unlink()
    with pytest.raises(ValueError, match="^" + DENIAL + "$"):
        spool.update((), now=NOW)
    assert not (root / NAME).exists()


def test_missing_lock_is_not_recreated_by_read_or_update(root):
    spool = initialized(root)
    (root / LOCK).unlink()
    for action in (spool.read, lambda: spool.update((), now=NOW)):
        with pytest.raises(ValueError, match="^" + DENIAL + "$"):
            action()
    assert not (root / LOCK).exists()


def test_unsafe_root_or_unknown_inventory_is_not_adopted(root, tmp_path):
    root.chmod(0o755)
    with pytest.raises(ValueError, match="^" + DENIAL + "$"):
        module().StockIncidentSpool(root).initialize(now=NOW)
    root.chmod(0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(root)
    with pytest.raises(ValueError, match="^" + DENIAL + "$"):
        module().StockIncidentSpool(linked).initialize(now=NOW)
    (root / "unrelated").write_text("preserve")
    with pytest.raises(ValueError, match="^" + DENIAL + "$"):
        module().StockIncidentSpool(root).initialize(now=NOW)
    assert {entry.name for entry in root.iterdir()} == {"unrelated"}


def test_exclusive_singleton_lock_denies_overlap_without_reset(root):
    import fcntl

    spool = initialized(root)
    with (root / LOCK).open("rb") as anchor:
        fcntl.flock(anchor.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = (root / NAME).read_bytes()
        with pytest.raises(ValueError, match="^" + DENIAL + "$"):
            spool.update(("timer_disabled",), now=NOW)
        assert (root / NAME).read_bytes() == before
    assert spool.update(("timer_disabled",), now=NOW)["incidents"] == [row("timer_disabled")]


def test_history_prunes_only_the_oldest_resolved_episodes_and_preserves_active(root):
    spool = initialized(root)
    record = spool.read()
    record["incidents"] = [
        row(
            "timer_disabled",
            first=NOW - timedelta(minutes=130 - i),
            last=NOW - timedelta(minutes=130 - i),
            resolved=NOW - timedelta(minutes=129 - i),
        )
        for i in range(128)
    ]
    (root / NAME).write_bytes(encoded(record))
    result = spool.update(("source_stale",), now=NOW)
    assert len(result["incidents"]) == 128
    assert result["incidents"][0] == record["incidents"][1]
    assert result["incidents"][-1] == row("source_stale")
    assert (root / NAME).stat().st_size <= 65536


@pytest.mark.parametrize("fault", ["write", "file_sync", "replace", "directory_sync"])
def test_atomic_persistence_failure_leaves_old_or_complete_new_state(root, monkeypatch, fault):
    spool = initialized(root)
    before = spool.read()
    original_sync = os.fsync

    def fail(*args, **kwargs):
        raise OSError("secret_provider_error")

    def sync(fd):
        directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        if directory == (fault == "directory_sync"):
            fail()
        original_sync(fd)

    with monkeypatch.context() as patch:
        if fault in {"file_sync", "directory_sync"}:
            patch.setattr(os, "fsync", sync)
        else:
            patch.setattr(os, "write" if fault == "write" else "replace", fail)
        with pytest.raises(ValueError, match="^" + DENIAL + "$"):
            spool.update(("timer_disabled",), now=NOW)
    after = spool.read()
    assert after == before or after["incidents"] == [row("timer_disabled")]
    assert {entry.name for entry in root.iterdir()} == {NAME, LOCK}


@pytest.mark.parametrize("target", ["lock", "temporary"])
def test_ambiguous_close_is_never_retried_and_other_descriptors_are_closed(
    root, monkeypatch, target
):
    spool = initialized(root)
    opened = []
    active = {}
    closed = []
    real_open, real_close = os.open, os.close
    failed = False

    def opening(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        entry = fd, str(path), len(opened)
        opened.append(entry)
        active[fd] = entry
        return fd

    def closing(fd):
        nonlocal failed
        entry = active.pop(fd, None)
        closed.append(entry)
        real_close(fd)
        name = entry[1]
        matches = name == LOCK if target == "lock" else name.startswith(".stock-incidents.pending-")
        if matches and not failed:
            failed = True
            raise OSError("ambiguous close")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "open", opening)
            patch.setattr(os, "close", closing)
            with pytest.raises(ValueError, match="^" + DENIAL + "$"):
                spool.update(("timer_disabled",), now=NOW)
        assert failed
        assert not active
        assert None not in closed
        assert sorted(opened) == sorted(closed)
    finally:
        for fd in active:
            real_close(fd)


def test_failed_write_and_ambiguous_cleanup_close_still_remove_only_owned_temporary(
    root, monkeypatch
):
    spool = initialized(root)
    original = (root / NAME).read_bytes()
    real_open, real_close = os.open, os.close
    temporary_fd = None

    def opening(path, *args, **kwargs):
        nonlocal temporary_fd
        fd = real_open(path, *args, **kwargs)
        if str(path).startswith(".stock-incidents.pending-"):
            temporary_fd = fd
        return fd

    def closing(fd):
        real_close(fd)
        if fd == temporary_fd:
            raise OSError("ambiguous close")

    def fail_write(*args):
        raise OSError("failed write")

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", opening)
        patch.setattr(os, "close", closing)
        patch.setattr(os, "write", fail_write)
        with pytest.raises(ValueError, match="^" + DENIAL + "$"):
            spool.update(("timer_disabled",), now=NOW)
    assert (root / NAME).read_bytes() == original
    assert {entry.name for entry in root.iterdir()} == {NAME, LOCK}
