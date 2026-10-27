"""Durable caller-owned refresh watch; fictional symbols and no account/SDK calls."""

import fcntl
import hashlib
import importlib
import json
import os
from contextlib import contextmanager
from dataclasses import make_dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from trading_bot.config import load_config
from trading_bot.domain import CodeHash
from trading_bot.runtime.stock_research_worker import StockResearchWatch

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 10, 26, 20, tzinfo=UTC)


def api():
    try:
        return importlib.import_module("trading_bot.runtime.stock_research_watch")
    except ModuleNotFoundError:
        pytest.fail("durable source-bound stock watch missing")


def watch(*, at=NOW, expiry=None, held=("ALFA",), watched=("BETA",), source="a"):
    return StockResearchWatch(held, watched, at, expiry or at + timedelta(hours=1), source * 64)


@pytest.fixture
def root(tmp_path):
    path = tmp_path.resolve() / "watch"
    path.mkdir(mode=0o700)
    return path


def publish(root, selected=None, at=NOW):
    return api().publish_stock_research_watch(
        root=root, watch=watch() if selected is None else selected, clock=lambda: at
    )


def read(root, at=NOW):
    return api().read_stock_research_watch(root=root, clock=lambda: at)


def test_publish_roundtrip_complete_payload_hashes_false_authority_and_idempotency(root):
    receipt = publish(root)
    raw = (root / "stock-watch.json").read_bytes()
    doc = json.loads(raw)
    assert (
        receipt.file == "stock-watch.json"
        and receipt.body_sha256 == hashlib.sha256(raw).hexdigest()
    )
    assert receipt.payload_sha256 == doc["payload_sha256"] and receipt.source_sha256 == "a" * 64
    assert read(root) == watch() and publish(root) == receipt
    assert (
        doc["source_authenticated"]
        is doc["account_verified"]
        is doc["execution_authorized"]
        is doc["live_authorized"]
        is False
    )
    assert sorted(p.name for p in root.iterdir()) == [".stock-watch.lock", "stock-watch.json"]
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in root.iterdir())


def test_reader_never_creates_missing_state_or_anchor(root):
    with pytest.raises(ValueError):
        read(root)
    assert list(root.iterdir()) == []


def test_reader_uses_only_readonly_opens_and_never_fsync_or_repair(root, monkeypatch):
    publish(root)
    m = api()
    original = m.os.open
    before = {
        p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
        for p in root.iterdir()
    }

    def readonly(path, flags, *args, **kwargs):
        assert flags & os.O_ACCMODE == os.O_RDONLY and not flags & os.O_CREAT
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(m.os, "open", readonly)
    monkeypatch.setattr(
        m.os, "fsync", lambda *_: pytest.fail("reader must work without writable filesystem")
    )
    assert read(root) == watch()
    after = {
        p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns, p.stat().st_ctime_ns)
        for p in root.iterdir()
    }
    assert after == before


def test_valid_expired_old_state_can_be_replaced_without_inventing_empty_inventory(root):
    old = watch(at=NOW - timedelta(hours=2), expiry=NOW - timedelta(hours=1))
    publish(root, old, at=old.as_of)
    with pytest.raises(ValueError):
        read(root)
    updated = watch(held=("GAMMA",), watched=(), source="b")
    publish(root, updated)
    assert read(root) == updated


@pytest.mark.parametrize("kind", ("same_clock_conflict", "rollback", "future", "expired"))
def test_current_clock_and_monotonic_owner_updates_are_not_inferred(root, kind):
    publish(root)
    old = (root / "stock-watch.json").read_bytes()
    selected = {
        "same_clock_conflict": watch(held=("GAMMA",)),
        "rollback": watch(at=NOW - timedelta(minutes=1)),
        "future": watch(at=NOW + timedelta(seconds=1)),
        "expired": watch(at=NOW - timedelta(hours=2), expiry=NOW),
    }[kind]
    with pytest.raises(ValueError):
        publish(root, selected)
    assert (root / "stock-watch.json").read_bytes() == old


@pytest.mark.parametrize(
    "kind", ("body", "hash", "scope", "unknown_field", "noncanonical", "too_large")
)
def test_corrupt_or_unrecognized_old_state_is_never_silently_replaced(root, kind):
    publish(root)
    path = root / "stock-watch.json"
    doc = json.loads(path.read_bytes())
    if kind == "body":
        raw = b"{}"
    elif kind == "too_large":
        raw = b"x" * 8193
    else:
        if kind == "hash":
            doc["payload"]["held_symbols"] = ["EVIL"]
        elif kind == "scope":
            doc["account_verified"] = True
        elif kind == "unknown_field":
            doc["extra"] = "ignore validation"
        raw = json.dumps(
            doc, sort_keys=True, separators=(",", ":"), indent=2 if kind == "noncanonical" else None
        ).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        read(root)
    with pytest.raises(ValueError):
        publish(root, watch(at=NOW + timedelta(minutes=1)), at=NOW + timedelta(minutes=1))
    assert path.read_bytes() == raw


@pytest.mark.parametrize("kind", ("symlink", "hardlink", "fifo", "mode", "unknown", "pending"))
def test_unsafe_metadata_and_unknown_entries_reject_without_cleanup(root, kind):
    publish(root)
    path = root / "stock-watch.json"
    if kind == "symlink":
        other = root.parent / "retained-watch"
        path.rename(other)
        path.symlink_to(other)
    elif kind == "hardlink":
        os.link(path, root / "second-watch")
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif kind == "mode":
        path.chmod(0o400)
    else:
        (root / (".pending-watch-" + "a" * 32 if kind == "pending" else "unexpected")).touch(
            mode=0o600
        )
    names = sorted(p.name for p in root.iterdir())
    with pytest.raises(ValueError):
        read(root)
    with pytest.raises(ValueError):
        publish(root)
    assert sorted(p.name for p in root.iterdir()) == names


def test_read_clock_rechecks_expiry_and_rollback(root):
    publish(root)
    for finish in (NOW + timedelta(hours=2), NOW - timedelta(seconds=1)):
        stamps = iter((NOW, finish))
        with pytest.raises(ValueError):
            api().read_stock_research_watch(root=root, clock=lambda stamps=stamps: next(stamps))


def test_writer_own_mutex_conflicts_with_readers_and_reader_conflicts_with_writer(root):
    publish(root)
    fd = os.open(root / ".stock-watch.lock", os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        with pytest.raises(ValueError):
            publish(root)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError):
            read(root)
    finally:
        os.close(fd)


def test_atomic_replace_failure_preserves_valid_old_bytes(root, monkeypatch):
    publish(root)
    old = (root / "stock-watch.json").read_bytes()

    def failed(*args, **kwargs):
        raise OSError("fictional replace failure")

    monkeypatch.setattr(api().os, "replace", failed)
    with pytest.raises(ValueError):
        publish(root, watch(at=NOW + timedelta(minutes=1)), at=NOW + timedelta(minutes=1))
    assert (root / "stock-watch.json").read_bytes() == old
    assert sorted(p.name for p in root.iterdir()) == [".stock-watch.lock", "stock-watch.json"]


@pytest.fixture
def cli(tmp_path, monkeypatch):
    worker = importlib.import_module("trading_bot.runtime.stock_research_worker")
    home = tmp_path.resolve()
    home.chmod(0o700)
    profile = home / "worker.yaml"
    profile.write_text("policy_id: stock-worker-current-provider-v1\n")
    loaded = load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=ROOT / "configs/hybrid/stock-research.yaml",
        stock_worker_policy_path=profile,
    )
    observed = []
    monkeypatch.setattr(
        worker, "load_stock_worker_identity", lambda *a, **kw: (loaded, CodeHash("b" * 64))
    )

    @contextmanager
    def ledger(_):
        observed.append("ledger")
        yield 3

    async def dispose():
        pass

    async def cycle(**kwargs):
        observed.append(kwargs)
        return {"status": "succeeded", "live_enabled": False}

    monkeypatch.setattr(worker, "_existing_private_ledger", ledger)
    monkeypatch.setattr(worker, "create_engine", lambda *a, **kw: SimpleNamespace(dispose=dispose))
    monkeypatch.setattr(worker, "async_session_factory", lambda *_: object())
    monkeypatch.setattr(worker, "run_stock_research_cycle", cycle)
    monkeypatch.setattr(
        worker,
        "RobinhoodMcpSdkConnection",
        lambda **kw: pytest.fail("CLI wiring must not construct SDK"),
    )
    args = [
        "--config-root",
        str(ROOT / "configs"),
        "--database",
        str(home / "ledger.sqlite3"),
        "--oauth-store",
        str(home / "unused-oauth"),
        "--archive-dir",
        str(home / "archive"),
        "--control-dir",
        str(home / "controls"),
    ]
    return worker, args, observed, home


def test_cli_absent_watch_flag_preserves_legacy_keyword_call(cli, capsys):
    worker, args, observed, _ = cli
    assert worker.main(args) == 0
    assert "watch" not in observed[-1]
    assert json.loads(capsys.readouterr().out)["live_enabled"] is False


def test_cli_reads_current_watch_and_passes_existing_local_model(cli, capsys):
    worker, args, observed, home = cli
    root = home / "watch"
    root.mkdir(mode=0o700)
    now = datetime.now(UTC)
    selected = watch(at=now)
    publish(root, selected, at=now)
    assert worker.main([*args, "--watch-dir", str(root)]) == 0
    assert (
        type(observed[-1]["watch"]) is worker.StockResearchWatch
        and observed[-1]["watch"] == selected
    )
    capsys.readouterr()


@pytest.mark.parametrize("invalid", ("missing", "expired", "same_archive"))
def test_cli_watch_failure_blocks_before_ledger_or_sdk(cli, capsys, invalid):
    worker, args, observed, home = cli
    root = home / "watch"
    root.mkdir(mode=0o700)
    if invalid == "expired":
        past = datetime.now(UTC) - timedelta(hours=2)
        publish(root, watch(at=past), at=past)
    elif invalid == "same_archive":
        root = home / "archive"
        root.mkdir(mode=0o700)
        now = datetime.now(UTC)
        publish(root, watch(at=now), at=now)
    assert worker.main([*args, "--watch-dir", str(root)]) == 2
    assert observed == []
    assert json.loads(capsys.readouterr().out)["reason"] == "worker_startup_blocked"


def test_cli_reconstructs_model_when_reader_has_other_module_class_identity(
    cli, monkeypatch, capsys
):
    worker, args, observed, home = cli
    root = home / "watch"
    root.mkdir(mode=0o700)
    foreign = make_dataclass(
        "OtherModuleWatch",
        [
            ("held_symbols", tuple),
            ("watch_symbols", tuple),
            ("as_of", datetime),
            ("expires_at", datetime),
            ("source_sha256", str),
        ],
    )
    now = datetime.now(UTC)
    value = foreign(("ALFA",), (), now, now + timedelta(hours=1), "a" * 64)
    monkeypatch.setattr(api(), "read_stock_research_watch", lambda **kwargs: value)
    assert worker.main([*args, "--watch-dir", str(root)]) == 0
    assert type(observed[-1]["watch"]) is worker.StockResearchWatch
    capsys.readouterr()


def test_cli_rejects_watch_inside_the_credential_store_before_constructing_any_resources(
    cli, capsys
):
    worker, args, observed, home = cli
    root = home / "unused-oauth"
    root.mkdir(mode=0o700)
    now = datetime.now(UTC)
    publish(root, watch(at=now), at=now)
    assert worker.main([*args, "--watch-dir", str(root)]) == 2
    assert observed == []
    assert json.loads(capsys.readouterr().out)["reason"] == "worker_startup_blocked"


@pytest.mark.parametrize("kind", ("public_root", "symlink_root"))
def test_watch_root_is_private_and_never_followed_through_symlink(root, kind):
    publish(root)
    target = root
    if kind == "public_root":
        root.chmod(0o755)
    else:
        target = root.parent / "alias"
        target.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError):
        read(target)
    with pytest.raises(ValueError):
        publish(target)
    assert (root / "stock-watch.json").exists()


@pytest.mark.parametrize("rebound", ("root", "anchor"))
def test_writer_fails_after_root_or_anchor_displacement_without_success_receipt(
    root, monkeypatch, rebound
):
    publish(root)
    original = api().os.replace

    def moved(*args, **kwargs):
        result = original(*args, **kwargs)
        if rebound == "root":
            root.rename(root.with_name("retained-watch-root"))
            root.mkdir(mode=0o700)
        else:
            anchor = root / ".stock-watch.lock"
            anchor.unlink()
            anchor.touch(mode=0o600)
        return result

    monkeypatch.setattr(api().os, "replace", moved)
    with pytest.raises(ValueError):
        publish(root, watch(at=NOW + timedelta(minutes=1)), at=NOW + timedelta(minutes=1))
    retained = root.with_name("retained-watch-root") if rebound == "root" else root
    assert (retained / "stock-watch.json").is_file()


def test_publisher_rejects_known_future_old_state_instead_of_repairing_it(root):
    future = watch(at=NOW + timedelta(hours=1))
    publish(root, future, at=future.as_of)
    original = (root / "stock-watch.json").read_bytes()
    with pytest.raises(ValueError):
        publish(root)
    assert (root / "stock-watch.json").read_bytes() == original


def test_cli_watch_flag_does_not_auto_select_a_different_worker_profile(cli, monkeypatch, capsys):
    worker, args, observed, home = cli
    legacy = home / "legacy-worker.yaml"
    legacy.write_text("policy_id: stock-worker-v1\n")
    loaded = load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/hybrid/paper.yaml",
        ROOT / "configs/hybrid/safety-envelope.yaml",
        {},
        hybrid_policy_path=ROOT / "configs/hybrid/policy.yaml",
        stock_research_policy_path=ROOT / "configs/hybrid/stock-research.yaml",
        stock_worker_policy_path=legacy,
    )
    monkeypatch.setattr(
        worker, "load_stock_worker_identity", lambda *a, **kw: (loaded, CodeHash("b" * 64))
    )
    root = home / "watch"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(
        api(),
        "read_stock_research_watch",
        lambda **kw: pytest.fail("old profile must reject before reading watch"),
    )
    assert worker.main([*args, "--watch-dir", str(root)]) == 2
    assert observed == []
    assert json.loads(capsys.readouterr().out)["reason"] == "worker_startup_blocked"
