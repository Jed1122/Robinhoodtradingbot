"""Actual local helper composes snapshot replay with the bounded canonical bundle."""

import hashlib
import io

import pytest

from tests.unit.runtime.test_stock_snapshot import sample as _sample
from trading_bot.runtime import stock_local_state as module
from trading_bot.runtime.stock_snapshot import verify_stock_snapshot
from trading_bot.runtime.stock_snapshot_bundle import unpack_snapshot

sample = _sample


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
