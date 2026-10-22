"""Bounded host observations and a private local incident outbox; no remediation or delivery."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MAX_BYTES = 262144
MAX_RECORDS = 256
MAX_INTEGER = 2**63 - 1
CONTAINER = "hybrid-paper-hybrid-paper-1"
CONDITIONS = {
    "container_inspection",
    "image_identity",
    "container_state",
    "container_health",
    "unexpected_restart",
    "http_health",
    "readiness_denial",
    "api_authentication",
    "disk_space",
    "inode_space",
    "memory_available",
    "backup_receipt",
}
DOCKER_FORMAT = (
    '{"Image":{{json .Image}},"Running":{{json .State.Running}},'
    '"Status":{{json .State.Status}},"OOMKilled":{{json .State.OOMKilled}},'
    '"RestartCount":{{json .RestartCount}},"StartedAt":{{json .State.StartedAt}},'
    '"Health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}}'
)


class UnsafeState(ValueError):
    """Operational evidence cannot be safely read or durably updated."""


class ObservationError(ValueError):
    """An external observation was unavailable, malformed or out of bounds."""


def _integer(value, *, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_INTEGER:
        raise UnsafeState("invalid integer")
    return value


def _hash(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise UnsafeState("invalid hash")
    return value


def _image(value):
    if type(value) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise UnsafeState("invalid image identity")
    return value


def _timestamp(value):
    if type(value) is not str or len(value) > 40:
        raise UnsafeState("invalid timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise UnsafeState("invalid timestamp") from exc
    return parsed


def _canonical(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise UnsafeState("duplicate JSON key")
            value[key] = item
        return value

    def invalid_constant(value):
        raise UnsafeState("invalid JSON constant")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise UnsafeState("invalid JSON") from exc


@contextmanager
def _directory(path, trusted_uid):
    """Walk using directory descriptors; reject every symlink, including ancestors."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise UnsafeState("absolute private path required")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in path.parts[1:]:
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        metadata = os.fstat(descriptor)
        if metadata.st_uid != trusted_uid or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise UnsafeState("directory must be privately owned")
        yield descriptor
    except OSError as exc:
        raise UnsafeState("private directory unavailable") from exc
    finally:
        os.close(descriptor)


def _file_metadata(descriptor, trusted_uid):
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != trusted_uid
        or metadata.st_mode & 0o7077
        or metadata.st_nlink != 1
    ):
        raise UnsafeState("file must be a private owned regular file")
    return metadata


def _read_at(directory, name, trusted_uid, limit):
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
        dir_fd=directory,
    )
    with os.fdopen(descriptor, "rb") as source:
        metadata = _file_metadata(source.fileno(), trusted_uid)
        if not 0 < metadata.st_size <= limit:
            raise UnsafeState("file size invalid")
        raw = source.read(limit + 1)
        if len(raw) != metadata.st_size or len(raw) > limit:
            raise UnsafeState("file changed during bounded read")
        return raw


def _read_private(path, trusted_uid, limit=16384):
    path = Path(path)
    with _directory(path.parent, trusted_uid) as directory:
        return _read_at(directory, path.name, trusted_uid, limit)


@dataclass(frozen=True)
class Manifest:
    release_id: str
    expected_image: str
    deployment_config_hash: str
    compose_sha256: str
    container_name: str
    backup_receipt: Path
    backup_max_age_seconds: int
    minimum_free_bytes: int
    minimum_free_inodes: int
    minimum_available_memory_bytes: int


def load_manifest(path, *, trusted_uid=0):
    try:
        value = _json(_read_private(path, trusted_uid))
        keys = set(Manifest.__dataclass_fields__) | {"schema_version"}
        if (
            type(value) is not dict
            or set(value) != keys
            or type(value["schema_version"]) is not int
        ):
            raise UnsafeState("manifest shape invalid")
        if value.pop("schema_version") != 1 or value["container_name"] != CONTAINER:
            raise UnsafeState("manifest identity invalid")
        for name in ("release_id", "deployment_config_hash", "compose_sha256"):
            _hash(value[name])
        _image(value["expected_image"])
        for name in (
            "backup_max_age_seconds",
            "minimum_free_bytes",
            "minimum_free_inodes",
            "minimum_available_memory_bytes",
        ):
            _integer(value[name], minimum=1)
        receipt = value["backup_receipt"]
        if type(receipt) is not str or len(receipt) > 4096:
            raise UnsafeState("receipt path invalid")
        receipt = Path(receipt)
        if not receipt.is_absolute() or ".." in receipt.parts:
            raise UnsafeState("receipt path invalid")
        return Manifest(**(value | {"backup_receipt": receipt}))
    except (OSError, TypeError, KeyError) as exc:
        raise UnsafeState("manifest unavailable") from exc


def bounded_command(command, *, timeout=5, limit=8192):
    """Bound process runtime and stdout; never collect stderr or ambient Docker credentials."""
    # The only production caller supplies fixed Docker argv; shell execution is never enabled.
    process = subprocess.Popen(  # nosec B603
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/nonexistent",
            "LANG": "C",
            "DOCKER_CONFIG": "/nonexistent",
            "DOCKER_HOST": "unix:///var/run/docker.sock",
        },
    )
    deadline = time.monotonic() + timeout
    output = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ObservationError("command timed out")
                chunk = os.read(process.stdout.fileno(), min(4096, limit + 1 - len(output)))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > limit:
                    raise ObservationError("command output exceeded bound")
        if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
            raise ObservationError("command failed")
        return bytes(output)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ObservationError("command unavailable") from exc
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def inspect_container(name):
    if name != CONTAINER:
        raise ObservationError("unexpected container")
    return _json(bounded_command(["/usr/bin/docker", "inspect", "--format", DOCKER_FORMAT, name]))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@contextmanager
def _deadline(seconds):
    def expired(signum, frame):
        raise ObservationError("HTTP total deadline exceeded")

    previous = signal.signal(signal.SIGALRM, expired)
    timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *timer)
        signal.signal(signal.SIGALRM, previous)


def request(path, *, timeout=3):
    if path not in {"/healthz", "/readyz", "/api/hybrid/snapshot"}:
        raise ObservationError("unexpected endpoint")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with _deadline(timeout):
        try:
            response = opener.open("http://127.0.0.1:8081" + path, timeout=timeout)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read(4097)
            if len(raw) > 4096:
                raise ObservationError("response exceeded bound")
            return response.code, raw


def available_memory():
    with open("/proc/meminfo", encoding="ascii") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ObservationError("memory observation exceeded bound")
    match = re.search(r"^MemAvailable:\s+([0-9]+) kB$", raw, re.MULTILINE)
    if match is None:
        raise ObservationError("memory observation unavailable")
    return _integer(int(match[1]) * 1024)


def free_disk(path):
    value = os.statvfs(path)
    return value.f_bavail * value.f_frsize, value.f_favail


def backup_current(manifest, now, trusted_uid):
    value = _json(_read_private(manifest.backup_receipt, trusted_uid))
    expected = {
        "schema_version",
        "completed_at",
        "release_id",
        "image_digest",
        "deployment_config_hash",
        "compose_sha256",
        "archive_sha256",
        "archive_name",
        "archive_bytes",
        "encryption",
        "structural_check",
        "application_check",
    }
    if type(value) is not dict or set(value) != expected:
        raise UnsafeState("backup receipt shape invalid")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise UnsafeState("backup receipt version invalid")
    for field, actual in (
        ("release_id", manifest.release_id),
        ("image_digest", manifest.expected_image),
        ("deployment_config_hash", manifest.deployment_config_hash),
        ("compose_sha256", manifest.compose_sha256),
        ("encryption", "age-v1"),
    ):
        if value[field] != actual:
            raise UnsafeState("backup receipt identity invalid")
    _hash(value["archive_sha256"])
    if value["structural_check"] is not True or value["application_check"] is not True:
        raise UnsafeState("backup checks unsuccessful")
    age = (now - _timestamp(value["completed_at"])).total_seconds()
    if age < 0 or age > manifest.backup_max_age_seconds:
        raise UnsafeState("backup receipt is not current")
    name = value["archive_name"]
    if (
        type(name) is not str
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,180}\.db\.age", name) is None
    ):
        raise UnsafeState("backup archive name invalid")
    size = _integer(value["archive_bytes"], minimum=1)
    with _directory(manifest.backup_receipt.parent, trusted_uid) as directory:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=directory,
        )
        try:
            if _file_metadata(descriptor, trusted_uid).st_size != size:
                raise UnsafeState("backup archive size invalid")
        finally:
            os.close(descriptor)
    return True


def _container(value, now):
    fields = {"Image", "Running", "Status", "OOMKilled", "RestartCount", "StartedAt", "Health"}
    if type(value) is not dict or set(value) != fields:
        raise ObservationError("container observation malformed")
    _image(value["Image"])
    _integer(value["RestartCount"])
    if type(value["Running"]) is not bool or type(value["OOMKilled"]) is not bool:
        raise ObservationError("container observation malformed")
    if value["Status"] not in {
        "created",
        "restarting",
        "running",
        "removing",
        "paused",
        "exited",
        "dead",
    }:
        raise ObservationError("container state unknown")
    if value["Health"] not in {None, "starting", "healthy", "unhealthy"}:
        raise ObservationError("container health unknown")
    if _timestamp(value["StartedAt"]) > now:
        raise ObservationError("container start is in future")
    return value


def _collect(manifest, spool, previous, now, inspector, requester, memory_reader, disk_reader, uid):
    checks = dict.fromkeys(CONDITIONS)
    runtime = previous["runtime"]
    try:
        value = _container(inspector(manifest.container_name), now)
        checks["container_inspection"] = True
        checks["image_identity"] = value["Image"] == manifest.expected_image
        checks["container_state"] = (
            value["Running"] and value["Status"] == "running" and not value["OOMKilled"]
        )
        checks["container_health"] = value["Health"] == "healthy"
        runtime = {
            "release_id": manifest.release_id,
            "started_at": value["StartedAt"],
            "restart_count": value["RestartCount"],
        }
        prior = previous["runtime"]
        checks["unexpected_restart"] = not (
            prior and prior["release_id"] == manifest.release_id and runtime != prior
        )
    except (OSError, ValueError, TypeError, KeyError):
        checks["container_inspection"] = False
    for code, path, expected in (
        ("http_health", "/healthz", 200),
        ("readiness_denial", "/readyz", 503),
        ("api_authentication", "/api/hybrid/snapshot", 401),
    ):
        try:
            status, raw = requester(path)
            valid = type(status) is int and status == expected and len(raw) <= 4096
            if code == "http_health":
                health = _json(raw)
                valid = (
                    valid
                    and type(health) is dict
                    and health.get("healthy") is True
                    and health.get("live_enabled") is False
                )
            checks[code] = valid
        except (OSError, ValueError, TypeError):
            checks[code] = False
    try:
        disks = [disk_reader(spool), disk_reader(manifest.backup_receipt.parent)]
        checks["disk_space"] = all(
            _integer(item[0]) >= manifest.minimum_free_bytes for item in disks
        )
        checks["inode_space"] = all(
            _integer(item[1]) >= manifest.minimum_free_inodes for item in disks
        )
    except (OSError, ValueError, TypeError, IndexError):
        checks["disk_space"] = checks["inode_space"] = False
    try:
        checks["memory_available"] = (
            _integer(memory_reader()) >= manifest.minimum_available_memory_bytes
        )
    except (OSError, ValueError, TypeError):
        checks["memory_available"] = False
    try:
        checks["backup_receipt"] = backup_current(manifest, now, uid)
    except (OSError, ValueError, TypeError, KeyError):
        checks["backup_receipt"] = False
    return checks, runtime


def _condition_id(release, code):
    return _digest([release, code])


def _validate_state(value, now):
    fields = {
        "schema_version",
        "observed_at",
        "sequence",
        "conditions",
        "outbox",
        "runtime",
        "integrity_sha256",
    }
    if type(value) is not dict or set(value) != fields:
        raise UnsafeState("spool shape invalid")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise UnsafeState("spool version invalid")
    if value["integrity_sha256"] != _digest(
        {key: item for key, item in value.items() if key != "integrity_sha256"}
    ):
        raise UnsafeState("spool integrity invalid")
    observed = _timestamp(value["observed_at"])
    if observed > now or type(value["conditions"]) is not dict or type(value["outbox"]) is not list:
        raise UnsafeState("spool time or records invalid")
    if len(value["conditions"]) + len(value["outbox"]) > MAX_RECORDS:
        raise UnsafeState("spool capacity exhausted")
    if _integer(value["sequence"]) != len(value["outbox"]):
        raise UnsafeState("spool sequence invalid")
    for identity, record in value["conditions"].items():
        if type(record) is not dict or set(record) != {
            "release_id",
            "image_digest",
            "reason_code",
            "active",
            "first_seen",
            "last_seen",
            "count",
            "recovered_at",
        }:
            raise UnsafeState("incident shape invalid")
        _hash(record["release_id"])
        _image(record["image_digest"])
        if record["reason_code"] not in CONDITIONS or identity != _condition_id(
            record["release_id"], record["reason_code"]
        ):
            raise UnsafeState("incident identity invalid")
        if type(record["active"]) is not bool:
            raise UnsafeState("incident state invalid")
        _integer(record["count"], minimum=1)
        first, last = _timestamp(record["first_seen"]), _timestamp(record["last_seen"])
        if not first <= last <= observed:
            raise UnsafeState("incident time invalid")
        recovered = record["recovered_at"]
        if (record["active"] and recovered is not None) or (
            not record["active"] and not last <= _timestamp(recovered) <= observed
        ):
            raise UnsafeState("incident recovery invalid")
    for sequence, event in enumerate(value["outbox"], 1):
        if type(event) is not dict or set(event) != {
            "id",
            "sequence",
            "type",
            "reason_code",
            "observed_at",
            "details",
            "status",
        }:
            raise UnsafeState("outbox event shape invalid")
        details = event["details"]
        if type(details) is not dict or set(details) != {
            "release_id",
            "image_digest",
            "condition_id",
        }:
            raise UnsafeState("outbox details invalid")
        identity = details["condition_id"]
        record = value["conditions"].get(identity)
        if record is None or details != {
            "release_id": record["release_id"],
            "image_digest": record["image_digest"],
            "condition_id": identity,
        }:
            raise UnsafeState("outbox binding invalid")
        if (
            type(event["sequence"]) is not int
            or event["sequence"] != sequence
            or event["reason_code"] != record["reason_code"]
            or event["status"] != "pending_local"
            or event["type"] not in {"host_operational_failure", "host_operational_recovery"}
            or event["id"] != _digest([identity, sequence, event["type"]])
            or _timestamp(event["observed_at"]) > observed
        ):
            raise UnsafeState("outbox event invalid")
    runtime = value["runtime"]
    if runtime is not None:
        if type(runtime) is not dict or set(runtime) != {
            "release_id",
            "started_at",
            "restart_count",
        }:
            raise UnsafeState("runtime observation invalid")
        _hash(runtime["release_id"])
        _integer(runtime["restart_count"])
        if _timestamp(runtime["started_at"]) > observed:
            raise UnsafeState("runtime observation time invalid")


def _update(value, manifest, checks, runtime, now):
    stamp = now.isoformat()
    for code in sorted(CONDITIONS):
        healthy = checks[code]
        identity = _condition_id(manifest.release_id, code)
        record = value["conditions"].get(identity)
        if healthy is None or (healthy and (record is None or not record["active"])):
            continue
        transition = healthy or record is None or not record["active"]
        if record is None:
            record = {
                "release_id": manifest.release_id,
                "image_digest": manifest.expected_image,
                "reason_code": code,
                "first_seen": stamp,
                "count": 0,
            }
            value["conditions"][identity] = record
        if not healthy:
            record["last_seen"] = stamp
            record["count"] += 1
        record["active"] = not healthy
        record["recovered_at"] = stamp if healthy else None
        if transition:
            value["sequence"] += 1
            sequence = value["sequence"]
            event_type = "host_operational_recovery" if healthy else "host_operational_failure"
            value["outbox"].append(
                {
                    "id": _digest([identity, sequence, event_type]),
                    "sequence": sequence,
                    "type": event_type,
                    "reason_code": code,
                    "observed_at": stamp,
                    "details": {
                        "release_id": manifest.release_id,
                        "image_digest": manifest.expected_image,
                        "condition_id": identity,
                    },
                    "status": "pending_local",
                }
            )
    value["observed_at"], value["runtime"] = stamp, runtime
    value["integrity_sha256"] = _digest(
        {key: item for key, item in value.items() if key != "integrity_sha256"}
    )
    _validate_state(value, now)
    encoded = _canonical(value)
    if len(encoded) > MAX_BYTES:
        raise UnsafeState("spool byte capacity exhausted")
    return encoded


def _atomic_write(directory, encoded, uid):
    temporary = ".state.next"
    descriptor = -1
    try:
        # An interrupted pre-rename write is never authoritative. Validate before discarding it.
        try:
            stale = os.open(
                temporary,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=directory,
            )
        except FileNotFoundError:
            pass
        else:
            with os.fdopen(stale, "rb") as handle:
                if _file_metadata(handle.fileno(), uid).st_size > MAX_BYTES:
                    raise UnsafeState("uncommitted spool exceeds bound")
            os.unlink(temporary, dir_fd=directory)
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, "state.json", src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    except OSError as exc:
        raise UnsafeState("spool could not be durably committed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def run_watchdog(
    manifest,
    spool,
    now,
    *,
    trusted_uid=0,
    inspector=None,
    requester=None,
    memory_reader=None,
    disk_reader=None,
):
    if now.tzinfo is None or now.utcoffset().total_seconds() != 0:
        raise UnsafeState("UTC clock required")
    with _directory(spool, trusted_uid) as directory:
        try:
            descriptor = os.open(
                "watchdog.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory,
            )
            with os.fdopen(descriptor, "r+b") as lock:
                _file_metadata(lock.fileno(), trusted_uid)
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                marker = lock.read(33)
                if marker not in {b"", b"initialized\n"}:
                    raise UnsafeState("spool initialization marker invalid")
                try:
                    raw = _read_at(directory, "state.json", trusted_uid, MAX_BYTES)
                except FileNotFoundError:
                    if marker:
                        raise UnsafeState("initialized spool is missing") from None
                    value = {
                        "schema_version": 1,
                        "observed_at": now.isoformat(),
                        "sequence": 0,
                        "conditions": {},
                        "outbox": [],
                        "runtime": None,
                    }
                else:
                    value = _json(raw)
                    _validate_state(value, now)
                    if raw != _canonical(value):
                        raise UnsafeState("spool encoding is not canonical")
                checks, runtime = _collect(
                    manifest,
                    spool,
                    value,
                    now,
                    inspector or inspect_container,
                    requester or request,
                    memory_reader or available_memory,
                    disk_reader or free_disk,
                    trusted_uid,
                )
                encoded = _update(value, manifest, checks, runtime, now)
                _atomic_write(directory, encoded, trusted_uid)
                if not marker:
                    lock.seek(0)
                    lock.write(b"initialized\n")
                    lock.flush()
                    os.fsync(lock.fileno())
                    os.fsync(directory)
                return {
                    "healthy": all(check is True for check in checks.values()),
                    "failed_conditions": sorted(
                        code for code, check in checks.items() if check is False
                    ),
                    "unknown_conditions": sorted(
                        code for code, check in checks.items() if check is None
                    ),
                    "pending_local_events": len(value["outbox"]),
                }
        except OSError as exc:
            raise UnsafeState("watchdog state unavailable or locked") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise UnsafeState("root operator required")
        manifest = load_manifest(args.manifest)
        result = run_watchdog(manifest, args.state_dir, datetime.now(UTC))
        print(json.dumps(result, sort_keys=True))
        return 0 if result["healthy"] else 1
    except Exception:
        # Never emit exception text, subprocess output, receipt contents or operator paths.
        print('{"healthy":false,"error":"watchdog_evidence_unavailable"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
