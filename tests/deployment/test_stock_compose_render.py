"""Owned build/probe and real bounded child capture; native Docker default-denied."""

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest
import yaml
from test_stock_probe_controller import Daemon, module
from test_stock_release_producer import opened
from test_stock_release_producer_probe import built
from test_stock_release_producer_probe import scenario as probe_scenario

from infra.hybrid import stock_process, stock_release_producer


def api():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_compose_render.py"
    assert path.is_file(), "Owned fixed Compose rendering is missing"
    return importlib.import_module("infra.hybrid.stock_compose_render")


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    result = probe_scenario.__wrapped__(tmp_path, monkeypatch)
    original = stock_process.subprocess.Popen

    def denied(argv, **kwargs):
        if argv[0] != "/usr/bin/git":
            raise AssertionError("Native Docker or unexpected executable forbidden")
        return original(argv, **kwargs)

    monkeypatch.setattr(stock_process.subprocess, "Popen", denied)
    executable = tmp_path / "bin" / "docker"
    executable.parent.mkdir(mode=0o700)
    executable.write_bytes(b"fixture executable must never be launched\n")
    executable.chmod(0o500)
    return result, original, executable


def model(lease):
    image = lease.built_image.image_digest
    attestation = lease.release_root / lease.source.digest / "runtime-image-attestation.json"

    def expand(value):
        if isinstance(value, dict):
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, str) and value.startswith("${STOCK_IMAGE:"):
            return image
        if isinstance(value, str) and value.startswith("${STOCK_ATTESTATION_FILE:"):
            return str(attestation)
        return value

    value = expand(yaml.safe_load(lease.source.compose_template))
    worker = value["services"]["stock-research"]
    worker["mem_limit"] = worker["memswap_limit"] = "536870912"
    for volume in worker["volumes"]:
        volume["bind"] = {}
    return value


class Commands:
    def __init__(self, scenario, lease):
        self.scenario, self.lease = scenario, lease
        self.calls = []
        self.version = b"2.40.3\n"
        self.render = json.dumps(model(lease), indent=2).encode()
        self.stderr = b""
        self.exit_code = 0
        self.after_launch = lambda _index: None

    def install(self, monkeypatch):
        _, original, executable = self.scenario
        monkeypatch.setattr(api(), "_DOCKER", executable)

        def launch(argv, **kwargs):
            if argv[0] == "/usr/bin/git":
                return original(argv, **kwargs)
            assert argv[0] == str(executable), "Native Docker forbidden"
            self.calls.append((tuple(argv), dict(kwargs)))
            raw = self.version if len(self.calls) == 1 else self.render
            program = (
                "import os; os.write(1,"
                + repr(raw)
                + "); os.write(2,"
                + repr(self.stderr)
                + "); raise SystemExit("
                + str(self.exit_code)
                + ")"
            )
            child = original((sys.executable, "-c", program), **kwargs)
            self.after_launch(len(self.calls))
            return child

        monkeypatch.setattr(stock_process.subprocess, "Popen", launch)
        return self


def probe(scenario, monkeypatch, lease):
    native, _, _ = scenario
    daemon = Daemon(native[1])
    daemon.install(monkeypatch, module())
    stock_release_producer._fresh_probe(lease)
    daemon.join()
    assert daemon.gone


def test_owned_render_is_fixed_scrubbed_bounded_and_retains_complete_native_output(
    scenario, monkeypatch
):
    renderer = api()
    native, _, executable = scenario
    for key in (
        "DOCKER_HOST",
        "DOCKER_CONFIG",
        "COMPOSE_FILE",
        "COMPOSE_ENV_FILES",
        "COMPOSE_PROJECT_NAME",
        "HOME",
        "PATH",
        "HTTPS_PROXY",
        "STOCK_IMAGE",
    ):
        monkeypatch.setenv(key, "invalid ambient fixture")
    with built(native, monkeypatch) as lease:
        probe(scenario, monkeypatch, lease)
        commands = Commands(scenario, lease).install(monkeypatch)
        raw = renderer._render(lease)
        assert json.loads(raw) == model(lease)
        assert raw == stock_release_producer._canonical(model(lease))
        assert lease.compose_bytes == raw and len(commands.calls) == 2
        directory = lease.root / "attempts" / lease.source.digest
        workspace = directory / "render"
        assert (workspace / "compose-template.yml").read_bytes() == lease.source.compose_template
        assert (workspace / "compose.env").read_bytes() == b""
        assert set(p.name for p in workspace.iterdir()) == {
            "compose-template.yml",
            "compose.env",
            "docker-config",
            "home",
            "empty-path",
        }
        for name in ("docker-config", "home", "empty-path"):
            assert not list((workspace / name).iterdir())
            assert (workspace / name).stat().st_mode & 0o777 == 0o700
        prefix = (
            str(executable),
            "--config",
            str(workspace / "docker-config"),
            "--host",
            "unix:///var/run/docker.sock",
            "compose",
        )
        assert commands.calls[0][0] == (*prefix, "version", "--short")
        assert commands.calls[1][0] == (
            *prefix,
            "--ansi",
            "never",
            "--project-name",
            "hybrid-stock-research",
            "--project-directory",
            str(workspace),
            "--env-file",
            str(workspace / "compose.env"),
            "--file",
            str(workspace / "compose-template.yml"),
            "config",
            "--format",
            "json",
            "--resolve-image-digests=false",
            "--lock-image-digests=false",
        )
        for _, options in commands.calls:
            assert options["env"] == {
                "DOCKER_CONFIG": str(workspace / "docker-config"),
                "HOME": str(workspace / "home"),
                "PATH": str(workspace / "empty-path"),
                "LC_ALL": "C",
                "STOCK_IMAGE": lease.built_image.image_digest,
                "STOCK_ATTESTATION_FILE": str(
                    lease.release_root / lease.source.digest / "runtime-image-attestation.json"
                ),
            }
            assert options["cwd"] == workspace
            assert options["close_fds"] and options["start_new_session"]
        assert (directory / "compose-render.stdout").read_bytes() == commands.render
        assert (directory / "compose-version.stdout").read_bytes() == commands.version
        receipt = json.loads((directory / "render-complete.json").read_bytes())
        assert receipt["compose_sha256"] == hashlib.sha256(raw).hexdigest()
        assert receipt["probe_result_sha256"] == lease.hashes["probe-result.json"]
        with pytest.raises(ValueError):
            renderer._render(lease)
        assert len(commands.calls) == 2


@pytest.mark.parametrize("kind", ["old", "leading_v", "extra", "stderr", "nonzero"])
def test_version_failure_never_renders_or_can_be_retried(scenario, monkeypatch, kind):
    renderer = api()
    native, _, _ = scenario
    with built(native, monkeypatch) as lease:
        probe(scenario, monkeypatch, lease)
        commands = Commands(scenario, lease)
        if kind in {"old", "leading_v", "extra"}:
            commands.version = {
                "old": b"2.40.2\n",
                "leading_v": b"v2.40.3\n",
                "extra": b"2.40.3\n2.40.3\n",
            }[kind]
        elif kind == "stderr":
            commands.stderr = b"fixture warning"
        else:
            commands.exit_code = 7
        commands.install(monkeypatch)
        with pytest.raises(ValueError):
            renderer._render(lease)
        with pytest.raises(ValueError):
            renderer._render(lease)
        assert len(commands.calls) == 1 and lease.compose_bytes is None
        directory = lease.root / "attempts" / lease.source.digest
        assert (directory / "compose-version.stdout").read_bytes() == commands.version
        assert not (directory / "render-complete.json").exists()


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "nan",
        "truncated",
        "large",
        "live",
        "mount",
        "tag",
        "extra_service",
        "scalar",
        "deep",
    ],
)
def test_unapproved_actual_render_does_not_yield_compose_authority(scenario, monkeypatch, kind):
    renderer = api()
    native, _, _ = scenario
    with built(native, monkeypatch) as lease:
        probe(scenario, monkeypatch, lease)
        commands = Commands(scenario, lease)
        if kind in {"duplicate", "nan", "truncated", "large", "scalar", "deep"}:
            commands.render = {
                "duplicate": b'{"services":{},"services":{}}',
                "nan": b'{"value":NaN}',
                "truncated": b"{",
                "large": b"x" * 65537,
                "scalar": b"[]",
                "deep": b"[" * 20000 + b"0" + b"]" * 20000,
            }[kind]
        else:
            value = model(lease)
            worker = value["services"]["stock-research"]
            if kind == "live":
                worker["environment"]["LIVE_TRADING_ENABLED"] = "true"
            elif kind == "mount":
                worker["volumes"][0]["bind"]["create_host_path"] = True
            elif kind == "tag":
                worker["image"] = "untrusted:latest"
            else:
                value["services"]["extra"] = worker
            commands.render = json.dumps(value).encode()
        commands.install(monkeypatch)
        with pytest.raises(ValueError):
            renderer._render(lease)
        assert lease.compose_bytes is None and len(commands.calls) == 2
        directory = lease.root / "attempts" / lease.source.digest
        assert len((directory / "compose-render.stdout").read_bytes()) <= 65536
        assert not (directory / "render-complete.json").exists()


def test_supplied_archive_without_current_owned_probe_cannot_render(scenario):
    renderer = api()
    native, _, _ = scenario
    with opened(native[0][0]) as lease, pytest.raises(ValueError):
        renderer._render(lease)


@pytest.mark.parametrize(
    "kind", ["late", "shutdown", "config_pollution", "namespace", "binary_replaced"]
)
def test_native_phase_and_filesystem_changes_fail_closed(scenario, monkeypatch, kind):
    renderer = api()
    native, _, executable = scenario
    with pytest.raises(ValueError), built(native, monkeypatch) as lease:
        probe(scenario, monkeypatch, lease)
        commands = Commands(scenario, lease)

        def mutate(index):
            if index != 2:
                return
            workspace = lease.root / "attempts" / lease.source.digest / "render"
            if kind == "late":
                native[0][0][5]["monotonic_ns"] += 5_000_000_000
            elif kind == "shutdown":
                lease.shutdown[0] = True
            elif kind == "config_pollution":
                (workspace / "docker-config/config.json").write_text("{}")
            elif kind == "binary_replaced":
                old = executable.read_bytes()
                executable.rename(executable.with_name("old-docker"))
                executable.write_bytes(old)
                executable.chmod(0o500)
            else:
                workspace.rename(workspace.with_name("old-render"))
                workspace.mkdir(mode=0o700)

        commands.after_launch = mutate
        commands.install(monkeypatch)
        renderer._render(lease)
    assert lease.compose_bytes is None


@pytest.mark.parametrize(
    "slot",
    [
        "compose-template.yml",
        "compose.env",
        "render-intent.json",
        "compose-version.stdout",
        "compose-render.stdout",
        "render-complete.json",
    ],
)
@pytest.mark.parametrize("failure", ["fsync", "shutdown"])
def test_render_durability_and_shutdown_boundaries_never_acknowledge_success(
    scenario, monkeypatch, slot, failure
):
    renderer = api()
    native, _, _ = scenario
    original = renderer.os.fsync
    reached = False
    with pytest.raises(ValueError), built(native, monkeypatch) as lease:
        probe(scenario, monkeypatch, lease)
        Commands(scenario, lease).install(monkeypatch)
        directory = lease.root / "attempts" / lease.source.digest
        target = directory / (
            "render/" + slot if slot in {"compose-template.yml", "compose.env"} else slot
        )

        def interrupt(fd):
            nonlocal reached
            original(fd)
            if target.exists() and not reached:
                info, named = renderer.os.fstat(fd), target.stat()
                if (info.st_dev, info.st_ino) == (named.st_dev, named.st_ino):
                    reached = True
                    if failure == "fsync":
                        raise OSError("fixture render durability failure")
                    lease.shutdown[0] = True

        monkeypatch.setattr(renderer.os, "fsync", interrupt)
        renderer._render(lease)
    assert reached and lease.compose_bytes is None


@pytest.mark.parametrize(
    "kind",
    ["symlink", "empty", "directory", "writable", "not_executable", "hardlink", "parent_writable"],
)
def test_untrusted_executable_metadata_never_launches_a_child(scenario, monkeypatch, kind):
    renderer = api()
    native, _, executable = scenario
    with built(native, monkeypatch) as lease:
        probe(scenario, monkeypatch, lease)
        commands = Commands(scenario, lease).install(monkeypatch)
        if kind in {"symlink", "directory"}:
            executable.rename(executable.with_name("other"))
            if kind == "symlink":
                executable.symlink_to(executable.with_name("other"))
            else:
                executable.mkdir()
        elif kind == "empty":
            executable.chmod(0o700)
            executable.write_bytes(b"")
        elif kind == "hardlink":
            executable.with_name("other").hardlink_to(executable)
        elif kind == "parent_writable":
            executable.parent.chmod(0o777)
        else:
            executable.chmod(0o777 if kind == "writable" else 0o400)
        with pytest.raises(ValueError):
            renderer._render(lease)
        assert not commands.calls and lease.compose_bytes is None
