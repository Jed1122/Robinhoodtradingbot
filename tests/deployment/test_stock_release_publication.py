"""Actual owned producer stages and exclusive immutable release-file publication."""

import importlib
import json
import os
from pathlib import Path

import pytest
from test_stock_compose_render import Commands, probe
from test_stock_compose_render import scenario as render_scenario
from test_stock_release_producer_probe import built

from infra.hybrid import stock_release


def api():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_release_publication.py"
    assert path.is_file(), "Owned durable stock release-file publication is missing"
    return importlib.import_module("infra.hybrid.stock_release_publication")


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    fixture = render_scenario.__wrapped__(tmp_path, monkeypatch)
    root = tmp_path / "releases"
    root.mkdir(mode=0o700)
    return fixture, root


def render(scenario, monkeypatch, lease):
    from infra.hybrid.stock_compose_render import _render

    fixture, root = scenario
    assert lease.release_root == root
    probe(fixture, monkeypatch, lease)
    Commands(fixture, lease).install(monkeypatch)
    return _render(lease)


def test_four_exclusive_durable_files_pass_the_existing_loader(scenario, monkeypatch):
    publisher = api()
    fixture, root = scenario
    with built(fixture[0], monkeypatch, release_root=root) as lease:
        raw = render(scenario, monkeypatch, lease)
        manifest = publisher._publish_files(lease)
        assert manifest == root / lease.source.digest / "manifest.json"
        assert lease.published_manifest == manifest
        assert set(p.name for p in manifest.parent.iterdir()) == set(stock_release._ARTIFACTS)
        for path in manifest.parent.iterdir():
            assert path.stat().st_mode & 0o777 == 0o444
            assert path.stat().st_nlink == 1
        loaded = stock_release._load_release(manifest, trusted_uid=os.geteuid(), release_root=root)
        assert loaded.compose_bytes == raw
        assert loaded.image_digest == lease.built_image.image_digest
        assert (manifest.parent / "stock-configuration.json").read_bytes() == (
            lease.probe_result.configuration
        )
        receipt = json.loads(
            (lease.root / "attempts" / lease.source.digest / "publication-files.json").read_bytes()
        )
        assert receipt["render_complete_sha256"] == lease.hashes["render-complete.json"]
        with pytest.raises(ValueError):
            publisher._publish_files(lease)


def test_no_current_render_means_no_release_publication(scenario, monkeypatch):
    publisher = api()
    fixture, root = scenario
    with built(fixture[0], monkeypatch, release_root=root) as lease:
        with pytest.raises(ValueError):
            publisher._publish_files(lease)
        assert not list(root.iterdir())


@pytest.mark.parametrize("kind", ["same_source", "unknown_release", "symlink", "writable"])
def test_unknown_or_existing_release_namespace_is_never_adopted(scenario, monkeypatch, kind):
    publisher = api()
    fixture, root = scenario
    with built(fixture[0], monkeypatch, release_root=root) as lease:
        render(scenario, monkeypatch, lease)
        if kind in {"same_source", "unknown_release"}:
            target = root / (lease.source.digest if kind == "same_source" else "a" * 64)
            target.mkdir(mode=0o700)
            (target / "preserve").write_bytes(b"preexisting")
        elif kind == "symlink":
            root.rename(root.with_name("old-releases"))
            root.symlink_to(root.with_name("old-releases"))
        else:
            root.chmod(0o777)
        with pytest.raises(ValueError):
            publisher._publish_files(lease)
        assert lease.published_manifest is None


@pytest.mark.parametrize(
    "slot",
    [
        "publication-intent.json",
        "stock-configuration.json",
        "stock-compose.resolved.json",
        "runtime-image-attestation.json",
        "manifest.json",
        "publication-files.json",
    ],
)
@pytest.mark.parametrize("failure", ["fsync", "shutdown"])
def test_lost_acknowledgement_or_shutdown_never_returns_file_publication_authority(
    scenario, monkeypatch, slot, failure
):
    publisher = api()
    fixture, root = scenario
    original = publisher.os.fsync
    reached = False
    with pytest.raises(ValueError), built(fixture[0], monkeypatch, release_root=root) as lease:
        render(scenario, monkeypatch, lease)
        target = (
            (lease.root / "attempts" / lease.source.digest / slot)
            if slot.startswith("publication-")
            else root / lease.source.digest / slot
        )

        def interrupted(fd):
            nonlocal reached
            original(fd)
            if target.exists() and not reached:
                info, named = publisher.os.fstat(fd), target.stat()
                if (info.st_dev, info.st_ino) == (named.st_dev, named.st_ino):
                    reached = True
                    if failure == "fsync":
                        raise OSError("fixture publication durability failure")
                    lease.shutdown[0] = True

        monkeypatch.setattr(publisher.os, "fsync", interrupted)
        publisher._publish_files(lease)
    assert reached and lease.published_manifest is None


@pytest.mark.parametrize("kind", ["file_replaced", "directory_replaced", "late_loader"])
def test_readable_files_are_not_current_acknowledgement_after_boundary_failure(
    scenario, monkeypatch, kind
):
    publisher = api()
    fixture, root = scenario
    original = stock_release._load_release
    reached = False
    with pytest.raises(ValueError), built(fixture[0], monkeypatch, release_root=root) as lease:
        render(scenario, monkeypatch, lease)

        def changed(path, **kwargs):
            nonlocal reached
            result = original(path, **kwargs)
            reached = True
            if kind == "file_replaced":
                target = path.parent / "stock-configuration.json"
                raw = target.read_bytes()
                target.unlink()
                target.write_bytes(raw)
                target.chmod(0o444)
            elif kind == "directory_replaced":
                path.parent.rename(root.parent / "detached-directory")
                path.parent.mkdir(mode=0o700)
            else:
                fixture[0][0][0][5]["monotonic_ns"] += 1_200_000_000_000
            return result

        monkeypatch.setattr(stock_release, "_load_release", changed)
        publisher._publish_files(lease)
    assert reached and lease.published_manifest is None


@pytest.mark.parametrize("phase", ["file_fsync", "directory_fsync"])
def test_original_write_inode_survives_readback_and_durable_acknowledgement(
    scenario, monkeypatch, phase
):
    publisher = api()
    fixture, root = scenario
    original = publisher.os.fsync
    reached = False
    with pytest.raises(ValueError), built(fixture[0], monkeypatch, release_root=root) as lease:
        render(scenario, monkeypatch, lease)
        target = root / lease.source.digest / "stock-configuration.json"

        def replace(fd):
            nonlocal reached
            original(fd)
            if not target.exists() or reached:
                return
            expected = target.stat() if phase == "file_fsync" else target.parent.stat()
            info = publisher.os.fstat(fd)
            if (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino):
                reached = True
                raw = target.read_bytes()
                target.unlink()
                target.write_bytes(raw)
                target.chmod(0o444)

        monkeypatch.setattr(publisher.os, "fsync", replace)
        publisher._publish_files(lease)
    assert reached and lease.published_manifest is None


@pytest.mark.parametrize("fault", ["zero_write", "chmod", "release_directory_fsync"])
def test_native_write_and_directory_flush_failures_cannot_publish(scenario, monkeypatch, fault):
    publisher = api()
    fixture, root = scenario
    reached = False
    with pytest.raises(ValueError), built(fixture[0], monkeypatch, release_root=root) as lease:
        render(scenario, monkeypatch, lease)
        target = root / lease.source.digest / "manifest.json"
        operation = {"zero_write": "write", "chmod": "fchmod", "release_directory_fsync": "fsync"}[
            fault
        ]
        original = getattr(publisher.os, operation)

        def failed(fd, *args):
            nonlocal reached
            if target.exists() and not reached:
                named = (
                    target.parent.stat() if fault == "release_directory_fsync" else target.stat()
                )
                info = publisher.os.fstat(fd)
                if (info.st_dev, info.st_ino) == (named.st_dev, named.st_ino):
                    reached = True
                    if fault == "zero_write":
                        return 0
                    raise OSError("fixture native publication failure")
            return original(fd, *args)

        monkeypatch.setattr(publisher.os, operation, failed)
        publisher._publish_files(lease)
    assert reached and lease.published_manifest is None
