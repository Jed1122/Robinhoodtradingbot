"""Actual local helper composes snapshot replay with the bounded canonical bundle."""

import hashlib
import io
import os
from types import SimpleNamespace

import pytest

from tests.unit.runtime.test_stock_snapshot import sample as _sample
from trading_bot.runtime import stock_local_state as module
from trading_bot.runtime.stock_snapshot import verify_stock_snapshot
from trading_bot.runtime.stock_snapshot_bundle import unpack_snapshot

sample = _sample


def pending_files(root, count):
    for number in range(count):
        path = root / f".pending-{number:032x}"
        path.write_bytes(b"retained")
        path.chmod(0o600)


@pytest.fixture
def capacity_probe(sample, tmp_path, monkeypatch):
    from trading_bot.runtime import stock_snapshot

    staging = tmp_path.resolve() / "maintenance"
    staging.mkdir(mode=0o700)
    reached = []
    space = SimpleNamespace(f_bavail=2**40, f_frsize=4096, f_favail=2**20)
    monkeypatch.setattr(module.os, "fstatvfs", lambda _descriptor: space)

    async def snapshot(**kwargs):
        reached.append(True)
        raise ValueError("fixture snapshot boundary reached")

    monkeypatch.setattr(stock_snapshot, "create_stock_snapshot", snapshot)
    return staging, reached, space


async def probe(sample, tmp_path, staging):
    with pytest.raises(ValueError, match="stock_local_state_unavailable"):
        await module.create_local_snapshot_bundle(
            loaded=sample["loaded"],
            code_hash=str(sample["code_hash"]),
            data_root=tmp_path.resolve(),
            destination_root=staging,
            identifier="a" * 32,
            now=sample["now"],
        )


@pytest.mark.asyncio
async def test_reduced_owner_helper_bundles_real_migrated_application(sample, tmp_path):
    staging = tmp_path.resolve() / "maintenance"
    staging.mkdir(mode=0o700)
    result = await module.create_local_snapshot_bundle(
        loaded=sample["loaded"],
        code_hash=str(sample["code_hash"]),
        data_root=tmp_path.resolve(),
        destination_root=staging,
        identifier="a" * 32,
        now=sample["now"],
    )
    assert result["status"] == "snapshot_bundled" and result["identifier"] == "a" * 32
    bundle = staging / ("a" * 32 + ".bundle")
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == result["bundle"]["bundle_sha256"]
    restored = tmp_path.resolve() / "unpacked"
    unpack_snapshot(io.BytesIO(bundle.read_bytes()), destination=restored)
    verification = await verify_stock_snapshot(restored)
    assert verification.manifest_sha256 == result["snapshot"]["manifest_sha256"]
    assert verification.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["", "../outside", "a" * 31, "A" * 32])
async def test_helper_cannot_select_arbitrary_staging(sample, tmp_path, identifier):
    staging = tmp_path.resolve() / "maintenance"
    staging.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="stock_local_state_unavailable"):
        await module.create_local_snapshot_bundle(
            loaded=sample["loaded"],
            code_hash=str(sample["code_hash"]),
            data_root=tmp_path.resolve(),
            destination_root=staging,
            identifier=identifier,
            now=sample["now"],
        )
    assert list(staging.iterdir()) == []


@pytest.mark.asyncio
async def test_unknown_or_full_staging_is_preserved_and_denied(sample, tmp_path):
    staging = tmp_path.resolve() / "maintenance"
    staging.mkdir(mode=0o700)
    unknown = staging / "unrelated"
    unknown.write_bytes(b"preserve")
    unknown.chmod(0o600)
    with pytest.raises(ValueError):
        await module.create_local_snapshot_bundle(
            loaded=sample["loaded"],
            code_hash=str(sample["code_hash"]),
            data_root=tmp_path.resolve(),
            destination_root=staging,
            identifier="a" * 32,
            now=sample["now"],
        )
    assert unknown.read_bytes() == b"preserve"


@pytest.mark.asyncio
async def test_four_partial_attempts_block_new_snapshot_without_pruning(sample, tmp_path):
    staging = tmp_path.resolve() / "maintenance"
    staging.mkdir(mode=0o700)
    for number in range(4):
        (staging / f"{number:032x}").mkdir(mode=0o700)
    before = sorted(path.name for path in staging.iterdir())
    with pytest.raises(ValueError, match="stock_local_state_unavailable"):
        await module.create_local_snapshot_bundle(
            loaded=sample["loaded"],
            code_hash=str(sample["code_hash"]),
            data_root=tmp_path.resolve(),
            destination_root=staging,
            identifier="a" * 32,
            now=sample["now"],
        )
    assert sorted(path.name for path in staging.iterdir()) == before


@pytest.mark.asyncio
async def test_archive_larger_than_fixed_inode_reserve_denies_before_snapshot(
    sample, tmp_path, capacity_probe
):
    staging, reached, space = capacity_probe
    pending_files(sample["archive_dir"], 700)
    pending_files(sample["export_dir"], 12)
    space.f_favail = 512
    await probe(sample, tmp_path, staging)
    assert reached == [] and list(staging.iterdir()) == []
    assert not (sample["archive_dir"] / ".stock-research.lock").exists()
    assert not (sample["export_dir"] / ".stock-research.lock").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("offset,admitted", [(-1, False), (0, True)])
async def test_inode_bound_counts_archive_exports_and_missing_copied_anchors(
    sample, tmp_path, capacity_probe, offset, admitted
):
    staging, reached, space = capacity_probe
    pending_files(sample["archive_dir"], 300)
    pending_files(sample["export_dir"], 17)
    space.f_favail = 300 + 17 + 2 + 256 + offset
    await probe(sample, tmp_path, staging)
    assert bool(reached) is admitted
    assert list(staging.iterdir()) == []
    assert not (sample["archive_dir"] / ".stock-research.lock").exists()
    assert not (sample["export_dir"] / ".stock-research.lock").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tree,count,anchor,admitted",
    [
        ("archive_dir", 128, False, False),
        ("archive_dir", 129, False, False),
        ("archive_dir", 127, True, True),
        ("export_dir", 63, False, False),
        ("export_dir", 62, True, True),
    ],
)
async def test_inode_preflight_obeys_source_file_limits_before_staging(
    sample, tmp_path, capacity_probe, monkeypatch, tree, count, anchor, admitted
):
    staging, reached, _ = capacity_probe
    config = sample["loaded"].config
    worker = config.stock_worker.model_copy(update={"max_archive_files": 128})
    monkeypatch.setattr(
        module, "_policy", lambda _loaded: config.model_copy(update={"stock_worker": worker})
    )
    pending_files(sample[tree], count)
    if anchor:
        lock = sample[tree] / ".stock-research.lock"
        lock.write_bytes(b"")
        lock.chmod(0o600)
    await probe(sample, tmp_path, staging)
    assert bool(reached) is admitted
    assert list(staging.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["name", "symlink", "hardlink", "public", "oversize"])
async def test_preflight_requires_closed_private_flat_source_inventory(
    sample, tmp_path, capacity_probe, change
):
    staging, reached, _ = capacity_probe
    path = sample["archive_dir"] / (".pending-" + "1" * 32)
    path.write_bytes(b"retain")
    path.chmod(0o600)
    if change == "name":
        path.rename(path.with_name("unknown"))
    elif change == "symlink":
        path.unlink()
        path.symlink_to(sample["database"])
    elif change == "hardlink":
        os.link(path, sample["archive_dir"] / (".pending-" + "2" * 32))
    elif change == "public":
        path.chmod(0o644)
    else:
        with path.open("r+b") as stream:
            stream.truncate(9_000_001)
    await probe(sample, tmp_path, staging)
    assert reached == [] and list(staging.iterdir()) == []
    assert not (sample["archive_dir"] / ".stock-research.lock").exists()


@pytest.mark.asyncio
async def test_byte_capacity_guard_still_denies_before_staging(sample, tmp_path, capacity_probe):
    staging, reached, space = capacity_probe
    space.f_bavail = 0
    await probe(sample, tmp_path, staging)
    assert reached == [] and list(staging.iterdir()) == []


@pytest.mark.asyncio
async def test_source_inventory_change_is_denied_before_staging(
    sample, tmp_path, capacity_probe, monkeypatch
):
    staging, reached, _ = capacity_probe
    pending_files(sample["archive_dir"], 1)
    original = module._source_inventory
    changed = []

    def mutate(directory, tree, **kwargs):
        rows = original(directory, tree, **kwargs)
        if tree == "archive" and not changed:
            next(sample["archive_dir"].iterdir()).write_bytes(b"changed")
            changed.append(True)
        return rows

    monkeypatch.setattr(module, "_source_inventory", mutate)
    await probe(sample, tmp_path, staging)
    assert changed == [True] and reached == [] and list(staging.iterdir()) == []


@pytest.mark.asyncio
async def test_source_byte_quota_is_checked_before_staging(
    sample, tmp_path, capacity_probe, monkeypatch
):
    staging, reached, _ = capacity_probe
    config = sample["loaded"].config
    worker = config.stock_worker.model_copy(update={"max_archive_bytes": 335544320})
    monkeypatch.setattr(
        module, "_policy", lambda _loaded: config.model_copy(update={"stock_worker": worker})
    )
    pending_files(sample["archive_dir"], 38)
    for path in sample["archive_dir"].iterdir():
        with path.open("r+b") as stream:
            stream.truncate(9_000_000)
    await probe(sample, tmp_path, staging)
    assert reached == [] and list(staging.iterdir()) == []


@pytest.mark.asyncio
async def test_projected_source_files_must_fit_closed_bundle_file_limit(
    sample, tmp_path, capacity_probe, monkeypatch
):
    from trading_bot.runtime import stock_snapshot_bundle

    staging, reached, _ = capacity_probe
    pending_files(sample["archive_dir"], 3)
    monkeypatch.setattr(stock_snapshot_bundle, "_MAXIMUM_FILES", 8)
    await probe(sample, tmp_path, staging)
    assert reached == [] and list(staging.iterdir()) == []
