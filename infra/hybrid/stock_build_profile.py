"""Fixed read-only incident profile; observations alone confer no write authority.

Only the reviewed Ubuntu systemd-activated legacy backend/source is qualified.
Capacity refresh is separate so historical facts survive a genuine later boot.
"""

from __future__ import annotations

import hashlib
import os
import socket
import stat
import struct
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from infra.hybrid.stock_attempts import _check_clock, _clock
from infra.hybrid.stock_container import _object, verify_engine_version
from infra.hybrid.stock_engine import (
    _body,
    _connection,
    _deadline,
    _headers,
    _receive,
    _remaining,
)
from infra.hybrid.stock_process import _capture
from infra.hybrid.stock_release import _close_all, _fingerprint
from infra.hybrid.stock_release_producer import _require, _sanitized
from infra.hybrid.stock_source_prepare import _capture_source, _native

_COMMIT = "479fca6ce789692d2a088b162fe6bcfeb2ad8336"
_TREE = "98257c8083cc6395fde92c600b1683b783952955"
_SOURCE = "a54a71ab93bbddb9b098678ba4fe638c12faefc0157ddc7cc3a7f7d1e120b674"
_ENGINE_SHA = "657cc3c9b56b63ae49d7e175d83afa6eabdb68637ad552e26e015f43f0733d3a"
_BINARY_SHA = "237b0603cc24496c74433aeb32d70a16931ae7e015f183b8f3c7c7db83c72a5f"
_BINARY_BYTES = 83879288
_UNITS = {
    "docker.service": "2e35580df3c26dc898440289f4abad013fbd62722f00c93f994dba002e468873",
    "docker.socket": "96c04477e86bd6f724560f3a78b7c0b00b539d5254a251d247641029fc7ad92e",
}
_MODULES = {
    "stock_build_engine.py": "9ad12baf09172fbd485b08b2ec1df3ca76119ecf34ec452759f3ba5782e12064",
    "stock_compose_render.py": "fbaba8973249e0b9afecab75c6c5a02868a68821e41639e1a51d11af00cc6d13",
    "stock_probe_controller.py": "40929e4f45c695b0429373fea2e77e32ba1d4ec15c9e2b0fefed3db144b5a3f8",
    "stock_producer.py": "8729100585927dd9588bd02fa6ef488e08202e8c5f4089987a7f16c7e85576dc",
    "stock_release_producer.py": "2ff1bee7bc22173a61f27c8f4ae14254bd9723bed417a14e7efaf9e53746d6fa",
    "stock_release_publication.py": (
        "5a1dd309a61226df3dfae6403b19653a96147bf2496076b527e99144f409d1e7"
    ),
    "stock_source_prepare.py": "10d3fba54190e9861eac997bf7990a17f78194dc627482254a1379a7b5f8803c",
}
_ROOTS = {
    "producer": Path("/var/lib/hybrid-stock-producer"),
    "release_root": Path("/opt/hybrid-stock-research/releases"),
    "docker": Path("/var/lib/docker"),
}
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def _root() -> None:
    _require(sys.platform == "linux" and os.geteuid() == 0)
    _require(
        getattr(os, "getresuid", lambda: None)()
        == getattr(os, "getresgid", lambda: None)()
        == (0, 0, 0)
    )


def _budget(cap: int) -> None:
    _require(type(cap) is int and 0 < time.monotonic_ns() < cap <= 2**63 - 1)


def _start_upper(ticks: int, hz: int) -> int:
    _require(type(ticks) is int and 0 <= ticks < 2**63 - 1)
    _require(type(hz) is int and 0 < hz <= 1_000_000_000)
    result = ((ticks + 1) * 1_000_000_000 + hz - 1) // hz
    _require(result <= 2**63 - 1)
    return result


def _read_file(
    path: Path, maximum: int, mode: int, cap: int, *, uid: int = 0, gid: int = 0
) -> tuple[bytes, tuple[int, ...]]:
    with _sanitized():
        _budget(cap)
        before = _fingerprint(path.lstat())
        fd = os.open(path, _READ)
        try:
            info = os.fstat(fd)
            _require(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == uid
                and info.st_gid == gid
                and stat.S_IMODE(info.st_mode) == mode
                and info.st_nlink == 1
                and 0 < info.st_size <= maximum
                and _fingerprint(info) == before
            )
            raw = bytearray()
            while len(raw) <= maximum:
                _budget(cap)
                part = os.read(fd, min(65536, maximum + 1 - len(raw)))
                if not part:
                    break
                raw.extend(part)
            _require(len(raw) == info.st_size)
            _require(before == _fingerprint(os.fstat(fd)) == _fingerprint(path.lstat()))
        finally:
            _close_all((fd,))
        _budget(cap)
        return bytes(raw), before


def _get(path: str, cap: int) -> dict[str, Any]:
    with _sanitized():
        _require(path in {"/version", "/v1.52/info"})
        _budget(cap)
        socket_stamp = _socket_binding()
        deadline = _deadline(cap)
        with _connection(deadline) as peer:
            option = getattr(socket, "SO_PEERCRED", None)
            if type(option) is not int:
                raise ValueError("stock_producer_unavailable")
            pid, uid, gid = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, option, 12))
            _require(pid == 1 and uid == gid == 0)
            peer.settimeout(_remaining(deadline))
            peer.sendall(
                (
                    "GET " + path + " HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n"
                ).encode("ascii")
            )
            headers, initial = _headers(peer, deadline)
            raw = _body(peer, deadline, headers, initial)
            _require(not _receive(peer, deadline, 1))
            _remaining(deadline)
        _budget(cap)
        _require(_socket_binding() == socket_stamp)
        return _object(raw)


def _canonical_directory(path: Path) -> tuple[int, int]:
    _require(path.is_absolute() and path.resolve(strict=True) == path)
    for parent in (path, *path.parents):
        info = parent.lstat()
        _require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == info.st_gid == 0
            and info.st_mode & 0o022 == 0
        )
    info = path.stat()
    return info.st_dev, info.st_ino


def _capacity() -> dict[str, Any]:
    result = {}
    for name, path in _ROOTS.items():
        device, inode = _canonical_directory(path)
        space = os.statvfs(path)
        available = space.f_bavail * space.f_frsize
        _require(available >= 5 * 1024**3 and space.f_favail >= 4096)
        _require(_canonical_directory(path) == (device, inode))
        result[name] = {
            "path": str(path),
            "device": device,
            "inode": inode,
            "available_bytes": available,
            "available_inodes": space.f_favail,
        }
    return result


def check_failed_capacity(capacity: dict[str, Any]) -> None:
    """Fresh current data-root/headroom, without the original boot or processes."""
    with _sanitized():
        _root()
        cap = time.monotonic_ns() + 5_000_000_000
        _require(_get("/v1.52/info", cap).get("DockerRootDir") == "/var/lib/docker")
        _require(type(capacity) is dict and set(capacity) == set(_ROOTS))
        fresh = _capacity()
        for name, value in fresh.items():
            old = capacity[name]
            _require(type(old) is dict and set(old) == set(value))
            _require(all(type(old[key]) is type(item) for key, item in value.items()))
            _require(all(old[key] == value[key] for key in ("path", "device", "inode")))
            _require(value["available_bytes"] >= 5 * 1024**3 and value["available_inodes"] >= 4096)
        _budget(cap)


def _unit(name: str, cap: int) -> dict[str, Any]:
    _require(name in _UNITS)
    common = ("ActiveState", "SubState", "NeedDaemonReload", "DropInPaths", "FragmentPath")
    keys = (
        *common,
        *(("MainPID", "Requires") if name == "docker.service" else ("Listen", "Triggers")),
    )
    result = _capture(
        ("/usr/bin/systemctl", "show", name, "--no-pager", "--property=" + ",".join(keys)),
        cwd=Path("/"),
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        limit=8192,
        deadline=min(cap / 1_000_000_000, time.monotonic() + 5),
    )
    _require(result.stderr == b"")
    lines = [line.split("=", 1) for line in result.stdout.decode("ascii").splitlines()]
    _require(all(len(line) == 2 for line in lines) and len(lines) == len(keys))
    properties = dict(lines)
    _require(set(properties) == set(keys))
    _require(
        properties["ActiveState"] == "active"
        and properties["SubState"] == "running"
        and properties["NeedDaemonReload"] == "no"
        and properties["DropInPaths"] == ""
        and properties["FragmentPath"] == "/usr/lib/systemd/system/" + name
    )
    path = Path(properties["FragmentPath"])
    _canonical_directory(path.parent)
    raw, stamp = _read_file(path, 8192, 0o644, cap)
    _require(hashlib.sha256(raw).hexdigest() == _UNITS[name])
    return {"properties": properties, "fingerprint": stamp, "sha256": _UNITS[name]}


def _listener_fds(pid: int, inode: int, cap: int) -> None:
    directory = Path("/proc") / str(pid) / "fd"
    names: list[Path] = []
    for path in directory.iterdir():
        _budget(cap)
        _require(len(names) < 8192)
        names.append(path)
    found = False
    for path in names:
        _budget(cap)
        try:
            found |= os.readlink(path) == "socket:[" + str(inode) + "]"
        except FileNotFoundError:
            continue
    _require(found)


def _socket_binding() -> tuple[int, ...]:
    """Join the actual transport alias to the one qualified kernel listener path."""
    path = Path("/run/docker.sock")
    alias = Path("/var/run/docker.sock")
    _canonical_directory(path.parent)
    _require(alias.resolve(strict=True) == path)
    info = path.lstat()
    stamp = _fingerprint(info)
    _require(
        stat.S_ISSOCK(info.st_mode)
        and info.st_uid == 0
        and info.st_mode & 0o007 == 0
        and info.st_nlink == 1
    )
    _require(_fingerprint(alias.lstat()) == stamp == _fingerprint(path.lstat()))
    _require(alias.resolve(strict=True) == path)
    return stamp


def _proc_read(path: Path, maximum: int, cap: int) -> bytes:
    """Bounded procfs read through actual EOF, including legal short reads."""
    fd = os.open(path, _READ)
    try:
        raw = bytearray()
        while len(raw) <= maximum:
            _budget(cap)
            part = os.read(fd, min(65536, maximum + 1 - len(raw)))
            if not part:
                break
            raw.extend(part)
        _require(0 < len(raw) <= maximum)
        return bytes(raw)
    finally:
        _close_all((fd,))


def _listener(pid: int, cap: int) -> tuple[int, tuple[int, ...]]:
    stamp = _socket_binding()
    # procfs files report size0; bounded reads cannot use regular-file size rules.
    raw = _proc_read(Path("/proc") / str(pid) / "net/unix", 1_048_576, cap)
    rows = [
        line.split()
        for line in raw.decode("ascii").splitlines()[1:]
        if line.split()[-1:] == ["/run/docker.sock"]
    ]
    _require(len(rows) == 1 and len(rows[0]) == 8)
    row = rows[0]
    _require(int(row[3], 16) & 0x10000 != 0 and row[4] == "0001" and row[5] == "01")
    inode = int(row[6])
    _require(inode > 0)
    _listener_fds(1, inode, cap)
    _listener_fds(pid, inode, cap)
    _require(_socket_binding() == stamp)
    return inode, stamp


def _process_start(pid: int, cap: int) -> int:
    raw = _proc_read(Path("/proc") / str(pid) / "stat", 8192, cap)
    _budget(cap)
    end = raw.rfind(b") ")
    _require(end > 0 and raw.startswith((str(pid) + " (").encode()))
    fields = raw[end + 2 :].split()
    _require(len(fields) > 19 and fields[19].isdigit())
    return int(fields[19])


def _binary(pid: int, cap: int) -> tuple[int, ...]:
    executable = Path("/proc") / str(pid) / "exe"
    path = Path("/usr/bin/dockerd")
    _canonical_directory(path.parent)
    _require(os.readlink(executable) == str(path))
    info = path.lstat()
    stamp = _fingerprint(info)
    _require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == info.st_gid == 0
        and stat.S_IMODE(info.st_mode) == 0o755
        and info.st_nlink == 1
        and info.st_size == _BINARY_BYTES
        and _fingerprint(executable.stat()) == stamp
    )
    fd = os.open(executable, os.O_RDONLY | os.O_CLOEXEC)
    try:
        _require(_fingerprint(os.fstat(fd)) == stamp)
        digest = hashlib.sha256()
        size = 0
        while size <= _BINARY_BYTES:
            _budget(cap)
            raw = os.read(fd, min(65536, _BINARY_BYTES + 1 - size))
            if not raw:
                break
            digest.update(raw)
            size += len(raw)
        _require(size == _BINARY_BYTES and digest.hexdigest() == _BINARY_SHA)
        _require(
            _fingerprint(os.fstat(fd))
            == stamp
            == _fingerprint(path.lstat())
            == _fingerprint(executable.stat())
            and os.readlink(executable) == str(path)
        )
    finally:
        _close_all((fd,))
    return stamp


def _source_profile(commit: str, cap: int) -> None:
    _require(type(commit) is str and commit == _COMMIT)
    path = Path("/opt/hybrid-stock-research/source") / _COMMIT
    _canonical_directory(path)
    source = _capture_source(path, deadline=cap / 1_000_000_000)
    _require(source.commit == _COMMIT and source.digest == _SOURCE)
    _require(
        _native(path, ("rev-parse", "--verify", "HEAD^{tree}"), cap / 1_000_000_000)
        == (_TREE + "\n").encode()
    )
    _canonical_directory(path / "infra/hybrid")
    for name, expected in _MODULES.items():
        raw, _ = _read_file(path / "infra/hybrid" / name, 1_048_576, 0o644, cap)
        _require(hashlib.sha256(raw).hexdigest() == expected)
    _require(
        _native(
            path, ("status", "--porcelain=v1", "-z", "--untracked-files=all"), cap / 1_000_000_000
        )
        == b""
    )


def observe_build_profile(
    source_commit: str,
    original_engine: bytes,
    original_origin: dict[str, Any],
    *,
    not_after_ns: int,
) -> dict[str, Any]:
    """Fresh bounded fixed observation, never a caller-supplied native authority."""
    with _sanitized():
        _root()
        _budget(not_after_ns)
        _require(socket.if_nameindex() == [(1, "lo")])
        _require(os.readlink("/proc/self/ns/net") != os.readlink("/proc/1/ns/net"))
        _check_clock(original_origin)
        _require(
            type(original_origin) is dict
            and set(original_origin) == {"boot_id", "utc", "monotonic_ns"}
        )
        started = _clock()
        _require(started["boot_id"] == original_origin["boot_id"])
        _require(
            type(original_engine) is bytes
            and hashlib.sha256(original_engine).hexdigest() == _ENGINE_SHA
        )
        _source_profile(source_commit, not_after_ns)
        common = _unit("docker.service", not_after_ns)
        socket_unit = _unit("docker.socket", not_after_ns)
        properties = common["properties"]
        _require(properties["MainPID"].isdigit())
        pid = int(properties["MainPID"])
        _require(pid > 1 and "docker.socket" in properties["Requires"].split())
        _require(
            socket_unit["properties"]["Listen"] == "/run/docker.sock (Stream)"
            and socket_unit["properties"]["Triggers"] == "docker.service"
        )
        inode, socket_stamp = _listener(pid, not_after_ns)
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        delta = datetime.fromisoformat(original_origin["utc"]) - epoch
        origin_ns = (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000
        _require(socket_stamp[8] < origin_ns)
        ticks = _process_start(pid, not_after_ns)
        upper = _start_upper(ticks, os.sysconf("SC_CLK_TCK"))
        _require(upper < original_origin["monotonic_ns"])
        binary_stamp = _binary(pid, not_after_ns)
        version = _get("/version", not_after_ns)
        from infra.hybrid.stock_attempts import _canonical

        verified = verify_engine_version(_canonical(version))
        _require(
            version.get("Version") == "29.1.3"
            and version.get("GitCommit") == "29.1.3-0ubuntu3~24.04.2"
            and verified.architecture == "amd64"
        )
        _require(_get("/v1.52/info", not_after_ns).get("DockerRootDir") == "/var/lib/docker")
        capacity = _capacity()
        _source_profile(source_commit, not_after_ns)
        _require(
            _unit("docker.service", not_after_ns) == common
            and _unit("docker.socket", not_after_ns) == socket_unit
            and _listener(pid, not_after_ns) == (inode, socket_stamp)
            and _process_start(pid, not_after_ns) == ticks
        )
        _require(
            _fingerprint(Path("/usr/bin/dockerd").lstat())
            == binary_stamp
            == _fingerprint((Path("/proc") / str(pid) / "exe").stat())
        )
        observed = _clock()
        _require(observed["boot_id"] == started["boot_id"])
        _budget(not_after_ns)
        return {
            "daemon_profile": {
                "profile_id": "ubuntu-docker-legacy-q-29.1.3-v1",
                "binary_sha256": _BINARY_SHA,
                "binary_bytes": _BINARY_BYTES,
                "peer_pid": 1,
                "daemon_pid": pid,
                "daemon_start_boottime_upper_ns": upper,
                "boot_id": observed["boot_id"],
                "observed_clock": observed,
                "source_profile_id": "stock-producer-causal-479-v1",
                "source_tree": _TREE,
                "docker_root": "/var/lib/docker",
                "socket_activation": {
                    "mode": "systemd_socket_activation",
                    "service_unit_sha256": _UNITS["docker.service"],
                    "socket_unit_sha256": _UNITS["docker.socket"],
                    "listener_inode": inode,
                    "socket_file_fingerprint": list(socket_stamp),
                },
            },
            "capacity": capacity,
        }
