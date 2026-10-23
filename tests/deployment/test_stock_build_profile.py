"""Read-only profile guards and harmless local process/filesystem fixtures."""

import importlib
import os
from pathlib import Path

import pytest

from infra.hybrid import stock_build_cohorts as cohorts


def fixture_modules(monkeypatch, modules):
    from dataclasses import replace

    monkeypatch.setattr(
        cohorts,
        "_COHORTS",
        (replace(cohorts._COHORTS[0], modules=tuple(modules.items())), *cohorts._COHORTS[1:]),
    )


def api():
    path = Path(__file__).resolve().parents[2] / "infra/hybrid/stock_build_profile.py"
    assert path.is_file(), "Qualified read-only build observer is missing"
    return importlib.import_module("infra.hybrid.stock_build_profile")


def test_process_start_uses_conservative_tick_upper_bound():
    module = api()
    assert module._start_upper(1430, 100) == 14_310_000_000
    assert module._start_upper(1, 3) == 666_666_667
    assert module._start_upper(0, 100) == 10_000_000


@pytest.mark.parametrize("ticks,hz", [(True, 100), (-1, 100), (1, 0), (1, True), (1, 1.5)])
def test_uncertain_process_tick_domain_is_denied(ticks, hz):
    with pytest.raises(ValueError):
        api()._start_upper(ticks, hz)


def test_native_observer_denies_before_io_without_linux_root_and_isolation(monkeypatch):
    module = api()
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module, "_get", lambda *a, **k: pytest.fail("Native Engine reached"))
    with pytest.raises(ValueError):
        module.observe_build_profile("4" * 40, b"{}", {}, not_after_ns=1)


def test_later_boot_capacity_binds_current_info_before_touching_old_root(monkeypatch):
    module = api()
    monkeypatch.setattr(module, "_root", lambda: None)
    monkeypatch.setattr(module, "_get", lambda *a, **k: {"DockerRootDir": "/mnt/docker"})
    monkeypatch.setattr(module, "_capacity", lambda: pytest.fail("Stale root inspected"))
    with pytest.raises(ValueError):
        module.check_failed_capacity({})


def test_later_boot_capacity_requires_fresh_identity_and_headroom(monkeypatch):
    module = api()
    monkeypatch.setattr(module, "_root", lambda: None)
    monkeypatch.setattr(module, "_get", lambda *a, **k: {"DockerRootDir": "/var/lib/docker"})
    paths = {
        "producer": "/var/lib/hybrid-stock-producer",
        "release_root": "/opt/hybrid-stock-research/releases",
        "docker": "/var/lib/docker",
    }
    capacity = {
        key: {
            "path": path,
            "device": 1,
            "inode": 10 + i,
            "available_bytes": 6 * 1024**3,
            "available_inodes": 5000,
        }
        for i, (key, path) in enumerate(paths.items())
    }
    monkeypatch.setattr(module, "_capacity", lambda: capacity)
    module.check_failed_capacity(capacity)
    changed = {key: dict(value) for key, value in capacity.items()}
    changed["docker"]["inode"] = 999
    with pytest.raises(ValueError):
        module.check_failed_capacity(changed)
    capacity["docker"]["available_bytes"] = 0
    with pytest.raises(ValueError):
        module.check_failed_capacity(changed)


def test_bounded_binary_read_detects_replacement_and_never_follows_symlink(tmp_path):
    module = api()
    path = tmp_path / "binary"
    path.write_bytes(b"verified fixture bytes")
    path.chmod(0o755)
    import hashlib
    import time

    raw, stamp = module._read_file(
        path, 64, 0o755, time.monotonic_ns() + 1_000_000_000, uid=os.geteuid(), gid=os.getegid()
    )
    assert (
        hashlib.sha256(raw).hexdigest()
        == "3ef993776411f75268188669a50e9192517feec13436b90e97802c0f4f5e299a"
    )
    assert stamp[6] == 22
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        module._read_file(
            link, 64, 0o755, time.monotonic_ns() + 1_000_000_000, uid=os.geteuid(), gid=os.getegid()
        )


def test_fixed_get_rejects_other_routes_before_connect(monkeypatch):
    module = api()
    monkeypatch.setattr(module, "_connection", lambda *a: pytest.fail("Unexpected connect"))
    with pytest.raises(ValueError):
        module._get("/containers/json", 1)


def test_get_requires_pid1_root_and_exact_eof(monkeypatch):
    module = api()
    import socket
    import struct

    monkeypatch.setattr(socket, "SO_PEERCRED", 17, raising=False)
    monkeypatch.setattr(module, "_socket_binding", lambda: (24, 1257, 0o140660, 0, 112, 1, 0, 1, 1))

    class Peer:
        def __init__(self, pid):
            self.pid = pid

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def getsockopt(self, level, option, size):
            assert (level, option, size) == (socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            return struct.pack("3i", self.pid, 0, 0)

        def settimeout(self, seconds):
            pass

        def sendall(self, data):
            assert data == b"GET /version HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n"

    import time

    cap = time.monotonic_ns() + 1_000_000_000
    monkeypatch.setattr(module, "_connection", lambda *a: Peer(950))
    with pytest.raises(ValueError):
        module._get("/version", cap)
    monkeypatch.setattr(module, "_connection", lambda *a: Peer(1))
    monkeypatch.setattr(module, "_headers", lambda *a: ({}, b'{"Version":"29.1.3"}'))
    monkeypatch.setattr(module, "_body", lambda peer, deadline, headers, initial: initial)
    monkeypatch.setattr(module, "_receive", lambda *a: b"")
    assert module._get("/version", cap) == {"Version": "29.1.3"}
    monkeypatch.setattr(module, "_receive", lambda *a: b"x")
    with pytest.raises(ValueError):
        module._get("/version", cap)


def _proc_reads(monkeypatch, module, path, chunks):
    """Replace only the fixed procfs descriptor boundary; preserve real parsers."""
    from collections import deque

    pending = deque(chunks)
    closed = []
    real_open, real_read, real_close = os.open, os.read, os.close

    def opening(candidate, flags, *args, **kwargs):
        if str(candidate) == path:
            assert flags & os.O_RDONLY == os.O_RDONLY
            return 900001
        return real_open(candidate, flags, *args, **kwargs)

    def reading(fd, size):
        if fd != 900001:
            return real_read(fd, size)
        part = pending.popleft() if pending else b""
        if len(part) > size:
            pending.appendleft(part[size:])
        return part[:size]

    def closing(fd):
        if fd == 900001:
            closed.append(fd)
            return None
        return real_close(fd)

    monkeypatch.setattr(module.os, "open", opening)
    monkeypatch.setattr(module.os, "read", reading)
    monkeypatch.setattr(module.os, "close", closing)
    return closed


def _stat_record(**changes):
    from types import SimpleNamespace

    fields = {
        "st_dev": 24,
        "st_ino": 1257,
        "st_mode": 0o140660,
        "st_uid": 0,
        "st_gid": 112,
        "st_nlink": 1,
        "st_size": 0,
        "st_mtime_ns": 1_000_000_000,
        "st_ctime_ns": 1_000_000_001,
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


def test_valid_process_stat_survives_legal_short_reads(monkeypatch):
    """A short kernel read must not be mistaken for a second procfs record."""
    import time

    module = api()
    raw = b"950 (dockerd) " + b" ".join([b"S", *([b"0"] * 18), b"1430"]) + b"\n"
    closed = _proc_reads(monkeypatch, module, "/proc/950/stat", [raw[:17], raw[17:], b""])
    assert module._process_start(950, time.monotonic_ns() + 1_000_000_000) == 1430
    assert closed == [900001]


def test_valid_listener_table_survives_legal_short_reads(monkeypatch):
    """A fragmented valid listening row must retain its full inherited binding."""
    import time

    module = api()
    monkeypatch.setattr(module, "_socket_binding", lambda: (24, 1257, 0o140660, 0, 112, 1, 0, 1, 1))
    raw = (
        b"Num RefCount Protocol Flags Type St Inode Path\n"
        b"0000000000000000: 00000002 00000000 00010000 0001 01 6522 /run/docker.sock\n"
    )
    monkeypatch.setattr(module, "_canonical_directory", lambda path: (24, 1))
    real_lstat = Path.lstat
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda path: _stat_record() if str(path) == "/run/docker.sock" else real_lstat(path),
    )
    holders = []
    monkeypatch.setattr(
        module, "_listener_fds", lambda pid, inode, cap: holders.append((pid, inode))
    )
    closed = _proc_reads(monkeypatch, module, "/proc/950/net/unix", [raw[:51], raw[51:], b""])
    inode, stamp = module._listener(950, time.monotonic_ns() + 1_000_000_000)
    assert (inode, stamp[:6]) == (6522, (24, 1257, 0o140660, 0, 112, 1))
    assert holders == [(1, 6522), (950, 6522)]
    assert closed == [900001]


@pytest.fixture
def observed_host(monkeypatch):
    """Whole coordinator with deterministic contracts for separately tested host I/O."""
    import copy
    import hashlib
    import time

    module = api()
    boot = "99d3c666-63ed-4615-8a71-881e31d2c89c"
    origin = {
        "boot_id": boot,
        "utc": "2026-10-23T01:26:41.000000+00:00",
        "monotonic_ns": 20_000_000_000,
    }
    observed = {
        "boot_id": boot,
        "utc": "2026-10-23T02:34:15.000000+00:00",
        "monotonic_ns": 30_000_000_000,
    }
    stamp = (1, 20, 0o100755, 0, 0, 1, 83879288, 1, 1)
    socket_stamp = (24, 1257, 0o140660, 0, 112, 1, 0, 1, 1)
    version = {
        "Version": "29.1.3",
        "GitCommit": "29.1.3-0ubuntu3~24.04.2",
        "ApiVersion": "1.52",
        "MinAPIVersion": "1.44",
        "Os": "linux",
        "Arch": "amd64",
    }
    engine = b"private recorded engine fixture"
    state = {
        "source_commit": "479fca6ce789692d2a088b162fe6bcfeb2ad8336",
        "source_valid": True,
        "source_checks": 0,
        "version": version,
        "docker_root": "/var/lib/docker",
        "tick": 1430,
        "socket_stamp": socket_stamp,
        "binary_stamp": stamp,
        "capacity": {
            name: {
                "path": str(path),
                "device": 1,
                "inode": i + 100,
                "available_bytes": 6 * 1024**3,
                "available_inodes": 5000,
            }
            for i, (name, path) in enumerate(module._ROOTS.items())
        },
        "observed": observed,
        "source_change_on_info": False,
        "units": {
            "docker.service": {"properties": {"MainPID": "950", "Requires": "docker.socket"}},
            "docker.socket": {
                "properties": {"Listen": "/run/docker.sock (Stream)", "Triggers": "docker.service"}
            },
        },
    }
    monkeypatch.setattr(module, "_root", lambda: None)
    monkeypatch.setattr(module.socket, "if_nameindex", lambda: [(1, "lo")])
    real_readlink = os.readlink
    monkeypatch.setattr(
        module.os,
        "readlink",
        lambda p: (
            {"/proc/self/ns/net": "net:[2]", "/proc/1/ns/net": "net:[1]"}.get(str(p), "")
            if str(p) in {"/proc/self/ns/net", "/proc/1/ns/net"}
            else real_readlink(p)
        ),
    )
    monkeypatch.setattr(module, "_clock", lambda: copy.deepcopy(state["observed"]))
    monkeypatch.setattr(module, "_ENGINE_SHA", hashlib.sha256(engine).hexdigest())

    def source_check(commit, cap):
        assert commit == state["source_commit"]
        state["source_checks"] += 1
        if not state["source_valid"]:
            raise ValueError("stock_producer_unavailable")

    def get(path, cap):
        assert path in {"/version", "/v1.52/info"}
        if path == "/version":
            return copy.deepcopy(state["version"])
        if state["source_change_on_info"]:
            state["source_valid"] = False
        return {"DockerRootDir": state["docker_root"]}

    monkeypatch.setattr(module, "_source_profile", source_check)
    monkeypatch.setattr(module, "_unit", lambda name, cap: copy.deepcopy(state["units"][name]))
    monkeypatch.setattr(module, "_listener", lambda pid, cap: (6522, state["socket_stamp"]))
    monkeypatch.setattr(module, "_process_start", lambda pid, cap: state["tick"])
    monkeypatch.setattr(module.os, "sysconf", lambda key: 100)
    monkeypatch.setattr(module, "_binary", lambda pid, cap: state["binary_stamp"])
    monkeypatch.setattr(module, "_get", get)
    monkeypatch.setattr(module, "_capacity", lambda: copy.deepcopy(state["capacity"]))
    real_lstat, real_stat = Path.lstat, Path.stat

    def binary_info():
        names = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        return _stat_record(**dict(zip(names, state["binary_stamp"], strict=True)))

    monkeypatch.setattr(
        Path,
        "lstat",
        lambda path: binary_info() if str(path) == "/usr/bin/dockerd" else real_lstat(path),
    )
    monkeypatch.setattr(
        Path,
        "stat",
        lambda path, **kw: binary_info() if str(path) == "/proc/950/exe" else real_stat(path, **kw),
    )

    def observe():
        return module.observe_build_profile(
            state["source_commit"],
            engine,
            origin,
            not_after_ns=time.monotonic_ns() + 10_000_000_000,
        )

    return module, state, origin, observe


def test_whole_observer_returns_only_closed_negative_profile(observed_host):
    _, _, _, observe = observed_host
    result = observe()
    assert set(result) == {"daemon_profile", "capacity"}
    profile = result["daemon_profile"]
    assert profile["peer_pid"] == 1 and profile["daemon_pid"] == 950
    assert profile["daemon_start_boottime_upper_ns"] == 14_310_000_000
    assert profile["source_tree"] == "98257c8083cc6395fde92c600b1683b783952955"
    assert profile["socket_activation"]["listener_inode"] == 6522
    assert not ({"manifest", "release", "producer_success"} & set(result))


def test_whole_observer_selects_second_original_cohort_and_checks_it_twice(observed_host):
    _, state, _, observe = observed_host
    state["source_commit"] = "bac162fd6eb6178516a212d30846fb1a055c90fb"
    result = observe()
    assert result["daemon_profile"]["source_profile_id"] == "stock-producer-causal-bac-v1"
    assert result["daemon_profile"]["source_tree"] == "21953af2db3189b5a3a9c03c22b3e35baea29683"
    assert state["source_checks"] == 2
    assert result["daemon_profile"]["profile_id"] == "ubuntu-docker-legacy-q-29.1.3-v1"


def test_whole_observer_rejects_source_drift_during_engine_observation(observed_host):
    """Successful host reads cannot validate a checkout replaced after first proof."""
    _, state, _, observe = observed_host
    state["source_change_on_info"] = True
    with pytest.raises(ValueError):
        observe()


@pytest.mark.parametrize(
    "field,value",
    [
        ("Version", "29.1.4"),
        ("GitCommit", "upstream-tag"),
        ("Arch", "arm64"),
        ("Os", "windows"),
        ("ApiVersion", "1.51"),
    ],
)
def test_whole_observer_denies_engine_profile_drift(observed_host, field, value):
    _, state, _, observe = observed_host
    state["version"][field] = value
    with pytest.raises(ValueError):
        observe()


@pytest.mark.parametrize(
    "mutation",
    ["pid", "requires", "listen", "trigger", "new_root", "same_tick", "new_boot", "ctime"],
)
def test_whole_observer_denies_unqualified_host_bindings(observed_host, mutation):
    _, state, origin, observe = observed_host
    if mutation == "pid":
        state["units"]["docker.service"]["properties"]["MainPID"] = "1"
    elif mutation == "requires":
        state["units"]["docker.service"]["properties"]["Requires"] = "network.target"
    elif mutation == "listen":
        state["units"]["docker.socket"]["properties"]["Listen"] = "/tmp/docker.sock (Stream)"
    elif mutation == "trigger":
        state["units"]["docker.socket"]["properties"]["Triggers"] = "other.service"
    elif mutation == "new_root":
        state["docker_root"] = "/mnt/docker"
    elif mutation == "same_tick":
        state["tick"] = 2000
    elif mutation == "new_boot":
        state["observed"]["boot_id"] = "19d3c666-63ed-4615-8a71-881e31d2c89c"
    elif mutation == "ctime":
        state["socket_stamp"] = (*state["socket_stamp"][:8], 1_792_718_801_000_000_000)
    assert origin["monotonic_ns"] == 20_000_000_000
    with pytest.raises(ValueError):
        observe()


@pytest.mark.parametrize("invalid", [0, True, -1, 2**63, "10"])
def test_budget_rejects_unbounded_or_uncertain_deadlines(invalid):
    with pytest.raises(ValueError):
        api()._budget(invalid)


@pytest.mark.parametrize("mode", [0o40755, 0o40777, 0o100644])
def test_canonical_directory_enforces_root_owned_directory_ancestors(monkeypatch, mode):
    module = api()
    monkeypatch.setattr(Path, "resolve", lambda path, strict: path)
    monkeypatch.setattr(Path, "lstat", lambda path: _stat_record(st_mode=mode, st_uid=0, st_gid=0))
    monkeypatch.setattr(Path, "stat", lambda path: _stat_record(st_mode=mode, st_uid=0, st_gid=0))
    if mode == 0o40755:
        assert module._canonical_directory(Path("/var/lib/docker")) == (24, 1257)
    else:
        with pytest.raises(ValueError):
            module._canonical_directory(Path("/var/lib/docker"))


def test_canonical_directory_denies_symlink_resolution(monkeypatch):
    module = api()
    monkeypatch.setattr(Path, "resolve", lambda path, strict: Path("/other/docker"))
    with pytest.raises(ValueError):
        module._canonical_directory(Path("/var/lib/docker"))


@pytest.mark.parametrize("bad", [None, "bytes", "inodes", "rebind"])
def test_capacity_requires_available_blocks_inodes_and_stable_identity(monkeypatch, bad):
    from types import SimpleNamespace

    module = api()
    counts = {}

    def directory(path):
        key = str(path)
        counts[key] = counts.get(key, 0) + 1
        return (24, 999 if bad == "rebind" and counts[key] > 1 else 1257)

    monkeypatch.setattr(module, "_canonical_directory", directory)
    monkeypatch.setattr(
        module.os,
        "statvfs",
        lambda path: SimpleNamespace(
            f_bavail=0 if bad == "bytes" else 6 * 1024**3,
            f_frsize=1,
            f_favail=0 if bad == "inodes" else 5000,
        ),
    )
    if bad:
        with pytest.raises(ValueError):
            module._capacity()
    else:
        result = module._capacity()
        assert set(result) == {"producer", "release_root", "docker"}
        assert result["docker"] == {
            "path": "/var/lib/docker",
            "device": 24,
            "inode": 1257,
            "available_bytes": 6442450944,
            "available_inodes": 5000,
        }


@pytest.mark.parametrize(
    "bad", [None, "dropin", "reload", "fragment", "inactive", "stderr", "row", "hash"]
)
def test_unit_binds_actual_properties_and_exact_published_bytes(monkeypatch, bad):
    import hashlib
    import time
    from types import SimpleNamespace

    module = api()
    raw = b"independent published unit fixture\n"
    monkeypatch.setattr(module, "_UNITS", {"docker.service": hashlib.sha256(raw).hexdigest()})
    properties = {
        "ActiveState": "inactive" if bad == "inactive" else "active",
        "SubState": "running",
        "NeedDaemonReload": "yes" if bad == "reload" else "no",
        "DropInPaths": "/run/override.conf" if bad == "dropin" else "",
        "FragmentPath": "/etc/docker.service"
        if bad == "fragment"
        else "/usr/lib/systemd/system/docker.service",
        "MainPID": "950",
        "Requires": "docker.socket",
    }

    def capture(argv, **kwargs):
        assert argv[:4] == ("/usr/bin/systemctl", "show", "docker.service", "--no-pager")
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
        output = "\n".join(key + "=" + value for key, value in properties.items()).encode() + b"\n"
        return SimpleNamespace(
            stdout=output + (b"malformed\n" if bad == "row" else b""),
            stderr=b"error" if bad == "stderr" else b"",
        )

    monkeypatch.setattr(module, "_capture", capture)
    monkeypatch.setattr(module, "_canonical_directory", lambda path: (1, 1))
    monkeypatch.setattr(
        module, "_read_file", lambda *a: (b"changed unit" if bad == "hash" else raw, (1, 2))
    )
    if bad:
        with pytest.raises(ValueError):
            module._unit("docker.service", time.monotonic_ns() + 1_000_000_000)
    else:
        result = module._unit("docker.service", time.monotonic_ns() + 1_000_000_000)
        assert result["properties"]["MainPID"] == "950"
        assert result["fingerprint"] == (1, 2)


@pytest.mark.parametrize("bad", [None, "missing", "disappeared", "too_many"])
def test_listener_requires_live_matching_holder_descriptor(monkeypatch, bad):
    import time

    module = api()
    entries = [Path("/proc/950/fd/1"), Path("/proc/950/fd/2")]
    monkeypatch.setattr(
        Path, "iterdir", lambda path: iter([entries[0]] * 8193 if bad == "too_many" else entries)
    )

    def readlink(path):
        if str(path).endswith("/1"):
            raise FileNotFoundError
        return "socket:[999]" if bad in {"missing", "disappeared"} else "socket:[6522]"

    monkeypatch.setattr(module.os, "readlink", readlink)
    if bad:
        with pytest.raises(ValueError):
            module._listener_fds(950, 6522, time.monotonic_ns() + 1_000_000_000)
    else:
        module._listener_fds(950, 6522, time.monotonic_ns() + 1_000_000_000)


@pytest.mark.parametrize("bad", [None, "commit", "digest", "tree", "dirty", "module"])
def test_source_profile_requires_exact_whole_checkout_and_module_content(monkeypatch, bad):
    import hashlib
    import time
    from types import SimpleNamespace

    module = api()
    raw = b"reviewed producer fixture bytes\n"
    fixture_modules(monkeypatch, {"fixture.py": hashlib.sha256(raw).hexdigest()})
    monkeypatch.setattr(module, "_canonical_directory", lambda path: (1, 1))
    monkeypatch.setattr(
        module,
        "_capture_source",
        lambda path, **kw: SimpleNamespace(
            commit="0" * 40 if bad == "commit" else "479fca6ce789692d2a088b162fe6bcfeb2ad8336",
            digest="0" * 64
            if bad == "digest"
            else "a54a71ab93bbddb9b098678ba4fe638c12faefc0157ddc7cc3a7f7d1e120b674",
        ),
    )

    def native(path, argv, cap):
        assert (
            str(path)
            == "/opt/hybrid-stock-research/source/479fca6ce789692d2a088b162fe6bcfeb2ad8336"
        )
        if argv == ("rev-parse", "--verify", "HEAD^{tree}"):
            return (
                "0" * 40 if bad == "tree" else "98257c8083cc6395fde92c600b1683b783952955"
            ).encode() + b"\n"
        assert argv == ("status", "--porcelain=v1", "-z", "--untracked-files=all")
        return b" M changed.py\0" if bad == "dirty" else b""

    monkeypatch.setattr(module, "_native", native)
    monkeypatch.setattr(
        module, "_read_file", lambda *a: (b"changed" if bad == "module" else raw, (1, 2))
    )
    if bad:
        with pytest.raises(ValueError):
            module._source_profile(
                "479fca6ce789692d2a088b162fe6bcfeb2ad8336", time.monotonic_ns() + 1_000_000_000
            )
    else:
        module._source_profile(
            "479fca6ce789692d2a088b162fe6bcfeb2ad8336", time.monotonic_ns() + 1_000_000_000
        )


@pytest.mark.parametrize("changed_module", [False, True])
@pytest.mark.parametrize(
    "commit,tree,source_sha,other",
    [
        (
            "479fca6ce789692d2a088b162fe6bcfeb2ad8336",
            "98257c8083cc6395fde92c600b1683b783952955",
            "a54a71ab93bbddb9b098678ba4fe638c12faefc0157ddc7cc3a7f7d1e120b674",
            "bac162fd6eb6178516a212d30846fb1a055c90fb",
        ),
        (
            "bac162fd6eb6178516a212d30846fb1a055c90fb",
            "21953af2db3189b5a3a9c03c22b3e35baea29683",
            "829465b9fcdc5efd10f61ee18ba7eea342cc697f5c3323486283c0c943a56e29",
            "479fca6ce789692d2a088b162fe6bcfeb2ad8336",
        ),
    ],
)
def test_each_original_checkout_requires_its_own_complete_causal_files(
    monkeypatch, changed_module, commit, tree, source_sha, other
):
    import subprocess
    import time
    from types import SimpleNamespace

    module = api()
    root = Path("/opt/hybrid-stock-research/source") / commit
    monkeypatch.setattr(module, "_canonical_directory", lambda path: (1, 1))

    def capture(path, **kwargs):
        assert path == root
        return SimpleNamespace(commit=commit, digest=source_sha)

    def native(path, argv, cap):
        assert path == root
        if argv == ("rev-parse", "--verify", "HEAD^{tree}"):
            return (tree + "\n").encode()
        assert argv == ("status", "--porcelain=v1", "-z", "--untracked-files=all")
        return b""

    def read(path, *args):
        assert path.parent == root / "infra/hybrid"
        version = other if changed_module else commit
        raw = subprocess.check_output(
            ("/usr/bin/git", "show", version + ":infra/hybrid/" + path.name),
            cwd=Path(__file__).resolve().parents[2],
        )
        return raw, (1, 2)

    monkeypatch.setattr(module, "_capture_source", capture)
    monkeypatch.setattr(module, "_native", native)
    monkeypatch.setattr(module, "_read_file", read)
    if changed_module:
        with pytest.raises(ValueError):
            module._source_profile(commit, time.monotonic_ns() + 5_000_000_000)
    else:
        module._source_profile(commit, time.monotonic_ns() + 5_000_000_000)


@pytest.mark.parametrize("bad", [None, "hash", "link", "owner", "size", "target", "overread"])
def test_binary_hash_is_bound_to_named_running_single_link_file(monkeypatch, bad):
    import hashlib
    import time

    module = api()
    raw = b"ELF fixture\n"
    monkeypatch.setattr(module, "_BINARY_BYTES", len(raw))
    monkeypatch.setattr(module, "_BINARY_SHA", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(module, "_canonical_directory", lambda path: (1, 1))
    info = _stat_record(
        st_mode=0o100755,
        st_uid=1 if bad == "owner" else 0,
        st_gid=0,
        st_nlink=2 if bad == "link" else 1,
        st_size=len(raw) + (1 if bad == "size" else 0),
    )
    monkeypatch.setattr(Path, "lstat", lambda path: info)
    monkeypatch.setattr(Path, "stat", lambda path: info)
    monkeypatch.setattr(module.os, "fstat", lambda fd: info)
    monkeypatch.setattr(
        module.os,
        "readlink",
        lambda path: "/usr/bin/other" if bad == "target" else "/usr/bin/dockerd",
    )
    data = b"X" * len(raw) if bad == "hash" else raw + (b"X" if bad == "overread" else b"")
    closed = _proc_reads(monkeypatch, module, "/proc/950/exe", [data, b""])
    if bad:
        with pytest.raises(ValueError):
            module._binary(950, time.monotonic_ns() + 1_000_000_000)
    else:
        assert module._binary(950, time.monotonic_ns() + 1_000_000_000)[6] == len(raw)
        assert closed == [900001]


def test_descriptor_inventory_stops_at_first_over_limit_entry(monkeypatch):
    """An oversized procfs directory must deny before allocating/reading its tail."""
    import time

    module = api()

    def entries(path):
        for _ in range(8193):
            yield Path("/proc/950/fd/1")
        pytest.fail("Descriptor inventory consumed beyond its finite admission bound")

    monkeypatch.setattr(Path, "iterdir", entries)
    monkeypatch.setattr(module.os, "readlink", lambda path: pytest.fail("Oversized inventory used"))
    with pytest.raises(ValueError):
        module._listener_fds(950, 6522, time.monotonic_ns() + 1_000_000_000)


@pytest.mark.parametrize("bad", ["euid", "real_uid", "real_gid", None])
def test_root_guard_checks_all_actual_saved_ids(monkeypatch, bad):
    module = api()
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.os, "geteuid", lambda: 10001 if bad == "euid" else 0)
    monkeypatch.setattr(
        module.os,
        "getresuid",
        lambda: (10001, 0, 0) if bad == "real_uid" else (0, 0, 0),
        raising=False,
    )
    monkeypatch.setattr(
        module.os,
        "getresgid",
        lambda: (0, 10001, 0) if bad == "real_gid" else (0, 0, 0),
        raising=False,
    )
    if bad:
        with pytest.raises(ValueError):
            module._root()
    else:
        module._root()


def test_get_denies_when_kernel_peer_credentials_are_unavailable(monkeypatch):
    import time
    from contextlib import nullcontext

    module = api()
    monkeypatch.setattr(module, "_socket_binding", lambda: (24, 1257, 0o140660, 0, 112, 1, 0, 1, 1))
    monkeypatch.setattr(module.socket, "SO_PEERCRED", None, raising=False)
    monkeypatch.setattr(module, "_connection", lambda deadline: nullcontext())
    with pytest.raises(ValueError):
        module._get("/version", time.monotonic_ns() + 1_000_000_000)


def test_different_original_source_is_denied_before_checkout_io(monkeypatch):
    import time

    module = api()
    monkeypatch.setattr(
        module, "_capture_source", lambda *a, **kw: pytest.fail("Unreviewed source captured")
    )
    with pytest.raises(ValueError):
        module._source_profile("0" * 40, time.monotonic_ns() + 1_000_000_000)


def test_read_file_denies_identical_byte_path_replacement(tmp_path, monkeypatch):
    """Matching content cannot substitute a new inode for the held file."""
    import time

    module = api()
    path = tmp_path / "profile"
    raw = b"reviewed fixture bytes"
    path.write_bytes(raw)
    path.chmod(0o644)
    real_read = os.read
    replaced = False

    def reading(fd, size):
        nonlocal replaced
        data = real_read(fd, size)
        if data and not replaced:
            replaced = True
            path.rename(tmp_path / "old-profile")
            path.write_bytes(raw)
            path.chmod(0o644)
        return data

    monkeypatch.setattr(module.os, "read", reading)
    with pytest.raises(ValueError):
        module._read_file(
            path, 64, 0o644, time.monotonic_ns() + 1_000_000_000, uid=os.geteuid(), gid=os.getegid()
        )
    assert path.read_bytes() == raw


def test_canonical_directory_checks_nonleaf_ancestor_ownership(monkeypatch):
    module = api()
    monkeypatch.setattr(Path, "resolve", lambda path, strict: path)
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda path: _stat_record(
            st_mode=0o40755, st_uid=10001 if str(path) == "/var/lib" else 0, st_gid=0
        ),
    )
    with pytest.raises(ValueError):
        module._canonical_directory(Path("/var/lib/docker"))


@pytest.mark.parametrize(
    "raw",
    [
        b"malformed",
        b"1 (dockerd) S 0\n",
        b"950 (dockerd) S 0\n",
        b"950 (dockerd) " + b" ".join([b"S", *([b"0"] * 18), b"-1"]),
        b"x" * 8193,
    ],
)
def test_process_start_denies_malformed_or_over_limit_kernel_records(monkeypatch, raw):
    import time

    module = api()
    closed = _proc_reads(monkeypatch, module, "/proc/950/stat", [raw, b""])
    with pytest.raises(ValueError):
        module._process_start(950, time.monotonic_ns() + 1_000_000_000)
    assert closed == [900001]


def test_process_tick_upper_bound_rejects_overflow():
    with pytest.raises(ValueError):
        api()._start_upper(2**63 - 2, 1)


def test_source_profile_denies_untrusted_inner_module_ancestor(monkeypatch):
    """Clean Git/content cannot qualify files reachable through an untrusted directory."""
    import hashlib
    import time
    from types import SimpleNamespace

    module = api()
    raw = b"reviewed producer fixture bytes\n"
    root = "/opt/hybrid-stock-research/source/479fca6ce789692d2a088b162fe6bcfeb2ad8336"
    fixture_modules(monkeypatch, {"fixture.py": hashlib.sha256(raw).hexdigest()})
    monkeypatch.setattr(Path, "resolve", lambda path, strict: path)
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda path: _stat_record(
            st_mode=0o40755, st_uid=10001 if str(path) == root + "/infra" else 0, st_gid=0
        ),
    )
    monkeypatch.setattr(
        Path, "stat", lambda path: _stat_record(st_mode=0o40755, st_uid=0, st_gid=0)
    )
    monkeypatch.setattr(
        module,
        "_capture_source",
        lambda *a, **kw: SimpleNamespace(
            commit="479fca6ce789692d2a088b162fe6bcfeb2ad8336",
            digest="a54a71ab93bbddb9b098678ba4fe638c12faefc0157ddc7cc3a7f7d1e120b674",
        ),
    )
    monkeypatch.setattr(
        module,
        "_native",
        lambda path, argv, cap: (
            b"98257c8083cc6395fde92c600b1683b783952955\n" if argv[0] == "rev-parse" else b""
        ),
    )
    monkeypatch.setattr(module, "_read_file", lambda *a: (raw, (1, 2)))
    with pytest.raises(ValueError):
        module._source_profile(
            "479fca6ce789692d2a088b162fe6bcfeb2ad8336", time.monotonic_ns() + 1_000_000_000
        )


@pytest.fixture
def fixed_get_host(monkeypatch):
    """Fixed socket spellings and an inherited-root transport, without host access."""
    import struct
    import time

    module = api()
    state = {
        "alias": "/run/docker.sock",
        "alias_inode": 1257,
        "canonical_inode": 1257,
        "alias_mode": 0o140660,
        "change_after_send": False,
    }
    canonical = Path("/run/docker.sock")
    alias = Path("/var/run/docker.sock")
    monkeypatch.setattr(module.socket, "SO_PEERCRED", 17, raising=False)
    monkeypatch.setattr(
        Path, "resolve", lambda path, strict=True: Path(state["alias"]) if path == alias else path
    )

    def metadata(path):
        if path in {canonical, alias}:
            return _stat_record(
                st_ino=state["alias_inode"] if path == alias else state["canonical_inode"],
                st_mode=state["alias_mode"] if path == alias else 0o140660,
            )
        return _stat_record(st_mode=0o40755, st_uid=0, st_gid=0)

    monkeypatch.setattr(Path, "lstat", metadata)
    monkeypatch.setattr(Path, "stat", lambda path, **kw: metadata(path))

    class Peer:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def getsockopt(self, level, option, size):
            assert (level, option, size) == (module.socket.SOL_SOCKET, 17, 12)
            return struct.pack("3i", 1, 0, 0)

        def settimeout(self, seconds):
            assert seconds > 0

        def sendall(self, raw):
            assert raw in {
                b"GET /version HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n",
                b"GET /v1.52/info HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            }
            if state["change_after_send"]:
                state["alias_inode"] = state["canonical_inode"] = 9911

    monkeypatch.setattr(module, "_connection", lambda deadline: Peer())
    monkeypatch.setattr(module, "_headers", lambda *a: ({}, b'{"DockerRootDir":"/var/lib/docker"}'))
    monkeypatch.setattr(module, "_body", lambda peer, deadline, headers, initial: initial)
    monkeypatch.setattr(module, "_receive", lambda *a: b"")
    return (
        module,
        state,
        lambda path="/version": module._get(path, time.monotonic_ns() + 1_000_000_000),
    )


@pytest.mark.parametrize("bad", ["alias_target", "alias_inode", "unsafe_alias"])
def test_get_denies_socket_alias_that_does_not_bind_verified_listener(fixed_get_host, bad):
    """PID1 credentials cannot bless a different pathname/socket than the listener."""
    _, state, get = fixed_get_host
    if bad == "alias_target":
        state["alias"] = "/tmp/other.sock"
    elif bad == "alias_inode":
        state["alias_inode"] = 9911
    else:
        state["alias_mode"] = 0o140666
    with pytest.raises(ValueError):
        get()


def test_get_denies_socket_replacement_between_dispatch_and_readback(fixed_get_host):
    """Both names resolving together to a new socket still break the held GET proof."""
    _, state, get = fixed_get_host
    state["change_after_send"] = True
    with pytest.raises(ValueError):
        get()


def test_capacity_get_uses_same_socket_alias_binding(fixed_get_host, monkeypatch):
    module, state, _ = fixed_get_host
    state["alias"] = "/tmp/other.sock"
    monkeypatch.setattr(module, "_root", lambda: None)
    capacity = {
        name: {
            "path": str(path),
            "device": 24,
            "inode": 1257,
            "available_bytes": 6 * 1024**3,
            "available_inodes": 5000,
        }
        for name, path in module._ROOTS.items()
    }
    monkeypatch.setattr(module, "_capacity", lambda: capacity)
    with pytest.raises(ValueError):
        module.check_failed_capacity(capacity)


def test_get_accepts_shared_safe_socket_alias_binding(fixed_get_host):
    _, _, get = fixed_get_host
    assert get() == {"DockerRootDir": "/var/lib/docker"}
