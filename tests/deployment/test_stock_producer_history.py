"""Historical admission from actual owned stages; no native Docker or providers."""

import importlib
import json
from pathlib import Path

import pytest
from test_stock_release_producer import opened
from test_stock_release_producer_probe import built
from test_stock_release_publication import render
from test_stock_release_publication import scenario as publication_scenario
from test_stock_source_prepare import git

from infra.hybrid.stock_release_publication import _publish_files
from infra.hybrid.stock_source_prepare import _prepare_source


def api():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_producer_history.py"
    assert path.is_file(), "Closed producer terminal facts and history are missing"
    return importlib.import_module("infra.hybrid.stock_producer_history")


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    return publication_scenario.__wrapped__(tmp_path, monkeypatch)


def complete(scenario, monkeypatch):
    history = api()
    fixture, release_root = scenario
    with built(fixture[0], monkeypatch, release_root=release_root) as lease:
        render(scenario, monkeypatch, lease)
        _publish_files(lease)
        history._seal(lease)
        assert lease.terminal_ack is True
        with pytest.raises(ValueError):
            history._seal(lease)
    return lease


def next_source(scenario):
    fixture, _ = scenario
    state = fixture[0][0][0]
    module, root, assets, _, _, clock, _ = state
    (assets / "src/next_fixture.py").write_text("# public fixture next source\n")
    git(assets, "add", ".")
    git(assets, "commit", "-qm", "fixture next source")
    staged = assets.parent / "next-staged.tar"
    sha = _prepare_source(staged, repo=assets)
    raw = staged.read_bytes()
    target = root / "inputs" / (sha + ".tar")
    target.write_bytes(raw)
    target.chmod(0o600)
    return module, root, assets, sha, raw, clock, [False]


def test_owned_completed_history_admits_only_a_distinct_fresh_source(scenario, monkeypatch):
    old = complete(scenario, monkeypatch)
    raw = (old.root / "attempts" / old.source.digest / "terminal.json").read_bytes()
    record = json.loads(raw)
    assert len(raw) <= 8192 and record["kind"] == "stock_producer_terminal_facts"
    assert record["source_sha256"] == old.source.digest
    assert "succeeded" not in raw.decode() and "caller_acknowledged" not in record
    fixture, release_root = scenario
    with pytest.raises(ValueError), opened(fixture[0][0][0], release_root=release_root):
        pytest.fail("Same source replayed")
    state = next_source(scenario)
    with opened(state, release_root=release_root) as current:
        assert current.completed_sources == {old.source.digest}
        assert current.built_image is current.probe_result is current.compose_bytes is None
        assert current.published_manifest is None and current.terminal_ack is False
        assert current.source.digest != old.source.digest


@pytest.mark.parametrize(
    "kind",
    [
        "missing_terminal",
        "wrong_hash",
        "wrong_type",
        "native_pending",
        "file_replaced",
        "directory_replaced",
        "extra_file",
        "config_polluted",
        "release_replaced",
        "bad_clock",
    ],
)
def test_incomplete_or_substituted_history_cannot_admit_a_new_attempt(scenario, monkeypatch, kind):
    old = complete(scenario, monkeypatch)
    _, release_root = scenario
    directory = old.root / "attempts" / old.source.digest
    terminal = directory / "terminal.json"
    if kind in {"wrong_hash", "wrong_type", "native_pending", "bad_clock"}:
        value = json.loads(terminal.read_bytes())
        if kind == "wrong_hash":
            value["files"]["attempt/build-response.http"]["sha256"] = "0" * 64
        elif kind == "wrong_type":
            value["schema_version"] = True
        elif kind == "native_pending":
            value["native_complete"] = False
        else:
            value["native_complete_clock"]["monotonic_ns"] = value["producer_deadline_ns"]
        terminal.write_bytes(
            (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
    elif kind == "missing_terminal":
        terminal.unlink()
    elif kind in {"file_replaced", "release_replaced"}:
        path = (
            directory / "source.tar"
            if kind == "file_replaced"
            else release_root / old.source.digest / "manifest.json"
        )
        raw, mode = path.read_bytes(), path.stat().st_mode & 0o777
        path.unlink()
        path.write_bytes(raw)
        path.chmod(mode)
    elif kind == "directory_replaced":
        path = directory / "render/home"
        path.rename(old.root.parent / "detached-home")
        path.mkdir(mode=0o700)
    elif kind == "config_polluted":
        (directory / "render/docker-config/config.json").write_text("{}")
    else:
        (directory / "extra.bin").write_bytes(b"unknown")
    state = next_source(scenario)
    with pytest.raises(ValueError), opened(state, release_root=release_root):
        pytest.fail("Invalid historical chain admitted")
    assert not (old.root / "attempts" / state[3]).exists()


@pytest.mark.parametrize("kind", ["fsync", "close", "late", "shutdown"])
def test_fresh_history_durability_is_required_before_admission(scenario, monkeypatch, kind):
    old = complete(scenario, monkeypatch)
    _, release_root = scenario
    state = next_source(scenario)
    target = old.root / "attempts" / old.source.digest / "build-complete.json"
    module = api()
    original = getattr(module.os, "close" if kind == "close" else "fsync")
    reached = False

    def failed(fd):
        nonlocal reached
        info, expected = module.os.fstat(fd), target.stat()
        selected = (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino)
        result = original(fd)
        if selected and not reached:
            reached = True
            if kind in {"fsync", "close"}:
                raise OSError("fixture historical durability failure")
            if kind == "late":
                state[5]["monotonic_ns"] += 1_200_000_000_000
            else:
                state[6][0] = True
        return result

    monkeypatch.setattr(module.os, "close" if kind == "close" else "fsync", failed)
    with pytest.raises(ValueError), opened(state, release_root=release_root):
        pytest.fail("Unacknowledged historical read admitted")
    assert reached and not (old.root / "attempts" / state[3]).exists()


@pytest.mark.parametrize("kind", ["fsync", "shutdown", "late"])
def test_complete_terminal_bytes_do_not_replace_current_acknowledgement(
    scenario, monkeypatch, kind
):
    history = api()
    fixture, release_root = scenario
    with (
        pytest.raises(ValueError),
        built(fixture[0], monkeypatch, release_root=release_root) as lease,
    ):
        render(scenario, monkeypatch, lease)
        _publish_files(lease)
        original = history.os.fsync
        target = lease.root / "attempts" / lease.source.digest / "terminal.json"

        def fail(fd):
            original(fd)
            if target.exists():
                info, expected = history.os.fstat(fd), target.stat()
                if (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino):
                    if kind == "fsync":
                        raise OSError("fixture lost terminal acknowledgement")
                    if kind == "shutdown":
                        lease.shutdown[0] = True
                    else:
                        fixture[0][0][0][5]["monotonic_ns"] += 1_200_000_000_000

        monkeypatch.setattr(history.os, "fsync", fail)
        history._seal(lease)
    assert target.exists() and lease.terminal_ack is False
    # The old invocation still failed. A later source must independently validate
    # and freshly flush completed facts; it never adopts the missing old ack.
    monkeypatch.setattr(history.os, "fsync", original)
    state = next_source(scenario)
    with opened(state, release_root=release_root) as current:
        assert current.completed_sources == {lease.source.digest}
        assert current.terminal_ack is False and current.built_image is None


def rehash_records(old, release_root, changed, mutate):
    """Adversarial balanced hash chain; semantic validators must still reject it."""
    history = api()
    directory = old.root / "attempts" / old.source.digest
    terminal = directory / "terminal.json"
    replacements = {}

    def replace(value):
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return replacements.get(value, value) if isinstance(value, str) else value

    for name in history._ATTEMPT_FILES:
        if not name.endswith(".json"):
            continue
        path = directory / name
        raw = path.read_bytes()
        value = replace(json.loads(raw))
        if name == changed:
            mutate(value)
        updated = history.release._canonical(value)
        if updated != raw:
            path.write_bytes(updated)
            replacements[history._sha(raw)] = history._sha(updated)
    facts = json.loads(terminal.read_bytes())
    for label in facts["files"]:
        if label.startswith("attempt/"):
            path = directory / label.removeprefix("attempt/")
        elif label.startswith("render/"):
            path = directory / label
        elif label.startswith("release/"):
            path = release_root / old.source.digest / label.removeprefix("release/")
        else:
            path = old.root / label
        facts["files"][label] = {
            "sha256": history._sha(path.read_bytes()),
            "fingerprint": list(history.release._fingerprint(path.stat())),
        }
    terminal.write_bytes(history.release._canonical(facts))


@pytest.mark.parametrize(
    "name,field,value",
    [
        ("source-preparation.json", "commit", "0" * 40),
        ("dispatch.json", "build_deadline_ns", True),
        ("build-complete.json", "image_digest", "sha256:" + "0" * 64),
        ("probe-intent.json", "build_complete_sha256", "0" * 64),
        ("probe-result.json", "status", "failed"),
        ("render-intent.json", "environment", {"LIVE_TRADING_ENABLED": "true"}),
        ("render-complete.json", "compose_sha256", "0" * 64),
        ("publication-intent.json", "files", {}),
        ("publication-files.json", "image_digest", "sha256:" + "0" * 64),
    ],
)
def test_fully_rehashed_semantically_invalid_native_chains_are_denied(
    scenario, monkeypatch, name, field, value
):
    old = complete(scenario, monkeypatch)
    _, release_root = scenario
    rehash_records(old, release_root, name, lambda record: record.__setitem__(field, value))
    state = next_source(scenario)
    with pytest.raises(ValueError), opened(state, release_root=release_root):
        pytest.fail("Balanced invalid native chain was accepted")
    assert not (old.root / "attempts" / state[3]).exists()


def test_history_accepts_only_the_exact_observed_ubuntu_renderer(scenario, monkeypatch):
    from test_stock_compose_render import Commands

    original = Commands.__init__

    def distro(self, *args):
        original(self, *args)
        self.version = b"2.40.3+ds1-0ubuntu1~24.04.1\n"

    monkeypatch.setattr(Commands, "__init__", distro)
    old = complete(scenario, monkeypatch)
    state = next_source(scenario)
    with opened(state, release_root=scenario[1]) as current:
        assert old.source.digest in current.completed_sources
